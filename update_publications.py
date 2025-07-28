#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_publications.py  — v2
--------------------------------
Pobiera WSZYSTKIE publikacje z Google Scholar dla danego autora i zapisuje je
do pliku JSON używanego przez stronę. Dodatkowo:
- normalizuje nazwę czasopisma/konferencji (unika wpisów typu "CRIS PK record"),
- eliminuje duplikaty,
- waliduje zgodność liczby pozycji: ile Scholar zwrócił vs ile zapisano,
- opcjonalnie tryb --strict: w razie rozbieżności kończy workflow kodem != 0,
- zapisuje metadane pobrania do pliku *.meta.json.

Użycie:
  python scripts/update_publications.py \
      --id RZAgZ88AAAAJ \
      --out lab_website/assets/publications.json \
      --selected 0 \
      --meta lab_website/assets/publications.meta.json \
      --strict
"""
import argparse, json, time, sys, re, datetime
from typing import List, Dict, Any, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from scholarly import scholarly


# -------------------------- Utility functions --------------------------

def _norm_authors(s: str) -> List[str]:
    """Rozbija łańcuch autorów Scholar na listę nazwisk."""
    if not s:
        return []
    parts = re.split(r",| and ", s)
    return [a.strip() for a in parts if a.strip()]

def _pick_venue(bib: Dict[str, Any]) -> str:
    """
    Preferencje pól: 'journal' > 'venue' > 'conference'.
    Odrzuca wpisy zawierające słowa kluczowe wskazujące na rekordy repozytoriów/CRIS.
    """
    candidates = [
        (bib.get("journal") or "").strip(),
        (bib.get("venue") or "").strip(),
        (bib.get("conference") or "").strip(),
    ]
    bad_tokens = [
        "cris pk", "cracow university of technology – cris record",
        "cracow university of technology - cris record", "cris record",
        "repository", "repozytorium", "record"
    ]
    for cand in candidates:
        if not cand:
            continue
        low = cand.lower()
        if any(tok in low for tok in bad_tokens):
            continue
        return re.sub(r"\s+", " ", cand)  # porządkuje wielokrotne spacje
    return ""

def _best_url(pfull: Dict[str, Any], bib: Dict[str, Any]) -> str:
    """Zwraca preferowany URL: DOI > eprint_url > pub_url > author_pub_url."""
    doi = (bib.get("doi") or "").strip()
    if doi:
        d = doi.lower()
        if d.startswith("https://doi.org/"):
            return doi
        if d.startswith("10."):
            return f"https://doi.org/{doi}"
    for key in ("eprint_url", "pub_url", "author_pub_url"):
        u = pfull.get(key)
        if u:
            return u
    return ""

def _year_int(bib: Dict[str, Any]) -> int:
    y = str(bib.get("pub_year", "")).strip()
    return int(y) if y.isdigit() else 0


# -------------------------- Fetching --------------------------

@retry(stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=1, min=2, max=30),
       retry=retry_if_exception_type(Exception))
def fetch_author(author_id: str) -> Dict[str, Any]:
    a = scholarly.search_author_id(author_id)
    return scholarly.fill(a, sections=["publications"])

def fill_publication(pub: Dict[str, Any]) -> Dict[str, Any]:
    return scholarly.fill(pub)


# -------------------------- Main --------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="Google Scholar user id (z URL citations?user=...)")
    ap.add_argument("--out", required=True, help="Ścieżka JSON z publikacjami (np. lab_website/assets/publications.json)")
    ap.add_argument("--selected", type=int, default=0, help="Ile najnowszych oznaczyć jako selected")
    ap.add_argument("--meta", default="", help="Opcjonalny plik metadanych (np. lab_website/assets/publications.meta.json)")
    ap.add_argument("--sleep", type=float, default=0.5, help="Opóźnienie [s] między zapytaniami")
    ap.add_argument("--strict", action="store_true", help="Przerwij z błędem gdy walidacja się nie zgadza")
    args = ap.parse_args()

    author = fetch_author(args.id)
    print('author: ', author)
    raw_list = author.get("publications", []) or []
    raw_count = len(raw_list)

    pubs: List[Dict[str, Any]] = []
    skipped: List[Tuple[str, str]] = []  # (reason, id/title)

    for p in raw_list:
        try:
            pfull = fill_publication(p)
            bib = pfull.get("bib", {}) or {}
            title = (bib.get("title") or "").strip()
            if not title:
                skipped.append(("no_title", str(pfull.get("author_pub_id"))))
                continue
            authors = _norm_authors(bib.get("author", ""))
            year    = _year_int(bib)
            venue   = _pick_venue(bib)
            abstract = (bib.get("abstract") or "").strip()
            url     = _best_url(pfull, bib)
            doi     = (bib.get("doi") or None)
            rec = {
                "title": title,
                "authors": authors,
                "journal": venue,
                "year": year,
                "abstract": abstract,
                "html": url,
                "doi": doi,
            }
            pubs.append(rec)
            time.sleep(max(0.0, args.sleep))
        except Exception as e:
            skipped.append(("exception", str(e)))

    # deduplikacja po (tytuł lower, rok)
    seen = set()
    deduped = []
    for r in pubs:
        key = (r["title"].strip().lower(), r.get("year", 0))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    pubs = deduped

    # sortowanie malejąco po roku, potem tytule
    pubs.sort(key=lambda r: (r.get("year", 0), r.get("title", "")), reverse=True)

    # oznacz 'selected' dla N najnowszych
    nsel = max(0, int(args.selected))
    for i, rec in enumerate(pubs):
        rec["selected"] = (i < nsel)

    # zapis JSON
    out_path = args.out
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pubs, f, ensure_ascii=False, indent=2)

    # walidacja i metadane
    result = {
        "scholar_user_id": args.id,
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "raw_count_from_scholar": raw_count,
        "written_count": len(pubs),
        "skipped_count": len(skipped),
        "skipped_reasons": skipped[:20],  # skrótowo
    }

    if args.meta:
        with open(args.meta, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    # krótkie podsumowanie w logu
    print(f"[update_publications] Scholar raw: {raw_count}, written: {len(pubs)}, skipped: {len(skipped)}")
    if len(pubs) < raw_count:
        msg = "UWAGA: liczba zapisanych publikacji < liczby z Google Scholar (szczegóły w meta)."
        print(msg, file=sys.stderr)
        if args.strict:
            sys.exit(2)

if __name__ == "__main__":
    main()
