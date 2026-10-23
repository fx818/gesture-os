"""Command line surface.

Subcommands exist from P0 even when their phase hasn't landed; an unimplemented one says so and
exits 2 rather than pretending. `doctor` is the gate every phase checks against.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from app.config import ConfigError, load, offline_requested

REPO_ROOT = Path(__file__).resolve().parent.parent

OK, WARN, FAIL = "  ok  ", " warn ", " FAIL "


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # noqa: PLC0415

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass


def _line(status: str, name: str, detail: str = "") -> None:
    print(f"[{status}] {name}" + (f"  — {detail}" if detail else ""))


# --------------------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check this machine. Phase-aware: a missing dependency that no landed phase needs is a
    warning, not a failure, so `doctor` stays green while the project is still being built."""
    # doctor is the command people run to find out why something is not working, so it has to see
    # the same environment the real commands do. Without this it reported TYPESAFE_API_KEY as
    # missing while .env sat right beside it — the exact false alarm doctor exists to prevent.
    _load_env()
    failures = 0

    in_venv = sys.prefix != sys.base_prefix
    _line(OK if in_venv else FAIL, "venv active", sys.prefix)
    failures += not in_venv

    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        Atspi.init()
        n = Atspi.get_desktop(0).get_child_count()
        _line(OK if n > 0 else WARN, "AT-SPI", f"{n} applications on the desktop")
    except Exception as e:  # noqa: BLE001
        _line(FAIL, "AT-SPI", f"{type(e).__name__}: {e}")
        failures += 1

    for mod, phase in (("mediapipe", "P2"), ("cv2", "P2"), ("evdev", "P4"), ("typesafe_sdk", "P1")):
        try:
            __import__(mod)
            _line(OK, f"import {mod}")
        except ImportError:
            _line(WARN, f"import {mod}", f"not installed — needed from {phase}")

    cams = sorted(Path("/dev").glob("video*"))
    _line(OK if cams else WARN, "camera", ", ".join(p.name for p in cams) or "none found")

    uinput = Path("/dev/uinput")
    if not uinput.exists():
        _line(WARN, "/dev/uinput", "missing — modprobe uinput")
    elif os.access(uinput, os.W_OK):
        _line(OK, "/dev/uinput", "writable")
    else:
        _line(WARN, "/dev/uinput", "not writable — needed from P4 (udev rule + input group)")

    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if offline_requested():
        _line(OK, "judgment", "GESTURE_OS_OFFLINE set — rules provider")
    elif key:
        _line(OK, "TYPESAFE_API_KEY", f"set ({len(key)} chars)")
    else:
        _line(WARN, "TYPESAFE_API_KEY", "not set — will fall back to the rules provider")

    try:
        cfg = load()
        _line(OK, "config", f"gross.speed={cfg.gross.speed}, window={cfg.arbitration.window_span_ms}ms")
    except ConfigError as e:
        _line(FAIL, "config", str(e))
        failures += 1

    if args.jev and key and not offline_requested():
        # Deliberately routed through decision/backends/typesafe.py: that module is the single
        # permitted importer of typesafe_sdk (.importlinter enforces it), so the CLI never
        # acquires its own door to the SDK.
        from app.decision.backends.typesafe import probe  # noqa: PLC0415

        r = probe()
        _line(OK if r.ok else FAIL, "Jev round-trip", r.detail or f"{r.latency_ms:.0f} ms")
        failures += not r.ok

    print()
    print("doctor:", "FAILED" if failures else "ok")
    return 1 if failures else 0


# --------------------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------------------


def _build_source(args: argparse.Namespace):
    from app.perception.backends.synthetic import GENERATORS
    from app.perception.ndjson import FileLandmarkSource

    if args.synthetic:
        if args.synthetic not in GENERATORS:
            raise SystemExit(
                f"unknown generator '{args.synthetic}'. available: {', '.join(sorted(GENERATORS))}"
            )
        return GENERATORS[args.synthetic]()
    if not args.fixture:
        raise SystemExit("pass a fixture path or --synthetic <generator>")
    return FileLandmarkSource(args.fixture, realtime=args.realtime)


def _build_effectors(name: str):
    from app.effectors.backends import null, recording
    from app.effectors.ports import EffectorSet

    if name == "uinput":
        from app.effectors.backends import logind_power, shell_ext
        from app.effectors.backends.uinput import UInputBackend, available

        ok, reason = available()
        if not ok:
            raise SystemExit(f"uinput unavailable: {reason}")
        backend = UInputBackend()

        # The GNOME Shell extension is an UPGRADE, not a dependency: without it the pointer and
        # keys still work and only arbitrary window placement goes missing. `shell_ext.available()`
        # never raises, so a missing or version-mismatched extension degrades here rather than
        # anywhere downstream — and it says so, because a capability that vanishes quietly is
        # indistinguishable from a bug.
        ok_ext, why = shell_ext.available()
        windows = shell_ext.ShellExtWindowManager() if ok_ext else None
        if not ok_ext:
            print(f"shell extension unavailable — window placement disabled ({why})")

        ok_pwr, why_pwr = logind_power.available()
        power = logind_power.LogindPowerSink() if ok_pwr else None
        if not ok_pwr:
            print(f"suspend unavailable — the down sweep will do nothing ({why_pwr})")
        return EffectorSet(pointer=backend, keys=backend, windows=windows, power=power), None
    if name == "recording":
        j = recording.Journal()
        return EffectorSet(
            pointer=recording.RecordingPointerSink(j),
            keys=recording.RecordingKeySink(j),
            windows=recording.RecordingWindowManager(j),
            power=recording.RecordingPowerSink(j),
        ), j
    if name == "null":
        return EffectorSet(pointer=null.NullPointerSink(), keys=null.NullKeySink()), None
    raise SystemExit(f"unknown effector backend '{name}' (recording|null|uinput)")


def cmd_replay(args: argparse.Namespace) -> int:
    source = _build_source(args)
    effectors, journal = _build_effectors(args.effector)

    # P3 wires features -> arbiter -> intents in here. Until then this proves the seam: a source
    # produces frames, the pipeline produces an intent stream, the router dispatches it.
    from app.runtime.pipeline import run_pipeline

    result = run_pipeline(source, effectors, dump_intents=args.dump_intents)

    print(f"source      {source.meta.name}  ({source.meta.model})")
    print(f"frames      {result.frames}")
    print(f"span        {result.span_ms:.1f} ms")
    print(f"intents     {len(result.intents)}")
    if journal is not None:
        print(f"effector    {len(journal)} call(s): {', '.join(journal.methods()) or '(none)'}")
    if result.unsupported:
        print(f"unsupported {result.unsupported}")
    effectors.close()
    return 0


# --------------------------------------------------------------------------------------
# judge / watch-focus  (P1)
# --------------------------------------------------------------------------------------


def cmd_judge(args: argparse.Namespace) -> int:
    """Ask one Jev point a question from the command line. The P1 exit criterion runs through
    this: same query should return source=jev, then source=cache, and source=rules with --offline."""
    _load_env()

    from app.decision.judgment_config import load as load_judgment
    from app.decision.points import a_app_context as point_a
    from app.decision.questions import PointId
    from app.runtime.wiring import build_judgment_provider, judgment_available
    from app.types import FocusInfo

    if args.point == "tile-role":
        return _judge_tile_role(args)
    if args.point != "app-context":
        print(f"point '{args.point}' is not built yet — see TODO.md", file=sys.stderr)
        return 2

    jcfg = load_judgment()
    pcfg = jcfg.point(PointId.A_APP_CONTEXT)
    provider = build_judgment_provider(
        jcfg, pcfg, force_offline=args.offline, use_cache=not args.no_cache
    )

    focus = FocusInfo(
        app_name=args.app, window_title=args.title, role="frame", pid=None, t_ms=0.0
    )
    t0 = time.monotonic()
    answers = provider.judge(point_a.build_request(focus, pcfg))
    ctx = point_a.interpret(answers, pcfg)
    ms = (time.monotonic() - t0) * 1000

    gate = "act" if ctx.confidence >= pcfg.act_threshold else (
        "confirm" if ctx.confidence >= pcfg.confirm_threshold else "fall back"
    )
    print(f"app_class        {ctx.app_class.value}")
    print(f"confidence       {ctx.confidence:.3f}   ({gate}, threshold {pcfg.act_threshold})")
    print(f"source           {ctx.source.value}")
    print(f"text_entry       {ctx.text_entry}")
    print(f"fullscreen_media {ctx.fullscreen_media}")
    print(f"latency          {ms:.0f} ms")
    if args.verbose and ctx.probabilities:
        print("probabilities:")
        for k, v in sorted(ctx.probabilities.items(), key=lambda kv: -kv[1])[:5]:
            print(f"  {k:<18} {v:.3f}")
    if not judgment_available(args.offline):
        print("\n(no TYPESAFE_API_KEY or offline requested — rules provider)")
    return 0


def _judge_tile_role(args: argparse.Namespace) -> int:
    """Jev point B — where should this window be placed?"""
    from app.decision.judgment_config import load as load_judgment
    from app.decision.points import b_tile_role
    from app.decision.questions import PointId
    from app.runtime.wiring import build_judgment_provider
    from app.types import AppClass, Rect, WindowInfo

    jcfg = load_judgment()
    pcfg = jcfg.point(PointId.B_TILE_ROLE)
    provider = build_judgment_provider(
        jcfg, pcfg, force_offline=args.offline, use_cache=not args.no_cache
    )

    try:
        app_class = AppClass(args.kind)
    except ValueError:
        print(f"unknown --kind; one of: {', '.join(c.value for c in AppClass)}", file=sys.stderr)
        return 2

    window = WindowInfo("1", args.app, args.title, Rect(0, 0, 800, 600), 0, 0, False)
    t0 = time.monotonic()
    answers = provider.judge(b_tile_role.build_request(window, app_class, None, pcfg))
    s = b_tile_role.interpret(answers, pcfg)
    ms = (time.monotonic() - t0) * 1000

    print(f"zone         {s.zone.value}")
    print(f"confidence   {s.confidence:.3f}   "
          f"({'pre-highlight' if not s.provisional else 'suggest only'}, "
          f"threshold {pcfg.act_threshold})")
    print(f"source       {s.source.value}")
    print(f"latency      {ms:.0f} ms")
    return 0


def cmd_watch_focus(args: argparse.Namespace) -> int:
    """Print the focused window as you alt-tab, optionally classifying each one."""
    _load_env()

    from app.effectors.backends.atspi_focus import AtspiFocusSource

    classify = None
    if args.jev:
        from app.decision.broker import JudgmentBroker
        from app.decision.judgment_config import load as load_judgment
        from app.decision.points import a_app_context as point_a
        from app.decision.questions import PointId
        from app.runtime.wiring import build_judgment_provider

        jcfg = load_judgment()
        pcfg = jcfg.point(PointId.A_APP_CONTEXT)
        broker = JudgmentBroker(build_judgment_provider(jcfg, pcfg, force_offline=args.offline))

        def classify(focus):
            answers = broker.judge_now(point_a.build_request(focus, pcfg))
            return point_a.interpret(answers, pcfg)

    source = AtspiFocusSource()
    seen = 0

    def on_focus(focus) -> None:
        nonlocal seen
        seen += 1
        line = f"{focus.app_name:<22} {focus.window_title[:58]:<60}"
        if classify is not None:
            try:
                ctx = classify(focus)
                line += f" -> {ctx.app_class.value:<15} {ctx.confidence:.2f} [{ctx.source.value}]"
            except Exception as e:  # noqa: BLE001
                line += f" -> ERROR {type(e).__name__}: {e}"
        print(line, flush=True)

    source.subscribe(on_focus)
    current = source.current()
    if current:
        print(f"(startup, may be inaccurate — AT-SPI ACTIVE is per-application)", flush=True)
        on_focus(current)
    print("watching window:activate — alt-tab between windows. ctrl-c to stop.", flush=True)

    try:
        source.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
    print(f"\n{seen} focus change(s)")
    return 0


# --------------------------------------------------------------------------------------
# record / bench  (P2)
# --------------------------------------------------------------------------------------


def _camera_source(args: argparse.Namespace, **kw):
    from app.config import load as load_config
    from app.perception.backends.mediapipe_camera import MediaPipeCameraSource

    cfg = load_config().perception
    return MediaPipeCameraSource(cfg, device=args.device, **kw)


def cmd_record(args: argparse.Namespace) -> int:
    """Record a landmark fixture. Recording is not a separate code path — it wraps whatever source
    you were already running, so a fixture is by construction what the system actually saw.

    `--synthetic <generator>` materializes an analytic stream instead of opening the camera. Those
    fixtures are clearly marked as synthetic in their sidecar: they exercise known-correct
    kinematics, which is what the arbiter needs, but they are NOT a substitute for real hands and
    the corpus should say so."""
    from pathlib import Path

    from app.perception.ndjson import NdjsonWriter
    from app.perception.source import TeeSource

    out = Path(args.output or f"fixtures/sessions/{args.label}.ndjson.gz")
    if args.synthetic:
        from app.perception.backends.synthetic import GENERATORS

        if args.synthetic not in GENERATORS:
            print(f"unknown generator. available: {', '.join(sorted(GENERATORS))}", file=sys.stderr)
            return 2
        source = GENERATORS[args.synthetic](duration_s=args.seconds)
    else:
        source = _camera_source(args, max_seconds=args.seconds)
    writer = NdjsonWriter(out, source.meta)
    tee = TeeSource(source, writer)

    print(f"recording '{args.label}' for {args.seconds}s to {out} — ctrl-c to stop early")
    n = with_hands = 0
    armed = not args.wait_for_hand
    streak = 0
    try:
        for frame in tee.frames():
            # Wait until a hand is actually visible before counting the take. Recording blind
            # produced a 147-frame fixture with zero hands in it — the camera was fine, the hand
            # simply was not in frame yet.
            if not armed:
                streak = streak + 1 if frame.hands else 0
                if streak >= args.arm_frames:
                    armed = True
                    print("\r  hand detected — GO" + " " * 30, flush=True)
                elif n % 10 == 0:
                    print("\r  waiting for a hand in frame…", end="", flush=True)
                n += 1
                continue
            n += 1
            with_hands += bool(frame.hands)
            if n % 10 == 0:
                bar = "#" * min(40, with_hands)
                print(f"\r  {with_hands:>4} frames with hands {bar}", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        tee.close()
    print(f"\r  {n} frames, {with_hands} with hands ({with_hands / n:.0%})" if n else "no frames")
    print(f"wrote {out}")
    return 0


def cmd_record_pose(args: argparse.Namespace) -> int:
    """Capture a held pose into the per-user template library."""
    from app.config import load as load_config
    from app.features.extract import ExtractState, extract
    from app.poses import PoseLibrary, average

    cfg = load_config()
    source = _camera_source(args, max_seconds=args.seconds)
    es = ExtractState()
    angle_samples: list[tuple[float, ...]] = []
    openness: list[float] = []

    print(f"hold the '{args.name}' pose still — sampling for {args.seconds}s")
    try:
        for frame in source.frames():
            es, ff = extract(es, frame, cfg.precision)
            h = ff.right or ff.left
            # Only sample while the hand is actually still: a template averaged over a moving hand
            # is a template of the motion, not of the pose.
            # Looser than the mode guard: gathering samples and recognising a
            # deliberate pose are different questions.
            if h is not None and h.palm_speed < cfg.macro.sample_max_speed:
                angle_samples.append(h.joint_angles)
                openness.append(h.openness)
                print(f"\r  {len(angle_samples)} samples", end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        source.close()

    print()
    if len(angle_samples) < args.min_samples:
        print(
            f"only {len(angle_samples)} still samples (need {args.min_samples}) — "
            f"nothing written. Hold the pose steadier, or check the hand is detected "
            f"(`python tools/check_frame.py`).",
            file=sys.stderr,
        )
        return 1

    library = PoseLibrary.load()
    template = average(args.name, angle_samples, openness, note=args.note)
    path = library.with_template(template).save()

    # Report how well the new pose separates from the ones already stored — a template that
    # matches an existing pose at 0.98 will fire the wrong macro, and it is much cheaper to find
    # that out now than from a misfire later.
    from app.poses import similarity

    clashes = [
        (t.name, similarity(template.angles, t.angles))
        for t in library.templates
        if t.name != template.name
    ]
    print(f"saved '{args.name}' from {len(angle_samples)} samples to {path}")
    if clashes:
        print("  similarity to existing poses (>= template_cosine_min would collide):")
        for name, score in sorted(clashes, key=lambda kv: -kv[1]):
            flag = "  <-- TOO SIMILAR" if score >= cfg.macro.template_cosine_min else ""
            print(f"    {name:<18} {score:.3f}{flag}")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Measure the real latency ladder. The scope doc targets <50ms glass-to-cursor; one 30fps
    frame interval is already 33ms, so this is measured before anything depends on it."""
    import statistics

    source = _camera_source(args, max_seconds=args.seconds)
    warmup_gaps: list[float] = []
    gaps: list[float] = []
    n = with_hands = 0
    t_prev = None
    print(f"benchmarking {args.seconds}s — first {args.warmup} frames counted separately…")
    try:
        loop_start = time.monotonic()
        steady_start = None
        for frame in source.frames():
            now = time.monotonic()
            if t_prev is not None:
                # MediaPipe's first inferences pay model load and XNNPACK warm-up — several times
                # the steady-state cost. Averaging them in makes the pipeline look twice as slow
                # as it is, which is how the first version of this bench reported 87 ms for
                # something that actually runs at 33 ms.
                (warmup_gaps if n <= args.warmup else gaps).append((now - t_prev) * 1000.0)
            if n == args.warmup:
                steady_start = now
            t_prev = now
            n += 1
            with_hands += bool(frame.hands)
        wall = time.monotonic() - (steady_start or loop_start)
        steady_n = max(1, n - args.warmup)
    finally:
        source.close()

    if not gaps:
        print("no steady-state frames captured — try a longer --seconds")
        return 1
    gaps.sort()
    pct = lambda q: gaps[min(len(gaps) - 1, int(len(gaps) * q))]  # noqa: E731
    med = statistics.median(gaps)
    budget = load_config_latency()

    timings = getattr(source, "timings", None)
    if timings is not None and timings.inference:
        print("\n  stage              p50        p95      (steady state)")
        for name, series in (
            ("capture", timings.capture),
            ("convert", timings.convert),
            ("inference", timings.inference),
            ("assemble", timings.assemble),
        ):
            s = sorted(series[args.warmup:]) or sorted(series)
            if not s:
                continue
            print(f"  {name:<16} {statistics.median(s):6.1f} ms  "
                  f"{s[min(len(s) - 1, int(len(s) * 0.95))]:6.1f} ms")

    print(f"\n  frames             {n}  ({with_hands} with hands)")
    if warmup_gaps:
        print(f"  warm-up            {len(warmup_gaps)} frames, "
              f"max {max(warmup_gaps):.0f} ms  (model load + XNNPACK)")
    print(f"  sustained fps      {steady_n / wall:.1f}")
    print(f"  frame interval     p50 {med:.1f} ms · p95 {pct(0.95):.1f} ms · max {max(gaps):.1f} ms")
    headroom = budget - med
    print(f"\n  capture + inference is {med:.0f} ms of a {budget:.0f} ms glass-to-cursor budget.")
    if headroom > 0:
        print(f"  {headroom:.0f} ms left for features, arbitration and injection.")
    else:
        print(f"  ALREADY OVER by {-headroom:.0f} ms before features or injection. "
              f"Record the real number in the README rather than the target.")
    return 0


def load_config_latency() -> float:
    from app.config import load as load_config

    return load_config().latency.precision_budget_ms


def cmd_golden(args: argparse.Namespace) -> int:
    """Regenerate or verify the golden intent streams."""
    from app.runtime import golden

    failures = 0
    for fixture in golden.fixtures():
        if args.update:
            path = golden.update(fixture)
            print(f"  wrote {path.name}")
            continue
        ok, expected, actual = golden.check(fixture)
        if ok:
            print(f"  ok    {fixture.name}")
            continue
        failures += 1
        print(f"  DIFF  {fixture.name}")
        exp, act = expected.splitlines(), actual.splitlines()
        for i in range(max(len(exp), len(act))):
            e = exp[i] if i < len(exp) else "(missing)"
            a = act[i] if i < len(act) else "(missing)"
            if e != a:
                print(f"        - {e}")
                print(f"        + {a}")
                break
    if not args.update:
        print(f"\n{len(golden.fixtures()) - failures}/{len(golden.fixtures())} golden streams match")
    return 1 if failures else 0


def _build_context_service(args: argparse.Namespace):
    """Focus watcher + judgment broker + prefetch, feeding DecisionContext into the loop.

    Degrades rather than failing: if AT-SPI is unavailable the service still runs, it just never
    learns an app class, and every guard gating on one declines instead of guessing.
    """
    from app.context.store import ContextService
    from app.decision.broker import JudgmentBroker
    from app.decision.cache import SqliteCache
    from app.decision.judgment_config import load as load_judgment
    from app.decision.questions import PointId
    from app.runtime.wiring import build_judgment_provider

    jcfg = load_judgment()
    cache = SqliteCache()
    provider = build_judgment_provider(
        jcfg, jcfg.point(PointId.A_APP_CONTEXT), force_offline=args.offline, cache=cache
    )

    focus = None
    try:
        from app.effectors.backends.atspi_focus import AtspiFocusSource

        focus = AtspiFocusSource()
    except Exception as e:  # noqa: BLE001
        print(f"  (no AT-SPI focus source: {type(e).__name__} — app-aware behaviour disabled)",
              file=sys.stderr)

    return ContextService(JudgmentBroker(provider), jcfg, focus_source=focus, cache=cache)


def cmd_run(args: argparse.Namespace) -> int:
    """The real thing: camera -> features -> arbiter -> intents -> effectors."""
    _load_env()

    from app.effectors.ports import EffectorSet
    from app.runtime.pipeline import run_pipeline

    from app.hud import overlay as hud_overlay

    effectors, journal = _build_effectors(args.effector)
    hud = hud_overlay.build(args.hud)
    if hud is not None and effectors.overlay is None:
        effectors.overlay = hud
    context_service = None if args.no_context else _build_context_service(args)
    source = _camera_source(args, max_seconds=args.seconds)

    print(f"running with effector={args.effector} hud={args.hud} "
          f"context={'on' if context_service else 'off'} — ctrl-c to stop")
    try:
        if context_service is not None:
            context_service.start()
        result = run_pipeline(
            source, effectors, dump_intents=args.verbose, hud=hud,
            record_misfires=True, context_service=context_service,
        )
    except KeyboardInterrupt:
        result = None
    finally:
        source.close()
        if context_service is not None:
            context_service.stop()
        if hud is not None:
            hud.close()
        effectors.close()
    if result is not None:
        print(f"\n  frames      {result.frames}")
        print(f"  transitions {[m.value for _, m in result.transitions]}")
        print(f"  intents     {len(result.intents)}")
        if result.report.unsupported:
            print(f"  unsupported {sorted(set(result.report.unsupported))}")
        if result.report.failed:
            print(f"  failed      {result.report.failed[:3]}")
        if result.watchdog_fires:
            print(f"  panic       {result.watchdog_fires} watchdog fire(s)")
        if result.misfire_dumps:
            print(f"  misfires    {len(result.misfire_dumps)} recorded — "
                  f"run `python main.py postmortem` to analyse them")
    return 0


def cmd_teach(args: argparse.Namespace) -> int:
    """Teach-by-demonstration: record a workflow, clean it with Jev point D, save it as a macro."""
    _load_env()

    import json
    from pathlib import Path as _Path

    from app.decision.judgment_config import load as load_judgment
    from app.decision.points import d_demo_cleanup
    from app.decision.questions import PointId
    from app.poses import PoseLibrary
    from app.runtime.wiring import build_judgment_provider
    from app.ui_actions import describe

    macros_path = REPO_ROOT / "config" / "macros.json"
    existing_raw = json.loads(macros_path.read_text()) if macros_path.exists() else {"macros": {}}

    try:
        from app.effectors.backends.atspi_recorder import AtspiRecorder
    except Exception as e:  # noqa: BLE001
        print(f"AT-SPI recorder unavailable: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    recorder = AtspiRecorder()
    print(f"recording '{args.name}' for {args.seconds}s — perform the workflow now.")
    print("(clicks and window changes are captured; keystrokes deliberately are not)")
    recorder.start()
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(0.2)
            print(f"\r  {len(recorder.record_actions())} steps", end="", flush=True)
    except KeyboardInterrupt:
        pass
    actions = list(recorder.stop())
    print(f"\r  recorded {len(actions)} steps" + " " * 20)
    if not actions:
        print("nothing recorded — is the accessibility bus reachable?", file=sys.stderr)
        return 1

    jcfg = load_judgment()
    pcfg = jcfg.point(PointId.D_DEMO_CLEANUP)
    provider = build_judgment_provider(jcfg, pcfg, force_offline=args.offline, use_cache=False)

    bound = {m.get("pose") for m in existing_raw["macros"].values()}
    unbound = [p.name for p in PoseLibrary.load().templates if p.name not in bound]
    existing = {k: [] for k in existing_raw["macros"]}

    cleaned = d_demo_cleanup.interpret(
        provider.judge(d_demo_cleanup.build_request(args.name, actions, existing, unbound, pcfg)),
        args.name, actions, existing, pcfg,
    )

    print(f"\nkept {len(cleaned.steps)} step(s):")
    for s in cleaned.steps:
        print(f"   {describe(s)}")
    if cleaned.dropped:
        print(f"dropped {len(cleaned.dropped)} as incidental:")
        for s in cleaned.dropped:
            print(f"   {describe(s)}")
    if cleaned.is_duplicate:
        print(f"\nthis looks like a duplicate of '{cleaned.duplicate_of}' — not saved.")
        return 0

    pose = cleaned.suggested_pose or (unbound[0] if unbound else "")
    if not pose:
        print("\nno unbound pose to trigger it — record one with `record-pose <name>` first.",
              file=sys.stderr)
        return 1

    existing_raw["macros"][args.name] = {
        "pose": pose,
        "steps": [
            {"verb": s.verb, "role": s.target_role, "name": s.target_name, "app": s.app_name}
            for s in cleaned.steps
        ],
    }
    macros_path.write_text(json.dumps(existing_raw, indent=2) + "\n")
    print(f"\nsaved '{args.name}' bound to the '{pose}' pose -> {macros_path}")
    return 0


def cmd_postmortem(args: argparse.Namespace) -> int:
    """Jev point F — analyse recorded misfires offline.

    Strictly batched: no latency budget, no rate-limit pressure. Run it nightly, or by hand after
    a session that went badly.
    """
    _load_env()

    import json

    from app.decision.judgment_config import load as load_judgment
    from app.decision.points import f_misfire
    from app.decision.questions import PointId
    from app.runtime.wiring import build_judgment_provider
    from app.telemetry.ring import MISFIRE_DIR, pending

    paths = pending(args.directory or MISFIRE_DIR)
    if not paths:
        print(f"no unanalysed misfires in {args.directory or MISFIRE_DIR}")
        return 0

    jcfg = load_judgment()
    pcfg = jcfg.point(PointId.F_MISFIRE)
    provider = build_judgment_provider(jcfg, pcfg, force_offline=args.offline, use_cache=False)

    causes: dict[str, int] = {}
    analysed = 0
    for path in paths[: args.limit]:
        data = json.loads(path.read_text(encoding="utf-8"))
        req = f_misfire.build_request(data["state"], pcfg, key=path.stem)
        try:
            verdict = f_misfire.interpret(provider.judge(req), pcfg)
        except Exception as e:  # noqa: BLE001
            print(f"  {path.name}: ERROR {type(e).__name__}: {e}")
            continue
        analysed += 1
        path.with_suffix(".verdict.json").write_text(
            json.dumps(
                {
                    "unintended": verdict.unintended,
                    "confidence": round(verdict.confidence, 3),
                    "cause": verdict.cause,
                    "cause_confidence": round(verdict.cause_confidence, 3),
                    "source": verdict.source.value,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if verdict.unintended:
            causes[verdict.cause] = causes.get(verdict.cause, 0) + 1
        mark = "MISFIRE" if verdict.unintended else "ok     "
        print(f"  {mark}  {verdict.cause:<18} conf={verdict.cause_confidence:.2f} "
              f"[{verdict.source.value}]  {path.name}")

    print(f"\nanalysed {analysed} episode(s)")
    if causes:
        print("cause distribution:")
        for cause, n in sorted(causes.items(), key=lambda kv: -kv[1]):
            print(f"  {cause:<20} {n}")
        top = max(causes, key=causes.get)
        hint = {
            "threshold_too_low": "raise gross.speed / gross.coherence in config/default.toml",
            "pose_ambiguity": "re-record the colliding poses, or raise macro.template_cosine_min",
            "grammar_misparse": "lengthen the grammar window or require a clearer separator",
            "context_wrong": "check Jev point A accuracy for the applications involved",
        }.get(top)
        if hint:
            print(f"\nmost common cause is '{top}' — {hint}")
    return 0


def _not_yet(phase: str):
    def run(args: argparse.Namespace) -> int:
        print(f"not implemented yet — lands in {phase}. See TODO.md.", file=sys.stderr)
        return 2

    return run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gesture-os", description="Unified Gesture Desktop OS")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check this machine")
    d.add_argument("--jev", action="store_true", help="also make one live Jev call")
    d.set_defaults(func=cmd_doctor)

    r = sub.add_parser("replay", help="run a fixture or synthetic stream through the pipeline")
    r.add_argument("fixture", nargs="?", help="path to a .ndjson(.gz) fixture")
    r.add_argument("--synthetic", help="use a generator instead of a file")
    r.add_argument("--effector", default="recording", help="recording|null|uinput")
    r.add_argument("--realtime", action="store_true", help="pace to recorded timestamps")
    r.add_argument("--dump-intents", action="store_true")
    r.set_defaults(func=cmd_replay)

    j = sub.add_parser("judge", help="ask one Jev point a question")
    j.add_argument("point", choices=["app-context", "tile-role"], help="which integration point")
    j.add_argument("--app", required=True, help="application name")
    j.add_argument("--title", default="", help="window title")
    j.add_argument("--offline", action="store_true", help="do not touch the network")
    j.add_argument("--no-cache", action="store_true", help="bypass the cache to see what the provider really says")
    j.add_argument("-v", "--verbose", action="store_true")
    j.add_argument("--kind", default="unknown", help="tile-role: the application class from point A")
    j.set_defaults(func=cmd_judge)

    w = sub.add_parser("watch-focus", help="print the focused window as you alt-tab")
    w.add_argument("--jev", action="store_true", help="also classify each window")
    w.add_argument("--offline", action="store_true")
    w.set_defaults(func=cmd_watch_focus)

    rec = sub.add_parser("record", help="record a landmark fixture from the camera")
    rec.add_argument("label", help="fixture name, e.g. swipe-left")
    rec.add_argument("--seconds", type=float, default=10.0)
    rec.add_argument("--device", default=0)
    rec.add_argument("--output")
    rec.add_argument("--synthetic", help="materialize a generator instead of using the camera")
    rec.add_argument("--wait-for-hand", action="store_true",
                     help="do not start counting until a hand is actually visible")
    rec.add_argument("--arm-frames", type=int, default=3)
    rec.set_defaults(func=cmd_record)

    rp = sub.add_parser("record-pose", help="capture a held pose into the template library")
    rp.add_argument("name", help="pose name, e.g. fist")
    rp.add_argument("--seconds", type=float, default=5.0)
    rp.add_argument("--device", default=0)
    rp.add_argument("--min-samples", type=int, default=10)
    rp.add_argument("--note", default="")
    rp.set_defaults(func=cmd_record_pose)

    b = sub.add_parser("bench", help="measure the capture+inference latency ladder")
    b.add_argument("--seconds", type=float, default=12.0)
    b.add_argument("--device", default=0)
    b.add_argument("--warmup", type=int, default=15, help="frames excluded from the steady state")
    b.set_defaults(func=cmd_bench)

    gold = sub.add_parser("golden", help="regenerate or check golden intent streams")
    gold.add_argument("--update", action="store_true", help="rewrite them — ALWAYS review the diff")
    gold.set_defaults(func=cmd_golden)

    run = sub.add_parser("run", help="run the real thing")
    run.add_argument("--effector", default="recording", help="recording|null|uinput")
    run.add_argument("--device", default=0)
    run.add_argument("--seconds", type=float, default=30.0)
    run.add_argument("-v", "--verbose", action="store_true", help="print every intent")
    run.add_argument("--offline", action="store_true", help="rules provider only, no network")
    run.add_argument("--hud", default="terminal", help="terminal|layer|none")
    run.add_argument("--no-context", action="store_true",
                     help="run without the Jev context service (no app-aware behaviour)")
    run.set_defaults(func=cmd_run)

    th = sub.add_parser("teach", help="record a workflow and bind it to a pose (Jev point D)")
    th.add_argument("name", help="what to call this workflow")
    th.add_argument("--seconds", type=float, default=20.0)
    th.add_argument("--offline", action="store_true")
    th.set_defaults(func=cmd_teach)

    pm = sub.add_parser("postmortem", help="analyse recorded misfires (Jev point F)")
    pm.add_argument("--directory", type=Path)
    pm.add_argument("--offline", action="store_true")
    pm.add_argument("--limit", type=int, default=100)
    pm.set_defaults(func=cmd_postmortem)

    for name, phase, helptext in (
        ("calibrate", "P5", "per-user threshold calibration wizard"),
    ):
        s = sub.add_parser(name, help=helptext)
        s.set_defaults(func=_not_yet(phase))

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
