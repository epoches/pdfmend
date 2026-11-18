"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdfmend import __version__, feedback, fields, licensing, llm, structure
from pdfmend.extract import extract
from pdfmend.quality import score_document
from pdfmend.services.conversion import (
    DEFAULT_FORMATS as _DEFAULT_FORMATS,
    FORMATS,
    SUPPORTED,
    convert_file,
    normalize_formats,
    scan_files,
)

DEFAULT_FORMATS = "md,xlsx,html"


def _utf8_when_piped() -> None:
    """Keep UTF-8 in logs/CI; leave an interactive console's code page alone.

    Windows defaults a piped stdout to the ANSI code page (CP936 on Chinese
    systems), which turns Chinese diagnostics into mojibake in CI and editor
    terminals. Piped output is almost always consumed as UTF-8, so say UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty() and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _p(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(text.encode(enc, "replace").decode(enc))


def _bar(score: int, width: int = 20) -> str:
    filled = int(round(score / 100 * width))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _convert_one(src: Path, outdir: Path, formats: set[str], quiet: bool, ocr: str = "never") -> int | None:
    result = convert_file(src, output_dir=outdir, formats=sorted(formats), ocr=ocr)
    if not result.ok:
        _p(f"{src.name}: 失败 — {result.error}")
        return None
    report = result.report
    if not quiet:
        _p(f"{src.name}")
        _p(f"  {_bar(report.score)} {report.score}/100  {report.verdict}")
        for t in report.tables:
            flag = f"  [{','.join(t.flags)}]" if t.flags else ""
            where = f"p{t.page}".ljust(5) if t.page else "     "
            _p(f"  - table {t.id:<4} {where} {t.shape:>8}  conf {t.confidence:.2f}{flag}")
        for r in report.reasons:
            _p(f"  · {r}")
        steps = list(dict.fromkeys(result.report.document.meta.get("ocr_steps") or []))
        if steps:
            _p(f"  · 图像预处理：{', '.join(steps)}")
        for err in result.report.document.meta.get("ocr_errors") or []:
            _p(f"  ! OCR {err}")
        for warning in result.warnings:
            _p(f"  ! {warning}")
        if result.outputs:
            _p(f"  -> {', '.join(result.output_names)}")
        _p()
    return report.score


def cmd_convert(args: argparse.Namespace) -> int:
    files = scan_files(args.input)
    missing = [p for p in args.input if not Path(p).exists()]
    for p in missing:
        _p(f"跳过：找不到 {p}")
    if not files:
        _p("没有可处理的文件。")
        return 1
    try:
        normalize_formats(args.format)
    except ValueError as exc:
        _p(str(exc))
        return 1

    scores = []
    for src in files:
        try:
            score = _convert_one(
                src,
                Path(args.outdir) if args.outdir else src.parent,
                set(normalize_formats(args.format)),
                args.quiet,
                ocr=args.ocr,
            )
        except Exception as e:  # noqa: BLE001 - one bad file must not kill the batch
            _p(f"{src.name}: 失败 — {type(e).__name__}: {e}")
            continue
        if score is not None:
            scores.append(score)
    if args.strict and scores and min(scores) < args.strict:
        _p(f"严格模式：最低分 {min(scores)} < {args.strict}")
        return 2
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    srcs = [Path(p) for p in args.input]
    worst = 100
    for src in srcs:
        try:
            report = score_document(extract(src, ocr=args.ocr))
        except Exception as e:  # noqa: BLE001
            _p(f"{src.name}: 失败 — {type(e).__name__}: {e}")
            worst = 0
            continue
        worst = min(worst, report.score)
        _p(f"{src.name}  {_bar(report.score)} {report.score}/100  {report.verdict}")
        for r in report.reasons:
            _p(f"  · {r}")
    return 0 if worst >= 60 else 2


def cmd_fields(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file():
        _p(f"找不到文件：{src}")
        return 1
    if not args.schema and not args.profile:
        _p("需要 --profile（resume/contract/research_report/default）或 --schema 文件")
        return 1
    schema_path = Path(args.schema) if args.schema else None
    try:
        messages = fields.dry_run_messages(
            src, schema_path, profile=args.profile, ocr=args.ocr, vision=args.vision
        )
    except (ValueError, OSError) as exc:
        _p(f"失败：{exc}")
        return 2
    if args.dry_run:
        preview = json.dumps(messages, ensure_ascii=False, indent=2)
        preview = _redact_images(preview)
        _p(preview[:4000])
        _p("（dry-run：没有调用 API，也没有读取任何 key）")
        return 0
    try:
        target = fields.run(
            src,
            schema_path,
            profile=args.profile,
            out=Path(args.out) if args.out else None,
            provider=args.provider,
            model=args.model,
            ocr=args.ocr,
            vision=args.vision,
            chunk=args.chunk,
        )
    except (llm.LLMError, ValueError, OSError) as exc:
        _p(f"失败：{exc}")
        return 2
    cfg = llm.config_from_env(args.provider, args.model)
    data = json.loads(target.read_text(encoding="utf-8"))
    stats = data.get("stats", {})
    _p(f"{src.name} -> {target.name}")
    _p(f"  · 模板 {data.get('profile')}，{stats.get('pages', '?')} 页 / {stats.get('chunks', '?')} 块，"
       f"{stats.get('passes', 1)} 轮抽取")
    _p(f"  · 字段 {stats.get('found', 0)}/{stats.get('fields', 0)} 找到，"
       f"{stats.get('conflicts', 0)} 处冲突，质量分 {data.get('quality', {}).get('score', '?')}")
    for name in stats.get("missing") or []:
        _p(f"  · 未找到：{name}")
    _p(f"  · {cfg.describe()}")
    if args.vision:
        _p("  · 已把首页图片发给模型（图片确实发到了服务商）")
    _p("  · 字段由模型生成，金额与日期请对照原件核验")
    return 0


def cmd_structure(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file():
        _p(f"找不到文件：{src}")
        return 1
    try:
        doc = extract(src, ocr=args.ocr)
    except Exception as exc:  # noqa: BLE001
        _p(f"{src.name}: 失败 — {type(exc).__name__}: {exc}")
        return 2
    counts = structure.counts(doc.blocks)
    _p(f"{src.name}  第 {doc.pages} 页 / {len(doc.blocks)} 个块")
    for kind, number in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        _p(f"  {kind:<14} {number}")
    if args.json:
        payload = json.dumps(doc.structure or {}, ensure_ascii=False, indent=2)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload + "\n", encoding="utf-8")
            _p(f"结构已写入 {out}")
        else:
            _p(payload)
        return 0
    for block in doc.blocks:
        if block.kind == "heading":
            indent = "  " * max(0, (block.level or 1) - 1)
            _p(f"{indent}# {block.text}")
        elif block.kind in ("bullet_list", "numbered_list"):
            _p(f"  - 列表 x{len(block.items or [])}：{(block.items or [''])[0][:50]}")
    return 0


def _redact_images(text: str) -> str:
    """Dry-run output: show that images are attached without dumping base64."""
    marker = "data:image/png;base64,"
    while True:
        start = text.find(marker)
        if start < 0:
            return text
        end = text.find('"', start + len(marker))
        if end < 0:
            return text
        text = text[:start] + f"<page image, {end - start - len(marker)} bytes of base64>" + text[end:]


def cmd_feedback_add(args: argparse.Namespace) -> int:
    try:
        tree = feedback.load_structure(args.structure)
        item = feedback.record(
            tree,
            args.block,
            args.to,
            document=args.document,
            document_type=args.document_type,
            note=args.note,
        )
        path = feedback.append(item, args.file)
    except feedback.FeedbackError as exc:
        _p(str(exc))
        return 1
    _p(f"已记录 {item['block_id']}：{item['original_type']} → {item['corrected_type']}（{path}）")
    return 0


def cmd_feedback_list(args: argparse.Namespace) -> int:
    try:
        records = feedback.load(args.file)
    except feedback.FeedbackError as exc:
        _p(str(exc))
        return 1
    for item in records[-max(1, args.limit):]:
        page = f" 第{item['page']}页" if item.get("page") else ""
        _p(
            f"{item.get('created_at', '')}  {item.get('block_id', '')}{page}  "
            f"{item.get('original_type')} → {item.get('corrected_type')}  "
            f"{(item.get('original_text') or '')[:60]}"
        )
    if not records:
        _p(f"{args.file} 里还没有记录")
    return 0


def cmd_feedback_stats(args: argparse.Namespace) -> int:
    try:
        data = feedback.stats(feedback.load(args.file))
    except feedback.FeedbackError as exc:
        _p(str(exc))
        return 1
    _p(f"共 {data['total']} 条纠错")
    for label, count in data["transitions"].items():
        _p(f"  {label:<28} {count}")
    for label, count in data["by_document_type"].items():
        _p(f"  [{label}] {count}")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    ok, message = licensing.register(
        args.user, args.code, allow_server=not args.offline
    )
    _p(("✅ " if ok else "❌ ") + message)
    return 0 if ok else 1


def cmd_request_code(args: argparse.Namespace) -> int:
    result = licensing.request_code(args.user, args.email, args.txn)
    _p(("✅ " if result.ok else "❌ ") + result.message)
    if result.ok:
        _p(f"机器码：{licensing.machine_id()}（已随申请一并提交）")
        _p("收到邮件后：pdfmend register --user <注册名> --code <注册码>")
    return 0 if result.ok else 1


def cmd_license(_: argparse.Namespace) -> int:
    _p(licensing.license_summary())
    _p(f"机器码：{licensing.machine_id()}")
    _p(f"状态文件：{licensing.state_path()}")
    return 0


def cmd_version(_: argparse.Namespace) -> int:
    _p(f"pdfmend {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdfmend",
        description="把 PDF/DOCX/PPTX/XLSX 转成 Markdown 和 Excel，并把坏掉的表格指出来。",
    )
    p.add_argument("-V", "--version", action="version", version=f"pdfmend {__version__}")
    sub = p.add_subparsers(dest="cmd")

    c = sub.add_parser("convert", aliases=["c"], help="转换文件或目录")
    c.add_argument("input", nargs="+", help="文件或目录")
    c.add_argument("-o", "--outdir", help="输出目录（默认与原文件同目录）")
    c.add_argument("-f", "--format", default=DEFAULT_FORMATS, help=f"逗号分隔，可选 {','.join(FORMATS)}")
    c.add_argument("-q", "--quiet", action="store_true")
    c.add_argument("--strict", type=int, metavar="N", help="质量分低于 N 时返回退出码 2")
    c.add_argument(
        "--ocr",
        choices=("auto", "always", "never"),
        default="auto",
        help="扫描页处理：auto=有文本层就跳过，always=扫描页必须 OCR（失败报错），never=不碰 OCR",
    )
    c.set_defaults(func=cmd_convert)

    k = sub.add_parser("check", aliases=["k"], help="只体检，不写文件")
    k.add_argument("input", nargs="+")
    k.add_argument("--ocr", choices=("auto", "always", "never"), default="auto")
    k.set_defaults(func=cmd_check)

    f = sub.add_parser("fields", help="用 LLM 把文档抽成 JSON 字段（需要 API key）")
    f.add_argument("input", help="文件（.pdf .docx .xlsx .pptx）")
    f.add_argument("--schema", help="JSON schema 文件，键=字段名（自定义字段时用）")
    f.add_argument(
        "--profile",
        choices=("resume", "contract", "research_report", "default"),
        help="文档模板：简历 / 合同 / 研报 / 通用；与 --schema 二选一",
    )
    f.add_argument("--provider", choices=("deepseek", "qwen", "openai"), help="默认 deepseek")
    f.add_argument("--model", help="覆盖模型名")
    f.add_argument("--ocr", choices=("auto", "always", "never"), default="auto")
    f.add_argument("-o", "--out", help="输出路径（默认 <文件名>.fields.json）")
    f.add_argument(
        "--no-chunk",
        dest="chunk",
        action="store_false",
        help="不分块，整篇一次发给模型（短文档才用；长文档会丢靠后的字段）",
    )
    f.add_argument(
        "--vision",
        action="store_true",
        help="把首页图片也发给模型（Qwen3-VL / GPT-4o 这类视觉模型，扫描件推荐）",
    )
    f.add_argument("--dry-run", action="store_true", help="只打印将要发送的内容，不调用 API")
    f.set_defaults(func=cmd_fields, chunk=True)

    s = sub.add_parser("structure", help="只打印识别出的结构（标题/列表/条款）")
    s.add_argument("input")
    s.add_argument("--ocr", choices=("auto", "always", "never"), default="auto")
    s.add_argument("--json", action="store_true", help="输出完整结构树 JSON")
    s.add_argument("-o", "--out", help="把结构 JSON 写到文件（配合 --json）")
    s.set_defaults(func=cmd_structure)

    fb = sub.add_parser("feedback", help="记录并汇总人工纠错（P2，用于改规则和攒评测集）")
    fbs = fb.add_subparsers(dest="feedback_cmd")
    fa = fbs.add_parser("add", help="把某个块的类型改对，追加到纠错文件")
    fa.add_argument("--structure", required=True, help="pdfmend structure --json 的输出文件")
    fa.add_argument("--block", required=True, help="块 id，例如 b17")
    fa.add_argument("--to", required=True, choices=feedback.KINDS, help="正确的类型")
    fa.add_argument("--note", default="", help="为什么改（会进统计，方便之后归类）")
    fa.add_argument("--document", default="", help="原文件名")
    fa.add_argument("--document-type", default="", help="合同/简历/研报…")
    fa.add_argument("--file", default=str(feedback.DEFAULT_FILE))
    fa.set_defaults(func=cmd_feedback_add)
    fl = fbs.add_parser("list", help="看最近几条纠错")
    fl.add_argument("--file", default=str(feedback.DEFAULT_FILE))
    fl.add_argument("--limit", type=int, default=20)
    fl.set_defaults(func=cmd_feedback_list)
    fs = fbs.add_parser("stats", help="按 original→corrected 汇总，找反复出错的模式")
    fs.add_argument("--file", default=str(feedback.DEFAULT_FILE))
    fs.set_defaults(func=cmd_feedback_stats)
    fb.set_defaults(func=lambda _a: (_p(fb.format_help()) or 1))

    v = sub.add_parser("version", help="显示版本")
    v.set_defaults(func=cmd_version)

    r = sub.add_parser("register", help="用用户名+注册码注册（默认先本机验证，再问服务器）")
    r.add_argument("--user", required=True, help="用户名")
    r.add_argument("--code", required=True, help="注册码，例如 20261117-ABCDEFGH23456789")
    r.add_argument("--offline", action="store_true", help="只做本机验证，不访问服务器")
    r.set_defaults(func=cmd_register)

    lic = sub.add_parser("license", help="显示注册状态与机器码")
    lic.set_defaults(func=cmd_license)

    req = sub.add_parser("request-code", help="申请注册码（填邮箱、注册名、赞助单号），等邮件")
    req.add_argument("--user", required=True, help="想绑定到哪个注册名")
    req.add_argument("--email", required=True, help="注册码发到这个邮箱")
    req.add_argument("--txn", required=True, help="赞助/订单单号")
    req.set_defaults(func=cmd_request_code)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8_when_piped()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0
    if argv[0] not in (
        "convert", "c", "check", "k", "fields", "structure", "feedback",
        "register", "license", "request-code", "version",
        "-V", "--version", "-h", "--help",
    ):
        argv = ["convert", *argv]
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
