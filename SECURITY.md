# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## Reporting a vulnerability

Please open a private security advisory on GitHub or contact the repository maintainers directly. Do not file public issues for credential leaks or token exposure.

## Token handling

This tool reads a CircleCI Personal API Token from:

- `CIRCLECI_TOKEN` or `CIRCLECI_API_TOKEN` environment variables
- `~/.circleci/cli.yml` (CircleCI CLI config)

Guidelines:

- Never commit tokens, usage CSV exports, or actor cache files containing production data
- Use CI secrets for scheduled runs
- Rotate tokens if they appear in logs or shared artifacts
- Tokens inherit your CircleCI permissions; use a dedicated service account where possible

## Data sensitivity

Usage exports and actor summaries can reveal project names, job names, and VCS usernames. Treat output files as internal operational data.
