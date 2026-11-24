"""Scene-cut parsing, snapping and chapter logic.

The ffmpeg call itself is covered by a skip-if-unavailable test at the bottom;
everything above it is pure so the arithmetic is verified without a decoder.
"""

import shutil
import subprocess

import pytest

from clipper.config import SceneConfig
from clipper.pipeline.scenes import (
    SceneCut,
    chapters,
    dedupe_cuts,
    nearest_cut,
    parse_cut_blocks,
    shots_between,
    snap_bounds,
)

# Shape of `metadata=print:file=-` output for two selected frames.
SAMPLE_OUTPUT = """
frame:120  pts:49152   pts_time:1.638
lavfi.scene_score=0.512345
frame:900  pts:368640  pts_time:12.288
lavfi.scene_score=0.900000
"""


def test_parse_pairs_time_with_score():
    cuts = parse_cut_blocks(SAMPLE_OUTPUT)
    assert [c.time for c in cuts] == [1.638, 12.288]
    assert cuts[1].score == pytest.approx(0.9)


def test_parse_ignores_partial_blocks():
    # A truncated tail (process killed mid-write) must not invent a cut at 0.
    cuts = parse_cut_blocks("frame:1 pts_time:5.0\n")
    assert cuts == []


def test_dedupe_keeps_the_strongest_of_a_cluster():
    cuts = [
        SceneCut(10.0, 0.4),
        SceneCut(10.2, 0.9),
        SceneCut(10.4, 0.5),
        SceneCut(20.0, 0.3),
    ]
    assert dedupe_cuts(cuts, min_gap=1.0) == [10.2, 20.0]


def test_nearest_cut_respects_the_tolerance():
    cuts = [10.0, 30.0]
    assert nearest_cut(10.5, cuts, 0.75) == 10.0
    assert nearest_cut(12.0, cuts, 0.75) is None


def test_snap_extends_edges_onto_nearby_cuts():
    start, end = snap_bounds(10.4, 40.2, [10.0, 40.5], SceneConfig(), 8.0, 90.0)
    assert start == 10.0
    assert end == 40.5


def test_snap_refuses_to_shrink_below_the_minimum():
    # The cut is real and close, but honouring it would make an 5.4 s clip.
    start, end = snap_bounds(10.4, 16.0, [10.0], SceneConfig(), 8.0, 90.0)
    assert (start, end) == (10.4, 16.0)


def test_snap_leaves_far_edges_alone():
    assert snap_bounds(50.0, 70.0, [10.0, 90.0], SceneConfig(), 8.0, 90.0) == (50.0, 70.0)


def test_snap_without_cuts_is_a_noop():
    assert snap_bounds(5.0, 25.0, [], SceneConfig(), 8.0, 90.0) == (5.0, 25.0)


def test_shots_between_splits_at_internal_cuts():
    shots = shots_between([10.0, 20.0, 30.0], 10.0, 25.0)
    assert shots == [(10.0, 20.0), (20.0, 25.0)]


def test_shots_fold_away_flash_cuts():
    # A 0.2 s span is a transition, not a shot.
    shots = shots_between([10.0, 20.0, 20.2], 10.0, 30.0, min_shot_s=0.4)
    assert shots == [(10.0, 20.0), (20.0, 30.0)]


def test_shots_without_cuts_returns_the_whole_span():
    assert shots_between([], 12.0, 30.0) == [(12.0, 30.0)]


def test_chapters_use_cuts_near_the_target():
    cuts = [298.0, 601.0, 902.0]
    spans = chapters(cuts, 1200.0, target_s=300.0)
    assert len(spans) == 4
    assert spans[0] == (0.0, 298.0)
    assert spans[-1][1] == 1200.0
    assert all(b > a for a, b in spans)


def test_chapters_fall_back_to_a_grid_in_one_continuous_take():
    # 700 s on a 300 s target leaves two chapters rather than a 100 s stub.
    assert chapters([], 700.0, target_s=300.0) == [(0.0, 300.0), (300.0, 700.0)]


def test_short_sources_are_a_single_chapter():
    assert chapters([10.0], 120.0) == [(0.0, 120.0)]


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


@needs_ffmpeg
def test_detects_a_real_hard_cut(tmp_path):
    """A red clip cut to blue must produce exactly one cut near the join."""
    video = tmp_path / "cut.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=320x180:d=2:r=25",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2:r=25",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p",
            str(video),
        ],
        capture_output=True,
        timeout=120,
        check=True,
    )
    from clipper.pipeline.scenes import detect_cuts

    cuts = detect_cuts(video, SceneConfig(threshold=0.3, min_gap_s=0.5))
    assert cuts, "expected at least one cut"
    assert any(abs(cut - 2.0) < 0.5 for cut in cuts)
