"""Editor exports: timecode maths, four formats, and the drift guard.

The important test here is `test_every_format_agrees_on_the_timeline`: three
backends derive the same clip's timing independently (ffmpeg's ASS events, SRT
cues, OTIO ranges). If they ever disagree, a handoff silently retimes captions
and nobody notices until the clip is posted.
"""

import json
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

import pytest

from clipper.domain import ClipCandidate, LLMJudgement, SourceInfo, Word
from clipper.editors import bundle, edl, otio, srt, xmeml
from clipper.editors.spec import spec_for
from clipper.editors.timecode import (
    frames_at,
    parse_timecode,
    rate_for,
    timecode,
)


def make_source(**overrides) -> SourceInfo:
    data = dict(
        id="src1",
        name="stream.mp4",
        path="C:/media/stream.mp4",
        duration=600.0,
        width=960,
        height=540,
        fps=30.0,
        size_bytes=1,
    )
    data.update(overrides)
    return SourceInfo(**data)


def make_candidate(start=45.0, end=63.0) -> ClipCandidate:
    words = [
        Word(text=word, start=start + index * 0.4, end=start + index * 0.4 + 0.35, prob=0.94)
        for index, word in enumerate(
            "you will not believe what happened next and then it got worse".split()
        )
    ]
    return ClipCandidate(
        id="clip1",
        source_id="src1",
        start=start,
        end=end,
        text=" ".join(w.text for w in words),
        words=words,
        llm=LLMJudgement(score=81, hook="You will not believe what happened next"),
        final=0.81,
        rank=1,
    )


def make_spec(**kwargs):
    return spec_for(make_source(), make_candidate(), 1, **kwargs)


# ---------------------------------------------------------------- timecode


def test_timecode_counts_frames_in_each_rate():
    assert timecode(0, rate_for(30.0)) == "00:00:00:00"
    assert timecode(29, rate_for(30.0)) == "00:00:00:29"
    assert timecode(30, rate_for(30.0)) == "00:00:01:00"
    assert timecode(1364, rate_for(30.0)) == "00:00:45:14"
    assert timecode(25, rate_for(25.0)) == "00:00:01:00"
    # 29.97 counts at 30 while advancing at 29.97 - non-drop, as documented.
    assert rate_for(29.97).nominal == 30
    assert rate_for(23.976).nominal == 24
    assert rate_for(59.94).nominal == 60


def test_timecode_roundtrips():
    for fps in (24.0, 25.0, 30.0, 60.0):
        rate = rate_for(fps)
        for frames in (0, 1, 59, 60, 1234, 108000):
            assert parse_timecode(timecode(frames, rate), rate) == frames


def test_frames_at_rounds_to_the_nearest_frame():
    rate = rate_for(30.0)
    assert frames_at(1.0, rate) == 30
    assert frames_at(1.01, rate) == 30
    assert frames_at(1.02, rate) == 31
    assert frames_at(-5.0, rate) == 0


def test_unknown_fps_falls_back_to_thirty():
    assert rate_for(0.0).fps == 30.0
    assert rate_for(0.0).nominal == 30


# -------------------------------------------------------------------- spec


def test_spec_is_frame_accurate():
    spec = make_spec()
    assert spec.rate.fps == 30.0
    assert spec.in_frame == 1350
    assert spec.out_frame == 1890
    assert spec.duration_frames == 540
    assert spec.duration == pytest.approx(18.0)


def test_spec_pages_are_clip_relative_and_clipped():
    spec = make_spec()
    spans = spec.page_spans()
    assert spans
    assert spans[0][0] == pytest.approx(0.0)
    assert all(0 <= start < end <= spec.duration + 1e-6 for start, end, _ in spans)


def test_spec_file_url_is_a_real_url():
    url = make_spec().file_url()
    assert url.startswith("file:///")
    assert " " not in url  # percent-encoded, which is what xmeml importers need


# -------------------------------------------------------------------- otio


def test_otio_has_one_track_and_one_clip_per_spec():
    timeline = otio.build([make_spec(), make_spec()])
    assert timeline["OTIO_SCHEMA"] == "Timeline.1"
    track = timeline["tracks"]["children"][0]
    assert track["OTIO_SCHEMA"] == "Track.1"
    assert len(track["children"]) == 2
    first = track["children"][0]
    assert first["OTIO_SCHEMA"] == "Clip.1"
    assert first["media_reference"]["OTIO_SCHEMA"] == "ExternalReference.1"
    assert first["source_range"]["start_time"]["value"] == 1350.0
    assert first["source_range"]["duration"]["value"] == 540.0


def test_otio_marks_the_hook():
    clip = otio.build([make_spec()])["tracks"]["children"][0]["children"][0]
    assert clip["markers"][0]["name"] == "hook"
    assert clip["markers"][0]["metadata"]["clip_factory"]["hook"].startswith("You will not")


def test_otio_is_json_serialisable():
    text = otio.dumps([make_spec()])
    assert json.loads(text)["OTIO_SCHEMA"] == "Timeline.1"


# ------------------------------------------------------------------ xmeml


def test_xmeml_is_well_formed_and_lays_clips_end_to_end():
    xml = xmeml.build([make_spec(), make_spec()])
    root = ET.fromstring(xml.split("?>", 1)[1])
    items = root.findall(".//clipitem")
    assert len(items) == 2

    first, second = items
    assert first.findtext("in") == "1350"
    assert first.findtext("out") == "1890"
    assert first.findtext("start") == "0"
    assert first.findtext("end") == "540"
    assert second.findtext("start") == "540"
    assert second.findtext("end") == "1080"
    assert root.findtext(".//sequence/duration") == "1080"


def test_xmeml_path_is_percent_encoded():
    xml = xmeml.build([make_spec()])
    path = ET.fromstring(xml.split("?>", 1)[1]).findtext(".//pathurl")
    assert path.startswith("file:///")
    assert " " not in path


def test_xmeml_keeps_source_dimensions():
    root = ET.fromstring(xmeml.build([make_spec()]).split("?>", 1)[1])
    assert root.findtext(".//samplecharacteristics/width") == "960"
    assert root.findtext(".//samplecharacteristics/height") == "540"


# -------------------------------------------------------------------- edl


def test_edl_has_contiguous_record_timecodes():
    spec = make_spec()
    text = edl.build([spec, spec])
    lines = [line for line in text.splitlines() if line and line[0].isdigit()]
    assert lines[0].split()[-4:] == ["00:00:45:00", "00:01:03:00", "00:00:00:00", "00:00:18:00"]
    assert lines[1].split()[-4:] == ["00:00:45:00", "00:01:03:00", "00:00:18:00", "00:00:36:00"]


def test_edl_carries_the_clip_name_as_a_comment():
    text = edl.build([make_spec()])
    assert "* FROM CLIP NAME: stream.mp4" in text
    assert "FCM: NON-DROP FRAME" in text


# -------------------------------------------------------------------- srt


def test_srt_cues_match_the_caption_pages():
    spec = make_spec()
    text = srt.build(spec)
    blocks = [b for b in text.strip().split("\n\n") if b.strip()]
    assert len(blocks) == len(spec.page_spans())
    assert blocks[0].splitlines()[0] == "1"
    assert "-->" in blocks[0].splitlines()[1]


def test_srt_timestamps_use_commas_and_are_monotonic():
    text = srt.build(make_spec())
    stamps = [
        line.split(" --> ") for line in text.splitlines() if "-->" in line
    ]
    assert all("," in start for start, _ in stamps)
    previous = -1.0
    for start, _ in stamps:
        hours, minutes, rest = start.split(":")
        seconds, millis = rest.split(",")
        value = int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000
        assert value >= previous
        previous = value


# ----------------------------------------------------------- drift guard


def test_every_format_agrees_on_the_timeline():
    """ASS events, SRT cues and OTIO ranges must describe the same seconds."""
    from clipper.render.ass import PRESETS, build_ass_document

    spec = make_spec()
    rate = spec.rate

    ass = build_ass_document(spec.pages, PRESETS["box"], spec.start)
    ass_lines = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    events = [line.split(",", 10)[1:3] for line in ass_lines]

    def ass_to_seconds(stamp: str) -> float:
        hours, minutes, rest = stamp.split(":")
        seconds = float(rest)
        return int(hours) * 3600 + int(minutes) * 60 + seconds

    otio_clip = otio.build([spec])["tracks"]["children"][0]["children"][0]
    otio_in = otio_clip["source_range"]["start_time"]["value"] / rate.fps
    otio_duration = otio_clip["source_range"]["duration"]["value"] / rate.fps

    assert otio_in == pytest.approx(spec.start, abs=1 / rate.fps)
    assert otio_duration == pytest.approx(spec.duration, abs=1 / rate.fps)

    # The renderer burns events relative to the clip; SRT says the same thing.
    cue_spans = spec.page_spans()
    assert len(events) == len(cue_spans)
    for (ass_start, ass_end), (cue_start, cue_end, _) in zip(events, cue_spans):
        start = ass_to_seconds(ass_start)
        end = ass_to_seconds(ass_end)
        # ASS stores centiseconds, so agreement is to 1/100 s - the finest
        # resolution the renderer has.
        assert start == pytest.approx(cue_start, abs=0.011)
        assert end == pytest.approx(cue_end, abs=0.011)


# ----------------------------------------------------------------- bundle


def test_bundle_contains_every_format_and_a_manifest():
    members = bundle.files([make_spec()])
    assert {"reel.otio", "reel.xml", "reel.edl", "README.txt", "manifest.json"} <= set(members)
    assert any(name.startswith("captions/") for name in members)

    manifest = json.loads(members["manifest.json"])
    assert manifest["media_embedded"] is False
    assert manifest["clip_count"] == 1
    assert manifest["clips"][0]["in_frame"] == 1350
    assert manifest["clips"][0]["timecode"]["in"] == "00:00:45:00"


def test_bundle_zips_and_reopens():
    payload = bundle.zip_bytes(bundle.files([make_spec()]))
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "reel.otio" in names
        assert json.loads(archive.read("manifest.json"))["clip_count"] == 1


def test_bundle_safe_name_strips_path_hostile_characters():
    assert bundle.safe_name("Clip Factory / reel: 1") == "Clip-Factory---reel--1"
    assert bundle.safe_name("") == "clip-factory-reel"


# ------------------------------------------------------- render integration


def test_auto_framing_knots_reach_the_manifest():
    spec = make_spec(crop=((0.0, 148.0), (14.5, 178.0)))
    manifest = json.loads(bundle.files([spec])["manifest.json"])
    assert manifest["clips"][0]["framing_knots"] == [[0.0, 148.0], [14.5, 178.0]]
    assert "FRAMING: auto" in bundle.files([spec])["reel.edl"].decode()
