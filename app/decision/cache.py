"""Persistent judgment cache.

The cache key always contains the point's `rev` from points.yaml, so editing a prompt invalidates
its own cache. Without that, a reworded question appears to do nothing until the TTL expires —
the single most confusing failure mode a cached model call has.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Mapping

from app.decision.provider import Judgment, Source

DEFAULT_CACHE_PATH = Path.home() / ".local" / "share" / "gesture-os" / "judgments.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS judgments (
    point      TEXT NOT NULL,
    cache_key  TEXT NOT NULL,
    stored_at  REAL NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (point, cache_key)
);
"""


class SqliteCache:
    def __init__(self, path: Path = DEFAULT_CACHE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, point: str, key: str, ttl_s: float) -> dict[str, Judgment] | None:
        row = self._conn.execute(
            "SELECT stored_at, payload FROM judgments WHERE point=? AND cache_key=?",
            (point, key),
        ).fetchone()
        if row is None:
            return None
        stored_at, payload = row
        if ttl_s > 0 and (time.time() - stored_at) > ttl_s:
            return None
        data = json.loads(payload)
        return {
            k: Judgment(
                key=k,
                value=v["value"],
                confidence=float(v["confidence"]),
                source=Source.CACHE,
                probabilities=v.get("probabilities"),
            )
            for k, v in data.items()
        }

    def put(self, point: str, key: str, answers: Mapping[str, Judgment]) -> None:
        payload = json.dumps(
            {
                k: {
                    "value": j.value,
                    "confidence": j.confidence,
                    "probabilities": dict(j.probabilities) if j.probabilities else None,
                }
                for k, j in answers.items()
            }
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO judgments (point, cache_key, stored_at, payload) "
            "VALUES (?,?,?,?)",
            (point, key, time.time(), payload),
        )
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM judgments")
        self._conn.commit()

    def __len__(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0])

    def close(self) -> None:
        self._conn.close()
