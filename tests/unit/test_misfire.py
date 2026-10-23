"""Jev point F — misfire post-mortem.

The rendering is the load-bearing part. Jev cannot count, do arithmetic, or compare numbers, so
every number that matters must become a word in code BEFORE the state is built. These tests pin
that, and pin the rules fallback so the nightly batch still produces something when Jev is down.
"""

from app.config import load
from app.decision.backends.rules import RuleProvider
from app.decision.judgment_config import load as load_judgment
from app.decision.points import f_misfire
from app.decision.questions import PointId
from app.intents import Direction, SendToWorkspace
from app.telemetry.ring import Episode, EventRing, render_episode
from app.types import BimanualFeatures, FeatureFrame, HandFeatures, ModeId

CFG = load(use_env=False)
PCFG = load_judgment().point(PointId.F_MISFIRE)


def _hand(speed=0.0, coherence=0.0, openness=1.0):
    return HandFeatures(
        palm_centroid=(0.5, 0.5, 0.0), palm_velocity=(0.0, 0.0, 0.0), palm_speed=speed,
        palm_dir_coherence=coherence, fingertip_speeds=(0.0,) * 5, openness=openness,
        joint_angles=(0.1,) * 15, palm_normal=(0.0, 0.0, 1.0), wrist_roll=0.0,
        pinch_thumb_index=1.0, pinch_thumb_middle=1.0, index_extension=0.0, tracking_score=1.0,
    )


def _episodes(mode=ModeId.GROSS, intents=(SendToWorkspace(Direction.LEFT),), speed=4.0):
    ring = EventRing()
    for i in range(20):
        f = FeatureFrame(t_ms=i * 50.0, right=_hand(speed=speed, coherence=0.95), left=None, bimanual=None)
        ring.push(i * 50.0, mode, f, None, intents if i == 10 else ())
    return ring.window(1000.0)


def test_the_state_sent_to_jev_contains_no_raw_numbers():
    # The single most important property of this integration. A state full of velocities would ask
    # Jev to do exactly what it documents itself as bad at.
    state = render_episode(_episodes(), CFG)
    blob = " ".join(state.values())
    digits = [c for c in blob if c.isdigit()]
    # Timeline timestamps like "at 0.5s" are the only numerals, and they are ordinal prose.
    assert all(f"at {d}" in blob or f"{d}." in blob or f".{d}" in blob for d in set(digits)), blob


def test_movement_and_direction_are_described_in_words():
    state = render_episode(_episodes(speed=CFG.gross.speed * 3), CFG)
    assert state["hand_movement"] in {
        "almost stationary", "moving slowly", "moving moderately", "moving fast", "moving very fast"
    }
    assert "direction" in state["hand_direction"]


def test_actions_taken_are_named_so_jev_can_tell_action_from_inaction():
    acted = render_episode(_episodes(), CFG)
    assert "SendToWorkspace" in acted["actions_the_system_took"]
    quiet = render_episode(_episodes(mode=ModeId.IDLE, intents=()), CFG)
    assert quiet["actions_the_system_took"] == "no action was taken"


def test_an_empty_ring_still_renders_something_sendable():
    assert render_episode([], CFG)["summary"]


def test_the_ring_only_returns_the_lookback_window():
    ring = EventRing(lookback_ms=500.0)
    for i in range(40):
        f = FeatureFrame(t_ms=i * 50.0, right=_hand(), left=None, bimanual=None)
        ring.push(i * 50.0, ModeId.IDLE, f)
    window = ring.window(2000.0)
    assert all(e.t_ms >= 1500.0 for e in window)


# --- rules fallback ----------------------------------------------------------------------

def _judge(state):
    return f_misfire.interpret(
        RuleProvider().judge(f_misfire.build_request(state, PCFG, key="k")), PCFG
    )


def test_a_panic_after_no_action_is_not_treated_as_a_misfire():
    # The user was disengaging, not reacting. Counting it would poison the cause distribution.
    v = _judge(render_episode(_episodes(mode=ModeId.IDLE, intents=()), CFG))
    assert not v.unintended


def test_a_panic_right_after_an_action_is_treated_as_a_misfire():
    v = _judge(render_episode(_episodes(), CFG))
    assert v.unintended


def test_the_fallback_says_unclear_rather_than_guessing_a_cause():
    # A fast, straight, committed-looking gesture that the user then rejected: a regex table
    # genuinely cannot tell why. Inventing a plausible cause would pollute the distribution the
    # thresholds are tuned from, which is the whole output of this integration.
    v = _judge(render_episode(_episodes(speed=CFG.gross.speed * 3), CFG))
    assert v.unintended
    assert v.cause == "unclear" and v.cause_confidence == 0.0


def test_the_fallback_does_identify_the_cause_it_can_actually_see():
    # Erratic direction plus an action taken is the one pattern a regex can legitimately call.
    state = render_episode(_episodes(), CFG)
    state["hand_direction"] = "changing direction erratically"
    v = _judge(state)
    assert v.cause == "threshold_too_low"


def test_the_fallback_answers_every_question_so_the_batch_never_stalls():
    answers = RuleProvider().judge(
        f_misfire.build_request(render_episode(_episodes(), CFG), PCFG, key="k")
    )
    assert set(answers) == set(PCFG.questions)


def test_cause_is_always_one_of_the_declared_options():
    options = set(PCFG.questions["cause"].options)
    for episodes in (_episodes(), _episodes(mode=ModeId.IDLE, intents=()), _episodes(speed=0.0)):
        assert _judge(render_episode(episodes, CFG)).cause in options
