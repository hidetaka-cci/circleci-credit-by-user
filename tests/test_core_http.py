"""Characterization tests for the HTTP-calling parts of core.py.

These lock in current behavior (request shape, error handling, polling
loop) using mocks instead of a live CircleCI API, so the behavior can be
safely ported to another implementation (e.g. a Go rewrite) via TDD.
"""

from __future__ import annotations

import io
import json
import tempfile
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from circleci_credit_by_user import core

FIXTURES_CSV = Path(__file__).parent / "fixtures" / "sample_usage.csv"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_api_request_returns_parsed_json_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core.urllib.request,
        "urlopen",
        lambda req, timeout=60: FakeResponse(json.dumps({"ok": True}).encode()),
    )
    result = core.api_request("GET", "https://example.com/x", "token")
    assert result == {"ok": True}


def test_api_request_returns_empty_dict_for_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core.urllib.request, "urlopen", lambda req, timeout=60: FakeResponse(b"")
    )
    assert core.api_request("GET", "https://example.com/x", "token") == {}


def test_api_request_raises_system_exit_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_http_error(req: object, timeout: int = 60) -> None:
        raise HTTPError("https://example.com/x", 404, "Not Found", None, io.BytesIO(b"nope"))

    monkeypatch.setattr(core.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(SystemExit):
        core.api_request("GET", "https://example.com/x", "token")


def test_api_request_returns_error_payload_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_http_error(req: object, timeout: int = 60) -> None:
        raise HTTPError("https://example.com/x", 500, "Boom", None, io.BytesIO(b"server error"))

    monkeypatch.setattr(core.urllib.request, "urlopen", raise_http_error)
    result = core.api_request(
        "GET", "https://example.com/x", "token", allow_http_error=True
    )
    assert result["_http_error"] == 500
    assert result["_detail"] == "server error"


def test_api_request_raises_system_exit_on_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_url_error(req: object, timeout: int = 60) -> None:
        raise URLError("connection refused")

    monkeypatch.setattr(core.urllib.request, "urlopen", raise_url_error)
    with pytest.raises(SystemExit):
        core.api_request("GET", "https://example.com/x", "token")


def test_download_url_returns_raw_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core.urllib.request, "urlopen", lambda req, timeout=120: FakeResponse(b"raw-bytes")
    )
    assert core.download_url("https://example.com/file.csv") == b"raw-bytes"


def test_create_usage_export_job_builds_job_from_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_api_request(method: str, url: str, token: str, payload: dict | None = None, **kw: object) -> dict:
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return {"usage_export_job_id": "job-1", "state": "created"}

    monkeypatch.setattr(core, "api_request", fake_api_request)
    job = core.create_usage_export_job(
        "https://example.com", "org-1", "token", date(2026, 1, 1), date(2026, 1, 2)
    )
    assert job.job_id == "job-1"
    assert job.state == "created"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/api/v2/organizations/org-1/usage_export_job"


def test_poll_usage_export_job_returns_completed_job(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        {"usage_export_job_id": "job-1", "state": "processing"},
        {"usage_export_job_id": "job-1", "state": "completed", "download_urls": ["https://x/1.csv.gz"]},
    ]

    def fake_api_request(*args: object, **kwargs: object) -> dict:
        return responses.pop(0)

    monkeypatch.setattr(core, "api_request", fake_api_request)
    monkeypatch.setattr(core.time, "sleep", lambda *_: None)
    job = core.poll_usage_export_job(
        "https://example.com", "org-1", "token", "job-1", poll_interval=0, timeout_seconds=60
    )
    assert job.state == "completed"
    assert job.download_urls == ["https://x/1.csv.gz"]


def test_poll_usage_export_job_raises_on_failed_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core,
        "api_request",
        lambda *a, **kw: {
            "usage_export_job_id": "job-1",
            "state": "failed",
            "error_reason": "quota exceeded",
        },
    )
    with pytest.raises(SystemExit):
        core.poll_usage_export_job("https://example.com", "org-1", "token", "job-1")


def test_poll_usage_export_job_raises_when_completed_without_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        core,
        "api_request",
        lambda *a, **kw: {"usage_export_job_id": "job-1", "state": "completed"},
    )
    with pytest.raises(SystemExit):
        core.poll_usage_export_job("https://example.com", "org-1", "token", "job-1")


def test_poll_usage_export_job_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core, "api_request", lambda *a, **kw: {"usage_export_job_id": "job-1", "state": "processing"}
    )
    monkeypatch.setattr(core.time, "sleep", lambda *_: None)
    with pytest.raises(SystemExit):
        core.poll_usage_export_job(
            "https://example.com",
            "org-1",
            "token",
            "job-1",
            poll_interval=0,
            timeout_seconds=0,
        )


def test_fetch_pipeline_actor_returns_login_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core,
        "api_request",
        lambda *a, **kw: {"trigger": {"actor": {"login": "octocat"}}},
    )
    pipeline_id, actor = core.fetch_pipeline_actor("https://example.com", "token", "pipe-a")
    assert pipeline_id == "pipe-a"
    assert actor == "octocat"


def test_fetch_pipeline_actor_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core,
        "api_request",
        lambda *a, **kw: {"_http_error": 404, "_detail": "not found"},
    )
    pipeline_id, actor = core.fetch_pipeline_actor("https://example.com", "token", "pipe-missing")
    assert pipeline_id == "pipe-missing"
    assert actor is None


def test_build_actor_map_fetches_missing_pipelines_over_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch(base_url: str, token: str, pipeline_id: str) -> tuple[str, str | None]:
        return pipeline_id, f"actor-for-{pipeline_id}"

    monkeypatch.setattr(core, "fetch_pipeline_actor", fake_fetch)

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "actors.json"
        cache_path.write_text(json.dumps({"pipe-a": "cached-user"}))

        actor_map = core.build_actor_map(
            "https://example.com",
            "token",
            ["pipe-a", "pipe-b"],
            cache_path=cache_path,
        )

        assert actor_map == {"pipe-a": "cached-user", "pipe-b": "actor-for-pipe-b"}
        persisted = json.loads(cache_path.read_text())
        assert persisted == actor_map


def test_fetch_usage_rows_composes_export_and_download_per_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_ranges: list[tuple[date, date]] = []
    downloaded_urls: list[str] = []

    def fake_create_job(base_url, org_id, token, start, end):
        created_ranges.append((start, end))
        return core.UsageExportJob(job_id=f"job-{start.isoformat()}", state="created", download_urls=[])

    def fake_poll_job(base_url, org_id, token, job_id, poll_interval, timeout_seconds):
        return core.UsageExportJob(job_id=job_id, state="completed", download_urls=[f"https://x/{job_id}.csv"])

    def fake_download(url, timeout=120):
        downloaded_urls.append(url)
        return (FIXTURES_CSV).read_bytes()

    monkeypatch.setattr(core, "create_usage_export_job", fake_create_job)
    monkeypatch.setattr(core, "poll_usage_export_job", fake_poll_job)
    monkeypatch.setattr(core, "download_url", fake_download)

    # 40-day range forces split_date_ranges to produce two chunks (max 32 days each).
    rows = core.fetch_usage_rows(
        "https://example.com",
        "org-1",
        "token",
        date(2026, 1, 1),
        date(2026, 2, 9),
        poll_interval=0,
        timeout_seconds=60,
    )

    assert len(created_ranges) == 2
    assert len(downloaded_urls) == 2
    assert len(rows) == 6  # 3 rows per chunk from the fixture, two chunks
