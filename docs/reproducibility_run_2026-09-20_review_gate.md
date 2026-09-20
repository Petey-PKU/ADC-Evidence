# 2026-09-20 来源复核门禁复现记录

本记录补充来源复核门禁提交后的当前状态，不改写同日早先的来源和日期审计历史。

## 固定版本与测试

| 项目 | 值 |
| --- | --- |
| 公共分支 | `research/v0.6-freeze` |
| 代码提交 | `365e5f724a785150e9218bd816d6847cd2f5c8a6` |
| 门禁代码提交 | `d3a122f3702f24851ab461997478ca88204fc550` |
| 本地测试 | 232 项发现，232 项通过，0 项跳过，0 项失败 |
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

本轮也复跑了公开数据库来源覆盖审计：23 个 ADC、3,503 条试验、1,410 篇文献和 6,754 条
实体关联；ClinicalTrials.gov 为 `partial`（2,000/13,978，比例 `0.143082`），PubMed 为
`partial`（1,015/165,105，比例 `0.006148`），ADCDB 为 `unknown`（`skipped` 且没有分母）。
审计 JSON 的 SHA-256 为
`e18f3c92a2efdd50daa12b8454bb43ab7831a070ebc566340ff16a862333ee99`；这些比例描述本次
抓取窗口，不代表来源全集覆盖率。

本轮还收紧了 benchmark/holdout 元数据门禁：公开 benchmark manifest 必须保持
`evaluation_use.status=development_exposed` 且 `eligible_for_unseen_test_claim=false`；独立
holdout manifest 除 `access_controlled=true` 外必须记录非空的控制方式和 attestation。缺少这些
字段时，校验会失败或投稿审计保持阻塞。

本轮又把同语料离线比较的条件写入两组报告并设为 fail-closed：网络关闭、sparse 检索、
最终 top-k=5、候选上限 60 和 `ExtractiveGenerator`。系统报告或基线报告缺少或改变任一
条件时，比较器不会生成对照结论；新增预算不一致回归测试已覆盖该门禁。

公开 benchmark 的命令行比较器也已加入同样的报告级门禁。在公开快照上运行 98 题 system
与 baseline 后，题集、数据库版本、提示版本和检索条件均匹配，比较结果生成成功；两份
报告和比较结果的 SHA-256 分别为：

- system：`6cb8d12aaaf273f1c823e2366145e1057625d4824262cdd592f9e6aa1ccacfce`
- baseline：`fd779b0104853d0677d0ad5f63691fc70d09972b309b9e82e4c08b806e1a1cf1`
- comparison：`30721b3885b85966bca00781604009f4e9d4e45fc52c31ed991244f1d6d7d0a8`

该结果只是公开开发题集的自动诊断，比较输出仍保留 `human_review_required=true`，不构成
独立测试集、人工金标准或论文主结果。

## 研究包

研究包由代码提交 `365e5f724a785150e9218bd816d6847cd2f5c8a6` 构建并通过
`scripts/verify_public_release.py` 验证：检查 79 个文件，数据库绝对路径计数为 0，
benchmark 和候选来源文件均存在，manifest 为 `research_only` 且
`redistribution_allowed=false`。包大小为 42,148,189 字节，SHA-256 为
`75a4636a4f7018f1c9341a5124057eda2c4b8fca888971a1042b7ab218059936`。

该包仍只用于本地研究复现；公开 GitHub Release 仍需逐项许可核查和正式 attestation。

## 投稿门禁复跑

在提交 `8c6f6df0479f477eb7626ccdfc38222598b9358a` 的工作树上运行：

```powershell
$env:PYTHONPATH="src"
python scripts/audit_paper_readiness.py --output .test_tmp/paper_readiness-current.json
```

结果为 `not_ready_for_submission`：公开题集不相交、公开 smoke 边界、配对统计工具、
复核来源门禁和公共卫生扫描通过；数据库质量为 warning（demo 数据库没有文献或试验记录）；
真实 `human_independent`/`human_adjudicated` 标签和独立访问受控 holdout 仍为两个 blocker。
审计 JSON 的 SHA-256 为
`8c49c1a0b85cd2dfee71defdcd951b82f148ec224d72ff18ce551ecaab02d17d`。
