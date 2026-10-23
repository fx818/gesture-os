# Unified Gesture Desktop OS

One RGB webcam replaces the mouse, keyboard shortcuts and window manager. No gloves, no wands, no
depth sensor. Full scope in [`docs/scope.md`](docs/scope.md); build plan and rationale in the ADRs.

## The idea

A window manager driven by sweeps, a gesture-to-macro engine, and a precision accessibility pointer
are all the same hand-tracking feed read at different timescales. A held pose is a macro trigger. A
slow continuous motion is a cursor. A fast committed motion is a window command. One arbitration
engine classifies intent frame by frame and routes to the right subsystem — **that engine, not any
single mode, is the core deliverable.**

## Two brains, deliberately separated

| | Arbitration engine | Jev (TypeSafe) |
|---|---|---|
| Decides | *that* something happened | *what it means* |
| Input | hand landmarks, numeric | app name, window title, text |
| Runs | every frame, on-device | on discrete events, over the network |
| Latency | sub-millisecond | ~150 ms |
| If it's unavailable | nothing works | one feature degrades |

Jev is a classifier that generates no text at all. It cannot see the camera and cannot do
arithmetic, so it is never on the per-frame path — see [ADR-0001](docs/adr/0001-jev-off-realtime-path.md).
It answers questions like "what kind of application is this?" and "was that a misfire?", cached and
confidence-gated, while the engine stays local and numeric.

## Status

Phases 0–4 complete: the full pipeline runs end to end, `make ci` is green (206 tests, no camera
and no network), and Jev point A is live and calibrated. See [TODO.md](TODO.md) for exactly where
things stand and what is blocked.

### Measured performance (this machine, 2026-09-18)

| stage | p50 |
|---|---|
| sensor cadence | **65 ms** — hard floor, see below |
| inference (`num_hands=1`) | 34 ms, overlapped with the sensor wait |
| convert + assemble | <1 ms |
| **end to end** | **~64 ms** (15.5 fps) |

**These numbers are disputed.** They were measured in a near-dark room (mean frame luminance
8.9/255), which is exactly when a webcam extends exposure and halves its frame rate. The claim that
the scope doc's 50 ms target is unreachable is **not established** and needs re-measuring with the
lights on — see the correction at the top of
[ADR-0006](docs/adr/0006-the-camera-is-the-bottleneck.md).

Hand tracking also does not work at this light level: 0/40 frames detected across every
configuration tried, with a hand plainly in frame.

Run `python main.py bench` on your own camera before assuming these apply; if it reports a 33 ms
cadence, the whole picture changes. Tracking one hand rather than two is the largest software lever
(30 ms vs 67 ms of inference) — [ADR-0005](docs/adr/0005-hand-count-is-the-latency-lever.md).

## How to actually use it

These are not preferences. Each one is the difference between a gesture working and not, and each
was found the hard way — measured, not guessed.

### Swipes need an asymmetric stroke

**Fast sweep out, then bring your hand back slowly** (or drop it out of frame), then repeat.

A rhythmic back-and-forth wave does not register at all. The engine requires sustained motion in
one direction across the whole window, and a return stroke travelling as fast as the swipe cancels
it. Measured: a symmetric wave produced 71 leftward and 71 rightward frames and **zero** detected
swipes; the same gesture with a slow return produced **five out of five**.

### The panic gesture needs both hands clearly in frame

**Raise both palms with your arms extended**, not close to the camera.

At normal working distance both hands fit in frame in only 3 of 71 frames — a laptop webcam is
narrow and you sit close. With arms extended it is 100%. That constraint is arguably right for a
kill switch: it has to be unmistakable.

### Light yourself, not the lens

Any bright source *behind* you or *pointing at* the camera destroys detection — the sensor meters
on the light and your hand becomes a silhouette. A ceiling full of tube lights in frame does the
same. Aim the camera at yourself, put light to the side or bounced, and run:

```bash
python tools/calibrate_camera.py --write    # picks exposure by DETECTION rate, not brightness
```

There is no universally correct exposure. The same value went from 12/12 detection to 0/12 within
an hour as the room changed.

### Hands on the keyboard are invisible

Typing and reaching across the desk happen below the camera's field of view, so they cannot trigger
anything. That is a feature — it means normal work carries no false-positive risk — but it also
means gestures must be made **up, in front of the camera**, deliberately.

### Record your own poses

The pose library ships empty on purpose. Your fist is not my fist.

```bash
python main.py record-pose fist --seconds 6
python main.py record-pose point --seconds 6
```

It warns if a new pose collides with one already stored.

## Requirements

Ubuntu 26.04 / GNOME Shell 50 / Wayland. A 720p+ webcam. Python 3.14.

```bash
sudo apt install -y python3-evdev python3-venv
python3 -m venv --system-site-packages venv    # required: gi and evdev are system packages
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # add your TYPESAFE_API_KEY (optional — it runs without one)
make doctor
```

Input injection needs `/dev/uinput`:

```bash
sudo tee /etc/udev/rules.d/60-gesture-os.rules <<'RULE'
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"
RULE
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG input "$USER"    # then log out and back in
```

## Running it

```bash
source venv/bin/activate
make doctor            # camera, uinput, AT-SPI, mediapipe, key — checks THIS machine
python main.py run     # 30 seconds, camera on, desktop untouched
```

Two defaults decide what `run` actually does, and both are deliberately timid:

- **`--effector` is `recording`, not `uinput`.** The whole pipeline runs and every intent is
  logged, but nothing reaches the desktop. Driving the machine for real is `--effector uinput`,
  which needs the udev rule above and a logout first.
- **`--seconds` is 30.** Long enough to see whether a gesture fires, short enough that a session
  gone wrong ends by itself. Pass `--seconds 3600` for a real sitting.

A ladder from safe to live:

```bash
python main.py run -v                                # watch intents, nothing executed
python main.py run --offline --no-context            # rules provider, Jev never called
python main.py run --effector uinput --hud terminal  # live, after the re-login
```

Before that last one: the downward sweep is bound to `Suspend`, and down is the direction a hand
moves involuntarily — falling back to the desk, or dropping at the end of some other gesture. No
negative fixture measures that binding yet ([ADR-0011](docs/adr/0011-a-negative-fixture-that-was-not-negative.md)),
so run the logging form for a while and confirm `Suspend` never appears in the stream before
handing the system real effectors.

## Development without hardware

After Phase 2 the camera is optional. Landmark streams are recorded once to NDJSON and replayed
deterministically, so the entire engine develops and tests from files:

```bash
make ci                                  # no camera, no display, no network
python main.py replay fixtures/sessions/swipes-lr-10.ndjson.gz --dump-intents
```

It also runs fully offline — `--offline` swaps Jev for a local rules provider behind the same
interface, and every test in `make ci` uses that path.
