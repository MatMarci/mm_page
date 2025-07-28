#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_publications.py — v2.2 (fast mode + partial abstracts + proxy)
- Pobiera WSZYSTKIE publikacje z Google Scholar dla danego autora.
- Abstrakty/DOI dociąga tylko dla N najnowszych (parametr --abstracts, domyślnie 8) => szybciej, mniejsze ryzyko timeoutu.
- Czyści 'journal'/venue (eliminuje wpisy typu 'CRIS PK record'), usuwa duplikaty, waliduje i zapisuje meta.
- Fallback (opcjonalny): jeśli ID zawiedzie, szuka po nazwisku + regexie afiliacji.
- Proxy (opcjonalne): SCRAPERAPI_KEY lub USE_FREE_PROXIES=true.

Użycie (CI):
  python scripts/update_publications.py \
    --id "$SCHOLAR_USER_ID" \
    --out lab_website/assets/publications.json \
    --meta lab_website/assets/publications.meta.json \
    --selected 0 \
    --abstracts 8 \
    --sleep 0.2 \
    --strict
"""
import argparse, json, time, sys, re, os, datetime
from typing import List, Dict, Any, Tuple, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from scholarly import scholarly, ProxyGenerator

# ---------- Proxy (opcjonalnie) ----------
def maybe_setup_proxy() -> None:
    try:
        pg = ProxyGenerator()
        key = os.getenv("SCRAPERAPI_KEY", "").strip()
        if key:
            if pg.ScraperAPI(key):
                scholarly.use_proxy(pg); print("[proxy] Using ScraperAPI proxy"); return
        if os.getenv("USE_FREE_PROXIES", "").lower() in {"1","true","yes"}:
            if pg.FreeProxies(timeout=1, wait_time=120):
                scholarly.use_proxy(pg); print("[proxy] Using rotating FreeProxies"); return
    except Exception as e:
        print(f"[proxy] Proxy setup failed (ignored): {e}", file=sys.stderr)

# ---------- Utils ----------
def _norm_authors(s: str) -> List[str]:
    if not s: return []
    parts = re.split(r",| and ", s)
    return [a.strip() for a in parts if a.strip()]

def _pick_venue(bib: Dict[str, Any]) -> str:
    candidates = [(bib.get("journal") or "").strip(),
                  (bib.get("venue") or "").strip(),
                  (bib.get("conference") or "").strip()]
    bad = ["cris pk","– cris record","- cris record","cris record","repository","repozytorium","record"]
    for cand in candidates:
        if not cand: continue
        low = cand.lower()
        if any(tok in low for tok in bad): continue
        return re.sub(r"\s+"," ",cand)
    return ""

def _best_url(pfull: Dict[str, Any], bib: Dict[str, Any]) -> str:
    doi = (bib.get("doi") or "").strip()
    if doi:
        d = doi.lower()
        if d.startswith("https://doi.org/"): return doi
        if d.startswith("10."): return f"https://doi.org/{doi}"
    for key in ("eprint_url","pub_url","author_pub_url"):
        u = pfull.get(key)
        if u: return u
    return ""

def _year_int(bib: Dict[str, Any]) -> int:
    y = str(bib.get("pub_year","")).strip()
    return int(y) if y.isdigit() else 0

# ---------- Fetch ----------
@retry(stop=stop_after_attempt(4),
       wait=wait_exponential(multiplier=1, min=1, max=20),
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
            if rx and not (rx.search(affil) or rx.search(email or "")): continue
            return scholarly.fill(filled, sections=["publications"])
        except Exception:
            continue
    return None

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="Google Scholar user id (z URL citations?user=...)")
    ap.add_argument("--name", default="", help="Imię i nazwisko (fallback)")
    ap.add_argument("--affil", default="", help="Regex afiliacji/domeny (fallback)")
    ap.add_argument("--out", required=True, help="Ścieżka JSON (np. lab_website/assets/publications.json)")
    ap.add_argument("--selected", type=int, default=0, help="Ile najnowszych oznaczyć jako selected")
    ap.add_argument("--meta", default="", help="Plik metadanych (opcjonalny)")
    ap.add_argument("--sleep", type=float, default=0.4, help="Opóźnienie [s] między zapytaniami")
    ap.add_argument("--strict", action="store_true", help="Błąd, gdy walidacja < liczby z GS")
    ap.add_argument("--abstracts", type=int, default=8, help="Ilu najnowszym publikacjom dociągnąć abstrakt/DOI (0=bez)")
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

    # mapuj tytuł -> oryginalny obiekt publikacji (ułatwia dociąganie szczegółów po sortowaniu)
    title2pub = {}
    for p in raw_list:
        bib = p.get("bib", {}) or {}
        title = (bib.get("title") or "").strip()
        if title and title not in title2pub:
            title2pub[title] = p

    # szybka lista bazowa (bez fill() dla wszystkich)
    base = []
    for p in raw_list:
        bib = p.get("bib", {}) or {}
        title = (bib.get("title") or "").strip()
        if not title: continue
        base.append({
            "title": title,
            "authors": _norm_authors(bib.get("author","")),
            "journal": _pick_venue(bib),
            "year": _year_int(bib),
            "abstract": "",
            "html": "",
            "doi": None
        })

    # posortuj po (rok, tytuł)
    base.sort(key=lambda r: (r.get("year",0), r.get("title","")), reverse=True)

    # dociągaj szczegóły tylko dla N najnowszych
    enrich_n = max(0, int(args.abstracts))
    enriched = 0
    pubs = []
    for i, rec in enumerate(base):
        out = dict(rec)
        if i < enrich_n:
            p = title2pub.get(rec["title"])
            if p:
                try:
                    pfull = scholarly.fill(p)
                    bpf = pfull.get("bib", {}) or {}
                    out["abstract"] = (bpf.get("abstract") or "").strip()
                    if not out["journal"]:
                        out["journal"] = _pick_venue(bpf)
                    out["html"] = _best_url(pfull, bpf)
                    out["doi"] = (bpf.get("doi") or None)
                    enriched += 1
                except Exception:
                    pass
            time.sleep(max(0.0, args.sleep))
        pubs.append(out)

    # deduplikacja po (tytuł, rok)
    seen = set(); dedup = []
    for r in pubs:
        key = (r["title"].strip().lower(), r.get("year",0))
        if key in seen: continue
        seen.add(key); dedup.append(r)
    pubs = dedup

    # selected: N najnowszych
    nsel = max(0, int(args.selected))
    for i, rec in enumerate(pubs):
        rec["selected"] = (i < nsel)

    # zapis
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pubs, f, ensure_ascii=False, indent=2)

    # meta + walidacja
    meta = {
        "method": "id" if args.id else "name+affil",
        "timestamp_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "raw_count_from_scholar": raw_count,
        "written_count": len(pubs),
        "enriched_abstracts": enriched,
        "abstracts_requested": enrich_n
    }
    if args.meta:
        with open(args.meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[update_publications] raw={raw_count}, written={len(pubs)}, enriched={enriched}/{enrich_n}")
    if len(pubs) < raw_count:
        msg = "UWAGA: zapisano mniej rekordów niż zwrócił Google Scholar (część pustych/bez tytułu odrzucona)."
        print(msg, file=sys.stderr)
        if args.strict:
            sys.exit(2)

if __name__ == "__main__":
    main()
