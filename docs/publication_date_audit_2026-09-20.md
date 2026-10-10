# 2026-09-20 文献日期边界核查

本轮从 `0f0725bb0b701035516f6db55da3a7c8e2efa56f` 开始，修改范围为公共数据库
审计脚本及回归测试，不更新数据库、索引、题集或人工标签。最终代码版本由本文件所在的
Git 提交绑定。审计发现 `--as-of` 虽被命令行解析，却未传给 `audit_database`，导致所有
命令都按默认日期判断；本轮修复并用跨越默认截止日的 CLI 回归测试验证。

## 日期含义与结果

现有 `publication_date` 来自 `JournalIssue/PubDate`。NLM 区分期刊卷期日期和
`ArticleDate DateType="Electronic"` 的电子发表日期；NLM 入库处理时间又是另一类日期。
依据：[Article/ArticleDate 说明](https://www.nlm.nih.gov/bsd/licensee/elements_article_source.html)、
[PubMedPubDate 定义](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/180101/el-PubMedPubDate.html)。

在本地公开快照的原始 XML 中，7 条晚于 `2026-09-30` 的卷期日期记录均通过原始文件
SHA-256 和唯一 PMID 绑定。结果如下（日期是来源记录值，未经过独立人工确认）：

| PMID | 卷期日期 | 电子发表日期 | 复核结论 |
| --- | --- | --- | --- |
| 42233446 | 2026-Oct | 缺失 | 只有较早的 PubMed/Entrez 入库日期，需复核 |
| 42296596 | 2026-Oct-15 | 2026-06-10 | 有截止日前电子发表线索 |
| 42409324 | 2026-Oct | 2026-07-06 | 有截止日前电子发表线索 |
| 42476270 | 2026-Nov | 2026-07-20 | 有截止日前电子发表线索 |
| 42476483 | 2026-Nov | 2026-07-20 | 有截止日前电子发表线索 |
| 42480966 | 2026-Oct-10 | 2026-07-21 | 有截止日前电子发表线索 |
| 42526386 | 2026-Oct | 2026-07-29 | 有截止日前电子发表线索 |

PMID 42233446 的记录另有日期顺序异常：接受日期为 2026-09-04，PubMed/Entrez 日期却为
2026-06-03。脚本将其标记为 `acceptance_after_publication_or_indexing`，不推断正确日期。
接受、投稿或修订日期均不能当作已经发表的证据。

因此，不能把这 7 条记录一律解释为未来文献并删除。若研究按电子发表日纳入，6 条有
候选支持；另 1 条须继续核查。若研究按期刊卷期日纳入，则需按该口径另建评测快照。
当前全部保持 `candidate_pending_review`，原日期审计仍为 `needs_review`。
较早的日期字段也不能证明当前记录内容在截止日前已经存在：还需采集时间、修订历史和
冻结快照支持时间切分。构建器的 `--as-of` 目前不是历史数据库恢复或全量过滤功能。

## 复现与完整性

```powershell
$env:PYTHONPATH="src"
python scripts/audit_public_dataset.py `
  --database data/processed/adc_public_2026-09-30.db `
  --as-of 2026-09-30 `
  --raw-root data/raw/public_2026-09-30 `
  --output .test_tmp/publication-date-audit.json
python -m unittest discover -s tests -q
```

不提供 `--raw-root` 时不读取原始文件；缺文件、越界路径、校验和不一致、XML 损坏或
PMID 不唯一时均返回 `unknown`。报告不包含本机路径、正文或摘要，也不修改原记录。
解压发布包不带原始 XML，因此无法单凭该包执行这一原始日期复核。

| 输入或输出 | SHA-256（原始字节） |
| --- | --- |
| 原始公共 SQLite | `8bae13afacf3fbb7a88bfb5720413a4e1e3524092bed59db1323a6f04f619f40` |
| 索引 manifest | `93abc3f6a7ee2587168544a8a6d917be8569df3029aafbb5a5c2cd8155313655` |
| 公开 benchmark JSONL | `7169601cf37bfd61ca3e9d36a417ba419ff8f38c829351475dae8884449efc5f` |
| 本轮完整审计 JSON | `8b58f36cc370eefde8fed37c4fd8adb8a10346754b9e71fbf640cd39ead8517c` |

本轮定向测试 10 项通过；完整测试 224 项，220 项通过、4 项可选依赖跳过。数据仍为 partial，未关闭独立人工复核、
独立受控测试集和再分发许可门禁。
