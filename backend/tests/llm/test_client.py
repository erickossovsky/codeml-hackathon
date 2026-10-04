import pytest

from l2c.llm.client import (
    Budget,
    BudgetExceeded,
    DiskCache,
    FakeClient,
    PromptTooLong,
    _decision_certainty,
    prompt_key,
)

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "enum": ["yes", "no", "unsure"]}},
}


def test_prompt_key_is_stable_and_sensitive():
    a = prompt_key("m", "v1", "s", "u", SCHEMA)
    assert a == prompt_key("m", "v1", "s", "u", SCHEMA)
    assert a != prompt_key("m", "v2", "s", "u", SCHEMA)
    assert a != prompt_key("m", "v1", "s", "u2", SCHEMA)


def test_fake_client_budget_and_default():
    c = FakeClient(budget=Budget(max_calls=1))
    assert c.ask("s", "u", SCHEMA, version="v").data == {"answer": "unsure"}
    with pytest.raises(BudgetExceeded):
        c.ask("s", "u", SCHEMA, version="v")


def test_fake_client_rejects_oversized_prompt():
    with pytest.raises(PromptTooLong):
        FakeClient().ask("s", "x" * 5000, SCHEMA, version="v")


def test_disk_cache_roundtrip(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.get("k") is None
    cache.put("k", {"data": {"answer": "yes"}, "certainty": 0.9})
    assert cache.get("k")["certainty"] == 0.9


def test_decision_certainty_from_logprobs():
    choice = {
        "logprobs": {
            "content": [
                {"token": "{", "logprob": -0.0, "top_logprobs": []},
                {
                    "token": "yes",
                    "logprob": -0.1,
                    "top_logprobs": [
                        {"token": "yes", "logprob": -0.1},
                        {"token": "no", "logprob": -2.4},
                    ],
                },
            ]
        }
    }
    c = _decision_certainty(choice, ["yes", "no", "unsure"])
    assert 0.88 < c < 0.95
