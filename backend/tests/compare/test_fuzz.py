import pytest

from l2c.compare.run import run_comparison
from l2c.mock.fuzz import fuzz_project

SEEDS = range(60)


@pytest.mark.parametrize("seed", SEEDS)
def test_every_injected_defect_is_found_and_nothing_else_is_flagged(seed):
    fp = fuzz_project(seed)
    findings = [f for f in run_comparison(fp.bundle) if f.check_type == "cross.plan_vs_shop"]
    got = {(f.level, f.grid): f.status for f in findings if f.status != "compliant"}
    want = {(i.level, i.grid): i.expected_status for i in fp.injected}
    assert got == want, {
        "seed": seed,
        "unexpected": got.keys() - want.keys(),
        "missed": want.keys() - got.keys(),
        "wrong": {k: (got[k], want[k]) for k in got.keys() & want.keys() if got[k] != want[k]},
    }


def test_fuzz_projects_really_vary():
    shapes = {
        (
            len(fp.bundle.levels),
            len({e.match_key.row for e in fp.bundle.elements}),
            len({e.fichier for e in fp.bundle.elements if e.source == "shop"}),
        )
        for fp in map(fuzz_project, SEEDS)
    }
    assert len(shapes) >= 10


def test_recall_over_all_seeds_is_one():
    found = total = 0
    for seed in SEEDS:
        fp = fuzz_project(seed)
        flagged = {
            (f.level, f.grid)
            for f in run_comparison(fp.bundle)
            if f.check_type == "cross.plan_vs_shop" and f.status != "compliant"
        }
        total += len(fp.injected)
        found += sum((i.level, i.grid) in flagged for i in fp.injected)
    assert total > 150 and found == total
