# circleci-credit-by-user

Community tool to aggregate **CircleCI credits by trigger actor** (GitHub/Bitbucket login).

CircleCI's [Usage API](https://circleci.com/docs/api/v2/index.html#tag/Usage) exposes credit consumption but intentionally omits user identifiers (PII). This CLI joins Usage export CSVs with the [Pipeline API](https://circleci.com/docs/api/v2/index.html#tag/Pipeline) to attribute credits to `trigger.actor.login`.

> **Disclaimer:** This is an unofficial community tool. It is not supported by CircleCI support. Results are based on Usage API data and trigger actors, not official billing invoices.

## Why this exists

| Source | Credits | User login |
|---|---|---|
| Usage API CSV | yes | no (by design) |
| Pipeline API | no | yes (`trigger.actor.login`) |
| Webhooks | no | partial |
| Insights API | approximate | no |

The supported approach is: **Usage CSV + Pipeline API JOIN**.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended)
- CircleCI Personal API Token ([create one](https://app.circleci.com/settings/user/tokens))
- Organization ID (Organization Settings in the CircleCI app)

## Install

```bash
git clone https://github.com/hidetaka-cci/circleci-credit-by-user.git
cd circleci-credit-by-user
uv sync
```

Run via uv:

```bash
uv run circleci-credit-by-user --help
```

Or install the CLI globally:

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

### Aggregate from an existing Usage CSV

```bash
uv run circleci-credit-by-user \
  --usage-csv usage_merged.csv \
  --summary-output user_credits_summary.csv
```

Pipeline actor lookups are cached at `.cache/pipeline_actors.json` by default.

## Output

Stdout table (default display: total, compute, and user/seat credits):

```
actor                                     pipelines     jobs  TOTAL_CREDITS COMPUTE_CREDITS   USER_CREDITS
------------------------------------------------------------------------------------------------------------
octocat                                          32      199       38295.00        12000.00       26295.00
seat-only-user                                    0        0           0.00            0.00       25000.00
```

Summary CSV columns: `actor`, `pipeline_count`, `job_rows`, plus **every credit column present in the Usage export**:

`TOTAL_CREDITS`, `COMPUTE_CREDITS`, `STORAGE_CREDITS`, `NETWORK_CREDITS`, `USER_CREDITS`, `DLC_CREDITS`, `LEASE_CREDITS`, `LEASE_OVERAGE_CREDITS`, `IPRANGES_CREDITS`

This lets you explain:

- **seat fee only** users (`USER_CREDITS` > 0, `COMPUTE_CREDITS` ≈ 0)
- users who **ran CI** (`COMPUTE_CREDITS` > 0)
- **IP Ranges / storage / network** spend without guessing an "OTHER" bucket

Sort and display options:

```bash
# Sort by compute instead of total
uv run circleci-credit-by-user --usage-csv usage.csv --sort-by COMPUTE_CREDITS

# Show all credit columns on stdout
uv run circleci-credit-by-user --usage-csv usage.csv \
  --display-column TOTAL_CREDITS \
  --display-column COMPUTE_CREDITS \
  --display-column USER_CREDITS \
  --display-column IPRANGES_CREDITS \
  --display-column STORAGE_CREDITS
```

## Limitations (read before production use)

1. **`Scheduled` is not a person** — scheduled pipelines attribute credits to actor `Scheduled`.
2. **Trigger actor ≠ commit author** — attribution uses who triggered the pipeline, not necessarily who wrote the code.
3. **Usage data lag** — refreshed daily (previous UTC day, typically 08:00–10:00 UTC).
4. **Date window** — max 32 days per Usage export request (longer ranges are split automatically).
5. **Rate limits** — Usage export POST: 10/hour/org; Pipeline API: 1000 req/min/token.
6. **Large orgs** — first run may require thousands of Pipeline API calls (cache helps on reruns).
7. **Not financial reporting** — use Usage API for operational FinOps, not as a legal invoice substitute.

## Development

```bash
uv sync --dev
uv run pytest
uv run circleci-credit-by-user --help
```

## Related projects

- [CircleCI-Labs/circleci-usage-reporter](https://github.com/CircleCI-Labs/circleci-usage-reporter) — Usage API wrapper (project/job/resource class; no per-user breakdown)

## License

MIT — see [LICENSE](LICENSE).
