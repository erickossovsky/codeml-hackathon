from l2c.extract.anchor import bind_blocks, find_outlines
from l2c.extract.grid import Grid
from l2c.ingest.pages import Shape


def shape(cx, cy, w=12.0, h=18.0):
    return Shape(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


GRID = Grid(rows={"K": 100.0, "L": 200.0}, cols={"3.4": 1400.0, "4": 1352.0, "5": 1220.0})


def test_find_outlines_snaps_to_cells_and_ignores_noise():
    shapes = [
        shape(1352, 100),
        shape(1400, 200),
        shape(500, 500),
        Shape(0, 0, 1, 1),
        shape(1352, 103),
    ]
    out = find_outlines(shapes, GRID, 14.0)
    assert set(out) == {("K", "4"), ("L", "3.4")}
    assert out[("K", "4")].shape.cy == 100  # closest candidate to the intersection wins


def test_binding_uses_consistent_offset_not_nearest_outline():
    outlines = find_outlines([shape(1352, 100), shape(1400, 100), shape(1220, 100)], GRID, 14.0)
    # blocks sit 35 pt right of and 20 pt below their column: the first block is nearer
    # to the neighbouring outline than to its own
    anchors = [(1352 + 35, 120), (1400 + 35, 120), (1220 + 35, 120)]
    bound = bind_blocks(anchors, outlines)
    assert [(b.row, b.col) for b in bound] == [("K", "4"), ("K", "3.4"), ("K", "5")]
    nearest_only = min(outlines, key=lambda k: abs(outlines[k].shape.cx - anchors[0][0]))
    assert nearest_only == ("K", "3.4")  # proves plain nearest-outline would have been wrong


def test_binding_is_one_to_one_and_leaves_extra_blocks_unbound():
    outlines = find_outlines([shape(1352, 100)], GRID, 14.0)
    bound = bind_blocks([(1353, 120), (1354, 121)], outlines)
    assert sum(b is not None for b in bound) == 1


def test_binding_margin_is_low_when_two_outlines_are_equally_close():
    outlines = find_outlines([shape(1352, 100), shape(1400, 100)], GRID, 14.0)
    (b,) = bind_blocks([(1376, 120)], outlines)
    assert b is not None and b.margin < 0.2


def test_empty_inputs():
    assert bind_blocks([], {}) == []
    assert bind_blocks([(1, 2)], {}) == [None]


def test_two_offset_modes_left_and_right_of_columns():
    cols = {"1": 100.0, "2": 400.0, "3": 700.0, "4": 1000.0, "5": 1300.0, "6": 1600.0}
    grid = Grid(rows={"K": 100.0}, cols=cols)
    outlines = find_outlines([shape(x, 100) for x in cols.values()], grid, 14.0)
    side = {"1": +80, "2": -80, "3": +80, "4": -80, "5": +80, "6": -80}
    anchors = [(cols[c] + dx, 120.0) for c, dx in side.items()]
    bound = bind_blocks(anchors, outlines)
    assert [b.col for b in bound] == list(side)
    assert all(not b.second_pass for b in bound)


def test_second_pass_binds_leftovers_with_penalised_margin():
    grid = Grid(rows={"K": 100.0}, cols={"1": 100.0, "2": 400.0})
    outlines = find_outlines([shape(100, 100), shape(400, 100)], grid, 14.0)
    # first block is 150 pt from its outline (beyond the 120 pt first-pass radius)
    bound = bind_blocks([(100 + 150, 100.0), (400, 120.0)], outlines)
    assert [b.col for b in bound] == ["1", "2"]
    assert bound[0].second_pass and not bound[1].second_pass
