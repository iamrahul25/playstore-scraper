"""Typer CLI entrypoint."""

from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console

from playstore_scraper.app_info import AppNotFoundError
from playstore_scraper.config import (
    InvalidCountError,
    InvalidSortError,
    build_config,
)
from playstore_scraper.input_parser import InvalidAppInputError, resolve_app_input
from playstore_scraper.languages import InvalidLanguageError
from playstore_scraper.prompts import resolve_user_options
from playstore_scraper.scraper import (
    ReviewScraper,
    ScrapeBlocked,
    ScrapeFormatError,
    ScrapeInterrupted,
)
from playstore_scraper.utils import format_count

app = typer.Typer(
    add_completion=False,
    help="Scrape Google Play Store reviews to raw JSON.",
)
console = Console(stderr=True)


def _setup_logging(verbose: bool, quiet: bool) -> None:
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def main(
    app_arg: Optional[str] = typer.Argument(
        None,
        metavar="APP",
        help="Package ID or Play Store URL (prompted if omitted).",
    ),
    count: Optional[str] = typer.Option(
        None,
        "--count",
        help="How many reviews: 100, 1000, 10k, 100000, or all (default: all).",
    ),
    sort: Optional[str] = typer.Option(
        None,
        "--sort",
        help="Sort: newest, relevant, rating, or all (default: newest).",
    ),
    lang: Optional[str] = typer.Option(
        None,
        "--lang",
        help="Language: en, hindi, en,hi, or any (default: en).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Do not prompt; use defaults for missing options.",
    ),
    country: str = typer.Option(
        "us",
        "--country",
        help="Comma-separated country codes (default: us).",
    ),
    no_star_split: bool = typer.Option(
        False,
        "--no-star-split",
        help="Do not add per-star streams.",
    ),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="Only keep reviews on/after this ISO date (YYYY-MM-DD).",
    ),
    until: Optional[str] = typer.Option(
        None,
        "--until",
        help="Only keep reviews on/before this ISO date (YYYY-MM-DD).",
    ),
    page_size: int = typer.Option(200, "--page-size", min=1, max=200),
    delay: float = typer.Option(1.0, "--delay", help="Base delay between requests."),
    workers: int = typer.Option(1, "--workers", min=1, max=4),
    out: str = typer.Option("data", "--out", help="Output root directory."),
    no_raw: bool = typer.Option(False, "--no-raw", help="Skip saving raw page bodies."),
    compress_raw: bool = typer.Option(
        False, "--compress-raw", help="Gzip raw pages after the run."
    ),
    pretty: bool = typer.Option(False, "--pretty", help="Pretty-print reviews.json."),
    fresh: bool = typer.Option(False, "--fresh", help="Ignore existing checkpoints."),
    no_prune: bool = typer.Option(
        False, "--no-prune", help="Disable adaptive stream pruning."
    ),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="HTTP/SOCKS proxy URL."),
    engine: str = typer.Option("native", "--engine", help="native (default) or library."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Fetch Play Store reviews for APP and save raw + normalized JSON."""
    _setup_logging(verbose, quiet)

    try:
        app_id, count_str, sort_str, lang_str = resolve_user_options(
            app=app_arg,
            count=count,
            sort=sort,
            lang=lang,
            yes=yes,
        )
        # If URL was passed, also pick up country from URL when using default
        if app_arg:
            parsed = resolve_app_input(app_arg)
            if parsed.country_from_url and country == "us":
                country = parsed.country_from_url

        cfg = build_config(
            app_id=app_id,
            count=count_str,
            sort=sort_str,
            lang=lang_str,
            country=country,
            no_star_split=no_star_split,
            page_size=page_size,
            delay=delay,
            out=out,
            no_raw=no_raw,
            compress_raw=compress_raw,
            fresh=fresh,
            no_prune=no_prune,
            pretty=pretty,
            proxy=proxy,
            workers=workers,
            since=since,
            until=until,
            engine=engine,
        )
    except (
        InvalidAppInputError,
        InvalidCountError,
        InvalidSortError,
        InvalidLanguageError,
        ValueError,
    ) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if cfg.sort == "all" and cfg.count is not None:
        console.print(
            "[yellow]Note:[/yellow] --sort all with a numeric --count mixes orderings; "
            f"stopping at {format_count(cfg.count)} unique reviews."
        )

    console.print(
        f"→ Fetching {format_count(cfg.count)} {cfg.sort} "
        f"review(s) ({', '.join(cfg.langs[:8])}{'…' if len(cfg.langs) > 8 else ''}) "
        f"for [bold]{cfg.app_id}[/bold]"
    )

    if cfg.engine != "native":
        console.print(
            "[yellow]--engine library is not implemented in v1; using native.[/yellow]"
        )

    scraper = ReviewScraper(cfg)
    try:
        scraper.run()
    except AppNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    except ScrapeBlocked as exc:
        console.print(
            f"[red]Blocked / rate-limited:[/red] {exc}\n"
            "Checkpoint saved. Resume later or try --proxy / higher --delay."
        )
        raise typer.Exit(code=3) from exc
    except ScrapeFormatError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=4) from exc
    except ScrapeInterrupted as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=130) from exc
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Unexpected error:[/red] {exc}")
        if verbose:
            console.print_exception()
        raise typer.Exit(code=1) from exc


def run() -> None:
    app()


if __name__ == "__main__":
    run()
