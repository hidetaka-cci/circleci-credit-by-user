"""Core logic for Usage API export and Pipeline API actor joins."""

from __future__ import annotations

import csv
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_BASE_URL = "https://circleci.com"
MAX_EXPORT_WINDOW_DAYS = 32
PIPELINE_ID_COLUMN = "PIPELINE_ID"
CREDIT_COLUMNS = (
    "TOTAL_CREDITS",
    "COMPUTE_CREDITS",
    "STORAGE_CREDITS",
    "NETWORK_CREDITS",
    "USER_CREDITS",
    "DLC_CREDITS",
    "LEASE_CREDITS",
    "LEASE_OVERAGE_CREDITS",
    "IPRANGES_CREDITS",
)


@dataclass(frozen=True)
class UsageExportJob:
    job_id: str
    state: str
    download_urls: list[str]


def resolve_token(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("CIRCLECI_TOKEN") or os.environ.get("CIRCLECI_API_TOKEN")
    if env:
        return env
    cli_path = Path.home() / ".circleci" / "cli.yml"
    if cli_path.is_file():
        for line in cli_path.read_text().splitlines():
            if line.startswith("token:"):
                return line.split(":", 1)[1].strip()
    raise SystemExit(
        "CircleCI token not found. Set CIRCLECI_TOKEN or add token to ~/.circleci/cli.yml"
    )


def api_request(
    method: str,
    url: str,
    token: str,
    payload: dict | None = None,
    timeout: int = 60,
    *,
    allow_http_error: bool = False,
) -> dict:
    data = None
    headers = {
        "Circle-Token": token,
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if allow_http_error:
            return {"_http_error": exc.code, "_detail": detail}
        raise SystemExit(f"HTTP {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        if allow_http_error:
            return {"_http_error": "url_error", "_detail": str(exc.reason)}
        raise SystemExit(f"Request failed for {url}: {exc.reason}") from exc


def to_export_datetime(value: date, end_of_day: bool = False) -> str:
    if end_of_day:
        dt = datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=timezone.utc)
    else:
        dt = datetime(value.year, value.month, value.day, 0, 0, 0, tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def split_date_ranges(start: date, end: date, max_days: int = MAX_EXPORT_WINDOW_DAYS) -> list[tuple[date, date]]:
    if start > end:
        raise ValueError("start date must be on or before end date")
    ranges: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        ranges.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return ranges


def create_usage_export_job(
    base_url: str,
    org_id: str,
    token: str,
    start: date,
    end: date,
) -> UsageExportJob:
    url = f"{base_url}/api/v2/organizations/{org_id}/usage_export_job"
    payload = {"start": to_export_datetime(start), "end": to_export_datetime(end, end_of_day=True)}
    body = api_request("POST", url, token, payload)
    return UsageExportJob(
        job_id=body["usage_export_job_id"],
        state=body.get("state", "created"),
        download_urls=body.get("download_urls") or [],
    )


def poll_usage_export_job(
    base_url: str,
    org_id: str,
    token: str,
    job_id: str,
    poll_interval: float = 5.0,
    timeout_seconds: float = 3600.0,
) -> UsageExportJob:
    url = f"{base_url}/api/v2/organizations/{org_id}/usage_export_job/{job_id}"
    deadline = time.monotonic() + timeout_seconds
    while True:
        body = api_request("GET", url, token)
        state = body.get("state", "unknown")
        job = UsageExportJob(
            job_id=body["usage_export_job_id"],
            state=state,
            download_urls=body.get("download_urls") or [],
        )
        if state == "completed":
            if not job.download_urls:
                raise SystemExit(f"Usage export job {job_id} completed without download URLs")
            return job
        if state == "failed":
            raise SystemExit(
                f"Usage export job {job_id} failed: {body.get('error_reason', 'unknown error')}"
            )
        if time.monotonic() >= deadline:
            raise SystemExit(f"Timed out waiting for usage export job {job_id} (last state={state})")
        time.sleep(poll_interval)


def download_url(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def iter_csv_rows_from_bytes(raw: bytes) -> Iterable[dict[str, str]]:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    yield from reader


def merge_usage_csv_parts(parts: Sequence[bytes]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for part in parts:
        rows.extend(iter_csv_rows_from_bytes(part))
    return rows


def load_usage_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    return list(iter_csv_rows_from_bytes(raw))


def save_usage_csv(path: Path, rows: Sequence[dict[str, str]]) -> None:
    if not rows:
        raise SystemExit("No usage rows to write")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fetch_usage_rows(
    base_url: str,
    org_id: str,
    token: str,
    start: date,
    end: date,
    poll_interval: float,
    timeout_seconds: float,
) -> list[dict[str, str]]:
    all_rows: list[dict[str, str]] = []
    for chunk_start, chunk_end in split_date_ranges(start, end):
        job = create_usage_export_job(base_url, org_id, token, chunk_start, chunk_end)
        print(
            f"Created usage export job {job.job_id} for {chunk_start}..{chunk_end}",
            file=sys.stderr,
        )
        completed = poll_usage_export_job(
            base_url,
            org_id,
            token,
            job.job_id,
            poll_interval=poll_interval,
            timeout_seconds=timeout_seconds,
        )
        print(
            f"Downloading {len(completed.download_urls)} file(s) for job {completed.job_id}",
            file=sys.stderr,
        )
        parts = [download_url(url) for url in completed.download_urls]
        chunk_rows = merge_usage_csv_parts(parts)
        print(f"Loaded {len(chunk_rows)} rows for {chunk_start}..{chunk_end}", file=sys.stderr)
        all_rows.extend(chunk_rows)
    return all_rows


def parse_float(value: str | None) -> float:
    if value in (None, "", r"\N", "NULL"):
        return 0.0
    return float(value)


def unique_pipeline_ids(rows: Sequence[dict[str, str]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        pipeline_id = row.get(PIPELINE_ID_COLUMN, "").strip()
        if pipeline_id and pipeline_id not in seen:
            seen.add(pipeline_id)
            ordered.append(pipeline_id)
    return ordered


def extract_actor_login(pipeline: dict) -> str | None:
    trigger = pipeline.get("trigger") or {}
    actor = trigger.get("actor") or {}
    login = actor.get("login")
    if login:
        return str(login)

    params = pipeline.get("trigger_parameters") or {}
    for key in ("circleci", "git", "github_app"):
        section = params.get(key) or {}
        for candidate_key in ("provider_login", "author_login", "user_username", "user_name"):
            candidate = section.get(candidate_key)
            if candidate:
                return str(candidate)
    return None


def fetch_pipeline_actor(
    base_url: str,
    token: str,
    pipeline_id: str,
) -> tuple[str, str | None]:
    url = f"{base_url}/api/v2/pipeline/{pipeline_id}"
    body = api_request("GET", url, token, allow_http_error=True)
    if body.get("_http_error"):
        print(
            f"Warning: pipeline {pipeline_id} lookup failed "
            f"(HTTP {body['_http_error']}); attributing as (unknown)",
            file=sys.stderr,
        )
        return pipeline_id, None
    return pipeline_id, extract_actor_login(body)


def build_actor_map(
    base_url: str,
    token: str,
    pipeline_ids: Sequence[str],
    workers: int = 8,
    cache_path: Path | None = None,
) -> dict[str, str | None]:
    actor_map: dict[str, str | None] = {}
    if cache_path and cache_path.is_file():
        actor_map.update(json.loads(cache_path.read_text()))

    missing = [pid for pid in pipeline_ids if pid not in actor_map]
    if not missing:
        return actor_map

    print(f"Fetching actor info for {len(missing)} pipeline(s)", file=sys.stderr)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_pipeline_actor, base_url, token, pipeline_id): pipeline_id
            for pipeline_id in missing
        }
        for future in as_completed(futures):
            pipeline_id, actor = future.result()
            actor_map[pipeline_id] = actor
            completed += 1
            if cache_path and completed % 250 == 0:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(actor_map, indent=2, sort_keys=True))
                print(f"Cached {completed}/{len(missing)} pipeline actors", file=sys.stderr)

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(actor_map, indent=2, sort_keys=True))
    return actor_map


def aggregate_by_actor(
    rows: Sequence[dict[str, str]],
    actor_map: dict[str, str | None],
    credit_column: str = "TOTAL_CREDITS",
) -> list[dict[str, str | float | int]]:
    totals: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"job_rows": 0, "pipeline_count": 0, credit_column: 0.0}
    )
    pipeline_sets: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        pipeline_id = row.get(PIPELINE_ID_COLUMN, "").strip()
        actor = actor_map.get(pipeline_id) or "(unknown)"
        bucket = totals[actor]
        bucket["job_rows"] = int(bucket["job_rows"]) + 1
        bucket[credit_column] = float(bucket[credit_column]) + parse_float(row.get(credit_column))
        pipeline_sets[actor].add(pipeline_id)

    result: list[dict[str, str | float | int]] = []
    for actor, bucket in totals.items():
        result.append(
            {
                "actor": actor,
                "pipeline_count": len(pipeline_sets[actor]),
                "job_rows": int(bucket["job_rows"]),
                credit_column: round(float(bucket[credit_column]), 4),
            }
        )
    result.sort(key=lambda item: float(item[credit_column]), reverse=True)
    return result


def write_summary_csv(path: Path, rows: Sequence[dict[str, str | float | int]]) -> None:
    if not rows:
        raise SystemExit("No aggregated rows to write")
    fieldnames = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: Sequence[dict[str, str | float | int]], credit_column: str) -> None:
    print(f"{'actor':40} {'pipelines':>10} {'jobs':>8} {credit_column:>14}")
    print("-" * 76)
    for row in rows:
        print(
            f"{row['actor']!s:40} {row['pipeline_count']:>10} "
            f"{row['job_rows']:>8} {float(row[credit_column]):>14.2f}"
        )
