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

## 扫描件与 AI（v0.3–v0.4，都是可选的）

默认安装依然纯本地、零网络。下面两块要显式开启，不装也能正常转文字版 PDF。

### 扫描件：OpenCV 预处理 + PaddleOCR

```bash
pip install "pdfmend[ocr]"
pdfmend 扫描件.pdf --ocr auto      # 只对没有文本层的页做 OCR（默认）
pdfmend 扫描件.pdf --ocr always    # 扫描页必须识别，失败就报错退出
```

流程：200dpi 渲染 → 去噪（non-local means）→ 纠偏（投影法找 ±10° 内的倾斜）→ CLAHE 增强 → PaddleOCR（中文/英文/手写）。识别出的行按坐标合成段落、按阅读顺序插入原文位置，报告里会写「第 N 页由 OCR 识别（扫描/手写），数字与专有名词请核对」。

没装 `pdfmend[ocr]` 时 `--ocr auto` 不报错，只是继续老实说「该页没有文本层」——不会假装识别过。

边界：OCR 只产出文字行，**不重建表格结构**。同一基线上的单元格会用 `|` 连起来（`月份 | 收入 | 成本`），保留列顺序，但它不是表格：没有列校验、没有 bbox、没有置信度，数字请自己核。要表格请先拿到有文本层的原件；扫描件的表格适合配 `pdfmend fields` 按字段抽，而不是整表还原。`examples/make_scan.py` 会生成一张 200dpi、倾斜 1.8°、带噪点的合成扫描件，可用来对比识别结果（本机实测 7 行全对、质量分 80「需抽查」）。

Windows 上 **paddlepaddle 3.3.x 的 oneDNN 会直接 abort**（`ConvertPirAttribute2RuntimeAttribute not support`），所以依赖里钉了 `paddlepaddle>=3.0,<3.3`；检测到 3.3 时 pdfmend 自动关掉 MKLDNN 保命（慢约 3 倍），想手动控制用 `PDFMEND_OCR_MKLDNN=0/1`。

速度：本机（32 核 CPU、无 GPU）200dpi A4 页面，首张约 25–30 秒（含加载模型），之后每页约 15 秒；同一进程里多页只付一次模型加载。`--ocr auto` 只对「整页是图片」的页动手，所以普通文字 PDF 不会被拖慢。

### 复杂字段：`pdfmend fields`（DeepSeek / Qwen3-VL）

```bash
export DEEPSEEK_API_KEY=sk-...          # 只放环境变量
pdfmend fields 合同.pdf --schema examples/schema.example.json
pdfmend fields 合同.pdf --schema s.json --dry-run        # 只打印将发送的内容
pdfmend fields 扫描件.pdf --schema s.json --provider qwen --vision  # Qwen3-VL 直接看页面图
```

`--vision` 把前 3 页渲染成 PNG 一起发过去（每页约 30–60 KB base64）；扫描件、印章、手写、表格歪斜这类「文字抽不干净」的情况，视觉模型通常比纯文本可靠。代价是三件事：要选支持视觉的模型（`qwen3-vl-plus`、`gpt-4o-mini`，`deepseek-chat` 实测也能读图）、发送体积变大、隐私暴露面从文字扩大到整页图片——身份证、银行卡那种页面别开。

`--vision` 的 token 比想象中便宜：2026-11-17 实测，一张 A4 页面图约 1000 tokens，一张 420×160 的纯图约 200 tokens（deepseek-chat，同一张图里随机 4 位数字两次都读对了，说明不是「假装看见」）。

输出 `<文件名>.fields.json`（`file` / `provider` / `model` / `vision` / `fields`，不含 key）。

隐私：这一步会把提取到的文本发给所选服务商。含身份证号、银行账号的文件请先脱敏，或把 `PDFMEND_LLM_BASE_URL` 指向自建服务。`--dry-run` 可以先看清到底发了什么。

key 的规矩：只从环境变量读（`DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `PDFMEND_LLM_API_KEY`），错误信息里自动打码，`.env` 已加入 `.gitignore`；`tests/test_secrets.py` 会扫全仓库的疑似真 key。示例见 [.env.example](.env.example)。

## 安装

还没发 PyPI（v0.4），先源码安装：

```bash
git clone https://github.com/epoches/pdfmend.git
cd pdfmend
python -m venv .venv
.venv\Scripts\activate        # Windows；macOS/Linux: source .venv/bin/activate
pip install -e .
```

要求 Python ≥ 3.10。默认依赖只有 `pdfplumber`、`python-docx`、`openpyxl`、`python-pptx`，没有云端调用。`pip install "pdfmend[ocr]"` 才装 OpenCV/PaddleOCR；`pdfmend fields` 只用标准库 + 环境变量里的 key。

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

- **不默认做 OCR。** 默认安装不碰 OCR；扫描件/图片页会检测出来并点名页码。装了 `pdfmend[ocr]` 并加 `--ocr auto` 才识别，且结果标注来源。
- **不默认联网。** `pdfmend fields` 是唯一会外发内容的命令，必须自己配 key、自己调用；`--dry-run` 可先审阅。
- **不做回填。** 不会把改好的 Excel 塞回 PDF（这是 `docs/why.md` 里记录的下一个真实需求）。
- **不碰 .doc / .xls 老格式。** 只支持 .docx / .xlsx / .pptx / .pdf。
- **不保证 100% 还原。** 跨页表会自动合并并标 continued；嵌套表、印章盖住表格仍会尽力转并标出来。

## 支持矩阵

| 格式 | 文本 | 表格 | 已知限制 |
|---|---|---|---|
| `.pdf` | ✅ | ✅ lines + cluster + text 三策略 | 无文本层的页报出来；装 `[ocr]` 后可识别；无框线表靠坐标聚类；识别不到时退化为文本 |
| `.docx` | ✅ | ✅ 按正文顺序 | 合并单元格保留内容、不重复；复杂嵌套表按外层处理 |
| `.xlsx` | — | ✅ 每个 sheet 一张表 | `read_only` 模式，单表最多 500 行 |
| `.pptx` | ✅ | ✅ | 图表/图片里的文字不提取 |

## 开发

```bash
pip install -e ".[dev]"
pytest                     # 73 个测试，含真实 PDF/DOCX/XLSX 夹具
python examples/make_demo.py
python examples/make_messy.py
python examples/make_scan.py       # 合成扫描件，验证 OCR/--vision
python examples/benchmark_vs_markitdown.py
```

`make_messy.py` 生成四个“难转”样例（无框线表、双栏、页眉页脚、跨页表），可以直接拿 `pdfmend` 和别的工具对比。

## English

`pdfmend` converts PDF / DOCX / PPTX / XLSX into Markdown + Excel, and **tells you when the result is likely wrong**.

- Tables stay tables (Markdown grid or Excel sheet), not paragraphs.
- Every table gets a confidence score; scanned pages, mojibake and suspected merged cells are flagged instead of silently dropped.
- Chinese-first: two-level headers, CJK text, and `1,234,500.00` are first-class cases.
- Local by default: files never leave your machine, no API keys needed.
- Optional v0.3–v0.4: `pdfmend[ocr]` adds OpenCV cleanup + PaddleOCR for scanned pages; `pdfmend fields` extracts JSON fields with DeepSeek / Qwen-VL (key from env only, `--dry-run` to inspect the payload); `--vision` sends the first pages as images for scans and stamps.
- v0.2 recovers **non-standard layouts**: rule-less tables (whitespace-only columns), multi-column prose read in column order, repeated running heads/footers dropped, and a table split across pages merged back into one (`continued`).
- It does **not** round-trip back into PDF, guess OCR results silently, or read legacy `.doc/.xls`.

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
