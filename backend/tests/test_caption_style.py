"""Caption style overrides: one clip can look different, and every consumer agrees.

The point of these tests is that a saved override reaches the burner, the ASS
download and the studio payload with the same numbers - restyling that changes
the preview but not the render is the failure this file exists to catch.
"""

from clipper.render.ass import (
    PRESETS,
    apply_overrides,
    clean_overrides,
    get_preset,
    resolve_style,
    style_payload,
    build_ass_document,
)
from clipper.pipeline.caption import CaptionPage, CaptionWord


def test_no_overrides_is_the_preset_untouched():
    style = get_preset("hormozi")
    assert apply_overrides(style, {}) == style
    assert apply_overrides(style, None) == style


def test_overrides_change_only_what_was_asked_for():
    style = apply_overrides(get_preset("minimal"), {"font": "Impact", "size": 120})
    assert style.font == "Impact"
    assert style.size == 120
    # Everything else stays from the preset.
    assert style.uppercase == PRESETS["minimal"].uppercase
    assert style.karaoke == PRESETS["minimal"].karaoke


def test_values_are_clamped_so_a_render_cannot_break():
    style = apply_overrides(get_preset("hormozi"), {"size": 9000, "outline_width": -4})
    assert style.size == 200
    assert style.outline_width == 0.0


def test_unknown_keys_and_bad_types_are_dropped():
    cleaned = clean_overrides({"font": "  ", "song": "yes", "size": "big", "karaoke": "spin"})
    assert cleaned == {"karaoke": "k"}


def test_colours_and_booleans_survive_cleaning():
    cleaned = clean_overrides({"primary": "&H0000FF00", "uppercase": False, "bold": True})
    assert cleaned == {"primary": "&H0000FF00", "uppercase": False, "bold": -1}


def test_payload_reports_the_effective_style_and_the_override_set():
    payload = style_payload(apply_overrides(get_preset("box"), {"size": 70}), {"size": 70})
    assert payload["size"] == 70
    assert payload["overrides"] == {"size": 70}
    assert payload["label"] == "Box"
    assert payload["preset"] == "box"


def test_a_clip_can_save_its_own_preset_not_just_overrides():
    style = resolve_style({"preset": "neon", "overrides": {"size": 82}}, "hormozi")
    assert style.key == "neon"
    assert style.size == 82
    assert style.font == PRESETS["neon"].font


def test_an_old_flat_override_row_still_loads():
    style = resolve_style({"font": "Impact", "size": 64}, "hormozi")
    assert style.key == "hormozi"
    assert style.font == "Impact"
    assert style.size == 64


def test_every_shipped_preset_is_renderable_and_distinct():
    assert len(PRESETS) >= 11
    assert len({style.label for style in PRESETS.values()}) == len(PRESETS)
    for key, style in PRESETS.items():
        assert style.key == key
        document = build_ass_document([_page()], style, 10.0)
        assert f"Style: Clip,{style.font}," in document


def _page() -> CaptionPage:
    return CaptionPage(
        index=0,
        start=10.0,
        end=11.0,
        words=[CaptionWord(text="hello", start=10.0, end=10.5)],
        lines=["hello"],
        text="hello",
        cps=5.0,
        warnings=[],
    )


def test_the_burned_ass_uses_the_override_font_and_size():
    style = apply_overrides(get_preset("hormozi"), {"font": "Impact", "size": 64, "uppercase": False})
    document = build_ass_document([_page()], style, 10.0)
    assert "Style: Clip,Impact,64," in document
    assert "hello" in document
    assert "HELLO" not in document


def test_the_ass_download_and_the_render_share_one_style_path():
    # Both callers start from get_preset + apply_overrides; a divergence here
    # would mean a handoff file that no longer matches the MP4.
    from clipper.editors.spec import spec_for
    from clipper.domain import ClipCandidate, SourceInfo

    source = SourceInfo(id="s", name="s", path="s.mp4", duration=60.0, width=1920, height=1080)
    candidate = ClipCandidate(
        id="c1",
        source_id="s",
        start=0.0,
        end=30.0,
        text="hello",
        caption_style={"font": "Impact", "size": 64},
    )
    spec = spec_for(source, candidate, 1)
    assert spec.caption_style == {"font": "Impact", "size": 64}
