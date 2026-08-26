"""Tests for circleci-credit-by-user."""

from __future__ import annotations

import gzip
import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from circleci_credit_by_user.core import (
    CREDIT_COLUMNS,
    aggregate_by_actor,
    build_actor_map,
    discover_credit_columns,
    extract_actor_login,
    load_usage_csv,
    merge_usage_csv_parts,
    parse_float,
    print_summary,
    resolve_token,
    save_usage_csv,
    split_date_ranges,
    to_export_datetime,
    unique_pipeline_ids,
    write_summary_csv,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_split_date_ranges_respects_32_day_window() -> None:
    ranges = split_date_ranges(date(2026, 1, 1), date(2026, 2, 15))
    assert ranges[0] == (date(2026, 1, 1), date(2026, 2, 1))
    assert ranges[1] == (date(2026, 2, 2), date(2026, 2, 15))


def test_split_date_ranges_raises_when_start_after_end() -> None:
    with pytest.raises(ValueError):
        split_date_ranges(date(2026, 2, 1), date(2026, 1, 1))


def test_unique_pipeline_ids_from_fixture() -> None:
    rows = load_usage_csv(FIXTURES / "sample_usage.csv")
    assert unique_pipeline_ids(rows) == ["pipe-a", "pipe-b"]


def test_merge_usage_csv_parts() -> None:
    raw = (FIXTURES / "sample_usage.csv").read_bytes()
    rows = merge_usage_csv_parts([raw])
    assert len(rows) == 3


def test_discover_credit_columns_from_fixture() -> None:
    rows = load_usage_csv(FIXTURES / "sample_usage.csv")
    assert discover_credit_columns(rows) == list(CREDIT_COLUMNS)


def test_discover_credit_columns_empty_rows_returns_all_columns() -> None:
    assert discover_credit_columns([]) == list(CREDIT_COLUMNS)


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


def test_extract_actor_login_falls_back_to_github_app_trigger_parameters() -> None:
    pipeline = {
        "trigger": {"actor": {}},
        "trigger_parameters": {"github_app": {"provider_login": "gha-user"}},
    }
    assert extract_actor_login(pipeline) == "gha-user"


def test_extract_actor_login_falls_back_to_user_name_candidate() -> None:
    pipeline = {
        "trigger": {"actor": {}},
        "trigger_parameters": {"git": {"user_name": "git-user"}},
    }
    assert extract_actor_login(pipeline) == "git-user"


def test_aggregate_by_actor_sums_all_credit_columns() -> None:
    rows = load_usage_csv(FIXTURES / "sample_usage.csv")
    actor_map = {"pipe-a": "alice", "pipe-b": "bob"}
    summary = aggregate_by_actor(rows, actor_map)
    by_actor = {row["actor"]: row for row in summary}

    assert by_actor["alice"]["TOTAL_CREDITS"] == 15.0
    assert by_actor["alice"]["COMPUTE_CREDITS"] == 12.0
    assert by_actor["alice"]["STORAGE_CREDITS"] == 1.0
    assert by_actor["alice"]["USER_CREDITS"] == 2.0
    assert by_actor["bob"]["TOTAL_CREDITS"] == 20.0
    assert by_actor["bob"]["COMPUTE_CREDITS"] == 0.0
    assert by_actor["bob"]["USER_CREDITS"] == 20.0
    assert by_actor["alice"]["IPRANGES_CREDITS"] == 0.0
    assert by_actor["alice"]["pipeline_count"] == 1
    assert by_actor["alice"]["job_rows"] == 2


def test_aggregate_by_actor_supports_sort_by() -> None:
    rows = load_usage_csv(FIXTURES / "sample_usage.csv")
    actor_map = {"pipe-a": "alice", "pipe-b": "bob"}
    summary = aggregate_by_actor(rows, actor_map, sort_by="USER_CREDITS")
    assert summary[0]["actor"] == "bob"


def test_aggregate_by_actor_raises_for_unknown_sort_column() -> None:
    rows = load_usage_csv(FIXTURES / "sample_usage.csv")
    actor_map = {"pipe-a": "alice", "pipe-b": "bob"}
    with pytest.raises(ValueError):
        aggregate_by_actor(rows, actor_map, sort_by="NOT_A_COLUMN")


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


def test_merge_usage_csv_parts_decompresses_gzip() -> None:
    raw = (FIXTURES / "sample_usage.csv").read_bytes()
    gzipped = gzip.compress(raw)
    rows = merge_usage_csv_parts([gzipped])
    assert len(rows) == 3
    assert rows[0]["PIPELINE_ID"] == "pipe-a"


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 0.0),
        ("", 0.0),
        (r"\N", 0.0),
        ("NULL", 0.0),
        ("3.5", 3.5),
        ("0", 0.0),
    ],
)
def test_parse_float_handles_null_markers(value: str | None, expected: float) -> None:
    assert parse_float(value) == expected


def test_to_export_datetime_start_of_day() -> None:
    assert to_export_datetime(date(2026, 1, 1)) == "2026-01-01T00:00:00Z"


def test_to_export_datetime_end_of_day() -> None:
    assert to_export_datetime(date(2026, 1, 1), end_of_day=True) == "2026-01-01T23:59:59Z"


def test_resolve_token_prefers_explicit_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIRCLECI_TOKEN", "env-token")
    assert resolve_token("explicit-token") == "explicit-token"


def test_resolve_token_falls_back_to_circleci_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIRCLECI_API_TOKEN", raising=False)
    monkeypatch.setenv("CIRCLECI_TOKEN", "env-token")
    assert resolve_token(None) == "env-token"


def test_resolve_token_falls_back_to_circleci_api_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIRCLECI_TOKEN", raising=False)
    monkeypatch.setenv("CIRCLECI_API_TOKEN", "api-env-token")
    assert resolve_token(None) == "api-env-token"


def test_resolve_token_falls_back_to_cli_config_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CIRCLECI_TOKEN", raising=False)
    monkeypatch.delenv("CIRCLECI_API_TOKEN", raising=False)
    circleci_dir = tmp_path / ".circleci"
    circleci_dir.mkdir()
    (circleci_dir / "cli.yml").write_text("token: file-token\nother: value\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert resolve_token(None) == "file-token"


def test_resolve_token_raises_when_nothing_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CIRCLECI_TOKEN", raising=False)
    monkeypatch.delenv("CIRCLECI_API_TOKEN", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(SystemExit):
        resolve_token(None)


def test_print_summary_formats_rows(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [
        {"actor": "alice", "pipeline_count": 1, "job_rows": 2, "TOTAL_CREDITS": 15.0},
    ]
    print_summary(rows, ["TOTAL_CREDITS"])
    out = capsys.readouterr().out
    assert "alice" in out
    assert "15.00" in out
    lines = out.splitlines()
    assert lines[0].split() == ["actor", "pipelines", "jobs", "TOTAL_CREDITS"]


def test_write_summary_csv_writes_header_and_rows(tmp_path: Path) -> None:
    rows = [{"actor": "alice", "TOTAL_CREDITS": 15.0}]
    out_path = tmp_path / "summary.csv"
    write_summary_csv(out_path, rows)
    content = out_path.read_text()
    assert "actor" in content.splitlines()[0]
    assert "alice" in content


def test_write_summary_csv_raises_on_empty_rows(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        write_summary_csv(tmp_path / "summary.csv", [])


def test_save_usage_csv_raises_on_empty_rows(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        save_usage_csv(tmp_path / "usage.csv", [])
