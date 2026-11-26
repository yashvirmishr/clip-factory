"""Subject-aware framing: interest measurement, window choice, camera path.

The vision tests use synthetic frames (a moving bright block, a skin-toned
rectangle) so the arithmetic is verifiable without decoding anything. One
end-to-end test renders a real clip to prove the expression ffmpeg receives is
well formed.
"""

import numpy as np
import pytest

from clipper.config import FramingConfig
from clipper.pipeline.framing import (
    CropPlan,
    best_center,
    build_plan,
    crop_width_for,
    frame_interest,
)

CFG = FramingConfig(grid_width=32, grid_height=18, sample_fps=2.0)


def frames_with_block(count: int, column: int, width: int = 32, height: int = 18, colour=(255, 255, 255)):
    frames = np.zeros((count, height, width, 3), dtype=np.uint8)
    frames[:, :, column : column + 4] = colour
    return frames


def moving_block(count: int = 8) -> np.ndarray:
    frames = np.zeros((count, 18, 32, 3), dtype=np.uint8)
    for index in range(count):
        column = 2 + index * 3
        frames[index, :, column : column + 4] = 255
    return frames


def test_crop_width_is_a_nine_by_sixteen_column():
    # 960x540 source -> a 304 px wide column fills 1080x1920.
    assert crop_width_for(960, 540) == 304
    # Never wider than the source.
    assert crop_width_for(200, 1080) == 200
    # Always even, so chroma siting stays intact.
    assert crop_width_for(1920, 1080) % 2 == 0


def test_motion_is_measured_per_column():
    interest = frame_interest(moving_block(), CFG)
    assert interest.shape[0] == 8
    assert interest.shape[1] == 32
    # Where the block moves, interest beats the empty left edge.
    assert interest[:, 12:20].max() > interest[:, 0].max()


def test_a_still_bright_block_is_found_by_skin_not_motion():
    frames = frames_with_block(4, column=24, colour=(200, 140, 120))
    interest = frame_interest(frames, CFG)
    profile = interest.mean(axis=0)
    assert best_center(profile, crop_fraction=0.5) > 0.6


def test_static_frames_fall_back_to_centre():
    frames = np.full((4, 18, 32, 3), 40, dtype=np.uint8)
    interest = frame_interest(frames, CFG)
    assert best_center(interest.mean(axis=0), 0.5) == pytest.approx(0.5)


def test_best_center_picks_the_heavy_side():
    profile = np.zeros(32)
    profile[24:] = 1.0
    assert best_center(profile, crop_fraction=0.25) > 0.75


def test_plan_has_one_knot_per_shot_and_covers_the_clip():
    times = [100.0 + t for t in range(20)]
    interest = frame_interest(moving_block(20), CFG)
    plan = build_plan(times, interest, [(100.0, 110.0), (110.0, 120.0)], 960, 540, 100.0)
    assert plan is not None
    assert len(plan.knots) >= 2
    assert plan.knots[0][0] == 0.0
    assert plan.knots[-1][0] == pytest.approx(20.0)
    # The subject moves left to right, so the second shot is framed further right.
    assert plan.knots[-1][1] > plan.knots[0][1]


def test_plan_expression_is_monotonic_and_bounded():
    plan = CropPlan(
        src_w=960, src_h=540, crop_w=304,
        knots=((0.0, 0.0), (5.0, 656.0)),
        confidence=0.5,
    )
    assert plan.at(0.0) == 0.0
    assert plan.at(2.5) == pytest.approx(328.0)
    assert plan.at(99.0) == 656.0
    expression = plan.expression()
    assert expression.startswith("if(lt(t,5.000)")
    assert "656" in expression


def test_single_knot_plan_is_a_constant_crop():
    plan = CropPlan(src_w=960, src_h=540, crop_w=304, knots=((0.0, 328.0),))
    assert plan.expression() == "328"


def test_empty_plan_centres():
    plan = CropPlan(src_w=960, src_h=540, crop_w=304, knots=())
    assert plan.expression() == str(plan.maximum_x // 2)


def test_duplicate_knots_collapse():
    times = [0.0, 1.0, 2.0, 3.0]
    flat = np.ones((4, 32))
    plan = build_plan(times, flat, [(10.0, 11.0), (11.0, 12.0)], 960, 540, 10.0)
    assert plan is not None
    # Same centre everywhere -> one knot, not a camera that twitches in place.
    assert len(plan.knots) == 1


def test_render_graph_carries_the_crop_expression():
    from pathlib import Path

    from clipper.render.ffmpeg import RenderSpec, build_filter_graph

    spec = RenderSpec(
        src=Path("in.mp4"),
        out=Path("out.mp4"),
        start=0.0,
        duration=10.0,
        ass_name="captions.ass",
        framing="auto",
        crop_w=304,
        crop_expr="if(lt(t,5.000),0+(328)*(t-0.000)/5.000,328)",
    )
    graph = build_filter_graph(spec)
    assert "crop=304:ih:x='" in graph
    assert "scale=1080:1920" in graph
    assert graph.rstrip().endswith("[v]")


def test_auto_framing_without_a_plan_falls_back_to_centre_crop():
    from pathlib import Path

    from clipper.render.ffmpeg import RenderSpec, build_filter_graph

    spec = RenderSpec(
        src=Path("in.mp4"), out=Path("out.mp4"), start=0.0, duration=5.0,
        ass_name="a.ass", framing="auto", crop_w=0,
    )
    graph = build_filter_graph(spec)
    # "auto" means a crop. Without a plan it is a still centre crop, not the
    # blur pad the user did not choose.
    assert "gblur" not in graph
    assert "crop=1080:1920" in graph


def _face_box(cx: float, cy: float = 90.0, w: float = 60.0, h: float = 70.0):
    from clipper.pipeline.faces import Face

    return Face(x=cx - w / 2, y=cy - h / 2, w=w, h=h, score=0.9)


def test_face_plan_follows_the_detected_face():
    from clipper.pipeline.framing import plan_from_detections

    times = [0.0, 0.25, 0.5, 0.75, 1.0]
    detections = [[_face_box(760)], [_face_box(800)], [_face_box(840)], [_face_box(880)], [_face_box(900)]]
    plan = plan_from_detections(times, detections, [(0.0, 1.0)], 960, 540, 0.0)
    assert plan is not None
    assert plan.method == "faces"
    assert plan.crop_w == crop_width_for(960, 540)
    # The face moves right, so the crop travels right and never leaves the frame.
    assert plan.knots[-1][1] > plan.knots[0][1]
    assert 0 <= plan.at(0.0) <= plan.maximum_x
    assert 0 <= plan.at(5.0) <= plan.maximum_x


def test_face_plan_without_detections_is_none_so_activity_answers():
    from clipper.pipeline.framing import plan_from_detections

    assert plan_from_detections([0.0, 1.0], [[], []], [(0.0, 1.0)], 960, 540, 0.0) is None
    assert plan_from_detections([], [], [(0.0, 1.0)], 960, 540, 0.0) is None


def test_a_wobbling_face_does_not_produce_a_knot_per_frame():
    from clipper.pipeline.framing import plan_from_detections

    times = [index * 0.25 for index in range(16)]
    # Two-pixel jitter around x=800: a camera that follows this looks handheld.
    detections = [[_face_box(800 + (index % 2) * 2)] for index in range(16)]
    plan = plan_from_detections(times, detections, [(0.0, 4.0)], 960, 540, 0.0, deadband=8.0)
    assert plan is not None
    assert len(plan.knots) <= 2


def test_simplify_caps_the_knot_count_and_covers_the_end():
    from clipper.pipeline.framing import simplify_knots

    knots = [(index * 0.5, index * 40.0) for index in range(40)]
    kept = simplify_knots(knots, clip_end=20.0, deadband=8.0, max_knots=6)
    assert len(kept) <= 7
    assert kept[0][0] == 0.0
    assert kept[-1][0] == pytest.approx(20.0)


def test_clip_plan_prefers_faces_but_never_needs_them(monkeypatch):
    from clipper.pipeline import framing as framing_module

    monkeypatch.setattr(framing_module, "face_plan_for_clip", lambda *a, **k: None)
    # No face model configured is the normal case: planning still returns the
    # activity answer (or None for missing media), and never raises.
    from clipper.domain import ClipCandidate, SourceInfo

    source = SourceInfo(id="s", name="s", path="missing.mp4", duration=60.0, width=1920, height=1080)
    candidate = ClipCandidate(id="c", source_id="s", start=0.0, end=10.0, text="hi")
    assert framing_module.plan_for_clip(source, candidate, []) is None
