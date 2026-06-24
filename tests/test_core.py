"""Tests for circleci-credit-by-user."""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from circleci_credit_by_user.core import (
    aggregate_by_actor,
    build_actor_map,
    extract_actor_login,
    load_usage_csv,
    merge_usage_csv_parts,
    split_date_ranges,
    unique_pipeline_ids,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_split_date_ranges_respects_32_day_window() -> None:
    ranges = split_date_ranges(date(2026, 1, 1), date(2026, 2, 15))
    assert ranges[0] == (date(2026, 1, 1), date(2026, 2, 1))
    assert ranges[1] == (date(2026, 2, 2), date(2026, 2, 15))


def test_unique_pipeline_ids_from_fixture() -> None:
    rows = load_usage_csv(FIXTURES / "sample_usage.csv")
    assert unique_pipeline_ids(rows) == ["pipe-a", "pipe-b"]


def test_merge_usage_csv_parts() -> None:
    raw = (FIXTURES / "sample_usage.csv").read_bytes()
    rows = merge_usage_csv_parts([raw])
    assert len(rows) == 3


def test_extract_actor_login_prefers_trigger_actor() -> None:
    pipeline = {
        "trigger": {"actor": {"login": "octocat"}},
        "trigger_parameters": {"git": {"author_login": "ignored"}},
    }
    assert extract_actor_login(pipeline) == "octocat"


def test_extract_actor_login_falls_back_to_trigger_parameters() -> None:
    pipeline = {
        "trigger": {"actor": {}},
        "trigger_parameters": {"circleci": {"provider_login": "fallback-user"}},
    }
    assert extract_actor_login(pipeline) == "fallback-user"


def test_aggregate_by_actor_defaults_to_total_compute_and_user_credits() -> None:
    rows = load_usage_csv(FIXTURES / "sample_usage.csv")
    actor_map = {"pipe-a": "alice", "pipe-b": "bob"}
    summary = aggregate_by_actor(rows, actor_map)
    by_actor = {row["actor"]: row for row in summary}
    assert by_actor["alice"]["TOTAL_CREDITS"] == 15.0
    assert by_actor["alice"]["COMPUTE_CREDITS"] == 12.0
    assert by_actor["alice"]["USER_CREDITS"] == 3.0
    assert by_actor["bob"]["TOTAL_CREDITS"] == 20.0
    assert by_actor["bob"]["COMPUTE_CREDITS"] == 0.0
    assert by_actor["bob"]["USER_CREDITS"] == 20.0
    assert by_actor["alice"]["pipeline_count"] == 1
    assert by_actor["alice"]["job_rows"] == 2


def test_aggregate_by_actor_supports_custom_credit_columns() -> None:
    rows = load_usage_csv(FIXTURES / "sample_usage.csv")
    actor_map = {"pipe-a": "alice", "pipe-b": "bob"}
    summary = aggregate_by_actor(rows, actor_map, credit_columns=["COMPUTE_CREDITS"])
    by_actor = {row["actor"]: row for row in summary}
    assert set(by_actor["alice"].keys()) == {"actor", "pipeline_count", "job_rows", "COMPUTE_CREDITS"}
    assert by_actor["alice"]["COMPUTE_CREDITS"] == 12.0


def test_build_actor_map_uses_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "actors.json"
        cache_path.write_text(json.dumps({"pipe-a": "cached-user"}))
        actor_map = build_actor_map(
            "https://example.com",
            "token",
            ["pipe-a"],
            cache_path=cache_path,
        )
        assert actor_map["pipe-a"] == "cached-user"
