#!/usr/bin/env python3
"""
update_publications.py
=======================

This script automates the retrieval of publications from Google Scholar for a
given author and writes the results to `assets/publications.json`. The output
file is consumed by the website's JavaScript to display selected and full
publication lists. Because Google does not provide an official API for Google
Scholar【529967508265334†L203-L210】, this script relies on the third‑party
library `scholarly` to perform web scraping. You must install `scholarly`
before running the script, for example via:

    pip install scholarly

Usage:
    python3 update_publications.py --id <GOOGLE_SCHOLAR_ID> [--selected N]

Arguments:
    --id        The Google Scholar author identifier (the `user` query
                parameter from the profile URL).
    --selected  Number of most recent publications to flag as selected
                (default: 3). Selected publications are highlighted on the
                homepage.

The script writes JSON output with keys: title, authors, journal, year,
abstract, url and selected.
"""
import argparse
import json
import os
import sys

try:
    from scholarly import scholarly
except ImportError:
    sys.stderr.write(
        "Error: The 'scholarly' library is not installed. Install it using 'pip install scholarly' and retry.\n"
    )
    sys.exit(1)


def fetch_publications(author_id: str, selected_count: int = 3):
    """Fetch publications for a given Google Scholar author ID.

    Parameters
    ----------
    author_id : str
        The Google Scholar author identifier.
    selected_count : int
        The number of publications to mark as selected.

    Returns
    -------
    List[dict]
        A list of publication dictionaries sorted by year descending.
    """
    try:
        author = scholarly.search_author_id(author_id)
        author = scholarly.fill(author, sections=["publications"])
    except Exception as exc:
        sys.stderr.write(f"Failed to retrieve author data: {exc}\n")
        return []

    publications = []
    for pub_entry in author.get("publications", []):
        try:
            pub = scholarly.fill(pub_entry)
        except Exception:
            # Skip any publications that cannot be retrieved
            continue
        bib = pub.get("bib", {})
        title = bib.get("title")
        authors_field = bib.get("author", "")
        authors = [a.strip() for a in authors_field.split(" and ")] if authors_field else []
        journal = bib.get("venue")
        year_str = bib.get("pub_year")
        try:
            year = int(year_str) if year_str is not None else None
        except ValueError:
            year = None
        abstract = bib.get("abstract")
        url = pub.get("pub_url") or pub.get("eprint_url")
        publications.append({
            "title": title,
            "authors": authors,
            "journal": journal,
            "year": year,
            "abstract": abstract,
            "url": url
        })
    # Sort by year descending
    publications.sort(key=lambda x: x.get("year", 0), reverse=True)
    # Mark selected publications
    for idx, p in enumerate(publications):
        p["selected"] = idx < selected_count
    return publications


def main():
    parser = argparse.ArgumentParser(description="Update the publications JSON file from Google Scholar")
    parser.add_argument("--id", required=True, help="Google Scholar author ID")
    parser.add_argument("--selected", type=int, default=3, help="Number of selected publications")
    args = parser.parse_args()

    pubs = fetch_publications(args.id, args.selected)
    if not pubs:
        sys.stderr.write("No publications were retrieved. Aborting update.\n")
        sys.exit(1)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "publications.json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(pubs, f, ensure_ascii=False, indent=2)
        print(f"Successfully wrote {len(pubs)} publications to {output_path}")
    except Exception as exc:
        sys.stderr.write(f"Failed to write JSON file: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()