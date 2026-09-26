"""Disk storage: raw pages, JSONL, final JSON, summary."""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from typing import Any, Iterable

from playstore_scraper.utils import run_folder_stamp, utc_now_iso


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def atomic_write_json(path: Path, data: Any, *, pretty: bool = False) -> None:
    if pretty:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    atomic_write_text(path, text + "\n")


class Storage:
    def __init__(self, run_dir: Path, *, save_raw: bool = True, pretty: bool = False) -> None:
        self.run_dir = run_dir
        self.save_raw = save_raw
        self.pretty = pretty
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "raw").mkdir(exist_ok=True)
        (self.run_dir / "errors").mkdir(exist_ok=True)
        self.reviews_jsonl = self.run_dir / "reviews.jsonl"
        self._jsonl_fp = self.reviews_jsonl.open("a", encoding="utf-8")

    @classmethod
    def create_run(
        cls,
        out_dir: Path,
        app_id: str,
        *,
        resume: bool,
        save_raw: bool = True,
        pretty: bool = False,
    ) -> Storage:
        app_dir = out_dir / app_id
        app_dir.mkdir(parents=True, exist_ok=True)

        if resume:
            # Prefer the latest run that has a checkpoint
            candidates = sorted(
                [p for p in app_dir.iterdir() if p.is_dir()],
                key=lambda p: p.name,
                reverse=True,
            )
            for cand in candidates:
                if (cand / "checkpoint.json").exists():
                    return cls(cand, save_raw=save_raw, pretty=pretty)

        run_dir = app_dir / run_folder_stamp()
        return cls(run_dir, save_raw=save_raw, pretty=pretty)

    def close(self) -> None:
        if self._jsonl_fp and not self._jsonl_fp.closed:
            self._jsonl_fp.flush()
            self._jsonl_fp.close()

    def append_review(self, review: dict[str, Any]) -> None:
        self._jsonl_fp.write(json.dumps(review, ensure_ascii=False) + "\n")
        self._jsonl_fp.flush()

    def save_raw_page(
        self,
        *,
        stream_id: str,
        page: int,
        url: str,
        f_req: str,
        http_status: int,
        body: str,
    ) -> None:
        if not self.save_raw:
            return
        folder = self.run_dir / "raw" / stream_id
        folder.mkdir(parents=True, exist_ok=True)
        envelope = {
            "stream": stream_id,
            "page": page,
            "requestedAt": utc_now_iso(),
            "request": {"url": url, "fReq": f_req},
            "httpStatus": http_status,
            "body": body,
        }
        path = folder / f"page_{page:04d}.json"
        atomic_write_json(path, envelope, pretty=False)

    def save_error(self, name: str, body: str, meta: dict[str, Any] | None = None) -> Path:
        path = self.run_dir / "errors" / f"{name}.txt"
        payload = {
            "meta": meta or {},
            "body": body,
        }
        atomic_write_json(path.with_suffix(".json"), payload, pretty=True)
        return path.with_suffix(".json")

    def load_seen_ids(self) -> set[str]:
        seen: set[str] = set()
        if not self.reviews_jsonl.exists():
            return seen
        with self.reviews_jsonl.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = obj.get("reviewId")
                if rid:
                    seen.add(rid)
        return seen

    def iter_reviews(self) -> Iterable[dict[str, Any]]:
        if not self.reviews_jsonl.exists():
            return
        with self.reviews_jsonl.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def finalize(
        self,
        *,
        sort_mode: str,
        summary: dict[str, Any],
        compress_raw: bool = False,
    ) -> Path:
        reviews = list(self.iter_reviews())

        if sort_mode == "rating":
            reviews.sort(
                key=lambda r: (
                    -(r.get("score") or 0),
                    -(r.get("atUnix") or 0),
                )
            )
        elif sort_mode == "relevant":
            # Preserve insertion order (Google's relevance order within streams)
            pass
        else:
            # newest / all → newest first
            reviews.sort(key=lambda r: -(r.get("atUnix") or 0))

        reviews_path = self.run_dir / "reviews.json"
        atomic_write_json(reviews_path, reviews, pretty=self.pretty)
        atomic_write_json(self.run_dir / "summary.json", summary, pretty=True)

        if compress_raw:
            raw_dir = self.run_dir / "raw"
            if raw_dir.exists():
                for path in raw_dir.rglob("*.json"):
                    gz_path = path.with_suffix(path.suffix + ".gz")
                    with path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    path.unlink()

        return reviews_path
