"""Face tracking maths, without OpenCV or a model installed."""

from clipper.pipeline import faces


def box(cx, cy=90.0, w=60.0, h=70.0):
    return faces.Face(x=cx - w / 2, y=cy - h / 2, w=w, h=h, score=0.9)


def test_face_detection_is_unavailable_without_the_optional_package():
    # No model path at all: never a hard import, never an exception.
    assert faces.available(None) is False
    assert faces.available("does/not/exist.onnx") is False
    assert faces.detect([object(), object()]) == [[], []]


def test_status_explains_the_fallback():
    report = faces.status("")
    assert report["available"] is False
    assert report["engine"] in {"activity", "opencv-yunet"}
    assert report["hint"]


def test_tracking_keeps_one_id_for_a_moving_face():
    frames = [
        [box(100)], [box(104)], [box(108)], [box(112)],
    ]
    tracks = faces.track(frames, [0.0, 0.25, 0.5, 0.75], fps=4.0)
    assert len(tracks) == 1
    assert len(tracks[0].boxes) == 4
    assert tracks[0].boxes[-1].cx > tracks[0].boxes[0].cx


def test_two_faces_stay_separate_tracks():
    frames = [
        [box(80), box(420)],
        [box(82), box(424)],
        [box(84), box(428)],
    ]
    tracks = faces.track(frames, [0.0, 0.25, 0.5], fps=4.0)
    assert len(tracks) == 2
    assert abs(tracks[0].median.cx - tracks[1].median.cx) > 200


def test_a_face_that_leaves_and_returns_is_a_new_track():
    frames = [
        [box(100)], [box(102)],
        [],
        [],
        [],
        [],
        [],
        [],
        [box(106)],
    ]
    times = [index * 0.25 for index in range(len(frames))]
    tracks = faces.track(frames, times, fps=4.0)
    assert len(tracks) == 2


def test_the_speaking_face_wins():
    left = faces.Track(id=1, boxes=[box(100)], times=[1.0])
    right = faces.Track(id=2, boxes=[box(400)], times=[1.0])
    left.mouth = 0.1
    right.mouth = 0.7
    chosen, reason = faces.choose_subject([left, right], 0.0, 5.0, crop_w=200, frame_width=640)
    assert chosen is right
    assert "speaking" in reason


def test_two_faces_that_fit_the_crop_are_both_kept_in_view():
    left = faces.Track(id=1, boxes=[box(300)], times=[1.0])
    right = faces.Track(id=2, boxes=[box(340)], times=[1.0])
    chosen, reason = faces.choose_subject([left, right], 0.0, 5.0, crop_w=200, frame_width=640)
    assert chosen is left
    assert "fit" in reason


def test_no_faces_says_so_instead_of_crashing():
    chosen, reason = faces.choose_subject([], 0.0, 5.0, crop_w=200, frame_width=640)
    assert chosen is None
    assert "no faces" in reason


def test_the_plan_curve_clamps_to_the_frame():
    track = faces.Track(id=1, boxes=[box(10), box(630)], times=[0.0, 1.0])
    knots = faces.plan_curve(track, crop_w=200, frame_width=640)
    assert [left for _when, left in knots] == [0.0, 440.0]
