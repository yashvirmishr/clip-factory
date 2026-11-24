"""Pick quality: matching maths, and a regression gate on the demo fixture.

The unit tests pin the scoring rules (partial credit is not given, duplicates
count against precision). The regression test is the one that matters day to day:
it runs the real pipeline over the labelled demo fixture and fails if the picker
gets worse.
"""

import json
from pathlib import Path

import pytest

from clipper import bench, demo, service
from clipper.config import SETTINGS
from clipper.domain import ClipCandidate, SourceInfo

GOLD_FILE = Path(__file__).resolve().parents[2] / "benchmarks" / "gold" / "demo-stream.json"


def gold(payload: list[dict]) -> bench.GoldSet:
    return bench.GoldSet(
        source="t.mp4",
        moments=[bench.GoldMoment(**item) for item in payload],
    )


# ------------------------------------------------------------- matching


def test_a_clip_covering_the_moment_counts():
    moments = gold([{"start": 10.0, "end": 30.0, "label": "a"}])
    report = bench.evaluate([(12.0, 28.0)], moments)
    assert report.hits == 1
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.coverage == pytest.approx(0.8)


def test_partial_credit_is_not_given():
    # Catching the last 25% of a story is not catching the story.
    moments = gold([{"start": 10.0, "end": 30.0, "label": "a"}])
    report = bench.evaluate([(25.0, 40.0)], moments)
    assert report.hits == 0
    assert report.missing


def test_the_threshold_is_the_clip_covering_the_moment():
    moments = gold([{"start": 0.0, "end": 20.0, "label": "a"}])
    assert bench.evaluate([(0.0, 7.0)], moments).hits == 0  # 35% of the moment
    assert bench.evaluate([(0.0, 9.0)], moments).hits == 1  # 45%


def test_two_clips_on_one_moment_is_a_duplicate():
    moments = gold([{"start": 10.0, "end": 30.0, "label": "a"}, {"start": 50.0, "end": 70.0, "label": "b"}])
    report = bench.evaluate([(10.0, 30.0), (12.0, 32.0), (50.0, 70.0)], moments)
    assert report.hits == 2
    assert report.duplicates == 1
    assert report.precision == pytest.approx(2 / 3, abs=1e-3)
    assert report.recall == 1.0


def test_a_clip_between_moments_is_a_miss():
    moments = gold([{"start": 10.0, "end": 30.0, "label": "a"}])
    report = bench.evaluate([(35.0, 55.0)], moments)
    assert report.precision == 0.0
    assert report.f1 == 0.0


def test_empty_reel_does_not_crash():
    moments = gold([{"start": 10.0, "end": 30.0}])
    report = bench.evaluate([], moments)
    assert (report.precision, report.recall, report.f1) == (0.0, 0.0, 0.0)
    assert len(report.missing) == 1


def test_best_match_wins_when_moments_overlap():
    moments = gold([{"start": 0.0, "end": 40.0}, {"start": 10.0, "end": 20.0}])
    report = bench.evaluate([(10.0, 20.0)], moments)
    assert report.matches[0].gold.start == 10.0


def test_zero_length_moment_is_ignored():
    moments = gold([{"start": 10.0, "end": 10.0}])
    assert bench.evaluate([(5.0, 25.0)], moments).hits == 0


# ------------------------------------------------------------- fixtures


def test_the_shipped_gold_file_loads():
    loaded = bench.load(GOLD_FILE)
    assert loaded.source == "demo-stream.mp4"
    assert len(loaded.moments) >= 4
    assert all(moment.end > moment.start for moment in loaded.moments)
    assert loaded.notes


def test_discover_finds_the_shipped_fixtures():
    found = bench.discover(GOLD_FILE.parent)
    assert any(path.name == "demo-stream.json" for path, _ in found)


def test_report_serialises():
    moments = gold([{"start": 10.0, "end": 30.0}])
    payload = bench.evaluate([(10.0, 30.0)], moments).to_dict()
    assert json.dumps(payload)
    assert payload["hits"] == 1 and payload["missing"] == []


# --------------------------------------------------- regression gate


@pytest.fixture(scope="module")
def demo_analysis():
    # The labels describe the 180 s demo, so the gate has to score that fixture.
    # Its own directory keeps it from colliding with the shorter demo other test
    # modules generate under the same filename.
    path = demo.generate(SETTINGS.media_dir() / "gold", seconds=180)
    source = service.ingest(path, "Gold fixture")
    return service.analyze(source, limit=6, force=True)


def test_picker_still_finds_the_labelled_moments(demo_analysis):
    """The gate. A change that makes the picks worse fails here, not on a hunch.

    Floors are set below the current score on purpose: this is a regression
    guard, not a target to game by tuning against one fixture.
    """
    loaded = bench.load(GOLD_FILE)
    report = bench.evaluate_result(demo_analysis, loaded, limit=5)
    assert report.precision >= 0.4, report.summary_line("demo")
    assert report.recall >= 0.4, report.summary_line("demo")
    assert report.duplicates <= 1, report.summary_line("demo")


def test_more_picks_never_lose_recall(demo_analysis):
    loaded = bench.load(GOLD_FILE)
    five = bench.evaluate_result(demo_analysis, loaded, limit=5)
    ten = bench.evaluate_result(demo_analysis, loaded, limit=10)
    assert ten.recall >= five.recall


def test_the_reel_matches_what_the_harness_scores(demo_analysis):
    """Scores must come from the ranked reel, not from every window ever built."""
    loaded = bench.load(GOLD_FILE)
    ranked = [c for c in demo_analysis.candidates if c.rank]
    assert ranked, "expected a ranked reel"
    assert bench.evaluate_result(demo_analysis, loaded, limit=5).clip_count == min(5, len(ranked))
