"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdfmend import __version__, fields, llm, structure
from pdfmend.extract import extract
from pdfmend.quality import score_document
from pdfmend.render import to_json, to_markdown, to_xlsx, write_html

SUPPORTED = {".pdf", ".docx", ".xlsx", ".pptx"}
FORMATS = ("md", "xlsx", "json", "html")
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


def _convert_one(src: Path, outdir: Path, formats: set[str], quiet: bool, ocr: str = "never") -> int:
    doc = extract(src, ocr=ocr)
    report = score_document(doc)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    written = []
    if "md" in formats:
        p = outdir / f"{stem}.md"
        p.write_text(to_markdown(report), encoding="utf-8")
        written.append(p.name)
    if "xlsx" in formats:
        if report.tables:
            written.append(to_xlsx(report, outdir / f"{stem}.xlsx").name)
        elif not quiet:
            _p("  ! 没有表格，跳过 xlsx")
    if "json" in formats:
        written.append(to_json(report, outdir / f"{stem}.report.json").name)
    if "html" in formats:
        written.append(write_html(report, outdir / f"{stem}.report.html").name)

    if not quiet:
        _p(f"{src.name}")
        _p(f"  {_bar(report.score)} {report.score}/100  {report.verdict}")
        for t in report.tables:
            flag = f"  [{','.join(t.flags)}]" if t.flags else ""
            where = f"p{t.page}".ljust(5) if t.page else "     "
            _p(f"  - table {t.id:<4} {where} {t.shape:>8}  conf {t.confidence:.2f}{flag}")
        for r in report.reasons:
            _p(f"  · {r}")
        steps = list(dict.fromkeys(doc.meta.get("ocr_steps") or []))
        if steps:
            _p(f"  · 图像预处理：{', '.join(steps)}")
        for err in doc.meta.get("ocr_errors") or []:
            _p(f"  ! OCR {err}")
        if written:
            _p(f"  -> {', '.join(written)}")
        _p()
    return report.score


def cmd_convert(args: argparse.Namespace) -> int:
    files: list[Path] = []
    for p in args.input:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(f for f in path.rglob("*") if f.suffix.lower() in SUPPORTED))
        elif path.is_file():
            files.append(path)
        else:
            _p(f"跳过：找不到 {p}")
    if not files:
        _p("没有可处理的文件。")
        return 1
    formats = {f.strip() for f in args.format.split(",") if f.strip()}
    bad = formats - set(FORMATS)
    if bad:
        _p(f"未知格式：{','.join(sorted(bad))}（可选 {','.join(FORMATS)}）")
        return 1

    scores = []
    for src in files:
        try:
            score = _convert_one(
                src,
                Path(args.outdir) if args.outdir else src.parent,
                formats,
                args.quiet,
                ocr=args.ocr,
            )
            scores.append(score)
        except Exception as e:  # noqa: BLE001 - one bad file must not kill the batch
            _p(f"{src.name}: 失败 — {type(e).__name__}: {e}")
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
        _p(json.dumps(doc.structure or {}, ensure_ascii=False, indent=2))
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
    s.set_defaults(func=cmd_structure)

    v = sub.add_parser("version", help="显示版本")
    v.set_defaults(func=cmd_version)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8_when_piped()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0
    if argv[0] not in (
        "convert", "c", "check", "k", "fields", "structure", "version",
        "-V", "--version", "-h", "--help",
    ):
        argv = ["convert", *argv]
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
