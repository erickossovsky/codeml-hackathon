import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "guard", Path(__file__).resolve().parents[3] / "scripts" / "guard.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_blocks_confidential_file_types_and_data_folders():
    problems = guard.check_paths(
        {
            "docs/plan.pdf": 10,
            "data/out/x/elements.json": 10,
            "deliverables/P/findings.xlsx": 10,
            "backend/l2c/ok.py": 100,
            "data/.gitkeep": 0,
        }
    )
    joined = "\n".join(problems)
    assert "docs/plan.pdf" in joined and "data/out/x/elements.json" in joined
    assert "findings.xlsx" in joined
    assert "ok.py" not in joined and ".gitkeep" not in joined


def test_oversized_files_and_notebook_outputs_are_blocked():
    problems = guard.check_paths({"big.txt": 2_000_000}, {"nb.ipynb"})
    assert any("big.txt" in p for p in problems) and any("nb.ipynb" in p for p in problems)


def test_synthetic_fixtures_are_allowed_even_if_they_are_json_or_pdf():
    assert guard.check_paths({"shared/fixtures/mock_a/elements.json": 5000}) == []
    assert guard.check_paths({"shared/fixtures/huge.json": 5_000_000})  # size still limited


def test_secret_patterns_are_detected():
    assert guard.find_secrets("a.py", 'api_key = "abcdef0123456789abcdef"')
    assert guard.find_secrets("b.txt", "-----BEGIN PRIVATE KEY-----")
    assert guard.find_secrets("c.py", "x = 1  # nothing here") == []


def test_local_analysis_notes_and_hand_labels_are_blocked():
    problems = guard.check_paths({"docs/private/baselines.md": 10, "metrics/gold/labels.csv": 10})
    assert any("docs/private/baselines.md" in p for p in problems)
    assert any("metrics/gold/labels.csv" in p for p in problems)
