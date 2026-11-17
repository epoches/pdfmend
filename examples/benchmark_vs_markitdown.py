"""Compare pdfmend with markitdown on the demo files.

    python examples/benchmark_vs_markitdown.py

markitdown is optional: if it is not installed the script says so and exits.
Both tools write UTF-8; the console code page is irrelevant because results are
read back from files.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
ROOT = HERE.parent


def md_table_stats(md: str) -> tuple[int, int]:
    """(max columns in a markdown table, number of table data rows)."""
    cols, rows = 0, 0
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c for c in s.strip("|").split("|")]
            if all(set(c.strip()) <= {"-", ":", " "} for c in cells):
                continue
            cols = max(cols, len(cells))
            rows += 1
    return cols, max(0, rows - 1) if rows else 0


def pdfmend_md(pdf: Path, tmp: Path) -> str:
    out = tmp / "pdfmend"
    env = {"PYTHONPATH": str(ROOT / "src")}
    subprocess.run(
        [sys.executable, "-m", "pdfmend", str(pdf), "-o", str(out), "-f", "md"],
        check=True, capture_output=True, env={**__import__("os").environ, **env},
    )
    return (out / (pdf.stem + ".md")).read_text(encoding="utf-8")


def markitdown_md(pdf: Path) -> str:
    from markitdown import MarkItDown

    return MarkItDown().convert(str(pdf)).text_content


def main() -> int:
    pdfs = sorted(OUT.glob("*.pdf"))
    if not pdfs:
        print("先运行 python examples/make_demo.py")
        return 1
    try:
        import markitdown  # noqa: F401
    except ImportError:
        print("未安装 markitdown：pip install markitdown")
        return 1

    print(f"{'file':<24}{'tool':<12}{'cols':>5}{'rows':>6}{'chars':>8}  note")
    for pdf in pdfs:
        with tempfile.TemporaryDirectory() as td:
            mine = pdfmend_md(pdf, Path(td))
        theirs = markitdown_md(pdf)
        for name, md in (("pdfmend", mine), ("markitdown", theirs)):
            cols, rows = md_table_stats(md)
            note = ""
            if name == "pdfmend":
                from pdfmend.extract import extract
                from pdfmend.quality import score_document

                r = score_document(extract(pdf))
                note = f"score={r.score} tables={len(r.tables)} " + ",".join(
                    f for t in r.tables for f in t.flags)
            print(f"{pdf.name:<24}{name:<12}{cols:>5}{rows:>6}{len(md):>8}  {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
