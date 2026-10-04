import pytest

from l2c.extract.calibrate import calibrate
from l2c.extract.grid import Grid
from l2c.ingest.pages import Word


def words(h: float) -> list[Word]:
    return [Word("ARM.:", 0, i * 3 * h, 4 * h, i * 3 * h + h) for i in range(10)]


@pytest.mark.parametrize("scale", [0.5, 1.0, 3.0])
def test_every_tolerance_scales_with_the_drawing(scale):
    grid = Grid(
        rows={"A": 100 * scale, "B": 236 * scale},
        cols={"1": 100 * scale, "2": 170 * scale, "3": 240 * scale},
    )
    base = calibrate(
        words(8.0), Grid(rows={"A": 100, "B": 236}, cols={"1": 100, "2": 170, "3": 240})
    )
    s = calibrate(words(8.0 * scale), grid)
    assert s.word_h == pytest.approx(base.word_h * scale)
    assert s.run_gap == pytest.approx(base.run_gap * scale)
    assert s.snap_tol == pytest.approx(base.snap_tol * scale)
    assert s.max_bind_dist == pytest.approx(base.max_bind_dist * scale)


def test_without_a_grid_tolerances_still_come_from_the_text_size():
    a, b = calibrate(words(8.0)), calibrate(words(16.0))
    assert b.snap_tol == pytest.approx(2 * a.snap_tol)
    assert b.max_bind_dist == pytest.approx(2 * a.max_bind_dist)


def test_no_words_falls_back_to_a_sane_default():
    s = calibrate([])
    assert s.word_h > 0 and s.run_gap > 0
