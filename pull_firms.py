"""Expand the UK accountancy-firm candidate pool from Companies House (more pages per SIC).
Writes a larger deduped CSV so we can reach ~500 named accountancy firms to enrich.
"""
import csv
import pathlib
import sys

REPO = pathlib.Path(r"C:\Users\tahaf\Project_y\repos\py-gtm")
sys.path.insert(0, str(REPO))
from core.lib.companies_house import search_sic  # noqa: E402

SICS = {"69201": "accounting/audit", "69202": "bookkeeping", "69203": "tax"}
OUT = pathlib.Path(r"C:\Users\tahaf\Downloads\uk-firms-expanded.csv")
ACCY = ("ACCOUNT", "TAX", "BOOKKEEP", "CHARTERED", "AUDIT")
SKIP = ("UMBRELLA", "LABOUR", "PAYROLL SERV", "LEGAL", "PROPERTY", "REMEDIATION")

seen = {}
for sic, label in SICS.items():
    n = 0
    for rec in search_sic([sic], size=100, max_pages=7, status="active"):  # ~700/SIC
        cn = rec.get("company_number") or rec["name"]
        n += 1
        if cn not in seen:
            seen[cn] = rec
    print(f"  SIC {sic} ({label}): pulled {n}")

rows = list(seen.values())
named = [r for r in rows if any(k in r["name"].upper() for k in ACCY) and not any(s in r["name"].upper() for s in SKIP)]
cols = ["name", "company_number", "sic", "region", "status", "location"]
with OUT.open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in named:
        w.writerow({c: r.get(c, "") for c in cols})

print(f"\nUNIQUE firms: {len(rows)} | accountancy-named (enrichment pool): {len(named)}")
print(f"written: {OUT}")
