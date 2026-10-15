# -*- coding: utf-8 -*-
"""
Cross-check our data against mevzuatkibris.com's RSS feeds.

mevzuatkibris.com is an independent archive built from the same gazette
PDFs. Its per-topic RSS feeds (latest 50 records each; RSS use is allowed by
its terms) are a second opinion on whether we missed recent decisions or
fell behind on new issues. This only reports; it never changes data and
always exits 0, so a problem on their side can't break the update.

    python crosscheck.py
"""

import json
import os
import re
import xml.etree.ElementTree as ET

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "web", "data", "decisions.json")
BASE = "https://mevzuatkibris.com"
FEEDS = {
    "atama": "/konu/atama/rss.xml",
    "yurttaslik": "/konu/yurttaslik/rss.xml",
    "tum": "/rss.xml",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ResmiGazeteArchiveBot/1.0)"}

# Item descriptions look like "Ü(K-I) 2670-2026 · RG sayı 196/2026 · ...".
KNO_RE = re.compile(r"^\s*([^·]*?\d+\s*-\s*\d{4})\s*·")
ISSUE_RE = re.compile(r"RG sayı (\d+)/(\d{4})")


def norm(kno):
    return re.sub(r"[^0-9A-ZÇĞİÖŞÜ]", "", kno.upper())


def fetch_items(path):
    r = requests.get(BASE + path, headers=HEADERS, timeout=60)
    r.raise_for_status()
    channel = ET.fromstring(r.content).find("channel")
    for it in channel.findall("item"):
        yield {
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "desc": (it.findtext("description") or "").strip(),
        }


def main():
    with open(DATA, encoding="utf-8") as f:
        ours = json.load(f)
    known = {norm(r["kno"]) for r in ours if r["kno"]}
    our_issues = {(r["y"], int(r["no"])) for r in ours if r["no"].isdigit()}
    our_last = max(our_issues, default=(0, 0))

    lines = ["## mevzuatkibris.com çapraz kontrolü", ""]
    for name, path in FEEDS.items():
        try:
            items = list(fetch_items(path))
        except Exception as e:  # noqa: BLE001
            lines.append(f"- `{path}`: okunamadı ({e})")
            continue

        missing, checked, their_issues = [], 0, set()
        for it in items:
            m = ISSUE_RE.search(it["desc"])
            if m:
                their_issues.add((int(m.group(2)), int(m.group(1))))
            if name == "tum":
                continue
            m = KNO_RE.match(it["desc"])
            if not m:
                continue
            checked += 1
            if norm(m.group(1)) not in known:
                missing.append(it)

        if name == "tum":
            their_last = max(their_issues, default=(0, 0))
            ok = their_last <= our_last
            lines.append(
                f"- Son sayı: bizde {our_last[1]}/{our_last[0]}, "
                f"mevzuatkibris'te {their_last[1]}/{their_last[0]}"
                + ("" if ok else " ⚠️ geride kaldık"))
            continue

        lines.append(f"- `{name}`: {checked} karar numarası kontrol edildi, "
                     f"{len(missing)} tanesi bizde yok")
        for it in missing:
            lines.append(f"  - {it['desc'].split('·')[0].strip()} — "
                         f"{it['title']} ({it['link']})")

    report = "\n".join(lines)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")


if __name__ == "__main__":
    main()
