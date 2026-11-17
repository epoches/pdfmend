"""The conversion service: one function the CLI and the desktop app both call.

Nothing here re-implements parsing -- it wires the existing engine together:

    extract() -> score_document() -> to_markdown()/to_xlsx()/to_json()/write_html()

Keeping it out of ``cli.py`` is what lets the GUI stay thin and lets both
entry points produce byte-identical outputs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from pdfmend import usage
from pdfmend.extract import extract
from pdfmend.model import Report
from pdfmend.quality import score_document
from pdfmend.render import to_json, to_markdown, to_xlsx, write_html

SUPPORTED = {".pdf", ".docx", ".xlsx", ".pptx"}
FORMATS = ("md", "xlsx", "json", "html")
DEFAULT_FORMATS = ("md", "xlsx", "json", "html")

SUFFIX = {
    "md": ".md",
    "xlsx": ".xlsx",
    "json": ".report.json",
    "html": ".report.html",
}


@dataclass
class ConversionResult:
    """What one file produced, including the report the GUI renders."""

    source: Path
    report: Report | None = None
    outputs: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def score(self) -> int:
        return self.report.score if self.report else 0

    @property
    def verdict(self) -> str:
        return self.report.verdict if self.report else "失败"

    @property
    def output_names(self) -> list[str]:
        return [p.name for p in self.outputs.values()]

    def message(self) -> str:
        if self.error:
            return f"{self.source.name}: 失败 — {self.error}"
        return f"{self.source.name}: {self.score}/100 {self.verdict}"

    def to_dict(self) -> dict:
        return {
            "source": str(self.source),
            "score": self.score,
            "verdict": self.verdict,
            "ok": self.ok,
            "error": self.error,
            "seconds": round(self.seconds, 2),
            "outputs": {fmt: str(path) for fmt, path in self.outputs.items()},
            "warnings": list(self.warnings),
        }


def supported(path: Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED


def scan_files(paths) -> list[Path]:
    """Expand files and folders into a de-duplicated list of supported files."""
    found: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        candidates: list[Path]
        if path.is_dir():
            candidates = sorted(
                p for p in path.rglob("*") if p.is_file() and supported(p)
            )
        elif path.is_file():
            candidates = [path]
        else:
            continue
        for item in candidates:
            key = item.resolve()
            if key not in seen:
                seen.add(key)
                found.append(item)
    return found


def normalize_formats(formats) -> tuple[str, ...]:
    """Accept 'md,xlsx' or ['md', 'xlsx']; reject anything we cannot render."""
    if isinstance(formats, str):
        formats = [f.strip() for f in formats.split(",")]
    cleaned: list[str] = []
    for fmt in formats or ():
        name = str(fmt).strip().lower()
        if name and name not in cleaned:
            cleaned.append(name)
    unknown = [f for f in cleaned if f not in FORMATS]
    if unknown:
        raise ValueError(f"未知格式：{','.join(unknown)}（可选 {','.join(FORMATS)}）")
    return tuple(cleaned)


def output_path(source: Path, output_dir: Path, fmt: str) -> Path:
    return Path(output_dir) / f"{Path(source).stem}{SUFFIX[fmt]}"


def convert_file(
    source,
    output_dir=None,
    formats=DEFAULT_FORMATS,
    ocr: str = "never",
) -> ConversionResult:
    """Parse one document, score it, and write the requested formats.

    Errors are captured on the result instead of raised, because the GUI and
    the batch runner both need "one bad file must not kill the run".
    """
    src = Path(source)
    result = ConversionResult(source=src)
    started = time.perf_counter()
    try:
        if ocr not in ("never", "auto", "always"):
            raise ValueError(f"未知 OCR 模式：{ocr}")
        wanted = normalize_formats(formats)
        if not supported(src):
            raise ValueError(f"不支持的文件类型：{src.suffix or '(无扩展名)'}")
        outdir = Path(output_dir) if output_dir else src.parent
        outdir.mkdir(parents=True, exist_ok=True)

        doc = extract(src, ocr=ocr)
        report = score_document(doc)
        result.report = report
        for fmt in wanted:
            if fmt == "md":
                path = output_path(src, outdir, "md")
                path.write_text(to_markdown(report), encoding="utf-8")
                result.outputs["md"] = path
            elif fmt == "xlsx":
                if report.tables:
                    result.outputs["xlsx"] = to_xlsx(report, output_path(src, outdir, "xlsx"))
                else:
                    result.warnings.append("没有表格，跳过 xlsx")
            elif fmt == "json":
                result.outputs["json"] = to_json(report, output_path(src, outdir, "json"))
            elif fmt == "html":
                result.outputs["html"] = write_html(report, output_path(src, outdir, "html"))
    except Exception as exc:  # noqa: BLE001 - surfaced on the result, not raised
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.seconds = time.perf_counter() - started
        _record(result)
    return result


def _record(result: ConversionResult) -> None:
    """Keep a local history line and advance the donation counter.

    Logging must never break a conversion, so every failure here is swallowed.
    """
    if not result.ok:
        return
    try:
        usage.log_conversion(result)
        usage.record_success()
    except Exception:  # noqa: BLE001 - history is best effort
        pass
