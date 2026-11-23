import subprocess

import pytest

from clipper.config import SETTINGS
from clipper.domain import Word
from clipper.pipeline.caption import group_words
from clipper.render.ass import PRESETS, build_ass_document, escape_text, get_preset
from clipper.render.ffmpeg import RenderSpec, build_args, build_filter_graph


def words() -> list[Word]:
    spec = [
        ("nobody", 0.0, 0.3),
        ("has", 0.35, 0.5),
        ("ever", 0.55, 0.8),
        ("done", 0.85, 1.1),
        ("this", 1.15, 1.4),
        ("before", 1.45, 1.9),
    ]
    return [Word(text=t, start=s, end=e, prob=0.95) for t, s, e in spec]


def test_ass_document_has_karaoke_tags_and_relative_timing():
    pages = group_words(words(), SETTINGS.captions)
    document = build_ass_document(pages, get_preset("hormozi"), clip_start=0.0)
    assert "ScriptType: v4.00+" in document
    assert "PlayResX: 1080" in document
    assert "PlayResY: 1920" in document
    assert "\\k" in document
    assert "NOBODY" in document  # uppercase preset
    assert "Dialogue: 0,0:00:00.00," in document


def test_pages_outside_the_clip_window_are_dropped():
    pages = group_words(words(), SETTINGS.captions)
    document = build_ass_document(pages, get_preset("hormozi"), clip_start=10.0)
    # every page ends before the clip starts, so no events survive
    assert "Dialogue:" not in document


def test_ass_escapes_override_braces():
    assert escape_text("a{b}c") == "a\\{b\\}c"


def test_ass_wraps_to_two_lines_and_joins_with_newline():
    from clipper.config import CaptionConfig

    many = [Word(text=f"word{i}", start=i * 0.2, end=i * 0.2 + 0.18, prob=0.9) for i in range(10)]
    pages = group_words(
        many, CaptionConfig(cps_limit=100.0, max_words=10, max_chars_per_line=40, max_lines=2)
    )
    document = build_ass_document(pages, get_preset("minimal"), clip_start=0.0, max_chars_per_line=13)
    assert "\\N" in document


def test_every_preset_produces_a_valid_header():
    for key, style in PRESETS.items():
        document = build_ass_document(group_words(words(), SETTINGS.captions), style, clip_start=0.0)
        assert document.startswith("[Script Info]")
        assert f"Style: Clip,{style.font}," in document
        assert key


def test_crop_framing_graph_scales_and_burns():
    spec = RenderSpec(
        src="in.mp4", out="out.mp4", start=1.0, duration=10.0,
        ass_name="c.ass", framing="crop",
    )
    graph = build_filter_graph(spec)
    assert "scale=1080:1920" in graph
    assert "crop=1080:1920" in graph
    assert "ass=c.ass" in graph
    assert "gblur" not in graph


def test_blur_framing_graph_composites_two_layers():
    spec = RenderSpec(
        src="in.mp4", out="out.mp4", start=0.0, duration=10.0,
        ass_name="c.ass", framing="blur",
    )
    graph = build_filter_graph(spec)
    assert "split=2" in graph
    assert "gblur" in graph
    assert "overlay=(W-w)/2:(H-h)/2" in graph
    assert graph.endswith("[v]")


def test_args_seek_before_input_and_bound_duration():
    spec = RenderSpec(
        src="C:/media in.mp4", out="out.mp4", start=12.5, duration=20.0,
        ass_name="c.ass", encoder="libx264",
    )
    args = build_args(spec)
    assert args.index("-ss") < args.index("-i")
    assert args[args.index("-ss") + 1] == "12.500"
    assert args[args.index("-t") + 1] == "20.000"
    assert "loudnorm=I=-14.0" in " ".join(args)
    assert "-movflags" in args and "+faststart" in args
    assert "C:/media in.mp4" in args


def test_hardware_encoders_get_their_own_flags():
    base = dict(src="i.mp4", out="o.mp4", start=0.0, duration=5.0, ass_name="c.ass")
    amf = build_args(RenderSpec(**base, encoder="h264_amf"))
    nvenc = build_args(RenderSpec(**base, encoder="h264_nvenc"))
    assert "h264_amf" in amf and "cqp" in amf
    assert "h264_nvenc" in nvenc and "-cq" in nvenc


@pytest.mark.slow
def test_real_render_produces_a_vertical_mp4(tmp_path):
    """End to end on a generated source: ffmpeg really runs."""
    from clipper import demo, service
    from clipper.render import render_clip

    path = demo.generate(SETTINGS.media_dir(), seconds=45)
    source = service.ingest(path, "Render fixture")
    result = service.analyze(source, limit=3, force=True)
    clip = next(c for c in result.candidates if c.rank)

    output = render_clip(source, clip, preset_key="hormozi", framing="blur", force=True)
    assert output["url"].endswith(".mp4")
    rendered = (SETTINGS.data_dir / "renders" / output["filename"])
    assert rendered.exists() and rendered.stat().st_size > 10_000

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(rendered)],
        capture_output=True, text=True, timeout=60,
    ).stdout.strip()
    assert probe == "1080,1920"
    assert 2.0 <= output["duration"] <= 40.0
