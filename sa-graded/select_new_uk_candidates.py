"""Select NEW UK accountancy-firm candidates from Companies House, INGEST them into the store, and emit a
candidates CSV for enrich_new_sa_batch.py (REGION=UK) — so UK firms flow through Dean's SAME engine
(crawl -> extract_profile -> select.py RUBRIC grade [size ~5-200] -> extract_people) as the SA firms.

This is the piece that makes UK match Dean: his grade reads the `companies` table, so Companies House
firms must be loaded into the store first (Companies House gives no website — Places resolves it at the
enrich step, exactly like SA phone-only firms).

Usage:
    python scripts/select_new_uk_candidates.py <out_candidates_csv> <N> <exclude_json> [max_pages]

    <exclude_json>  [{"name": "...", "website": "...", "province": "..."}, ...] of already-worked UK firms
                    (export your uk-master-final.csv to this shape). Pass a path to an empty [] if none.
    <max_pages>     Companies House pages per SIC (100/page, default 5 ~= 1500/SIC before name-filter).
"""
import csv, json, pathlib, re, shutil, sys

REPO = pathlib.Path("C:/Users/tahaf/Project_y/repos/py-gtm")  # <- edit to your py-gtm clone
sys.path[:0] = [str(REPO)]

from core.store import Store                       # noqa: E402
from core.lib.companies_house import search_sic    # noqa: E402
from core.contract import normalize_company        # noqa: E402

SNAPSHOT = pathlib.Path.home() / "Downloads" / "sourcing-snapshot-copy.db"
WORKDB = REPO / "data" / "sourcing.db"
ICP_ID = "accountancy-firms-partnership"
SICS = ["69201", "69202", "69203"]                 # accounting/audit, bookkeeping, tax
ACCY = ("ACCOUNT", "TAX", "BOOKKEEP", "CHARTERED", "AUDIT")
SKIP = ("UMBRELLA", "LABOUR", "PAYROLL SERV", "LEGAL", "PROPERTY", "REMEDIATION", "RECRUIT")


def host_of(url):
    u = re.sub(r"^https?://", "", (url or "").lower().strip())
    return re.sub(r"^www\.", "", u).split("/")[0]


def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    out = pathlib.Path(sys.argv[1]); n = int(sys.argv[2]); exj = pathlib.Path(sys.argv[3])
    max_pages = int(sys.argv[4]) if len(sys.argv) > 4 else 5

    excl = json.loads(exj.read_text(encoding="utf-8-sig")) if exj.exists() else []
    ex_names = {normalize_company(e["name"]) for e in excl if normalize_company(e.get("name", ""))}
    ex_hosts = {host_of(e.get("website", "")) for e in excl if host_of(e.get("website", ""))}

    if not WORKDB.exists():                          # working DB provides the schema + engine tables
        WORKDB.parent.mkdir(parents=True, exist_ok=True)
        print(f"  seeding working DB from snapshot -> {WORKDB}")
        shutil.copy2(SNAPSHOT, WORKDB)
    st = Store(str(WORKDB))

    # 1) pull + name-filter Companies House
    recs, seen = [], set()
    for r in search_sic(SICS, max_pages=max_pages, status="active"):
        up = r["name"].upper()
        if not any(k in up for k in ACCY) or any(s in up for s in SKIP):
            continue
        key = r.get("company_norm") or normalize_company(r["name"])
        if not key or key in seen:
            continue
        seen.add(key)
        parts = [p.strip() for p in (r.get("location") or "").split(",") if p.strip()]
        r["company_norm"] = key
        r["suburb"] = parts[0] if parts else ""
        r["province"] = parts[1] if len(parts) > 1 else r.get("region", "GB")
        recs.append(r)

    # 2) ingest into the store (org_key = company_norm, since CH has no domain yet)
    ingested = st.ingest_companies(recs, track="accountancy-firms")

    # 3) select NEW ones: not already ICP-assessed, not in the worked-exclusion list
    chosen, skipped_sheet, skipped_assessed = [], 0, 0
    for r in recs:
        if len(chosen) >= n:
            break
        ok = r["company_norm"]
        if ok in ex_names:
            skipped_sheet += 1; continue
        if st.get_icp_assessment(ok, ICP_ID) is not None:
            skipped_assessed += 1; continue
        chosen.append(r)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["org_key", "name", "suburb", "province", "website", "phone", "lane"])
        for r in chosen:
            # website/phone left blank on purpose — enrich_new_sa_batch resolves them via Google Places (+44)
            w.writerow([r["company_norm"], r["name"], r.get("suburb", ""), r.get("province", ""), "", "", "uk-new"])
    print(f"UK: CH firms (accountancy-named) = {len(recs)} | ingested = {ingested} | "
          f"selected NEW = {len(chosen)} (skipped {skipped_sheet} worked, {skipped_assessed} already-assessed)")
    print(f"  -> {out}  (websites blank; Places resolves them at enrich)")
    st.close()


if __name__ == "__main__":
    main()
