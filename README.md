# circleci-credit-by-user

**English** | [日本語](README.ja.md)

Community CLI to aggregate **CircleCI credits by trigger actor** (GitHub/Bitbucket login).

CircleCI's [Usage API](https://circleci.com/docs/api/v2/index.html#tag/Usage) exposes credit consumption but intentionally omits user identifiers (PII). This tool joins Usage export CSVs with the [Pipeline API](https://circleci.com/docs/api/v2/index.html#tag/Pipeline) to attribute credits to `trigger.actor.login`, and breaks down **all Usage API credit columns** per actor.

> **Disclaimer:** Unofficial community tool. Not supported by CircleCI Support. Results reflect Usage API data and pipeline trigger actors, not legal invoices.

## Why this exists

| Source | Credits | User login |
|---|---|---|
| Usage API CSV | yes | no (by design) |
| Pipeline API | no | yes (`trigger.actor.login`) |
| Webhooks | no | partial |
| Insights API | approximate | no |

The practical approach is: **Usage CSV + Pipeline API JOIN**.

## Features

- Export Usage API data for a date range (auto-splits windows longer than 32 days)
- Merge multi-part `.csv.gz` downloads
- Resolve `pipeline_id` → actor via Pipeline API (with JSON cache)
- Aggregate **all credit breakdown columns** from the Usage export
- Sort and print a terminal summary; write a full CSV for BI / FinOps

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended)
- CircleCI Personal API Token — [create one](https://app.circleci.com/settings/user/tokens)
- Organization ID — shown in **Organization Settings** in the CircleCI app

## Install

```bash
git clone https://github.com/hidetaka-cci/circleci-credit-by-user.git
cd circleci-credit-by-user
uv sync
```

Run without installing:

```bash
uv run circleci-credit-by-user --help
```

Install globally:

```bash
uv tool install .
circleci-credit-by-user --help
```

## Quick start

```bash
export CIRCLECI_TOKEN="your-personal-api-token"
export CIRCLECI_ORG_ID="your-org-uuid"

uv run circleci-credit-by-user \
  --start-date 2026-05-01 \
  --end-date 2026-05-31 \
  --usage-output usage_merged.csv \
  --summary-output user_credits_summary.csv
```

### From an existing Usage CSV

```bash
uv run circleci-credit-by-user \
  --usage-csv usage_merged.csv \
  --summary-output user_credits_summary.csv
```

Pipeline actor lookups are cached at `.cache/pipeline_actors.json` by default.

## How it works

```
Usage Export API
  POST /organizations/{org_id}/usage_export_job
  GET  /organizations/{org_id}/usage_export_job/{job_id}   (poll)
  download_urls[] (.csv.gz) → merge
        ↓ PIPELINE_ID
Pipeline API
  GET /pipeline/{pipeline_id}   (parallel + cache)
        ↓ trigger.actor.login
GROUP BY actor → sum all credit columns
```

## Output

### Summary CSV (always full breakdown)

Columns:

| Column | Description |
|---|---|
| `actor` | Pipeline trigger login (`Scheduled`, bots, humans, etc.) |
| `pipeline_count` | Distinct pipelines attributed to the actor |
| `job_rows` | Usage export job-level rows |
| `TOTAL_CREDITS` | Total credits |
| `COMPUTE_CREDITS` | Compute / executor usage |
| `USER_CREDITS` | User / seat fees |
| `STORAGE_CREDITS` | Storage |
| `NETWORK_CREDITS` | Network |
| `DLC_CREDITS` | Docker Layer Caching |
| `LEASE_CREDITS` | Lease |
| `LEASE_OVERAGE_CREDITS` | Lease overage |
| `IPRANGES_CREDITS` | IP ranges |

Only columns **present in the Usage export header** are aggregated. CircleCI's standard export includes all nine credit columns above.

### Stdout table (compact by default)

Default display columns: `TOTAL_CREDITS`, `COMPUTE_CREDITS`, `USER_CREDITS`.

```
actor                                     pipelines     jobs  TOTAL_CREDITS COMPUTE_CREDITS   USER_CREDITS
------------------------------------------------------------------------------------------------------------
octocat                                          32      199       38295.00        12000.00       26295.00
seat-only-user                                    0        0           0.00            0.00       25000.00
Scheduled                                       286      836     5899706.00       144730.00     2500000.00
```

### FinOps examples

| Pattern | Signal |
|---|---|
| Seat fee only | `USER_CREDITS` > 0 and `COMPUTE_CREDITS` ≈ 0 |
| Active CI user | `COMPUTE_CREDITS` > 0 |
| Scheduled batch cost | actor = `Scheduled`, often high `IPRANGES_CREDITS` or `COMPUTE_CREDITS` |
| Bot automation | `renovate[bot]`, `dependabot[bot]`, `mt-eng2-bot`, etc. |

No need to infer an "OTHER" bucket — use the Usage API breakdown columns directly.

## CLI reference

| Option | Default | Description |
|---|---|---|
| `--org-id` | `$CIRCLECI_ORG_ID` | Organization UUID |
| `--token` | `$CIRCLECI_TOKEN` / CLI config | Personal API token |
| `--base-url` | `https://circleci.com` | API base URL (for self-hosted) |
| `--start-date` | — | Export start (`YYYY-MM-DD`) |
| `--end-date` | — | Export end (`YYYY-MM-DD`) |
| `--usage-csv` | — | Skip export; read merged CSV |
| `--usage-output` | — | Write merged Usage CSV |
| `--summary-output` | `user_credits_summary.csv` | Write actor summary CSV |
| `--actor-cache` | `.cache/pipeline_actors.json` | Pipeline actor cache |
| `--sort-by` | `TOTAL_CREDITS` | Sort key for summary rows |
| `--display-column` | TOTAL, COMPUTE, USER | Stdout columns (repeatable) |
| `--workers` | `8` | Parallel Pipeline API workers |
| `--poll-interval` | `5` | Usage export poll interval (seconds) |
| `--timeout` | `3600` | Usage export timeout (seconds) |
| `--skip-pipeline-fetch` | off | Export Usage CSV only |

### Examples

```bash
# Sort by compute usage
uv run circleci-credit-by-user \
  --usage-csv usage_merged.csv \
  --sort-by COMPUTE_CREDITS

# Show IP ranges on stdout
uv run circleci-credit-by-user \
  --usage-csv usage_merged.csv \
  --display-column TOTAL_CREDITS \
  --display-column COMPUTE_CREDITS \
  --display-column USER_CREDITS \
  --display-column IPRANGES_CREDITS

# Export Usage data only (no Pipeline API calls)
uv run circleci-credit-by-user \
  --org-id "$CIRCLECI_ORG_ID" \
  --start-date 2026-06-01 \
  --end-date 2026-06-07 \
  --usage-output usage_merged.csv \
  --skip-pipeline-fetch
```

## Environment variables

| Variable | Purpose |
|---|---|
| `CIRCLECI_TOKEN` | Personal API token (preferred) |
| `CIRCLECI_API_TOKEN` | Alias for token |
| `CIRCLECI_ORG_ID` | Default organization UUID |
| `CIRCLECI_BASE_URL` | API base URL |

Token resolution order: `--token` → env vars → `~/.circleci/cli.yml`.

## Limitations

1. **`Scheduled` is not a person** — scheduled pipelines use actor `Scheduled`.
2. **Trigger actor ≠ commit author** — attribution is who triggered the pipeline.
3. **Usage lag** — data through the previous UTC day (typically refreshed 08:00–10:00 UTC).
4. **32-day export window** — longer ranges are split automatically.
5. **Rate limits** — Usage export POST: 10/hour/org; Pipeline GET: 1000/min/token.
6. **Large orgs** — first run may require thousands of Pipeline lookups (cache helps later).
7. **Not billing** — operational FinOps only, not a substitute for invoices.
8. **Missing pipelines** — deleted pipelines may return 404 and map to `(unknown)`.

## Development

```bash
uv sync --dev
uv run pytest
uv run circleci-credit-by-user --help
```

## Related projects

- [CircleCI-Labs/circleci-usage-reporter](https://github.com/CircleCI-Labs/circleci-usage-reporter) — Usage API wrapper (project / job / resource class; no per-user breakdown)

## License

MIT — see [LICENSE](LICENSE).
