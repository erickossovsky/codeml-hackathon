from l2c.compare.run import run_comparison
from l2c.mock.generate import mock_project


def test_mock_project_produces_exactly_the_expected_findings():
    m = mock_project()
    findings = run_comparison(m.bundle)
    got = {(f.check_type, f.status, f.level, f.grid) for f in findings if f.status != "compliant"}
    want = {(x.check_type, x.status, x.level, x.grid) for x in m.expected}
    assert got == want, {"unexpected": got - want, "missing": want - got}


def test_compliant_pairs_are_reported_with_full_trust():
    findings = run_comparison(mock_project().bundle)
    ok = [f for f in findings if f.status == "compliant"]
    assert len(ok) > 10
    assert all(f.check_type == "cross.plan_vs_shop" and f.confidence >= 0.9 for f in ok)


def test_low_trust_difference_is_not_a_firm_verdict():
    findings = run_comparison(mock_project().bundle)
    f = next(
        x
        for x in findings
        if x.grid == "K-4" and x.level == "N3" and x.check_type == "cross.plan_vs_shop"
    )
    assert f.status == "needs_review" and f.evidence.rule.fired and f.diffs[0].field == "count"
    assert f.trust == 0.4 and f.confidence == 0.4


def test_peer_outlier_and_cross_finding_agree_on_the_known_case():
    findings = run_comparison(mock_project().bundle)
    here = [f for f in findings if f.grid == "K-5" and f.level == "N2"]
    kinds = {(f.check_type, f.status) for f in here}
    assert ("cross.plan_vs_shop", "non_compliant") in kinds
    assert ("self.peer_outlier", "needs_review") in kinds
    outlier = next(f for f in here if f.check_type == "self.peer_outlier")
    assert outlier.evidence.ml and outlier.evidence.ml.peer_anomaly > 0.8


def test_findings_are_deterministic_and_have_unique_ids():
    a = run_comparison(mock_project().bundle)
    b = run_comparison(mock_project().bundle)
    assert [f.model_dump_json() for f in a] == [f.model_dump_json() for f in b]
    assert len({f.id for f in a}) == len(a)


def test_a_pair_without_differences_but_low_trust_keeps_a_meaningful_confidence():
    from l2c.compare.run import run_comparison
    from l2c.contract.io import MetaBundle
    from l2c.mock.elements import make_element

    plan = make_element("plan", "N2", "K", 3, overall=0.6)
    shop = make_element("shop", "N2", "K", 3, overall=0.9)
    (f,) = [
        x
        for x in run_comparison(MetaBundle(project="x", elements=[plan, shop]))
        if x.check_type == "cross.plan_vs_shop"
    ]
    assert f.status == "needs_review" and not f.evidence.rule.fired
    assert f.trust == 0.6 and f.confidence == 0.6  # not 0.0
