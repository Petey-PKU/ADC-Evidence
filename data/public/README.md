# Public ADC dataset

This directory contains a reproducible, redistributable catalog seed for the
public ADC-Evidence application. It is deliberately separate from the private
SQLite database and private expert-review exports.

The public dataset builder also creates a `literature_topics` table. Its
`literature-topic-rule-v1` lexical labels (`mechanism`, `efficacy`, `safety`)
are triage metadata only and remain marked `needs_review` until a human checks
the source and relevance.

## Scope

`marketed_adc_catalog.csv` is a **candidate global regulatory catalog**. The
current snapshot window is `2026-06-30`, the latest complete public inventory
used while this release is being prepared. The requested target window is
`2026-09-30`; records that changed after the current window must be added only
after a source check. The catalog contains products that had received approval
by the snapshot date, including historically approved products that were later
withdrawn. Use `catalog_status` to distinguish `marketed`, `withdrawn`, and
`approved_not_marketed` records.

The catalog is a public starting point, not a claim that every field has been
independently verified. `verification_status=primary_check_pending` means a
primary regulator label or registry record still needs to be checked before a
paper uses the field as a gold-standard fact.
`marketed_adc_catalog.audit.json` is a deterministic review queue for these
checks; it reports generic regulator landing pages and missing required fields
without containing private notes.

目录范围由 `catalog_scope_policy.json` 单独声明并机器校验。当前 23 条记录中，21 条属于
核心 `antibody_drug_conjugate`，`adc_021` 是光免疫偶联物，`adc_023` 是重组免疫毒素，
两者保留在扩展集合中但不计入核心 ADC 数量。该分类是待一手来源复核的范围元数据，不是
结构字段的金标准：

```powershell
$env:PYTHONPATH="src"
python scripts/validate_public_catalog_scope.py
```

`catalog_source_locator_candidates.jsonl` 记录了首批 FDA 标签的字段级候选定位。它只表示
`candidate_direct` 或 `partial` 线索，所有行仍为 `pending_independent_primary_source_review`；
不得直接用于论文金标准统计。

要逐字段开展一级来源复核，可生成空白审核包（不会自动写入任何人工结论）：

```powershell
$env:PYTHONPATH="src"
python scripts/build_catalog_field_review_packet.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --output artifacts/evaluation/catalog_field_review.jsonl `
  --manifest artifacts/evaluation/catalog_field_review.manifest.json
```

审核包中的 `candidate_source.source_url` 是候选来源链接，`verification.status` 初始为
`pending_primary_check`；只有人工逐项检查后才可填写 verdict 和 confirmed value。

可在提交审核结果前运行严格的结构校验。默认模式允许待审核项存在，但会报告其数量；
`--require-complete` 用作发布门禁，要求每个字段都有受控 verdict 和具体来源定位，
不会把 URL 可访问性或自动文本匹配转换为审核结论：

```powershell
$env:PYTHONPATH="src"
python scripts/validate_catalog_field_review.py `
  --packet artifacts/evaluation/catalog_field_review.jsonl `
  --manifest artifacts/evaluation/catalog_field_review.manifest.json `
  --catalog data/public/marketed_adc_catalog.csv
```

## Data policy

- The CSV contains structured facts and source links only; it contains no
  reviewer identities, private notes, API keys, raw API responses, or model
  outputs.
- Publication status is jurisdiction-specific. A product marked `marketed`
  means marketed in at least one listed jurisdiction at the snapshot window;
  it does not imply approval in every country.
- The catalog source is a secondary inventory used to make the initial scope
  reproducible. FDA, EMA, PMDA, NMPA, or other regulator sources must be bound
  to each record before a release is treated as a regulatory gold set.
- Literature abstracts and trial records are collected separately by the
  public builder. Abstract redistribution and any full text require a source
  license check; the builder records URLs, retrieval time, and hashes.

## Build a local database

From the repository root:

```powershell
$env:PYTHONPATH="src"
python scripts/build_public_dataset.py --catalog data/public/marketed_adc_catalog.csv
```

The generated SQLite database, raw responses, and retrieval index stay in local
ignored paths. The command accepts `--as-of YYYY-MM-DD` and records the actual
source windows in its manifest. It does not call a generative model.

To run the Streamlit app against a generated snapshot without replacing the
demo database, set these variables before starting Streamlit:

```powershell
$env:ADC_DATABASE_PATH="data/processed/adc_public_2026-09-30.db"
$env:ADC_SEED_PATH="data/public/marketed_adc_catalog.csv"
$env:ADC_VECTOR_INDEX_PATH="artifacts/vector_index/public_2026-09-30"
streamlit run src/adc_evidence/app.py
```

## Use a downloaded release

Download the ZIP artifact from the manual `Build public dataset release`
workflow. Verify it before extraction, then expand it at the repository root:

```powershell
python scripts/verify_public_release.py .\adc-public-2026-09-30.zip
Expand-Archive .\adc-public-2026-09-30.zip -DestinationPath . -Force
$env:ADC_OFFLINE_ONLY="true"
$env:ADC_DATABASE_PATH="data/processed/adc_public_2026-09-30.db"
$env:ADC_SEED_PATH="data/public/marketed_adc_catalog.csv"
$env:ADC_VECTOR_INDEX_PATH="artifacts/vector_index/public_2026-09-30"
streamlit run src/adc_evidence/app.py
```

The release uses the offline extractive path and does not require a model API
key. `RELEASE_MANIFEST.json` records the database, index, catalog, benchmark,
and source-window hashes; retain it with the extracted files when reporting a
reproduction.

## Refresh entity links after alias edits

The collectors search canonical ADC names and catalog aliases directly. After
editing aliases, existing local snapshots can be relinked without downloading
new records:

```powershell
$env:PYTHONPATH="src"
python scripts/relink_public_snapshot.py `
  --database data/processed/adc_public_2026-09-30.db `
  --seed data/public/marketed_adc_catalog.csv
```

This command only rebuilds trial/document links and evidence from records
already in SQLite; it does not call a model API or any network source.
