"""Select a region's accountancy-firm candidates from the sourcing store -> candidates CSV.

Companion to scripts/enrich_region_batch.py. Pulls firms for a target province/region, prioritising those
already graded `in_icp`, then topping up with the best-seeded (website/phone-present) assessed-or-raw firms.

Output columns match what enrich_region_batch.py expects: org_key,name,suburb,province,website,phone,lane

Usage:
    python scripts/select_region_candidates.py <sqlite_db> <out_candidates_csv> <PROVINCE_LIKE> <N>

    <PROVINCE_LIKE>  a substring matched against companies.province (case-insensitive), e.g. "KwaZulu".
                     Handles spelling variants automatically (KwaZulu-Natal / KwaZulu Natal).
    <N>              total firms to select (in_icp first, then top-ups).

Example (KwaZulu-Natal, 100 firms, from the shared snapshot):
    python scripts/select_region_candidates.py \
        ~/Downloads/sourcing-snapshot-copy.db data/lists/kzn_candidates.csv KwaZulu 100

NB: the canonical worker DB is data/sourcing.db (synced from Neon — see docs/CONTINUE-ENRICHMENT.md).
For a one-off pull you may point at any snapshot copy. This script only READS the DB.
"""
import csv
import pathlib
import sqlite3
import sys

TRACK = "accountancy-firms"


def main():
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)
    db_path, out_path, prov_like, n = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    like = f"%{prov_like}%"
    GEO = "(co.province LIKE ? OR co.province LIKE ?)"
    # KwaZulu-Natal vs "KwaZulu Natal" — match both by also trying a de-hyphenated variant
    args = (like, like.replace("-", " "))
    cols = "co.org_key, co.name, co.suburb, co.province, co.website, co.phone"

    inicp = c.execute(
        f"""SELECT {cols} FROM companies co JOIN icp_assessment a ON co.org_key = a.org_key
            WHERE co.track = ? AND a.status = 'in_icp' AND {GEO}
            ORDER BY (co.website != '') DESC, (co.phone != '') DESC, co.name""",
        (TRACK, *args)).fetchall()
    chosen = list(inicp[:n])
    chosen_keys = {r["org_key"] for r in chosen}

    if len(chosen) < n:                                  # top up with best-seeded non-in_icp firms
        topup = c.execute(
            f"""SELECT {cols} FROM companies co LEFT JOIN icp_assessment a ON co.org_key = a.org_key
                WHERE co.track = ? AND {GEO}
                  AND COALESCE(a.status,'') NOT IN ('in_icp','out_of_icp','wrong_icp_now')
                  AND co.website != ''
                ORDER BY (co.phone != '') DESC, co.name""",
            (TRACK, *args)).fetchall()
        for r in topup:
            if len(chosen) >= n:
                break
            if r["org_key"] not in chosen_keys:
                chosen.append(r); chosen_keys.add(r["org_key"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_inicp = min(len(inicp), n)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["org_key", "name", "suburb", "province", "website", "phone", "lane"])
        for i, r in enumerate(chosen):
            lane = "in_icp" if i < n_inicp else "topup"
            w.writerow([r["org_key"], r["name"], r["suburb"] or "", r["province"] or "",
                        r["website"] or "", r["phone"] or "", lane])
    wsite = sum(1 for r in chosen if r["website"])
    wphone = sum(1 for r in chosen if r["phone"])
    print(f"selected {len(chosen)} firms ({n_inicp} in_icp + {len(chosen) - n_inicp} top-up) -> {out_path}")
    print(f"  website on file: {wsite}/{len(chosen)} | phone on file: {wphone}/{len(chosen)}")


if __name__ == "__main__":
    main()
