# circleci-credit-by-user

[English](README.md) | **日本語**

CircleCI の **クレジット利用量をトリガー actor（GitHub/Bitbucket ログイン）別に集計**するコミュニティ CLI です。

[Usage API](https://circleci.com/docs/api/v2/index.html#tag/Usage) にはクレジット量は含まれますが、ユーザー識別子は意図的に除外されています（PII 非掲載）。本ツールは Usage export CSV と [Pipeline API](https://circleci.com/docs/api/v2/index.html#tag/Pipeline) を JOIN し、`trigger.actor.login` ごとに **Usage API の全クレジット内訳列** を集計します。

> **免責:** 非公式コミュニティツールです。CircleCI サポート対象外です。結果は Usage API と pipeline trigger actor に基づく FinOps 向け集計であり、請求書の代替ではありません。

## 背景

| 手段 | クレジット | ユーザー情報 |
|---|---|---|
| Usage API CSV | ✅ | ❌（設計仕様） |
| Pipeline API | ❌ | ✅（`trigger.actor.login`） |
| Webhook | ❌ | △ |
| Insights API | △（請求とズレる） | ❌ |

現実解は **Usage CSV + Pipeline API JOIN** です。

## 機能

- 指定期間の Usage Export 取得（32 日超は自動分割）
- 複数 `.csv.gz` のマージ
- `pipeline_id` → actor を Pipeline API で解決（JSON キャッシュ付き）
- Usage export に含まれる **全クレジット列** を actor 別に合計
- ターミナルにサマリー表示、BI / FinOps 用に CSV 出力

## 必要条件

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)（推奨）
- CircleCI Personal API Token — [作成](https://app.circleci.com/settings/user/tokens)
- Organization ID — CircleCI アプリの **Organization Settings** に表示

## インストール

```bash
git clone https://github.com/hidetaka-cci/circleci-credit-by-user.git
cd circleci-credit-by-user
uv sync
```

そのまま実行:

```bash
uv run circleci-credit-by-user --help
```

グローバルインストール:

```bash
uv tool install .
circleci-credit-by-user --help
```

## クイックスタート

```bash
export CIRCLECI_TOKEN="your-personal-api-token"
export CIRCLECI_ORG_ID="your-org-uuid"

uv run circleci-credit-by-user \
  --start-date 2026-05-01 \
  --end-date 2026-05-31 \
  --usage-output usage_merged.csv \
  --summary-output user_credits_summary.csv
```

### 既存 Usage CSV から集計

```bash
uv run circleci-credit-by-user \
  --usage-csv usage_merged.csv \
  --summary-output user_credits_summary.csv
```

Pipeline actor のルックアップは `.cache/pipeline_actors.json` にキャッシュされます（デフォルト）。

## 処理フロー

```
Usage Export API
  POST /organizations/{org_id}/usage_export_job
  GET  /organizations/{org_id}/usage_export_job/{job_id}   (ポーリング)
  download_urls[] (.csv.gz) → マージ
        ↓ PIPELINE_ID
Pipeline API
  GET /pipeline/{pipeline_id}   (並列 + キャッシュ)
        ↓ trigger.actor.login
GROUP BY actor → 全クレジット列を合計
```

## 出力

### サマリー CSV（常に全内訳）

| 列 | 説明 |
|---|---|
| `actor` | トリガー login（`Scheduled`、bot、人間など） |
| `pipeline_count` | その actor に帰属した pipeline 数 |
| `job_rows` | Usage export の job 行数 |
| `TOTAL_CREDITS` | 合計 |
| `COMPUTE_CREDITS` | compute / executor |
| `USER_CREDITS` | ユーザー / seat 課金 |
| `STORAGE_CREDITS` | ストレージ |
| `NETWORK_CREDITS` | ネットワーク |
| `DLC_CREDITS` | Docker Layer Caching |
| `LEASE_CREDITS` | リース |
| `LEASE_OVERAGE_CREDITS` | リース超過 |
| `IPRANGES_CREDITS` | IP Ranges |

Usage export のヘッダーに存在する列のみ集計します。標準 export には上記 9 列すべてが含まれます。

### 標準出力（デフォルトは主要 3 列のみ）

デフォルト表示: `TOTAL_CREDITS`, `COMPUTE_CREDITS`, `USER_CREDITS`

```
actor                                     pipelines     jobs  TOTAL_CREDITS COMPUTE_CREDITS   USER_CREDITS
------------------------------------------------------------------------------------------------------------
octocat                                          32      199       38295.00        12000.00       26295.00
seat-only-user                                    0        0           0.00            0.00       25000.00
Scheduled                                       286      836     5899706.00       144730.00     2500000.00
```

**CSV には常に全クレジット列が出力されます。** stdout は `--display-column` で絞れます。

### FinOps での読み方

| パターン | 見方 |
|---|---|
| seat fee のみ | `USER_CREDITS` > 0 かつ `COMPUTE_CREDITS` ≈ 0 |
| CI を実行しているユーザー | `COMPUTE_CREDITS` > 0 |
| 定例バッチ | actor = `Scheduled`（`IPRANGES_CREDITS` や `COMPUTE_CREDITS` が大きいことも） |
| bot | `renovate[bot]`, `dependabot[bot]`, `mt-eng2-bot` など |

「OTHER」を推測する必要はありません。Usage API の内訳列をそのまま使えます。

## CLI リファレンス

| オプション | デフォルト | 説明 |
|---|---|---|
| `--org-id` | `$CIRCLECI_ORG_ID` | Organization UUID |
| `--token` | 環境変数 / CLI 設定 | Personal API Token |
| `--base-url` | `https://circleci.com` | API ベース URL |
| `--start-date` | — | 取得開始日 (`YYYY-MM-DD`) |
| `--end-date` | — | 取得終了日 |
| `--usage-csv` | — | Export をスキップし CSV を読む |
| `--usage-output` | — | マージ済み Usage CSV の出力先 |
| `--summary-output` | `user_credits_summary.csv` | サマリー CSV の出力先 |
| `--actor-cache` | `.cache/pipeline_actors.json` | actor キャッシュ |
| `--sort-by` | `TOTAL_CREDITS` | ソート列 |
| `--display-column` | TOTAL, COMPUTE, USER | stdout 表示列（繰り返し指定可） |
| `--workers` | `8` | Pipeline API 並列数 |
| `--poll-interval` | `5` | Export ポーリング間隔（秒） |
| `--timeout` | `3600` | Export タイムアウト（秒） |
| `--skip-pipeline-fetch` | off | Usage CSV 取得のみ |

### 使用例

```bash
# compute 使用量でソート
uv run circleci-credit-by-user \
  --usage-csv usage_merged.csv \
  --sort-by COMPUTE_CREDITS

# stdout に IP Ranges も表示
uv run circleci-credit-by-user \
  --usage-csv usage_merged.csv \
  --display-column TOTAL_CREDITS \
  --display-column COMPUTE_CREDITS \
  --display-column USER_CREDITS \
  --display-column IPRANGES_CREDITS

# Usage 取得のみ（Pipeline API は呼ばない）
uv run circleci-credit-by-user \
  --org-id "$CIRCLECI_ORG_ID" \
  --start-date 2026-06-01 \
  --end-date 2026-06-07 \
  --usage-output usage_merged.csv \
  --skip-pipeline-fetch
```

## 環境変数

| 変数 | 用途 |
|---|---|
| `CIRCLECI_TOKEN` | Personal API Token（推奨） |
| `CIRCLECI_API_TOKEN` | Token の別名 |
| `CIRCLECI_ORG_ID` | デフォルト org UUID |
| `CIRCLECI_BASE_URL` | API ベース URL |

Token 解決順: `--token` → 環境変数 → `~/.circleci/cli.yml`

## 制約・注意点

1. **`Scheduled` は個人ではない** — スケジュール trigger は actor = `Scheduled`
2. **trigger actor ≠ commit author** — パイプラインを起動した主体で帰属
3. **データ鮮度** — 前日 UTC 分まで（通常 08:00–10:00 UTC に更新）
4. **Export 期間** — 1 リクエスト最大 32 日（超える場合は自動分割）
5. **レート制限** — Usage export POST: 10 回/時/org、Pipeline GET: 1000 回/分/token
6. **大規模 org** — 初回は Pipeline 取得が数千〜万回（キャッシュで短縮）
7. **請求書ではない** — FinOps 用途のみ
8. **404 pipeline** — 削除済み pipeline は `(unknown)` に帰属

## 開発

```bash
uv sync --dev
uv run pytest
uv run circleci-credit-by-user --help
```

## 関連プロジェクト

- [CircleCI-Labs/circleci-usage-reporter](https://github.com/CircleCI-Labs/circleci-usage-reporter) — Usage API ラッパー（project / job / resource class 別。ユーザー別は未対応）

## ライセンス

MIT — [LICENSE](LICENSE) を参照
