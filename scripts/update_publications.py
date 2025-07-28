#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_publications.py — v2.1 (fallback + proxy)
Pobiera WSZYSTKIE publikacje z Google Scholar i zapisuje do JSON na stronę.
- Fallback: jeśli search_author_id() zawiedzie, użyj search_author(NAME) + filtr afiliacji.
- Proxy (opcjonalne): SCRAPERAPI_KEY lub USE_FREE_PROXIES=true.
- Czyści 'journal'/venue (eliminuje 'CRIS PK record' itd.), usuwa duplikaty, waliduje i zapisuje meta.

Użycie (CI):
  python scripts/update_publications.py \
    --id "$SCHOLAR_USER_ID" \
    --name "$SCHOLAR_NAME" \
    --affil "$SCHOLAR_AFFIL_REGEX" \
    --out lab_website/assets/publications.json \
    --meta lab_website/assets/publications.meta.json \
    --selected 0 \
    --sleep 0.2 \
    --strict
"""
import argparse, json, time, sys, re, os, datetime
from typing import List, Dict, Any, Tuple, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from scholarly import scholarly, ProxyGenerator

# ----------------------- Proxy setup (optional) -----------------------
def maybe_setup_proxy() -> None:
    """
    Użyj proxy jeśli dostępne:
      - SCRAPERAPI_KEY -> ProxyGenerator.ScraperAPI
      - USE_FREE_PROXIES=true -> ProxyGenerator.FreeProxies()
    """
    try:
        pg = ProxyGenerator()
        key = os.getenv("SCRAPERAPI_KEY", "").strip()
        if key:
            ok = pg.ScraperAPI(key)
            if ok:
                scholarly.use_proxy(pg)
                print("[proxy] Using ScraperAPI proxy")
                return
        if os.getenv("USE_FREE_PROXIES", "").lower() in {"1","true","yes"}:
            ok = pg.FreeProxies(timeout=1, wait_time=120)
            if ok:
                scholarly.use_proxy(pg)
                print("[proxy] Using rotating FreeProxies")
                return
    except Exception as e:
        print(f"[proxy] Proxy setup failed (ignored): {e}", file=sys.stderr)

# -------------------------- Utility functions --------------------------
def _norm_authors(s: str) -> List[str]:
    if not s:
        return []
    parts = re.split(r",| and ", s)
    return [a.strip() for a in parts if a.strip()]

def _pick_venue(bib: Dict[str, Any]) -> str:
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
        return re.sub(r"\s+", " ", cand)
    return ""

def _best_url(pfull: Dict[str, Any], bib: Dict[str, Any]) -> str:
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

# -------------------------- Fetching helpers --------------------------
@retry(stop=stop_after_attempt(5),
       wait=wait_exponential(multiplier=1, min=2, max=30),
       retry=retry_if_exception_type(Exception))
def fetch_author_by_id(author_id: str) -> Dict[str, Any]:
    a = scholarly.search_author_id(author_id)
    return scholarly.fill(a, sections=["publications"])

def fetch_author_by_name(name: str, affil_regex: Optional[str]) -> Optional[Dict[str, Any]]:
    q = scholarly.search_author(name)
    rx = re.compile(affil_regex, re.I) if affil_regex else None
    for cand in q:
        try:
            filled = scholarly.fill(cand, sections=["basics"])
            affil = (filled.get("affiliation") or "")
            email = (filled.get("email_domain") or "")
            ok = True
            if rx and not (rx.search(affil) or rx.search(email or "")):
                ok = False
            if ok:
                return scholarly.fill(filled, sections=["publications"])
        except Exception:
            continue
    return None

# ------------------------------ Main ----------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="Google Scholar user id (z URL citations?user=...)")
    ap.add_argument("--name", default="", help="Imię i nazwisko autora (fallback)")
    ap.add_argument("--affil", default="", help="Regex afiliacji/domeny (fallback), np. 'pk\\.edu\\.pl|Cracow University|Politechnika Krakowska'")
    ap.add_argument("--out", required=True, help="Ścieżka JSON (np. lab_website/assets/publications.json)")
    ap.add_argument("--selected", type=int, default=0, help="Ile najnowszych oznaczyć jako selected")
    ap.add_argument("--meta", default="", help="Plik metadanych (opcjonalny)")
    ap.add_argument("--sleep", type=float, default=0.6, help="Opóźnienie [s] między zapytaniami")
    ap.add_argument("--strict", action="store_true", help="Błąd, gdy walidacja < liczby z GS")
    args = ap.parse_args()

    maybe_setup_proxy()

    author = None
    if args.id:
        try:
            author = fetch_author_by_id(args.id)
        except Exception as e:
            print(f"[warn] search_author_id failed: {e}. Falling back to name/affil...", file=sys.stderr)
    if author is None and args.name:
        author = fetch_author_by_name(args.name, args.affil)
    if author is None:
        print("[error] Nie można pobrać profilu autora ani po ID, ani po nazwisku/afiliacji.", file=sys.stderr)
        sys.exit(1)

    raw_list = author.get("publications", []) or []
    raw_count = len(raw_list)

    pubs: List[Dict[str, Any]] = []
    skipped: List[Tuple[str, str]] = []  # (reason, id/title)

    for p in raw_list:
        try:
            pfull = scholarly.fill(p)
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

    # sort malejąco: rok, tytuł
    pubs.sort(key=lambda r: (r.get("year", 0), r.get("title","")), reverse=True)

    # selected: N najnowszych
    nsel = max(0, int(args.selected))
    for i, rec in enumerate(pubs):
        rec["selected"] = (i < nsel)

    # zapis
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pubs, f, ensure_ascii=False, indent=2)

    # metadane + walidacja
    meta = {
        "method": "id" if args.id else "name+affil",
        "scholar_user_id": args.id,
        "name": args.name,
        "affil_regex": args.affil,
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "raw_count_from_scholar": raw_count,
        "written_count": len(pubs),
        "skipped_count": len(skipped),
        "skipped_reasons": skipped[:20],
    }
    if args.meta:
        with open(args.meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[update_publications] raw={raw_count}, written={len(pubs)}, skipped={len(skipped)}")
    if len(pubs) < raw_count:
        msg = "UWAGA: zapisano mniej rekordów niż zwrócił Google Scholar (patrz meta)."
        print(msg, file=sys.stderr)
        if args.strict:
            sys.exit(2)

if __name__ == "__main__":
    main()
