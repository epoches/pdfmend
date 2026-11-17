# pdfmend

[![tests](https://github.com/epoches/pdfmend/actions/workflows/tests.yml/badge.svg)](https://github.com/epoches/pdfmend/actions/workflows/tests.yml)

把 PDF / DOCX / PPTX / XLSX 转成 **Markdown** 和 **Excel**，并且**告诉你哪里可能错了**。

中文优先、纯本地运行、不传文件到任何服务器。

```
$ pdfmend 利润表.pdf
利润表.pdf
  [####################] 98/100  可直接使用
  - table p1t1 p1           8x6  conf 0.97
  · 未发现明显问题
  -> 利润表.md, 利润表.xlsx, 利润表.report.html
```

---

## 它和别的转换器差在哪

不是“转得更准”这种空话，是两件具体的事：

1. **表格不塌。** PDF 里的表格走表格通道（进 Markdown 表格 / 进 Excel 的 sheet），不会被拍平成一段文字，也不会多出一堆空列把数据挤歪。
2. **错了会说。** 每张表有置信度，扫描页、乱码页、疑似合并单元格会被标出来，而不是静默返回一个看起来很正常、实际对不上账的文件。

同一份中文利润表（两级表头、6 列、6 行数据）：

| | pdfmend | markitdown 0.1.9 |
|---|---|---|
| 表格列数 | **6** | 9（多出 3 个空列，首列数据整体右移一格） |
| 两级表头 | 合并成 `本期发生额 / 借方` | 拆成两行数据行 |
| 扫描件 | 明确报「第 1 页没有文本层，不做 OCR」 | 输出空字符串，不解释 |
| 结果可信度 | 质量分 98/100 + 每表置信度 | 无 |

复现：`python examples/make_demo.py && python examples/benchmark_vs_markitdown.py`

markitdown 是个好工具，我们在它上面省了很多时间。但它面向的是“尽量转成文本”，`pdfmend` 面向的是“转完你敢直接拿去对账吗”。

---

## 非标 PDF 才是重点（v0.2）

大模型能把版面规整的 PDF 转得不错，所以通用转换不是这个仓库的战场。真正没人愿意干、也最容易出错的是**版面不规整的 PDF**：没有表格线的表、双栏排版、每页重复的页眉页脚、一张表被切到下一页。

v0.2 的做法是绕开 PDF 自带的文字流，直接按字符坐标重建版面（`src/pdfmend/layout.py`）：

| 你遇到的情况 | pdfmend 现在怎么做 |
|---|---|
| 表格只有空格、没有框线（常见于扫描后 OCR 过的报表） | 按每列的 x 坐标聚类还原列 → 6 行 4 列，数字原样进 Excel |
| 正文是双栏/多栏，复制出来两句夹在一起 | 找到栏间空档，按栏读完再读下一栏 |
| 每页顶部/底部有公司名和页码，被当成正文混进表格 | 只删“跨 ≥60% 页面重复且贴页边”的行，正文一个字不动 |
| 一张表被分到两页，表头重复一遍 | 识别重复表头，合并成一张表，标 `continued`，`page_end` 记结束页 |

复现：`python examples/make_messy.py`，四个样例各对应上面一行；`pytest tests/test_layout.py` 是同一组的断言。

这里没有“大模型猜”，全是几何和统计，所以**本地、可解释、可测**。代价是规则有边界：竖排文字、印章盖字、手写批注仍然处理不了 —— 这类会走“报出来”而不是“猜一个”。

实测一份 67 页、14 张表的 HTML 导出研报（表格无框线、单元格大量换行）：转出 14 张表，总分 84 → **需抽查**，并点名“7 张表有大量空白格（单元格换行或纵向合并被拆开）”。它不会假装这份文件是干净的 —— 这正是这个工具存在的理由。

---

## 安装

还没发 PyPI（v0.2），先源码安装：

```bash
git clone https://github.com/epoches/pdfmend.git
cd pdfmend
python -m venv .venv
.venv\Scripts\activate        # Windows；macOS/Linux: source .venv/bin/activate
pip install -e .
```

要求 Python ≥ 3.10。依赖只有 `pdfplumber`、`python-docx`、`openpyxl`、`python-pptx`，没有云端调用。

## 用法

```bash
pdfmend 报表.pdf                          # 默认输出 .md + .xlsx + .report.html
pdfmend 报表.pdf -f md                    # 只要 Markdown
pdfmend 目录/ -o out/ -f md,xlsx,json     # 批处理整个目录
pdfmend 报表.pdf --strict 85              # 质量分低于 85 时退出码 2（给 CI 用）
pdfmend check 报表.pdf                    # 只体检，不写文件
```

`-f` 可选：`md`、`xlsx`、`json`、`html`。

Python API：

```python
from pathlib import Path
from pdfmend.extract import extract
from pdfmend.quality import score_document
from pdfmend.render import to_markdown, to_xlsx

report = score_document(extract(Path("报表.pdf")))
print(report.score, report.verdict, report.reasons)
for t in report.tables:
    print(t.id, t.shape, round(t.confidence, 2), t.flags)

Path("报表.md").write_text(to_markdown(report), encoding="utf-8")
to_xlsx(report, Path("报表.xlsx"))
```

## 输出长什么样

`报表.md` —— 表格是真的 Markdown 表格，页边界用 HTML 注释保留（渲染时看不见，RAG 切块时有用）：

```markdown
> **质量分 98/100 · 可直接使用** — 未发现明显问题

> 1 张表：表1 高置信（8x6）

<!-- page 1 -->

2026 年度利润表（节选）

| 科目 | 本期发生额 / 借方 | 贷方 | 上期发生额 / 借方 | 贷方 | 变动 / 比例 |
| --- | --- | --- | --- | --- | --- |
| 营业收入 | 1,284,300.00 | 0.00 | 1,102,450.00 | 0.00 | 16.5% |
| 营业成本 | 612,800.00 | 0.00 | 588,300.00 | 0.00 | 4.2% |
```

`报表.xlsx` —— `_report` 表给出总览和每张表的置信度/告警；每张表一个 sheet，表头加粗冻结，`1,284,300.00` 存成真数字 `1284300`，`16.5%` 存成 `0.165` 并带百分比格式。

`报表.report.html` —— 单文件、无外链，可直接发给人看：分数、告警、每张表的置信度色块。

## 质量分怎么算的

不是玄学，是四个可观测的量加权（每张表独立算，再按行数汇总到文档）：

```
confidence = 0.45 × 填充率
           + 0.25 × (1 − 参差行比例)
           + 0.20 × 类型一致性
           + 0.10 × 有无表头
```

触发这些标记会再扣分，并写进报告：

| 标记 | 含义 |
|---|---|
| `collapsed_single_column` | 表格塌成一列（PDF 提表的经典失败） |
| `ragged_rows` | 某些行列数不一致，多半是合并单元格或漏切 |
| `empty_cells` | 超过 40% 的格子是空的 |
| `mixed_types` | 数字列里混进了文字（页脚、备注掉进数据区） |
| `merged_cells_suspected` | 相邻格子重复，疑似纵向合并被展开 |
| `no_header` | 首行不像表头 |
| `too_small` | 少于 2 行或 2 列 |
| `continued` | 表格从上一页续过来，已合并（看 `page_end`） |
| `sparse_rows` | 多行只剩一两个格子有字：单元格换行被拆成了多行，或纵向合并被展开 |

文档级：≥85 可直接用，≥60 建议抽查，否则人工复核。**这是启发式，不是测量** —— 它宁可保守地喊一声，也不假装 100% 正确。

## 明确不做的事

- **不做 OCR。** 扫描件/图片页会检测出来并点名页码，然后停在这里。
- **不做回填。** 不会把改好的 Excel 塞回 PDF（这是 `docs/why.md` 里记录的下一个真实需求）。
- **不碰 .doc / .xls 老格式。** 只支持 .docx / .xlsx / .pptx / .pdf。
- **不保证 100% 还原。** 跨页表会自动合并并标 continued；嵌套表、印章盖住表格仍会尽力转并标出来。

## 支持矩阵

| 格式 | 文本 | 表格 | 已知限制 |
|---|---|---|---|
| `.pdf` | ✅ | ✅ lines + cluster + text 三策略 | 无文本层的页报出来；无框线表靠坐标聚类；识别不到时退化为文本 |
| `.docx` | ✅ | ✅ 按正文顺序 | 合并单元格保留内容、不重复；复杂嵌套表按外层处理 |
| `.xlsx` | — | ✅ 每个 sheet 一张表 | `read_only` 模式，单表最多 500 行 |
| `.pptx` | ✅ | ✅ | 图表/图片里的文字不提取 |

## 开发

```bash
pip install -e ".[dev]"
pytest                     # 34 个测试，含真实 PDF/DOCX/XLSX 夹具
python examples/make_demo.py
python examples/make_messy.py
python examples/benchmark_vs_markitdown.py
```

`make_messy.py` 生成四个“难转”样例（无框线表、双栏、页眉页脚、跨页表），可以直接拿 `pdfmend` 和别的工具对比。

## English

`pdfmend` converts PDF / DOCX / PPTX / XLSX into Markdown + Excel, and **tells you when the result is likely wrong**.

- Tables stay tables (Markdown grid or Excel sheet), not paragraphs.
- Every table gets a confidence score; scanned pages, mojibake and suspected merged cells are flagged instead of silently dropped.
- Local-only: files never leave your machine. No API keys, no upload.
- Chinese-first: two-level headers, CJK text, and `1,234,500.00` are first-class cases.
- v0.2 recovers **non-standard layouts**: rule-less tables (whitespace-only columns), multi-column prose read in column order, repeated running heads/footers dropped, and a table split across pages merged back into one (`continued`).
- v0.2 does **not** do OCR, round-tripping back into PDF, or legacy `.doc/.xls`.

```bash
pip install -e .
pdfmend report.pdf            # -> report.md, report.xlsx, report.report.html
pdfmend report.pdf --strict 85
```

## 为什么开源这个

`docs/why.md` 记录了完整推导：从百度下拉词、知乎/小红书原话，到 markitdown 的 272 个 table issue。结论是——**用户抱怨的不是慢和贵，是“转完是乱的”**。这个仓库先解决“可信”，再谈别的。

如果你手上有把工具转崩的文件（脱敏后），欢迎开 [issue](https://github.com/epoches/pdfmend/issues) 附上，失败样本比 star 有用。

## License

MIT
