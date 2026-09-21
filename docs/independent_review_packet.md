# 独立盲评执行包

这份说明用于生成和复核正式投稿所需的人工证据。它不能把 AI 输出或同一人的
两次评分伪装成独立复核。

## 评审前

1. 在开发完成后，单独冻结题集、数据库/语料版本、代码提交和评测窗口。
2. 将正式题集保存在公共仓库之外的访问受控路径，并生成不含题目内容的 manifest：

```powershell
python scripts/build_independent_holdout_manifest.py `
  --questions D:\private-review\holdout_questions.jsonl `
  --question-set-version holdout-v1 `
  --evaluation-window-id window-1 `
  --access-control-method "owner-controlled private ACL" `
  --database-data-version <data-version> `
  --code-commit <commit> `
  --output D:\private-review\holdout_manifest.json
```

`access_control_method` 是操作者的声明，脚本不会伪造或自动证明文件系统权限；
评测前必须由项目负责人独立确认权限和题集未泄露。按比较臂选择 `benchmark assemble`
或下文的双臂构建器生成盲评包和身份映射。盲评包交给评审者；身份映射
   只由项目负责人保存，评审完成和分歧裁决前不得打开。
3. 两名评审者分别使用 `primary` 和 `secondary` 槽位，各自完成预先指定的全部高风险题
   和普通题抽样。评审者应先看问题、答案、引用和原始证据，再填写判断。

对于只比较 ADC-Evidence 与离线 RAG 的运行报告，可使用公共仓库中的双臂构建器。
它接受 `run_public_holdout.py` 的报告格式，并校验题集内容哈希、题号哈希和每臂唯一题号。
生成盲包不改变运行报告的用途：公开 smoke 或草稿运行不能因此升级成正式独立测试。
输出必须位于公共仓库之外，使用全新目录，脚本拒绝覆盖已有文件：

```powershell
python scripts/build_blinded_holdout_review.py `
  --questions D:\private-review\holdout_questions.jsonl `
  --run D:\private-review\holdout_run.json `
  --packet D:\private-review\blinded_review_packet.json `
  --identity-map D:\private-review\blinded_identity_map.json `
  --reviews D:\private-review\review_template.jsonl `
  --manifest D:\private-review\review_manifest.json
```

构建器将题面、候选回答、主张文本和可核查引用放入盲包；标准答案、方法身份、路由、
自动验证结果、内部来源记录 ID 和原始输出哈希不交给评审者。A/B 排序使用私有随机密钥，
密钥只保存在身份映射中；同一次评审必须保留并使用首次生成的包，不能中途重新分配。
回答风格和来源内容仍可能暗示方法身份，因此这属于方法标签隐藏，不能保证完全盲化。
每个候选均生成 primary、secondary 两个空白槽位，身份映射在评审和裁决完成前保持隔离。
协调者还需另行确认代码、数据库、索引和检索预算一致；本构建器不替代运行条件审计。

此双臂模板以 `candidate_id` 区分同一题的两个候选。不要把含两个候选的原始模板直接送入
只接受每题两个评分的 `summarize_inter_rater_agreement.py`，也不要直接当作每题一行的
`paired_labels.jsonl`。必须按候选完成独立评分及裁决，再按身份映射转换成配对标签。
来源无法获取或问题本身无效时记录 `unassessable` 和原因，等待裁决；不能仅因无法判断
就给 `partial`（部分正确）。

独立 holdout 的每条题目在冻结前必须包含可核查的 gold schema：`category`、
`expected_route`、`expected_status`、`standard_answer`、`evidence_sources`、
`allow_partial`、`should_refuse` 和 `scoring`。其中 `evidence_sources` 的每项必须
绑定来源类型、来源 ID、URL 和字段；`scoring` 必须同时列出自动字段、人工字段和主指标。
`build_independent_holdout_manifest.py` 会在生成 manifest 前拒绝缺少这些字段的题集，
因此只有题目文本和 ID 的文件不能被标记为正式 unseen holdout。

## 每条答案的最低记录

JSONL 每行至少包含：

```json
{"question_id":"q001","reviewer_slot":"primary","review_origin":"human_independent","answer_verdict":"correct","evidence_verdict":"supported","citation_verdict":"corresponding","completeness_verdict":"complete","refusal_verdict":"not_applicable","severity":"none","error_categories":[]}
```

`review_origin` 只有真实人员独立评分时填写 `human_independent`。裁决后的最终标签才填写
`human_adjudicated`；`ai_assisted_primary`、`automatic` 或空值不能进入论文主结果。
评审身份、自由文本备注和联系方式留在私有环境，不进入公开 JSONL。

## 评审顺序

- 先判断问题和 gold 是否有效；无效题应记录原因，不把它算作系统答对。
- 再判断答案是否回答了所有必需信息、是否有误导性附加结论。
- 逐条检查证据是否真的支持结论，引用是否对应来源，拒答是否合理。
- 两人提交后才查看身份映射；分歧由预先指定的 adjudicator 裁决，并保留原始两份评分。

## 统计与导出

先计算双评一致性：

```powershell
$env:PYTHONPATH="src"
python scripts/summarize_inter_rater_agreement.py private_reviews.jsonl --output agreement.json
```

再导出去身份化的、已完成裁决的配对标签：

```powershell
python scripts/summarize_human_paired_reviews.py paired_labels.jsonl --output paired_summary.json
python scripts/build_human_review_manifest.py paired_labels.jsonl `
  --review-set-version review-v1 `
  --evaluation-window-id holdout-window-1 `
  --output human_review_manifest.json
python scripts/audit_paper_readiness.py `
  --human-review-jsonl paired_labels.jsonl `
  --human-review-manifest human_review_manifest.json `
  --independent-holdout-manifest holdout_manifest.json `
  --independent-holdout-questions holdout_questions.jsonl `
  --output readiness.json
```

题集文件必须随 manifest 一起提供，并通过 `question_file_sha256`、`question_set_hash`、`question_id_sha256` 和 `question_count` 绑定。只提供 manifest 而不提供文件时，投稿审计保持阻塞。

提供题集文件时，投稿审计还会把它与公开开发题集做题号和规范化题面不相交校验；任何重合都会 fail closed。通过哈希绑定不等于题集独立，访问控制和不相交性必须分别验证。
不能把结果写成独立测试准确率、专家金标准或系统优越性。

## 公开前检查

- 公开仓库只保留去身份化汇总、方法、代码和有再分发许可的样例；
- 删除 reviewer、备注、身份映射、原始 API 响应、密钥和本机路径；
- 保存代码、数据库、语料、题集、prompt、评审导出和统计报告的 hash；
- 同时报告全部题目、可回答题、拒答题、每个类别的分母和失败运行；
- 若任一题未完成裁决或任一来源是 AI/自动标签，投稿审计必须保持阻塞。
