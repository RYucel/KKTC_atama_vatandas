# KKTC Resmî Gazete — Karar Arama & İstatistik

[![Update gazette data](https://github.com/RYucel/KKTC_atama_vatandas/actions/workflows/update-data.yml/badge.svg)](https://github.com/RYucel/KKTC_atama_vatandas/actions/workflows/update-data.yml)
[![Deploy to GitHub Pages](https://github.com/RYucel/KKTC_atama_vatandas/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/RYucel/KKTC_atama_vatandas/actions/workflows/deploy-pages.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Canlı demo: <https://ryucel.github.io/KKTC_atama_vatandas/>**

A minimalist, modern search application over the decisions ("kararlar") published in
the **Turkish Republic of Northern Cyprus (KKTC) Official Gazette**
([basimevi.gov.ct.tr](https://basimevi.gov.ct.tr/)), covering **every year from 2006 to the
current year** — roughly 72,000+ decisions. Data is refreshed **automatically every
night** by a GitHub Actions workflow.

It lets you:

- See **per-year totals** for the four tracked decision categories
- **Search** the full text of ~70,000 decisions and decision numbers
- **Filter** by category and year range
- Open the **source PDF** for any gazette issue
- **Export** the current result set to CSV

## Tracked categories

| Key | Turkish | Meaning |
| --- | --- | --- |
| `atama` | Atamalar | Appointment decrees |
| `gorevden_alma` | Görevden Almalar | Dismissal decrees |
| `yurttasliga_alinma` | Yurttaşlığa Alınma | Citizenship granted |
| `yurttasliktan_cikarma` | Yurttaşlıktan Çıkarılma | Citizenship revoked / cancelled |

---

## How it works

The gazette archive (`/ARŞİV/<year>`) lists every issue with a **fully structured
İÇERİK column**: for each issue it gives the issue number (SAYI), date (TARİH) and a
table of decisions, each with its annex (EK), decision number (karar sayısı) and
description. No PDF parsing is needed — all data comes from the listing pages.

The **current year** is usually not yet published under `/ARŞİV/<year>` (that page is
empty); its issues appear on the **home page** instead. The scraper detects this
automatically: if the archive page for a year yields no decisions, it falls back to the
home page (and always fetches it fresh, never from cache).

```text
scraper.py  ──fetch 2006–current──▶  parse + classify  ──▶  web/data/decisions.json (≈22 MB, ~72.7k rows)
                                                          web/data/summary.json   (per-year counts)

web/index.html + app.js + styles.css   ──load JSON──▶   dashboard · charts · search · filters
```

The frontend is dependency-free vanilla JS. The dashboard renders instantly from the
small `summary.json`; the full `decisions.json` is prefetched in the background so
search is instant.

---

## Usage

### 1. Build / refresh the dataset

Requires Python 3 with `requests`, `beautifulsoup4`, `lxml`.

```bash
pip install requests beautifulsoup4 lxml

# Scrape all years (uses a local HTML cache in ./cache after the first run)
python scraper.py

# Re-download everything (ignore cache)
python scraper.py --refresh

# Only certain years
python scraper.py 2024 2025
```

Output is written to `web/data/`. Fetched pages are cached under `./cache/` so you can
re-run the classifier without re-downloading.

### 2. Run the app

The app loads JSON via `fetch`, so it must be served over HTTP (not opened as a
`file://` path).

```bash
cd web
python -m http.server 8000
```

Then open <http://localhost:8000>.

---

## Project layout

```text
ResmiGazete/
├── scraper.py          # fetch + parse + classify  →  web/data/*.json
├── cache/              # cached HTML pages (auto-created, safe to delete)
├── web/
│   ├── index.html      # app shell
│   ├── styles.css      # minimalist theme (light/dark)
│   ├── app.js          # dashboard, chart, search, filters, CSV export
│   └── data/
│       ├── summary.json    # per-year / per-category aggregate counts
│       └── decisions.json  # flat list of every decision record
└── README.md
```

### Decision record schema (`decisions.json`)

```jsonc
{
  "y": 2025,                       // year
  "no": "262",                     // gazette issue number (SAYI)
  "date": "31.12.2025",            // publication date (TARİH)
  "iso": "2025-12-31",             // ISO date for sorting/filtering
  "ek": "EK III",                  // annex / section
  "kno": "A.E.1071",               // decision number (karar sayısı)
  "desc": "…FİYAT İSTİKRAR FONU…", // decision text (İÇERİK)
  "pdf": "https://basimevi.gov.ct.tr/Portals/6/2025/262.pdf?ver=…",
  "cats": ["atama"]                // matched categories (0..n)
}
```

---

## Notes & limitations

- **Classification is keyword-based** and tolerant of the wording variations across the
  20-year span (e.g. citizenship grants appear as `YURTTAŞLIĞINA ALINMASI`,
  `YURTTAŞLIĞI'NA ALINMA`, or `YURTTAŞLIĞI VERİLMESİ`). A decision can belong to more
  than one category (e.g. *"görevden alma ve atama"*). Counts are best-effort, not legal
  figures — full-text search surfaces everything regardless of category.
- A small number of decisions in very large/malformed gazette issues may be attributed
  to a neighbouring issue number; their text and category are still captured.
- **Source typos in dates are corrected** where possible: impossible years
  (e.g. issue 217/2007 printed as "10.12.2027") are fixed to the archive year, and
  mashed dates ("08.092006", "22..04.2026") are recovered. For issues with no printed
  date in the listing, the date is read from the gazette PDF's first page (cached in
  `cache/pdf_dates.json`). Only 3 issues remain dateless — their PDFs are 404 at the
  source (2010/146, 2018/196, 2020/93); they show "—" but stay under the correct year.
- Data is derived from the public archive and this tool is **unofficial**.

---

## Deployment (GitHub Pages + Actions)

This repository is self-updating:

- **`.github/workflows/update-data.yml`** — runs the scraper every night at 03:00 UTC,
  commits `web/data/*.json` only when the data actually changed, then triggers a
  Pages deployment. Can also be run manually from the *Actions* tab.
- **`.github/workflows/deploy-pages.yml`** — publishes the `web/` folder to GitHub
  Pages on every push to `main`.

To fork & host your own copy: fork the repo, then in **Settings → Pages** set
*Source* to **GitHub Actions**. That's all — no server, no database, no cost.

## Contributing

Issues and pull requests are welcome. Useful starting points:

- Improving the keyword classification rules in [scraper.py](scraper.py) (`classify`)
- Adding new tracked categories (e.g. tüzükler, ihale kararları)
- UI improvements in [web/app.js](web/app.js) — the app is dependency-free vanilla JS

## License

[MIT](LICENSE) © 2026 Rüştü Yücel. The gazette content itself is published by the
KKTC Devlet Basımevi and remains subject to its own terms.
