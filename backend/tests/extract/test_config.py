import dataclasses
import json

import pytest

from l2c.extract.config import DEFAULT_CONFIG, Config, load_config


def test_defaults_cover_french_and_english_keywords():
    c = DEFAULT_CONFIG
    assert c.starts("ARM.: 4-25M", c.block_start) and c.starts("REINF.: 4-25M", c.block_start)
    assert c.starts("béton: 25MPa", c.end_line)  # matching ignores case
    assert c.starts("BÉTON: 25MPa", c.end_line) and c.starts("BETON: 25MPa", c.end_line)
    assert "ARM" in c.keywords() and "VERT" in c.keywords() and "EL:" in c.keywords()


def test_config_is_hashable_so_parsers_can_cache_per_config():
    assert hash(DEFAULT_CONFIG) == hash(Config())
    assert hash(dataclasses.replace(DEFAULT_CONFIG, default_spacing_unit="mm")) != hash(
        DEFAULT_CONFIG
    )


def test_json_overrides_replace_only_the_given_keys(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(
        json.dumps({"ties_line": ["STIRRUPS"], "level_names": {"BASEMENT": "SS"}}), encoding="utf-8"
    )
    c = load_config(f)
    assert c.ties_line == ("STIRRUPS",) and c.level_names == (("BASEMENT", "SS"),)
    assert c.block_start == DEFAULT_CONFIG.block_start  # untouched


def test_unknown_keys_fail_loudly(tmp_path):
    f = tmp_path / "c.json"
    f.write_text('{"ties_lines": ["x"]}', encoding="utf-8")  # typo
    with pytest.raises(ValueError, match="unknown config keys"):
        load_config(f)


def test_no_config_means_defaults():
    assert load_config(None) is DEFAULT_CONFIG
