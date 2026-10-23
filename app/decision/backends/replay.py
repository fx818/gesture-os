"""Replay recorded Jev responses. Lets CI exercise the real answer shapes with no network.

`make ci-live` re-runs the same cases against the live API and diffs against these fixtures, which
is how prompt and model drift get caught on a schedule instead of in a red pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from app.decision.provider import (
    Judgment,
    JudgmentRequest,
    ProviderError,
    ProviderHealth,
    Source,
)

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "judgment"


class ReplayProvider:
    def __init__(self, directory: Path = FIXTURE_DIR, *, strict: bool = True) -> None:
        self.directory = Path(directory)
        self.strict = strict
        self._calls = 0

    def _path(self, req: JudgmentRequest) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in req.cache_key)[:120]
        return self.directory / f"{req.point.value}__{safe}.json"

    def record(self, req: JudgmentRequest, answers: Mapping[str, Judgment]) -> Path:
        path = self._path(req)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "point": req.point.value,
                    "cache_key": req.cache_key,
                    "rev": req.rev,
                    "state": dict(req.state),
                    "answers": {
                        k: {
                            "value": j.value,
                            "confidence": j.confidence,
                            "probabilities": dict(j.probabilities) if j.probabilities else None,
                        }
                        for k, j in answers.items()
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def judge(self, req: JudgmentRequest) -> Mapping[str, Judgment]:
        self._calls += 1
        path = self._path(req)
        if not path.exists():
            if self.strict:
                raise ProviderError(f"no recorded judgment at {path.name}")
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            k: Judgment(
                key=k,
                value=v["value"],
                confidence=float(v["confidence"]),
                source=Source.REPLAY,
                probabilities=v.get("probabilities"),
            )
            for k, v in data["answers"].items()
        }

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            name="replay", available=self.directory.exists(), calls=self._calls
        )
