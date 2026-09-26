"""Scraper orchestration: streams, pagination, dedupe, resume."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from playstore_scraper.app_info import AppNotFoundError, fetch_app_info
from playstore_scraper.checkpoint import Checkpoint
from playstore_scraper.config import ScrapeConfig
from playstore_scraper.http_client import HttpError, PlayStoreClient, RateLimitedError
from playstore_scraper.parser import normalize_review
from playstore_scraper.rpc import (
    RpcDecodeError,
    build_reviews_payload,
    build_reviews_url,
    decode_reviews_response,
)
from playstore_scraper.storage import Storage, atomic_write_json
from playstore_scraper.streams import Stream, build_stream_matrix, should_round_robin
from playstore_scraper.utils import format_count, utc_now_iso

logger = logging.getLogger(__name__)
console = Console(stderr=True)

PRUNE_THRESHOLD = 0.02
PRUNE_STREAK = 5
EMPTY_STREAK_LIMIT = 3


class ScrapeInterrupted(Exception):
    pass


class ScrapeBlocked(Exception):
    pass


class ScrapeFormatError(Exception):
    pass


def _review_date(rec: dict[str, Any]) -> date | None:
    ts = rec.get("atUnix")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def _passes_date_filters(rec: dict[str, Any], cfg: ScrapeConfig) -> bool:
    d = _review_date(rec)
    if d is None:
        return True
    if cfg.since and d < cfg.since:
        return False
    if cfg.until and d > cfg.until:
        return False
    return True


def _since_passed(rec: dict[str, Any], cfg: ScrapeConfig, sort: str) -> bool:
    """For newest sort, stop stream once reviews are older than since."""
    if sort != "newest" or not cfg.since:
        return False
    d = _review_date(rec)
    return d is not None and d < cfg.since


class ReviewScraper:
    def __init__(self, cfg: ScrapeConfig) -> None:
        self.cfg = cfg
        self.storage = Storage.create_run(
            cfg.out_dir,
            cfg.app_id,
            resume=cfg.resume,
            save_raw=cfg.save_raw_pages,
            pretty=cfg.pretty,
        )
        self.client = PlayStoreClient(
            delay_seconds=cfg.delay_seconds,
            max_retries=cfg.max_retries,
            timeout_seconds=cfg.timeout_seconds,
            proxy=cfg.proxy,
        )
        self.checkpoint, self.resumed = Checkpoint.load_or_create(
            self.storage.run_dir / "checkpoint.json",
            app_id=cfg.app_id,
            config_hash=cfg.config_hash(),
            resume=cfg.resume,
        )
        self.seen_ids = self.storage.load_seen_ids() if self.resumed else set()
        if self.resumed and self.checkpoint.totalUnique == 0:
            self.checkpoint.totalUnique = len(self.seen_ids)
        self.app_info: dict[str, Any] | None = None
        self.finished_at: str | None = None
        self._count_reached = False

    def close(self) -> None:
        self.storage.close()
        self.client.close()

    def run(self) -> dict[str, Any]:
        try:
            return self._run()
        except KeyboardInterrupt as exc:
            self.checkpoint.save()
            self.storage.close()
            raise ScrapeInterrupted(
                "Interrupted. Resume with the same command."
            ) from exc
        finally:
            self.close()

    def _run(self) -> dict[str, Any]:
        # App info / 404 check
        try:
            self.app_info = fetch_app_info(
                self.client,
                self.cfg.app_id,
                lang=self.cfg.langs[0],
                country=self.cfg.countries[0],
            )
            atomic_write_json(
                self.storage.run_dir / "app_info.json", self.app_info, pretty=True
            )
        except AppNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("App info fetch failed: %s", exc)
            self.app_info = {"appId": self.cfg.app_id, "title": None}

        title = (self.app_info or {}).get("title") or self.cfg.app_id
        ratings = (self.app_info or {}).get("ratings")
        ratings_label = f"{ratings:,}" if isinstance(ratings, int) else "?"

        console.print(
            f"[bold]App:[/bold] {title} ({self.cfg.app_id}) — {ratings_label} ratings"
        )
        console.print(
            f"[bold]Request:[/bold] count={self.cfg.count_label} | "
            f"sort={self.cfg.sort} | lang={','.join(self.cfg.langs[:5])}"
            + ("…" if len(self.cfg.langs) > 5 else "")
        )
        if self.resumed:
            console.print(
                f"[yellow]Resuming[/yellow] → {self.storage.run_dir} "
                f"({len(self.seen_ids):,} reviews already saved)"
            )

        streams = build_stream_matrix(self.cfg)
        # Language pre-check for multi-lang
        if len(self.cfg.langs) > 1:
            streams = self._filter_empty_languages(streams)

        console.print(f"[bold]Streams:[/bold] {len(streams)} planned")

        if should_round_robin(self.cfg):
            self._run_round_robin(streams)
        else:
            self._run_sequential(streams)

        self.finished_at = utc_now_iso()
        summary = self._build_summary()
        self.storage.finalize(
            sort_mode=self.cfg.sort,
            summary=summary,
            compress_raw=self.cfg.compress_raw,
        )
        self._print_done(summary)
        return summary

    def _filter_empty_languages(self, streams: list[Stream]) -> list[Stream]:
        alive: set[str] = set()
        checked: set[str] = set()
        for lang in self.cfg.langs:
            if lang in checked:
                continue
            checked.add(lang)
            country = self.cfg.countries[0]
            try:
                arrays, _ = self._fetch_page(
                    Stream(lang=lang, country=country, sort="newest", star_filter=None),
                    token=None,
                    page=0,
                    persist_raw=False,
                )
                if arrays:
                    alive.add(lang)
                else:
                    console.print(f"  [dim]skip lang={lang} (no reviews)[/dim]")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Language pre-check failed for %s: %s", lang, exc)
                alive.add(lang)  # optimistic: keep it
        return [s for s in streams if s.lang in alive]

    def _run_sequential(self, streams: list[Stream]) -> None:
        for stream in streams:
            if self._count_reached:
                break
            st = self.checkpoint.get_stream(stream.id)
            if st.done:
                continue
            # Skip per-star until primary of same sort/lang/country is done when count limited
            if (
                self.cfg.count is not None
                and stream.star_filter is not None
                and not self._primary_done(stream)
            ):
                # Primary still running or not started — sequential order already
                # puts primary first, so if we get here primary is done or skipped.
                pass
            self._scrape_stream(stream)

    def _primary_done(self, stream: Stream) -> bool:
        primary_id = Stream(
            lang=stream.lang,
            country=stream.country,
            sort=stream.sort,
            star_filter=None,
        ).id
        return self.checkpoint.get_stream(primary_id).done

    def _run_round_robin(self, streams: list[Stream]) -> None:
        """One page at a time across languages for mixed samples."""
        # Prefer primary streams first across langs, then star filters
        primary = [s for s in streams if s.is_primary]
        secondary = [s for s in streams if not s.is_primary]
        for group in (primary, secondary):
            active = [s for s in group if not self.checkpoint.get_stream(s.id).done]
            while active and not self._count_reached:
                next_active: list[Stream] = []
                for stream in active:
                    if self._count_reached:
                        break
                    st = self.checkpoint.get_stream(stream.id)
                    if st.done:
                        continue
                    done = self._scrape_one_page(stream)
                    st = self.checkpoint.get_stream(stream.id)
                    if not st.done and not done:
                        next_active.append(stream)
                active = next_active

    def _scrape_stream(self, stream: Stream) -> None:
        st = self.checkpoint.get_stream(stream.id)
        token = st.token
        page = st.pages
        restarted = False

        with Progress(
            SpinnerColumn(),
            TextColumn(f"[cyan]{stream.id}[/cyan]"),
            BarColumn(),
            TextColumn("page {task.completed}"),
            TextColumn("{task.fields[stats]}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("scrape", total=None, stats="0 fetched / 0 new")
            while not self._count_reached:
                if (
                    self.cfg.max_pages_per_stream is not None
                    and page >= self.cfg.max_pages_per_stream
                ):
                    self.checkpoint.mark_done(stream.id, "max_pages")
                    self.checkpoint.save()
                    break

                try:
                    done_reason = self._process_page(stream, token, page, progress, task)
                except RpcDecodeError:
                    if token and not restarted:
                        # Expired token — restart stream
                        console.print(
                            f"  [yellow]{stream.id}: token expired, restarting stream[/yellow]"
                        )
                        token = None
                        restarted = True
                        continue
                    raise

                st = self.checkpoint.get_stream(stream.id)
                token = st.token
                page = st.pages

                if done_reason:
                    self.checkpoint.mark_done(stream.id, done_reason)
                    self.checkpoint.save()
                    console.print(
                        f"  [green]{stream.id}[/green] done ({done_reason}) "
                        f"pages={st.pages} fetched={st.fetched:,} new={st.new:,}"
                    )
                    break

    def _scrape_one_page(self, stream: Stream) -> bool:
        """Fetch one page; return True if stream is finished."""
        st = self.checkpoint.get_stream(stream.id)
        token = st.token
        page = st.pages
        try:
            done_reason = self._process_page(stream, token, page, progress=None, task=None)
        except RpcDecodeError:
            if token:
                self.checkpoint.get_stream(stream.id).token = None
                self.checkpoint.save()
                return False
            raise
        if done_reason:
            self.checkpoint.mark_done(stream.id, done_reason)
            self.checkpoint.save()
            return True
        return False

    def _process_page(
        self,
        stream: Stream,
        token: str | None,
        page: int,
        progress: Progress | None,
        task: Any,
    ) -> str | None:
        """
        Fetch and process one page.

        Returns done_reason string if stream should stop, else None.
        """
        try:
            arrays, next_token = self._fetch_page(stream, token=token, page=page)
        except RateLimitedError as exc:
            self.checkpoint.save()
            raise ScrapeBlocked(str(exc)) from exc
        except HttpError as exc:
            if exc.status_code in {429, 503}:
                self.checkpoint.save()
                raise ScrapeBlocked(str(exc)) from exc
            raise
        except RpcDecodeError as exc:
            self.storage.save_error(
                f"{stream.id}_page_{page}",
                exc.body_preview,
                meta={"stream": stream.id, "page": page, "error": str(exc)},
            )
            self.checkpoint.save()
            raise ScrapeFormatError(
                f"Unexpected response format (see errors/). Update rpc.py if Play Store changed. {exc}"
            ) from exc

        new = 0
        since_stop = False
        for arr in arrays:
            if self.cfg.count is not None and len(self.seen_ids) >= self.cfg.count:
                self._count_reached = True
                break
            rec = normalize_review(
                arr,
                lang=stream.lang,
                country=stream.country,
                sort=stream.sort,
                star_filter=stream.star_filter,
                stream_id=stream.id,
            )
            rid = rec.get("reviewId")
            if not rid:
                continue
            if _since_passed(rec, self.cfg, stream.sort):
                since_stop = True
                break
            if not _passes_date_filters(rec, self.cfg):
                continue
            if rid in self.seen_ids:
                self.checkpoint.duplicatesSkipped += 1
                continue
            # Trim to exact count
            if self.cfg.count is not None and len(self.seen_ids) >= self.cfg.count:
                self._count_reached = True
                break
            self.seen_ids.add(rid)
            self.storage.append_review(rec)
            new += 1
            self.checkpoint.totalUnique = len(self.seen_ids)
            if self.cfg.count is not None and len(self.seen_ids) >= self.cfg.count:
                self._count_reached = True
                break

        fetched = len(arrays)
        empty_streak = self.checkpoint.get_stream(stream.id).emptyStreak
        low_yield_streak = self.checkpoint.get_stream(stream.id).lowYieldStreak

        if fetched == 0:
            empty_streak += 1
        else:
            empty_streak = 0

        if fetched > 0 and (new / fetched) < PRUNE_THRESHOLD:
            low_yield_streak += 1
        else:
            low_yield_streak = 0

        page += 1
        self.checkpoint.update_stream(
            stream.id,
            token=next_token,
            pages=page,
            fetched_delta=fetched,
            new_delta=new,
            empty_streak=empty_streak,
            low_yield_streak=low_yield_streak,
        )
        self.checkpoint.save()

        if progress is not None and task is not None:
            st = self.checkpoint.get_stream(stream.id)
            progress.update(
                task,
                completed=page,
                stats=f"{st.fetched:,} fetched / {st.new:,} new",
            )

        if self._count_reached:
            return "count_reached"
        if since_stop:
            return "since"
        if next_token is None:
            return "exhausted"
        if fetched == 0 and empty_streak >= EMPTY_STREAK_LIMIT:
            return "exhausted"
        if fetched == 0 and next_token:
            # allow a few empty pages
            pass
        if (
            self.cfg.prune
            and stream.star_filter is not None
            and low_yield_streak >= PRUNE_STREAK
        ):
            return "pruned"
        return None

    def _fetch_page(
        self,
        stream: Stream,
        *,
        token: str | None,
        page: int,
        persist_raw: bool = True,
    ) -> tuple[list[list], str | None]:
        url = build_reviews_url(stream.lang, stream.country)
        body = build_reviews_payload(
            self.cfg.app_id,
            stream.sort,
            self.cfg.page_size,
            token=token,
            score=stream.star_filter,
        )
        text, status = self.client.post_form(url, body, lang=stream.lang)
        if persist_raw:
            self.storage.save_raw_page(
                stream_id=stream.id,
                page=page,
                url=url,
                f_req=body,
                http_status=status,
                body=text,
            )
        return decode_reviews_response(text)

    def _build_summary(self) -> dict[str, Any]:
        by_score: dict[str, int] = defaultdict(int)
        by_lang: dict[str, int] = defaultdict(int)
        with_text = 0
        for rec in self.storage.iter_reviews():
            score = rec.get("score")
            if score is not None:
                by_score[str(score)] += 1
            lang = (rec.get("source") or {}).get("lang") or "?"
            by_lang[lang] += 1
            if rec.get("content"):
                with_text += 1

        ratings = (self.app_info or {}).get("ratings")
        unique = len(self.seen_ids)
        coverage = (unique / ratings) if isinstance(ratings, int) and ratings > 0 else None

        return {
            "appId": self.cfg.app_id,
            "appTitle": (self.app_info or {}).get("title"),
            "startedAt": self.checkpoint.startedAt,
            "finishedAt": self.finished_at or utc_now_iso(),
            "totalRatingsReported": ratings,
            "request": {
                "count": self.cfg.count_label,
                "sort": self.cfg.sort,
                "langs": self.cfg.langs,
            },
            "requested": self.cfg.count,
            "uniqueReviews": unique,
            "withText": with_text,
            "coverageOfRatings": coverage,
            "byScore": dict(sorted(by_score.items())),
            "byLang": dict(by_lang),
            "duplicatesSkipped": self.checkpoint.duplicatesSkipped,
            "requests": self.client.request_count,
            "retries": self.client.retry_count,
            "streams": self.checkpoint.stream_summary(),
            "outputDir": str(self.storage.run_dir),
            "config": self.cfg.to_summary_dict(),
        }

    def _print_done(self, summary: dict[str, Any]) -> None:
        console.print(
            f"[bold green]Total unique:[/bold green] {summary['uniqueReviews']:,} | "
            f"duplicates skipped: {summary['duplicatesSkipped']:,} | "
            f"requests: {summary['requests']} | "
            f"requested: {format_count(summary.get('requested'))}"
        )
        console.print(f"Saved → {summary['outputDir']}")
