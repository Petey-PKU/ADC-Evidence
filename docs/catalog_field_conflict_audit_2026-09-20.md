# 2026-09-20 公共目录字段冲突审计

来源候选文件包含 161 条记录，覆盖 158 个 ADC-字段组合。按 `(adc_id, field)`
分组并按候选值去重后，只有以下 3 组存在竞争值。所有行仍是
`pending_independent_primary_source_review`；本记录不把任何值选为金标准。

| ADC | 字段 | 竞争值 | 当前处理 |
| --- | --- | --- | --- |
| `adc_016` Trastuzumab rezetecan | `dar` | 目录 `5.7`；PLOS 原始研究 `6` | 保留两值；需核对分析方法和产品资料 |
| `adc_016` Trastuzumab rezetecan | `payload_name` | NCI `rezetecan`；PLOS 原始研究 `SHR169265` | 不把名称自动视为同义词；需核对结构/命名关系 |
| `adc_019` Pivekimab sunirine | `payload_name` | FDA 标签 `DGN549C`；FDA 机制段 `FGN849` | 区分连接子-载荷复合物与释放后的细胞毒组分 |

来源定位：

- `adc_016` 的公开原始研究：[PLOS One](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0326691)；药物名称：[NCI Drug Dictionary](https://www.cancer.gov/publications/dictionaries/cancer-drug/def/trastuzumab-rezetecan)。
- `adc_019` 的来源为 [FDA Pivekimab 标签](https://www.accessdata.fda.gov/drugsatfda_docs/label/2026/761460Orig1s000lbl.pdf)。

## 机器复核规则

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_catalog_source_locator_candidates -q
```

测试要求竞争组集合精确等于上表三组。新增候选值会故意使测试失败，迫使维护者更新
冲突记录和论文主张范围；删除候选值也不会静默把剩余值升级为已确认值。字段复核包仍
要求两名独立复核者和必要的裁决，AI 辅助结果不能替代该门禁。
