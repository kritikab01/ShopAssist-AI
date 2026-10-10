"""Convert data/store_faq.md into data/store_faq.pdf (input for workflow 01).

Usage:  pip install reportlab   then   python scripts/make_faq_pdf.py

This is a deliberately tiny Markdown renderer: headings, bullet lists, bold text,
tables and paragraphs. It is only meant for our FAQ file. You can also export the
PDF any other way (see data/README.md).
"""
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "store_faq.md"
OUT = ROOT / "data" / "store_faq.pdf"

styles = getSampleStyleSheet()


def inline(text: str) -> str:
    """Escape XML characters and turn **bold** / `code` into reportlab markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", text)
    return text


def build():
    story, table_rows = [], []

    def flush_table():
        if not table_rows:
            return
        t = Table(table_rows)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.extend([t, Spacer(1, 8)])
        table_rows.clear()

    for line in SRC.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):  # skip |---| separator rows
                table_rows.append(cells)
            continue
        flush_table()
        if not s or s == "---":
            story.append(Spacer(1, 6))
        elif s.startswith("# "):
            story.append(Paragraph(inline(s[2:]), styles["Title"]))
        elif s.startswith("## "):
            story.append(Paragraph(inline(s[3:]), styles["Heading2"]))
        elif s.startswith("> "):
            story.append(Paragraph("<i>" + inline(s[2:]) + "</i>", styles["Normal"]))
        elif s.startswith("- "):
            story.append(Paragraph("&bull; " + inline(s[2:]), styles["Normal"]))
        else:
            story.append(Paragraph(inline(s), styles["Normal"]))
    flush_table()

    SimpleDocTemplate(str(OUT), pagesize=A4, title="UrbanThread Store FAQ").build(story)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
