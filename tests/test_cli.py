"""Tests for the CLI argument parsing and orchestration in cli.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from circleci_credit_by_user import cli

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CIRCLECI_ORG_ID", "CIRCLECI_TOKEN", "CIRCLECI_API_TOKEN", "CIRCLECI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)


def test_parse_args_defaults() -> None:
    args = cli.parse_args(["--org-id", "org-1"])
    assert args.org_id == "org-1"
    assert args.base_url == cli.DEFAULT_BASE_URL
    assert args.sort_by == "TOTAL_CREDITS"
    assert args.workers == 8
    assert args.poll_interval == 5.0
    assert args.timeout == 3600.0
    assert args.summary_output == Path("user_credits_summary.csv")
    assert args.actor_cache == Path(".cache/pipeline_actors.json")
    assert args.display_columns is None
    assert args.skip_pipeline_fetch is False


def test_parse_args_org_id_defaults_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIRCLECI_ORG_ID", "org-from-env")
    args = cli.parse_args([])
    assert args.org_id == "org-from-env"


def test_parse_args_display_column_repeats() -> None:
    args = cli.parse_args(
        ["--display-column", "COMPUTE_CREDITS", "--display-column", "USER_CREDITS"]
    )
    assert args.display_columns == ["COMPUTE_CREDITS", "USER_CREDITS"]


def test_parse_args_rejects_unknown_sort_column() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--sort-by", "NOT_A_COLUMN"])


def test_main_requires_org_id_without_usage_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIRCLECI_TOKEN", "test-token")
    with pytest.raises(SystemExit):
        cli.main([])


def test_main_requires_dates_without_usage_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIRCLECI_TOKEN", "test-token")
    with pytest.raises(SystemExit):
        cli.main(["--org-id", "org-1"])


def test_main_skip_pipeline_fetch_loads_usage_csv_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CIRCLECI_TOKEN", "test-token")
    exit_code = cli.main(
        [
            "--usage-csv",
            str(FIXTURES / "sample_usage.csv"),
            "--skip-pipeline-fetch",
        ]
    )
    assert exit_code == 0
    assert "Loaded 3 usage rows" in capsys.readouterr().err


def test_main_writes_usage_output_when_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CIRCLECI_TOKEN", "test-token")
    usage_output = tmp_path / "merged.csv"
    exit_code = cli.main(
        [
            "--usage-csv",
            str(FIXTURES / "sample_usage.csv"),
            "--skip-pipeline-fetch",
            "--usage-output",
            str(usage_output),
        ]
    )
    assert exit_code == 0
    assert usage_output.is_file()
    assert "pipe-a" in usage_output.read_text()


def test_main_full_flow_writes_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CIRCLECI_TOKEN", "test-token")

    def fake_build_actor_map(base_url, token, pipeline_ids, workers=8, cache_path=None):
        return {"pipe-a": "alice", "pipe-b": "bob"}

    monkeypatch.setattr(cli, "build_actor_map", fake_build_actor_map)

    summary_output = tmp_path / "summary.csv"
    exit_code = cli.main(
        [
            "--usage-csv",
            str(FIXTURES / "sample_usage.csv"),
            "--summary-output",
            str(summary_output),
        ]
    )

    assert exit_code == 0
    assert summary_output.is_file()
    content = summary_output.read_text()
    assert "alice" in content
    assert "bob" in content

    out = capsys.readouterr().out
    assert "alice" in out
    assert "bob" in out
