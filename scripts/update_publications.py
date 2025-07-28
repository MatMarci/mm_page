#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_publications.py
Pobiera publikacje z Google Scholar i zapisuje je do assets/publications.json.
Wymaga: pip install scholarly tenacity
Użycie:
  python scripts/update_publications.py --id RZAgZ88AAAAJ --out lab_website/assets/publications.json --selected 3
"""
import argparse, json, time, sys
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from scholarly import scholarly

def _norm_authors(s: str) -> List[str]:
    if not s:
        return []
    return [a.strip() for a in s.replace(" and ", ",").split(",") if a.strip()]

@retry(stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=1, min=2, max=30),
       retry=retry_if_exception_type(Exception))
def fetch_author(author_id: str):
    a = scholarly.search_author_id(author_id)
    return scholarly.fill(a, sections=["publications"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="Google Scholar user id (from citations?user=...)")
    ap.add_argument("--out", required=True, help="output JSON path, e.g. lab_website/assets/publications.json")
    ap.add_argument("--selected", type=int, default=3, help="how many newest to mark as selected")
    args = ap.parse_args()

    author = fetch_author(args.id)
    pubs = []
    for p in author.get("publications", []):
        try:
            pfull = scholarly.fill(p)
            bib = pfull.get("bib", {}) or {}
            title   = bib.get("title") or ""
            authors = _norm_authors(bib.get("author", ""))
            yearstr = str(bib.get("pub_year", "")).strip()
            year    = int(yearstr) if yearstr.isdigit() else 0
            venue   = bib.get("venue") or ""
            abstract = bib.get("abstract") or ""
            url     = pfull.get("eprint_url") or pfull.get("pub_url") or pfull.get("author_pub_url") or ""
            doi     = bib.get("doi")
            pubs.append({
                "title": title,
                "authors": authors,
                "journal": venue,
                "year": year,
                "abstract": abstract,
                "html": url,
                "doi": doi,
            })
            time.sleep(0.5)
        except Exception:
            continue

    pubs.sort(key=lambda r: (r.get("year", 0), r.get("title","")), reverse=True)

    # mark newest N as selected
    nsel = max(0, int(args.selected))
    for i, rec in enumerate(pubs):
        rec["selected"] = (i < nsel)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pubs, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    sys.exit(main())
