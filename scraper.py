# -*- coding: utf-8 -*-
"""
KKTC Resmi Gazete (TRNC Official Gazette) archive scraper.

Fetches the yearly archive listings from basimevi.gov.ct.tr (2006-2025),
parses every gazette issue and its individual decisions ("kararlar"), then
classifies each decision into searchable categories:

    atama                 - appointment decrees
    gorevden_alma         - dismissal decrees
    yurttasliga_alinma    - granted TRNC citizenship
    yurttasliktan_cikarma - revoked / lost TRNC citizenship

Output (written into web/data/):
    decisions.json  - flat list of every decision record
    summary.json    - per-year / per-category aggregate counts + metadata

Re-run any time to refresh:  python scraper.py
Optionally limit years:      python scraper.py 2024 2025
"""

import json
import os
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE = "https://basimevi.gov.ct.tr"
# The archive path is /ARŞİV/<year> (Turkish characters, percent-encoded).
YEAR_PATH = "/AR%C5%9E%C4%B0V/{year}"
START_YEAR = 2006
END_YEAR = 2026
# The current year is usually not yet published under /ARŞİV/<year>; its issues
# live on the home page instead, so we fall back to it when the archive is empty.
HOME_PATH = "/"

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "web", "data")
CACHE_DIR = os.path.join(HERE, "cache")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ResmiGazeteArchiveBot/1.0)"
}


# --------------------------------------------------------------------------
# Category classification
# --------------------------------------------------------------------------
# Wording varies across the 20 year span, so each category matches several
# phrasings. A single decision may belong to more than one category
# (e.g. "GÖREVDEN ALMA VE ATAMA YAPILMASI").

def classify(text_upper):
    cats = []

    dismissal = "GÖREVDEN AL" in text_upper  # ALMA / ALINMA / ALINMASI
    if dismissal:
        cats.append("gorevden_alma")

    # Appointment: rely on appointment-specific phrases. Dismissal records
    # contain "ATANMIŞ OLAN" (describing a prior posting) which we must NOT
    # treat as an appointment, and vacancy notices ("İLK ATAMA KADROSU
    # MÜNHAL İLANI") are job ads, not appointments.
    is_vacancy = ("MÜNHAL" in text_upper) or ("İLK ATAMA KADRO" in text_upper)
    appointment_markers = (
        "ATAMA KARARNAME",
        "ATANMASI",
        "ATANMASININ",
        "ATAMA YAPILMASI",
        "ATAMA YAPILMASINA",
    )
    if not is_vacancy and any(m in text_upper for m in appointment_markers):
        cats.append("atama")

    # Citizenship: wording varies a lot across the 20 years
    # ("YURTTAŞLIĞINA ALINMASI", "YURTTAŞLIĞI'NA ALINMA",
    #  "YURTTAŞLIĞI VERİLMESİ", "...İPTAL EDİLMESİ", "...ÇIKARILMASI",
    #  "...KAYBETMESİ", "...ISKAT"). Normalise apostrophes first.
    t = text_upper.replace("'", "").replace("’", "").replace("`", "")
    is_citizen = any(s in t for s in (
        "YURTTAŞLIĞ", "YURTTAŞLIK", "VATANDAŞLIĞ", "VATANDAŞLIK"))
    if is_citizen:
        revoked = any(m in t for m in (
            "ÇIKARIL", "İPTAL", "KAYBET", "ISKAT", "GERİ ALIN"))
        if revoked:
            cats.append("yurttasliktan_cikarma")
        elif any(m in t for m in ("ALINMA", "VERİLME", "VERİLECEK", "KABUL")):
            cats.append("yurttasliga_alinma")

    return cats


CATEGORIES = [
    "atama",
    "gorevden_alma",
    "yurttasliga_alinma",
    "yurttasliktan_cikarma",
]


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def clean(s):
    if s is None:
        return ""
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


# Tolerant of source typos like "22..04.2026" (doubled separators) and
# "08.092006" / "05.012015" (missing separator before the year).
DATE_RE = re.compile(r"(\d{1,2})\s*[.\/]+\s*(\d{1,2})\s*[.\/]*\s*(\d{4})")


def to_iso(date_text):
    m = DATE_RE.search(date_text or "")
    if not m:
        return None
    d, mo, y = m.groups()
    try:
        return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return None


PDF_RE = re.compile(r"\.pdf", re.I)
HEADER_LABELS = {"SAYI", "TARİH", "İÇERİK", "TARIH", "ICERIK"}


MODULE_ID_RE = re.compile(r"HtmlModule_lblContent")


def listing_rows(soup):
    """Yield every listing <tr> in document order.

    The gazette listing lives in `*_HtmlModule_lblContent` divs. Malformed /
    unclosed tables in large issues cause the HTML parser to spill rows into
    sibling tables and even a second content module, so we stream rows from
    *all* such modules (in document order) and let the issue context carry
    across the boundaries instead of trusting any single <table>.
    """
    modules = soup.find_all("div", id=MODULE_ID_RE)
    listing = [m for m in modules if m.find("tr") is not None]
    if not listing:
        # Fallback: the table with the most issue links.
        best, best_n = None, 0
        for t in soup.find_all("table"):
            n = len(t.find_all("a", href=PDF_RE))
            if n > best_n:
                best, best_n = t, n
        listing = [best] if best is not None else []

    seen = set()
    for tr in soup.find_all("tr"):
        if id(tr) in seen:
            continue
        if any(m in tr.parents for m in listing):
            seen.add(id(tr))
            yield tr


def is_issue_header(tr):
    """An issue row carries the <a href="...NNN.pdf">NNN</a> number link."""
    for a in tr.find_all("a", href=PDF_RE):
        if clean(a.get_text()).isdigit():
            return a
    return None


def parse_year(year, html, restrict_year=False):
    soup = BeautifulSoup(html, "lxml")

    records = []
    cur = None  # current issue context: dict(no, date, iso, pdf)

    # listing_rows yields a document-order traversal: each issue header row
    # appears before the decision rows that belong to it.
    for tr in listing_rows(soup):
        a = is_issue_header(tr)
        if a is not None:
            issue_no = clean(a.get_text())
            href = a.get("href", "")
            pdf_url = href if href.startswith("http") else BASE + href
            # The date is the dd.mm.yyyy in the dedicated TARİH cell. Only
            # accept it from a *short* cell: otherwise an empty TARİH cell
            # makes us swallow a date mentioned inside the İÇERİK text.
            date_text = ""
            for td in tr.find_all("td", recursive=False):
                t = clean(td.get_text())
                if len(t) > 20:
                    continue
                m = DATE_RE.search(t)
                if m:
                    date_text = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                    break
                # Truncated year (e.g. "23.01.212" for 2012, "23.01.208"
                # for 2018): take day/month and use the page's year.
                m = re.fullmatch(
                    r"(\d{1,2})\s*[.\/]+\s*(\d{1,2})\s*[.\/]+\s*\d{1,3}", t)
                if m and 1 <= int(m.group(2)) <= 12:
                    date_text = f"{m.group(1)}.{m.group(2)}.{year}"
                    break
                # Unparseable but date-like (e.g. "23.0.2012"): keep the raw
                # printed text so the user still sees the source value.
                if not date_text and re.fullmatch(r"[\d.\/\s]{6,}", t):
                    date_text = t
            iso = to_iso(date_text)
            # Archive pages contain a single year, so the page's year is
            # authoritative; correct source typos in the printed year
            # (e.g. issue 217/2007 is printed as "10.12.2027").
            if not restrict_year and iso and not iso.startswith(f"{year}-"):
                fixed = f"{year}-" + iso[5:]
                date_text = DATE_RE.sub(
                    lambda m: f"{m.group(1)}.{m.group(2)}.{year}", date_text)
                iso = fixed
            cur = {
                "no": issue_no,
                "date": date_text,
                "iso": iso,
                "pdf": pdf_url,
            }
            continue

        if cur is None:
            continue  # rows before the first issue (page/table headers)
        # When sourcing from the home page (current year), keep only issues
        # whose date falls in the requested year; the archive pages already
        # contain a single year so no restriction is applied there.
        if restrict_year:
            iso = cur["iso"]
            if iso:
                in_year = iso.startswith(f"{year}-")
            else:
                # No readable date on this issue: fall back to the year
                # folder in its PDF path.
                in_year = f"/{year}/" in cur["pdf"]
            if not in_year:
                continue

        cells = tr.find_all("td", recursive=False)
        vals = [clean(c.get_text()) for c in cells]
        while vals and vals[-1] == "":
            vals.pop()
        if not any(vals):
            continue
        # Skip repeated column-header rows.
        if any(v.upper() in HEADER_LABELS for v in vals):
            continue

        nonempty = [v for v in vals if v]
        if len(nonempty) >= 3:
            ek, kno, desc = vals[0], vals[1], " ".join(v for v in vals[2:] if v)
        elif len(nonempty) == 2:
            ek, kno, desc = "", nonempty[0], nonempty[1]
        else:
            ek, kno, desc = "", "", nonempty[0]
        if not desc:
            continue

        cats = classify(desc.upper())
        records.append({
            "y": year,
            "no": cur["no"],
            "date": cur["date"],
            "iso": cur["iso"],
            "ek": ek,
            "kno": kno,
            "desc": desc,
            "pdf": cur["pdf"],
            "cats": cats,
        })

    return records


# --------------------------------------------------------------------------
# PDF date backfill
# --------------------------------------------------------------------------
# A handful of issues have no (or a broken) printed date in the listing.
# The gazette PDF's first page carries it as e.g. "22 Mart 2016, Salı",
# so fetch those PDFs once and extract it. Results are cached.

TR_MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4,
    "mayıs": 5, "mayis": 5, "haziran": 6, "temmuz": 7,
    "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}
TR_WEEKDAYS = {
    "pazartesi": 0, "salı": 1, "sali": 1, "sah": 1,  # "Salı" OCR'd as "Sah"
    "çarşamba": 2, "carsamba": 2, "perşembe": 3, "persembe": 3,
    "cuma": 4, "cumartesi": 5, "pazar": 6,
}
# Day may be OCR'd as l/I ("l Nisan"); month-year may be comma separated
# ("12 Haziran, 2006"); an optional weekday may follow ("…, Salı").
TR_DATE_RE = re.compile(
    r"([\dlI]{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]{3,8})\s*,?\s*(\d{4})"
    r"(?:\s*,\s*([A-Za-zÇĞİÖŞÜçğıöşü]+))?")


def _lev(a, b):
    """Tiny Levenshtein for fuzzy OCR month matching."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1,
                            prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def date_from_pdf(pdf_url, year, session):
    """Return (date_text, iso) read from the PDF's first page, or None."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    try:
        b = session.get(pdf_url, headers=HEADERS, timeout=120).content
        doc = fitz.open(stream=b, filetype="pdf")
        text = doc[0].get_text()
    except Exception:  # noqa: BLE001
        return None

    for m in TR_DATE_RE.finditer(text):
        day_s, mon_name, y = m.group(1), m.group(2).lower(), int(m.group(3))
        if y != year:
            continue
        try:
            d = int(day_s.replace("l", "1").replace("I", "1"))
        except ValueError:
            continue
        weekday = TR_WEEKDAYS.get((m.group(4) or "").lower())

        mon = TR_MONTHS.get(mon_name)
        if mon is None:
            # OCR-garbled month (e.g. "Maıi" for "Mart"): take close names
            # and let the printed weekday disambiguate.
            cands = []
            for name, num in TR_MONTHS.items():
                if _lev(mon_name, name) <= 2 and num not in cands:
                    cands.append(num)
            if weekday is not None:
                cands = [n for n in cands if _valid_weekday(y, n, d, weekday)]
            if len(cands) != 1:
                continue
            mon = cands[0]
        try:
            dt = datetime(y, mon, d)
        except ValueError:
            continue
        return dt.strftime("%d.%m.%Y"), dt.strftime("%Y-%m-%d")
    return None


def _valid_weekday(y, mon, d, weekday):
    try:
        return datetime(y, mon, d).weekday() == weekday
    except ValueError:
        return False


def backfill_dates(records, session):
    """Fill missing iso dates from the issue PDFs (cached across runs)."""
    cache_file = os.path.join(CACHE_DIR, "pdf_dates.json")
    cache = {}
    if os.path.exists(cache_file):
        with open(cache_file, encoding="utf-8") as f:
            cache = json.load(f)

    missing = {}
    for r in records:
        if not r["iso"]:
            missing.setdefault(f'{r["y"]}/{r["no"]}', r)

    fixed = 0
    for key, r in missing.items():
        if key in cache:
            got = cache[key]  # may be None for known-unreadable PDFs
        else:
            got = date_from_pdf(r["pdf"], r["y"], session)
            cache[key] = got
        if got:
            date_text, iso = got
            for rec in records:
                if rec["y"] == r["y"] and rec["no"] == r["no"]:
                    rec["date"], rec["iso"] = date_text, iso
            fixed += 1

    if missing:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        print(f"  PDF date backfill: {fixed}/{len(missing)} issues recovered")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def fetch_url(url, cache_key, session, retries=3, use_cache=True):
    # Serve from a local cache when available so re-runs (e.g. to refine the
    # category rules) don't re-download the whole archive.
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.html")
    if use_cache and os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return f.read()

    last = None
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=120)
            r.raise_for_status()
            r.encoding = "utf-8"
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                f.write(r.text)
            return r.text
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"    ...{cache_key} attempt {attempt}/{retries} failed: {e}")
            time.sleep(2 * attempt)
    raise last


def fetch_year(year, session, use_cache=True):
    """Return (html, source) for a year, falling back to the home page when
    the archive page for that year is empty (typical for the current year)."""
    archive = fetch_url(BASE + YEAR_PATH.format(year=year), str(year),
                        session, use_cache=use_cache)
    if parse_year(year, archive):
        return archive, "archive"
    # The home page (current-year source) changes constantly, so never serve a
    # stale cached copy for it.
    home = fetch_url(BASE + HOME_PATH, "home", session, use_cache=False)
    return home, "home"


def main():
    argv = sys.argv[1:]
    use_cache = not any(a in ("--refresh", "--no-cache") for a in argv)
    args = [int(a) for a in argv if a.isdigit()]
    years = args if args else list(range(START_YEAR, END_YEAR + 1))

    os.makedirs(DATA_DIR, exist_ok=True)
    session = requests.Session()

    all_records = []
    summary = {
        "generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": BASE,
        "categories": CATEGORIES,
        "years": {},
    }

    for year in years:
        try:
            html, source = fetch_year(year, session, use_cache=use_cache)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {year}: fetch failed: {e}")
            continue
        recs = parse_year(year, html, restrict_year=(source == "home"))
        if not recs:
            print(f"  {year}: no decisions found (skipped)")
            continue
        all_records.extend(recs)

        issues = {r["no"] for r in recs}
        counts = {c: 0 for c in CATEGORIES}
        for r in recs:
            for c in r["cats"]:
                counts[c] += 1
        summary["years"][str(year)] = {
            "issues": len(issues),
            "decisions": len(recs),
            "counts": counts,
        }
        tag = "" if source == "archive" else f" [{source}]"
        print(f"  {year}{tag}: {len(issues):>3} issues, {len(recs):>5} decisions, "
              + ", ".join(f"{c}={counts[c]}" for c in CATEGORIES))
        time.sleep(0.3)

    # Recover dates missing from the listings via the issue PDFs.
    backfill_dates(all_records, session)

    # Sort newest first
    all_records.sort(key=lambda r: (r["iso"] or "0000-00-00"), reverse=True)

    with open(os.path.join(DATA_DIR, "decisions.json"), "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DATA_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    totals = {c: sum(y["counts"][c] for y in summary["years"].values()) for c in CATEGORIES}
    print(f"\nTOTAL: {len(all_records)} decisions across {len(summary['years'])} years")
    print("Category totals:", totals)
    print(f"Wrote {DATA_DIR}\\decisions.json and summary.json")


if __name__ == "__main__":
    main()
