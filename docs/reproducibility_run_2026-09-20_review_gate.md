# 2026-09-20 来源复核门禁复现记录

本记录补充来源复核门禁提交后的当前状态，不改写同日早先的来源和日期审计历史。

## 固定版本与测试

| 项目 | 值 |
| --- | --- |
| 公共分支 | `research/v0.6-freeze` |
| 代码提交 | `3cb75bea3ffb30480bb3ee332afc424786207076` |
| 门禁代码提交 | `d3a122f3702f24851ab461997478ca88204fc550` |
| 本地测试 | 234 项发现，234 项通过，0 项跳过，0 项失败 |
| GitHub CI | Python 3.11/3.12 的 base 与 generation 四个 job 均成功 |
| 公共卫生扫描 | 216 个受跟踪文件，`status=clean`，无发现 |

复现命令：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -q
python scripts/audit_public_hygiene.py --output .test_tmp/hygiene-review-gate.json
git diff --check
```

## 复核器门禁

`scripts/validate_catalog_field_review.py` 现在对 completed 字段项采取 fail-closed 规则：

- `reviewed_primary_source`、`rejected` 和 `unclear` 必须带 `primary` 或 `secondary` 槽位，且 `review_origin=human_independent`；
- `adjudicated` 必须带 `adjudicator` 槽位，且 `review_origin=human_adjudicated`；
- pending 项不得携带 verdict、来源定位或复核元数据；
- `ai_assisted_primary` 不能通过字段复核验证。

这项改动只限制错误标注，不产生人工结论。当前公共目录的 299 个字段项仍为
`pending_primary_check`，因此不能声称已经完成独立人工来源复核。

本轮新增 `scripts/merge_catalog_field_reviews.py`：它分别验证 primary、secondary 和可选
adjudicator 文件，输出逐字段一致性、分歧数和裁决状态；没有裁决时报告保持
`needs_adjudication`，不会自动选择竞争值。

本轮还把目录来源内容审计的候选定位覆盖与人工核验分开记录：候选文件为 161 条记录、158 个唯一 ADC-字段组合，覆盖 23 个 ADC；按 23×7 个结构字段计算，候选定位覆盖 158/161，仍有 3 个结构组合缺候选 URL。将论文要求的 `indication` 纳入核心事实后，覆盖为 158/184，仍有 26 个核心事实组合缺候选定位，其中 23 个为适应证字段。所有候选仍为 `candidate_locator_pending_human_review`，不构成字段事实或金标准。

在同一代码版本上重新运行候选 URL 内容审计（生成时间 `2026-09-20T15:27:39+00:00`）：23/23 个来源返回 HTTP 响应，其中 21 个为 reachable、2 个为 HTTP error；17 个文本页面完成扫描、4 个 PDF 仅记录可访问性、2 个保持 pending；16 个响应出现 ADC 名称或别名。审计 JSON 的 SHA-256 为 `3f7ae4f1a0f85a731addd38ffaa30e4ccd908b8bf414d4a4cb483fa360b5b484`。这只证明内容可访问或出现名称线索，核心事实候选覆盖仍为 158/184，不能替代人工字段核验。新增的候选值文本预筛在 120 个可扫描候选值中命中 16 个（命中率 0.1333）；其余候选值可能位于未提取的 PDF、页面结构或不同术语中，命中率不作正确性指标。该审计 JSON 的 SHA-256 为 `5083de3508e2a249cf1ebe6445000b0f3b2a892c37c290b050d827831b26dd00`。

本轮也复跑了公开数据库来源覆盖审计：23 个 ADC、3,503 条试验、1,410 篇文献和 6,754 条
实体关联；ClinicalTrials.gov 为 `partial`（2,000/13,978，比例 `0.143082`），PubMed 为
`partial`（1,015/165,105，比例 `0.006148`），ADCDB 为 `unknown`（`skipped` 且没有分母）。
审计 JSON 的 SHA-256 为
`e18f3c92a2efdd50daa12b8454bb43ab7831a070ebc566340ff16a862333ee99`；这些比例描述本次
抓取窗口，不代表来源全集覆盖率。

最新公共数据库审计（数据库哈希绑定当前 `adc_public_2026-09-30.db`）仍为 `partial`：23 个 ADC、3,503 条试验、1,410 篇文献和 6,754 条实体关联；ClinicalTrials.gov 与 PubMed 为 `partial`，ADCDB 为 `unknown`。字段来源质量状态现在明确为 `needs_review`，原因是 10 类 ADC 事实的来源类型仍为 `curated_seed_not_independently_reviewed`，即使 URL 有效也不能视为人工来源核验。审计 JSON 的 SHA-256 为 `b6263077c5e59039a1bc9fe7058b2cf32db1dc2cf65bd3841de14168080a06cd`。

本轮还收紧了 benchmark/holdout 元数据门禁：公开 benchmark manifest 必须保持
`evaluation_use.status=development_exposed` 且 `eligible_for_unseen_test_claim=false`；独立
holdout manifest 除 `access_controlled=true` 外必须记录非空的控制方式和 attestation。缺少这些
字段时，校验会失败或投稿审计保持阻塞。

本轮又把同语料离线比较的条件写入两组报告并设为 fail-closed：网络关闭、sparse 检索、
最终 top-k=5、候选上限 60 和 `ExtractiveGenerator`。系统报告或基线报告缺少或改变任一
条件时，比较器不会生成对照结论；新增预算不一致回归测试已覆盖该门禁。

本轮还收紧了独立 holdout 的题目 schema。正式 unseen holdout 的每题必须有
`standard_answer`、`evidence_sources`、`allow_partial`、`should_refuse` 和 `scoring`，并
包含类别、路由和预期状态；只有题目文本与 ID 的文件现在会在 manifest 生成和文件绑定时
被拒绝。公开 smoke holdout 仍保持单独的开发用途边界。

公开 benchmark 的命令行比较器也已加入同样的报告级门禁。在公开快照上运行 98 题 system
与 baseline 后，题集、数据库版本、提示版本和检索条件均匹配，比较结果生成成功；两份
报告和比较结果的 SHA-256 分别为：

- system：`3b2374296e442ac65a358c7e45218aa19c238ca9339526a222867a09570a3b44`
- baseline：`a2c4f39c81df2699e6c0bcb453b13297b98141534141f2e5c809d25c97a57079`
- comparison：`30721b3885b85966bca00781604009f4e9d4e45fc52c31ed991244f1d6d7d0a8`

该结果只是公开开发题集的自动诊断，比较输出仍保留 `human_review_required=true`，不构成
独立测试集、人工金标准或论文主结果。

随后又把这些 provenance 字段复制到 comparison JSON 本身，最新 comparison 的 SHA-256 为
`f5311d129374c32c6b3b676b54f01bb903df300e8a019e228012634af8a791b6`；其中记录题集哈希
`sha256:b22f528867cf6197df1b48f2e328e812abcc16e8f03f480e13fb04cb357aeec0`、数据库版本
`data_465aab2dc23d8b11c769c7a8b61c6f3144f496ca02355e0318321f2b6ebc93d4` 和
`prompt_version=public-benchmark-v1`。

## 研究包

研究包由代码提交 `3cb75bea3ffb30480bb3ee332afc424786207076` 构建并通过
`scripts/verify_public_release.py` 验证：检查 79 个文件，数据库绝对路径计数为 0，
benchmark 和候选来源文件均存在，manifest 为 `research_only` 且
`redistribution_allowed=false`。包大小为 42,149,006 字节，SHA-256 为
`da97e3fd77c9fe20e626fba49c27803119412b843c190773696d7cefebc2bd50`。

本轮投稿门禁复跑的审计 JSON 哈希仍为
`8c49c1a0b85cd2dfee71defdcd951b82f148ec224d72ff18ce551ecaab02d17d`：真实人工证据和独立
holdout blocker 仍未提供。

该包仍只用于本地研究复现；公开 GitHub Release 仍需逐项许可核查和正式 attestation。

当前公共 artifact manifest 绑定提交 `8fc2a8fe9487e52b810af31d0de996beb122649c`，包含 216 个受跟踪文件，卫生状态为 `clean`；manifest SHA-256 为 `b61d93facf0603d3c999365b920df610671a09840aec8b72452095ef0e27aeb2`。

## 投稿门禁复跑

在提交 `3cb75bea3ffb30480bb3ee332afc424786207076` 的工作树上运行：

```powershell
$env:PYTHONPATH="src"
python scripts/audit_paper_readiness.py --output .test_tmp/paper_readiness-current.json
```

结果为 `not_ready_for_submission`：公开题集不相交、公开 smoke 边界、配对统计工具、
复核来源门禁和公共卫生扫描通过；数据库质量为 warning（demo 数据库没有文献或试验记录）；
真实 `human_independent`/`human_adjudicated` 标签和独立访问受控 holdout 仍为两个 blocker。
审计 JSON 的 SHA-256 为
`8c49c1a0b85cd2dfee71defdcd951b82f148ec224d72ff18ce551ecaab02d17d`。
