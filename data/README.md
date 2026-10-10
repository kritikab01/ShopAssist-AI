# data/ – knowledge-base source files (all fake)

| File | Used by | Pinecone metadata |
|------|---------|-------------------|
| `store_faq.md` | Source text of the store policy | – |
| `store_faq.pdf` | Workflow 01 downloads and embeds this PDF | `source = "faq"` |
| `urls.txt` | Workflow 02 reads this list of pages to scrape | – |
| `pages/*.html` | Fake UrbanThread web pages that workflow 02 scrapes and summarizes | `source = "website"`, `url = <page url>` |

The pages are HTML (not Markdown) so that the **HTML Extract** step in workflow 02 does real work
(removing `<nav>`, tags, etc.), just like scraping a live website.

## Exporting the FAQ as PDF

`store_faq.pdf` is already committed. If you edit `store_faq.md`, regenerate the PDF with **one** of:

1. **Python (recommended):** `pip install reportlab` then `python scripts/make_faq_pdf.py`
2. **VS Code:** install the "Markdown PDF" extension → open `store_faq.md` → right-click → *Markdown PDF: Export (pdf)*.
3. **Google Docs / Word:** paste the text, then *File → Download → PDF*. Upload it to Google Drive
   if you prefer the Google Drive node instead of the HTTP Request node in workflow 01.
4. **pandoc:** `pandoc data/store_faq.md -o data/store_faq.pdf` (needs a LaTeX engine).

## Raw GitHub URLs

Workflows 01 and 02 download these files from
`https://raw.githubusercontent.com/kritikab01/ShopAssist-AI/main/data/...`.
This only works when the repository is **public** and the files are on the **main** branch.
If you keep the repo private, upload the files to Google Drive (or paste the page text into n8n) instead.
