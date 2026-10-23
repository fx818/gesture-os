"""The fixture format is the project's memory. If a roundtrip is lossy, every golden intent
stream silently drifts, and it also breaks the SubprocessLandmarkSource escape hatch, which uses
this same format as its wire protocol."""

import json
from pathlib import Path

from app.perception.backends.synthetic import GENERATORS, swipe_left
from app.perception.ndjson import (
    FileLandmarkSource,
    NdjsonWriter,
    frame_from_dict,
    frame_to_dict,
    meta_path,
    read_meta,
)
from app.perception.source import SourceMeta, TeeSource
from app.types import Handedness


def _write(tmp_path: Path, source, name="s.ndjson.gz"):
    path = tmp_path / name
    w = NdjsonWriter(path, source.meta)
    for f in source.frames():
        w.write(f)
    w.close()
    return path


def test_single_frame_roundtrips_exactly(tmp_path):
    original = next(iter(swipe_left().frames()))
    restored = frame_from_dict(json.loads(json.dumps(frame_to_dict(original))))
    assert restored.seq == original.seq
    assert restored.t_ms == original.t_ms
    assert restored.hands[0].handedness is original.hands[0].handedness
    # 5 decimal places on normalized coords is ~0.06px at 1080p — below the noise floor of the
    # landmark model, and it keeps fixtures small enough to commit.
    for a, b in zip(restored.hands[0].landmarks, original.hands[0].landmarks):
        assert a == tuple(round(c, 5) for c in b)


def test_whole_stream_roundtrips_through_a_gzipped_file(tmp_path):
    src = swipe_left()
    expected = list(src.frames())
    path = _write(tmp_path, swipe_left())
    got = list(FileLandmarkSource(path).frames())
    assert len(got) == len(expected)
    assert [f.t_ms for f in got] == [f.t_ms for f in expected]


def test_two_handed_frames_survive(tmp_path):
    path = _write(tmp_path, GENERATORS["two_hand_panic"]())
    frames = list(FileLandmarkSource(path).frames())
    assert all(len(f.hands) == 2 for f in frames)
    assert {h.handedness for h in frames[0].hands} == {Handedness.LEFT, Handedness.RIGHT}


def test_frames_with_no_hands_survive(tmp_path):
    # Absence is a signal the arbiter acts on (decay to Idle). A format that dropped empty frames
    # would silently delete the evidence of a hand leaving frame.
    path = _write(tmp_path, GENERATORS["absent"](duration_s=0.5))
    frames = list(FileLandmarkSource(path).frames())
    assert len(frames) == 15
    assert all(f.hands == () for f in frames)


def test_meta_sidecar_is_written_and_read_back(tmp_path):
    path = _write(tmp_path, swipe_left())
    assert meta_path(path).name == "s.meta.json"
    meta = read_meta(path)
    assert meta.name == "swipe_left"
    assert meta.model == "synthetic"
    assert json.loads(meta_path(path).read_text())["frames"] == 12


def test_reading_a_fixture_with_no_sidecar_does_not_explode(tmp_path):
    # Hand-authored or truncated fixtures still have to replay; the sidecar is metadata, not
    # required structure.
    path = tmp_path / "bare.ndjson"
    path.write_text(json.dumps(frame_to_dict(next(iter(swipe_left().frames())))) + "\n")
    assert len(list(FileLandmarkSource(path).frames())) == 1
    assert read_meta(path).name == "bare"


def test_tee_source_passes_frames_through_while_recording(tmp_path):
    # `record` is not a separate code path — you record by wrapping whatever source you were
    # already running, so a fixture is by construction what the system actually saw.
    path = tmp_path / "teed.ndjson.gz"
    inner = swipe_left()
    tee = TeeSource(inner, NdjsonWriter(path, inner.meta))
    passed_through = list(tee.frames())
    tee.close()
    on_disk = list(FileLandmarkSource(path).frames())
    assert len(passed_through) == len(on_disk) == 12
    assert [f.seq for f in passed_through] == [f.seq for f in on_disk]


def test_uncompressed_and_gzipped_paths_are_equivalent(tmp_path):
    a = list(FileLandmarkSource(_write(tmp_path, swipe_left(), "a.ndjson.gz")).frames())
    b = list(FileLandmarkSource(_write(tmp_path, swipe_left(), "b.ndjson")).frames())
    assert [frame_to_dict(f) for f in a] == [frame_to_dict(f) for f in b]


def test_generators_are_deterministic_across_runs():
    # Golden intent streams depend on this absolutely.
    for name, gen in GENERATORS.items():
        one = [frame_to_dict(f) for f in gen().frames()]
        two = [frame_to_dict(f) for f in gen().frames()]
        assert one == two, name
