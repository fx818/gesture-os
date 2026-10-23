"""The realtime firewall, made structural.

`JudgmentBroker` owns the ONLY thread permitted to call a JudgmentProvider. The frame loop calls
`request()` (returns immediately) and `drain()` (non-blocking), never `judge()`. Combined with the
import contract in `.importlinter`, there is no path from the arbitration engine to the network.

`calls_from_loop_thread` is not diagnostics — `tests/perf/test_jev_firewall.py` asserts it is zero,
which turns ADR-0001 from a written rule into a failing build.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Mapping

from app.decision.provider import (
    Judgment,
    JudgmentProvider,
    JudgmentRequest,
    ProviderError,
)

LOOP_THREAD_NAMES = frozenset({"perception", "MainThread"})


@dataclass(frozen=True, slots=True)
class JudgmentReady:
    point: str
    cache_key: str
    answers: Mapping[str, Judgment]
    error: str = ""
    latency_ms: float = 0.0


class JudgmentBroker:
    def __init__(self, provider: JudgmentProvider, *, loop_thread_names=LOOP_THREAD_NAMES) -> None:
        self._provider = provider
        self._loop_names = frozenset(loop_thread_names)
        self._in: queue.Queue[JudgmentRequest | None] = queue.Queue()
        self._out: queue.Queue[JudgmentReady] = queue.Queue()
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.calls_from_loop_thread = 0

    # -- called from the loop -------------------------------------------------------

    def request(self, req: JudgmentRequest) -> bool:
        """Enqueue. Returns False if an identical request is already in flight.

        Coalescing matters: alt-tabbing quickly through five windows and back must not queue five
        round trips for the window you land on.
        """
        key = f"{req.point.value}|{req.cache_key}"
        with self._lock:
            if key in self._inflight:
                return False
            self._inflight.add(key)
        self._in.put(req)
        return True

    def drain(self) -> list[JudgmentReady]:
        """Non-blocking. Safe to call once per frame."""
        out: list[JudgmentReady] = []
        while True:
            try:
                out.append(self._out.get_nowait())
            except queue.Empty:
                return out

    def judge_now(self, req: JudgmentRequest) -> Mapping[str, Judgment]:
        """Synchronous escape hatch for the CLI and offline batch jobs.

        Counts any call made from a loop thread. That counter is asserted to be zero in CI, so
        misuse from the frame loop fails the build rather than degrading someone's cursor.
        """
        if threading.current_thread().name in self._loop_names:
            self.calls_from_loop_thread += 1
        return self._provider.judge(req)

    # -- lifecycle ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="judgment", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread is None:
            return
        self._in.put(None)
        self._thread.join(timeout)
        self._thread = None

    def pending(self) -> int:
        with self._lock:
            return len(self._inflight)

    # -- worker ---------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            req = self._in.get()
            if req is None:
                return
            key = f"{req.point.value}|{req.cache_key}"
            t0 = time.monotonic()
            try:
                answers = self._provider.judge(req)
                ready = JudgmentReady(
                    point=req.point.value,
                    cache_key=req.cache_key,
                    answers=answers,
                    latency_ms=(time.monotonic() - t0) * 1000,
                )
            except ProviderError as e:
                ready = JudgmentReady(
                    point=req.point.value, cache_key=req.cache_key, answers={}, error=str(e)
                )
            except Exception as e:  # noqa: BLE001 — the worker must outlive any single failure
                ready = JudgmentReady(
                    point=req.point.value,
                    cache_key=req.cache_key,
                    answers={},
                    error=f"{type(e).__name__}: {e}",
                )
            finally:
                with self._lock:
                    self._inflight.discard(key)
            self._out.put(ready)
