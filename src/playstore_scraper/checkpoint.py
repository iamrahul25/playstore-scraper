"""Resume checkpoint state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from playstore_scraper.storage import atomic_write_json
from playstore_scraper.utils import utc_now_iso


@dataclass
class StreamState:
    token: str | None = None
    pages: int = 0
    fetched: int = 0
    new: int = 0
    done: bool = False
    doneReason: str | None = None
    emptyStreak: int = 0
    lowYieldStreak: int = 0


@dataclass
class Checkpoint:
    appId: str
    configHash: str
    streams: dict[str, StreamState] = field(default_factory=dict)
    totalUnique: int = 0
    duplicatesSkipped: int = 0
    startedAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    path: Path | None = field(default=None, repr=False)

    def get_stream(self, stream_id: str) -> StreamState:
        if stream_id not in self.streams:
            self.streams[stream_id] = StreamState()
        return self.streams[stream_id]

    def update_stream(
        self,
        stream_id: str,
        *,
        token: str | None,
        pages: int,
        fetched_delta: int,
        new_delta: int,
        empty_streak: int = 0,
        low_yield_streak: int = 0,
    ) -> None:
        st = self.get_stream(stream_id)
        st.token = token
        st.pages = pages
        st.fetched += fetched_delta
        st.new += new_delta
        st.emptyStreak = empty_streak
        st.lowYieldStreak = low_yield_streak
        self.updatedAt = utc_now_iso()

    def mark_done(self, stream_id: str, reason: str) -> None:
        st = self.get_stream(stream_id)
        st.done = True
        st.doneReason = reason
        st.token = None
        self.updatedAt = utc_now_iso()

    def save(self) -> None:
        if self.path is None:
            raise RuntimeError("Checkpoint has no path")
        data = {
            "appId": self.appId,
            "configHash": self.configHash,
            "streams": {k: asdict(v) for k, v in self.streams.items()},
            "totalUnique": self.totalUnique,
            "duplicatesSkipped": self.duplicatesSkipped,
            "startedAt": self.startedAt,
            "updatedAt": self.updatedAt,
        }
        atomic_write_json(self.path, data, pretty=True)

    @classmethod
    def load_or_create(
        cls,
        path: Path,
        *,
        app_id: str,
        config_hash: str,
        resume: bool,
    ) -> tuple[Checkpoint, bool]:
        """
        Returns (checkpoint, resumed).
        """
        if resume and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = None
            if raw and raw.get("appId") == app_id:
                streams: dict[str, StreamState] = {}
                for sid, sdata in (raw.get("streams") or {}).items():
                    streams[sid] = StreamState(
                        token=sdata.get("token"),
                        pages=int(sdata.get("pages") or 0),
                        fetched=int(sdata.get("fetched") or 0),
                        new=int(sdata.get("new") or 0),
                        done=bool(sdata.get("done")),
                        doneReason=sdata.get("doneReason"),
                        emptyStreak=int(sdata.get("emptyStreak") or 0),
                        lowYieldStreak=int(sdata.get("lowYieldStreak") or 0),
                    )
                cp = cls(
                    appId=app_id,
                    configHash=raw.get("configHash") or config_hash,
                    streams=streams,
                    totalUnique=int(raw.get("totalUnique") or 0),
                    duplicatesSkipped=int(raw.get("duplicatesSkipped") or 0),
                    startedAt=raw.get("startedAt") or utc_now_iso(),
                    updatedAt=raw.get("updatedAt") or utc_now_iso(),
                    path=path,
                )
                # If config changed, keep matching streams but reset hash
                if cp.configHash != config_hash:
                    cp.configHash = config_hash
                return cp, True

        cp = cls(appId=app_id, configHash=config_hash, path=path)
        cp.save()
        return cp, False

    def stream_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "id": sid,
                "pages": st.pages,
                "fetched": st.fetched,
                "new": st.new,
                "doneReason": st.doneReason,
            }
            for sid, st in self.streams.items()
        ]
