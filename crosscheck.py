# -*- coding: utf-8 -*-
"""
Cross-check our data against mevzuatkibris.com's RSS feeds.

mevzuatkibris.com is an independent archive built from the same gazette
PDFs. Its per-topic RSS feeds (latest 50 records each; RSS use is allowed by
its terms) are a second opinion on whether we missed recent decisions or
fell behind on new issues. This only reports; it never changes data and
always exits 0, so a problem on their side can't break the update.

Writes the report to crosscheck.md and, under GitHub Actions, sets the step
outputs `diff` (true/false) and `fingerprint` (stable hash of the findings)
so the workflow can open / update / close a tracking issue.

Known source typos that would otherwise be reported every night go into
crosscheck-ignore.json as {"<karar no>": "<reason>"}.

    python crosscheck.py
"""

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "web", "data", "decisions.json")
IGNORE = os.path.join(HERE, "crosscheck-ignore.json")
REPORT = os.path.join(HERE, "crosscheck.md")
BASE = "https://mevzuatkibris.com"
TOPIC_FEEDS = {
    "atama": "/konu/atama/rss.xml",
    "yurttaslik": "/konu/yurttaslik/rss.xml",
}
ALL_FEED = "/rss.xml"
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


def load_ignore():
    try:
        with open(IGNORE, encoding="utf-8") as f:
            return {norm(k): v for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def check():
    """Return (findings, notes). Findings are real differences; notes are
    informational lines (feed errors, ignored items) that don't raise an
    alarm on their own."""
    with open(DATA, encoding="utf-8") as f:
        ours = json.load(f)
    known = {norm(r["kno"]) for r in ours if r["kno"]}
    our_last = max(((r["y"], int(r["no"])) for r in ours if r["no"].isdigit()),
                   default=(0, 0))
    ignore = load_ignore()

    findings, notes = [], []

    try:
        their_issues = set()
        for it in fetch_items(ALL_FEED):
            m = ISSUE_RE.search(it["desc"])
            if m:
                their_issues.add((int(m.group(2)), int(m.group(1))))
        their_last = max(their_issues, default=(0, 0))
        line = (f"Son sayı: bizde **{our_last[1]}/{our_last[0]}**, "
                f"mevzuatkibris'te **{their_last[1]}/{their_last[0]}**")
        if their_last > our_last:
            findings.append(("geride", line + " → geride kaldık"))
        else:
            notes.append(line)
    except Exception as e:  # noqa: BLE001
        notes.append(f"`{ALL_FEED}` okunamadı ({e})")

    for name, path in TOPIC_FEEDS.items():
        try:
            items = list(fetch_items(path))
        except Exception as e:  # noqa: BLE001
            notes.append(f"`{path}` okunamadı ({e})")
            continue
        checked = 0
        for it in items:
            m = KNO_RE.match(it["desc"])
            if not m:
                continue
            checked += 1
            key = norm(m.group(1))
            if key in known:
                continue
            kno = m.group(1).strip()
            if key in ignore:
                notes.append(f"`{kno}` bilinen fark, yok sayıldı: {ignore[key]}")
                continue
            findings.append((
                f"{name}:{key}",
                f"`{name}`: **{kno}** bizde yok — {it['title']} ([kayıt]({it['link']}))"))
        notes.append(f"`{name}`: {checked} karar numarası kontrol edildi")

    return findings, notes


def main():
    try:
        findings, notes = check()
    except Exception as e:  # noqa: BLE001
        findings, notes = [], [f"Kontrol çalıştırılamadı: {e}"]

    fp = hashlib.sha256(
        "\n".join(sorted(k for k, _ in findings)).encode()).hexdigest()[:16]

    lines = ["## mevzuatkibris.com çapraz kontrolü", ""]
    if findings:
        lines.append("### Farklar")
        lines += [f"- {text}" for _, text in findings]
        lines.append("")
    else:
        lines += ["Fark bulunmadı.", ""]
    lines.append("### Ayrıntılar")
    lines += [f"- {n}" for n in notes]
    if findings:
        lines += [
            "",
            "Bir fark kaynaktaki yazım hatasıysa (karar bizde başka numarayla "
            "varsa) `crosscheck-ignore.json` dosyasına eklenebilir.",
        ]
    lines.append(f"\n<!-- crosscheck-fp:{fp} -->")
    report = "\n".join(lines)

    print(report)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"diff={'true' if findings else 'false'}\n")
            f.write(f"fingerprint={fp}\n")


if __name__ == "__main__":
    main()
