# Changelog

## 0.5.0 — 2026-11-17

V2：长文档分块抽取 + 文档结构识别。

- **`pdfmend structure`**：把段落升级成标题（level 1–3）、有序/无序列表、条款、引用；PDF 用字号 + 编号标记 + 坐标，DOCX 用 Word 的 List 样式。
- **分块抽取**（`chunk.py`）：按页对齐切块，默认 6500 字符/块、上限 8000，页对齐保证证据能指回页码；重叠段落只作为上下文标注「不要从这里抽取」。
- **证据化输出**：每块要求模型给 `value / evidence / source_page / confidence`，JSON 拆成 `fields`（值）+ `evidence`（来源、页码、置信度、冲突）。
- **合并与补查**（`merge.py`）：同值合并证据；异值先比对证据再比置信度，仍不一致记 `conflict`；缺失字段按模板线索词回查命中页，做第二轮定向抽取。
- **内置模板**（`profiles/*.json`，数据而非代码）：`resume` / `contract` / `research_report` / `default`，`--profile` 直接用，旧 `--schema` 仍然兼容。
- **六维质量分**：文字完整性 20 / 表格 20 / 结构 20 / 阅读顺序 15 / 字段 15 / OCR 10；最长段落超 500 字、有列表符号却没有列表、有「第X条」却没有条款、多页无标题都会扣分。
- 实测：67 页研报切成 18 块、覆盖全部 67 页，含「研究机构」线索的页（61–65）落在 `chunk_016`；简历 1 页 → 9 标题 / 11 个列表 / 26 个列表项；合成合同 → 条款 2、有序列表 2、标题层级正确，Markdown 不再出现「1. 1. …」。
- 边界：`（1）（2）（3）` 子列表仍并进条款正文；证据由模型给出，可能张冠李戴。

## 0.4.1 — 2026-11-17

- **真实 DeepSeek 调用已验证**（用户自备 key，只走环境变量，仓库里零命中）：简历 PDF → 姓名/手机/邮箱/学历/院校全对，文档里没有的字段返回 `null` 而不是编造；67 页研报 → 公司名、代码、评级、五条风险全对，24s；扫描件 `scan_sample.pdf` → OCR + 字段，`收入合计 4530.5`、`成本合计 2830.3` 与图一致，45s。
- `--vision` 顺带验了 `deepseek-chat`：同一张图里随机 4 位数字连测两次都读对，A4 页面约 1000 tokens，说明它不是「看不见图也硬答」。
- OCR 在真实扫描件上验过一遍（`tmp/real/donation.pdf`，中文公函，31s 冷启动、80 分「需抽查」），识别文本基本可直接阅读。
- 关闭 paddleocr 3.x 默认加载的 `doc_ori` / `UVDoc` 两个模型：pdfmend 自己纠偏，而且这两个模型会额外拉模型、还会改动页面几何，导致 OCR 坐标对不上原页。
- `_quiet()` 现在同时重定向 fd 2：paddle 的 `Creating model: (...)` 横幅走的是 stderr，之前会漏到用户终端上。

## 0.4.0 — 2026-11-17

- **`pdfmend fields --vision`**：把前 3 页渲染成 PNG，和 schema、文本一起发给视觉模型（`qwen3-vl-plus` / `gpt-4o-mini` 等），专治扫描件、印章、手写、歪斜表格这类「文字抽不干净」的字段。`--dry-run` 会把 base64 折成 `<page image, N bytes>`，不会把整页图片糊到终端上。
- `fields` 的 JSON 增加 `vision` 字段（布尔），方便事后区分这次是不是看了图。
- 隐私说明同步到 README：`--vision` 的暴露面从“文字”扩大到“整页图片”。

## 0.3.1 — 2026-11-17

用真实 PaddleOCR 3.7 + paddlepaddle 跑通后修的兼容与体验问题（0.3.0 的适配层只过了假引擎的测试）：

- **真实 API 对齐**：3.x 走 `predict()`（`ocr()` 只是转发且会告警）；构造参数改用 `use_textline_orientation`，不再触发 `use_angle_cls` 那一串 doc_ori / UVDoc 等多余模型。
- **paddlepaddle 3.3.x 在 Windows CPU 上会 abort**（`ConvertPirAttribute2RuntimeAttribute not support`，oneDNN），依赖钉到 `>=3.0,<3.3`；检测到 3.3 时自动关 MKLDNN 保命。可用 `PDFMEND_OCR_MKLDNN=0/1` 手动控制。
- **`--ocr auto` 只对「整页是图片」的页识别**（`_has_page_image`：图像覆盖 ≥30% 页面），空白页/封面页不再白等一次模型加载；要强制识别用 `--ocr always`。
- **静音 paddle 的 C++ 输出**：oneDNN 探测、模型加载横幅原来会混进 CLI 的 stdout，现在 OCR 期间临时重定向 fd 1。
- **同行单元格用 `|` 连接**（`月份 | 收入 | 成本`），OCR 文本不再把整行拍平、丢列序；仍然不重建表格结构，报告要求核对数字。
- **OCR 失败会写进报告**：`meta["ocr_errors"]` 现在会变成原因行（"OCR 未完成（1 页）：…"），不再只在 `meta` 里躺着。
- **`available()` 用 `find_spec`** 探测，不再 `import paddleocr`：普通文字 PDF 的 `--ocr auto` 从 50 秒降到 0.2 秒（测试套件 180 秒 → 13 秒）。
- 新增 `examples/make_scan.py`（200dpi、倾斜 1.8°、带噪点的合成扫描件），本机实测 7 行全对、质量分 80「需抽查」。
- 测试 70 个。

## 0.3.0 — 2026-11-17

扫描件与字段抽取，均为**可选**能力，默认安装仍纯本地：

- **图像预处理**（`src/pdfmend/preprocess.py`，需 `pdfmend[ocr]`）：non-local means 去噪、投影法纠偏（±10°）、CLAHE + 轻锐化增强；`prepare()` 返回实际执行了哪几步。
- **OCR**（`src/pdfmend/ocr.py`，PaddleOCR）：兼容 2.x / 3.x 两种返回结构；行按几何合成段落，中文不加空格、英文按词加空格、行尾连字符去掉；“手写”由所选 PaddleOCR 模型决定。
- **接入提取流程**：`extract(path, ocr="auto"|"always"|"never")`；只对无文本层页面识别，识别页记入 `meta["ocr_pages"]`、预处理步骤记入 `meta["ocr_steps"]`，失败不致命（`meta["ocr_errors"]`），报告里点名要求核对数字。
- **`pdfmend fields`**（`src/pdfmend/llm.py` + `fields.py`）：OpenAI 兼容协议，DeepSeek（`deepseek-chat`）或 Qwen3-VL（`qwen3-vl-plus`）；`--schema` 定义字段，输出 `<文件名>.fields.json`；`--dry-run` 只打印将发送的 prompt。
- **key 只从环境变量读**：`DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` / `PDFMEND_LLM_API_KEY`，错误信息里自动打码，`.env` 进 `.gitignore`，新增 `.env.example` 与 `tests/test_secrets.py`（扫仓库疑似真 key）。
- `batch` 与 `check` 新增 `--ocr`；报告新增“由 OCR 识别”原因行；扫描件提示改为“安装 pdfmend[ocr] 后加 --ocr auto 可识别”。
- 测试 67 个（新增 `test_llm.py` / `test_ocr.py` / `test_ocr_pipeline.py` / `test_fields.py` / `test_preprocess.py` / `test_secrets.py`）。

## 0.2.0 — 2026-11-17

版面重建层，专治“非标 PDF”（`src/pdfmend/layout.py`）：

- **无框线表格**：按字符 x 坐标聚类还原列（`origin="cluster"`）。费用表、银行流水这类只有空格的表终于不用一行行手敲。
- **双栏/多栏正文**：检测栏间空档，按栏读完再读下一栏，不再出现“上句接了下句”的串行文本；两栏散文不会被误判成表格。
- **页眉页脚**：只删除“贴页边 + 跨 ≥60% 页面重复”的行，正文一个字不动；删除内容记入 `meta["running_heads"]`。
- **跨页表格**：下一页重复表头时自动合并，`Table.page_end` 记录结束页，`flags` 增加 `continued`，Markdown 标题写“第 1–2 页”。
- 段落切分改为按页面自身行距判断，不再把紧排的正文切成一行一段。
- 版本号 0.2.0；新增 `examples/make_messy.py`（四个难转样例）与 `tests/test_layout.py`（4 个断言组，含无 CJK 字体的英文回退）。
- 新增 `sparse_rows` 标记：单元格换行或纵向合并被拆成多行时明确点名（实测 67 页研报 14 张表里 7 张命中，总分从 87 降到 84 → 需抽查）。

## 0.1.0 — 2026-11-17

首个可用版本：

- PDF / DOCX / PPTX / XLSX → Markdown + Excel + JSON + HTML 报告。
- 表格质量分（填充率 / 参差行 / 类型一致性 / 表头）与 7 种告警标记。
- Excel 输出数值化（`1,234.50` → 数字、`16.5%` → 0.165），表头冻结、置信度着色。
- 扫描页检测并明确报页码，不做 OCR（v0.1 边界）。
