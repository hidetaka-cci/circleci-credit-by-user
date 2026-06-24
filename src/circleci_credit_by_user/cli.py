"""CLI entry point."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from circleci_credit_by_user.core import (
    CREDIT_COLUMNS,
    DEFAULT_BASE_URL,
    DEFAULT_SUMMARY_CREDIT_COLUMNS,
    aggregate_by_actor,
    build_actor_map,
    fetch_usage_rows,
    load_usage_csv,
    print_summary,
    resolve_token,
    save_usage_csv,
    unique_pipeline_ids,
    write_summary_csv,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate CircleCI credits by trigger actor (Usage API + Pipeline API).",
        epilog="See https://github.com/hidetaka-cci/circleci-credit-by-user for limitations.",
    )
    parser.add_argument("--org-id", default=os.environ.get("CIRCLECI_ORG_ID"))
    parser.add_argument("--token", help="CircleCI personal API token")
    parser.add_argument("--base-url", default=os.environ.get("CIRCLECI_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--usage-csv",
        type=Path,
        help="Skip Usage API export and read an existing merged usage CSV",
    )
    parser.add_argument(
        "--usage-output",
        type=Path,
        help="Write merged usage CSV to this path",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("user_credits_summary.csv"),
        help="Write actor summary CSV (default: user_credits_summary.csv)",
    )
    parser.add_argument(
        "--actor-cache",
        type=Path,
        default=Path(".cache/pipeline_actors.json"),
        help="Cache Pipeline API actor lookups",
    )
    parser.add_argument(
        "--credit-column",
        dest="credit_columns",
        action="append",
        choices=CREDIT_COLUMNS,
        metavar="COLUMN",
        help=(
            "Credit column(s) to aggregate. Repeat for multiple columns. "
            f"Default: {', '.join(DEFAULT_SUMMARY_CREDIT_COLUMNS)} "
            "(TOTAL + compute + seat/user fees)"
        ),
    )
    parser.add_argument("--workers", type=int, default=8, help="Parallel Pipeline API workers")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--skip-pipeline-fetch", action="store_true", help="Only export/merge usage CSV")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    token = resolve_token(args.token)

    if args.usage_csv:
        usage_rows = load_usage_csv(args.usage_csv)
    else:
        if not args.org_id:
            raise SystemExit("--org-id or CIRCLECI_ORG_ID is required unless --usage-csv is provided")
        if not args.start_date or not args.end_date:
            raise SystemExit("--start-date and --end-date are required unless --usage-csv is provided")
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        usage_rows = fetch_usage_rows(
            args.base_url.rstrip("/"),
            args.org_id,
            token,
            start,
            end,
            poll_interval=args.poll_interval,
            timeout_seconds=args.timeout,
        )

    if args.usage_output:
        save_usage_csv(args.usage_output, usage_rows)
        print(f"Wrote merged usage CSV to {args.usage_output}", file=sys.stderr)

    if args.skip_pipeline_fetch:
        print(f"Loaded {len(usage_rows)} usage rows", file=sys.stderr)
        return 0

    pipeline_ids = unique_pipeline_ids(usage_rows)
    actor_map = build_actor_map(
        args.base_url.rstrip("/"),
        token,
        pipeline_ids,
        workers=args.workers,
        cache_path=args.actor_cache,
    )
    credit_columns = args.credit_columns or list(DEFAULT_SUMMARY_CREDIT_COLUMNS)
    summary = aggregate_by_actor(usage_rows, actor_map, credit_columns=credit_columns)
    write_summary_csv(args.summary_output, summary)
    print_summary(summary, credit_columns)
    print(f"\nWrote summary to {args.summary_output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
