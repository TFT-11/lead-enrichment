"""Apollo API runner - find ONE decision-maker per firm by domain, reveal EMAIL ONLY.
No phone, no waterfall, per_page=1 (top senior person). Appends results to apollo-found-people.csv.
Usage: apollo_run.py <input_csv>
"""
import csv
import pathlib
import sys
import time

import requests

REPO = pathlib.Path(r"C:\Users\tahaf\Project_y\repos\py-gtm")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipelines" / "accountancy-firms" / "profile"))
from core.config import key  # noqa: E402

APOLLO = key("APOLLO_USER_API_KEY")
HDR = {"X-Api-Key": APOLLO, "Content-Type": "application/json", "Cache-Control": "no-cache"}
SEARCH = "https://api.apollo.io/api/v1/mixed_people/api_search"
MATCH = "https://api.apollo.io/api/v1/people/match"
TITLES = ["Owner", "Founder", "Co-Founder", "Director", "Managing Director", "Partner", "Principal", "CEO", "Manager"]
SENIOR = ["owner", "founder", "partner", "c_suite", "director"]
SIZE_MIN, SIZE_MAX = 10, 300                       # ICP headcount window (firms of 10-300 employees)
SIZE_RANGES = [f"{SIZE_MIN},{SIZE_MAX}"]           # Apollo people-search company-size filter
INP = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(r"C:\Users\tahaf\Downloads\apollo-found-people.csv")
COLS = ["company", "first_name", "last_name", "title", "email", "email_status", "linkedin", "org_size", "domain", "result"]

rows = list(csv.DictReader(open(INP, encoding="utf-8-sig")))
new = not OUT.exists()
reveals = found = 0
with OUT.open("a", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    if new:
        w.writerow(COLS)
    for i, fm in enumerate(rows, 1):
        company, domain = fm.get("company", ""), fm.get("domain", "")
        first = last = title = email = estatus = li = size = ""
        result = ""
        if not domain:
            result = "no-domain (skipped API)"
        else:
            try:
                r = requests.post(SEARCH, headers=HDR, json={"q_organization_domains": domain,
                    "person_titles": TITLES, "person_seniorities": SENIOR,
                    "organization_num_employees_ranges": SIZE_RANGES,  # only firms of SIZE_MIN-SIZE_MAX staff
                    "page": 1, "per_page": 1}, timeout=40)
                if r.status_code != 200:
                    result = f"search HTTP {r.status_code}"
                else:
                    ppl = r.json().get("people", []) or []
                    if not ppl:
                        result = "no person in Apollo"
                    else:
                        p = ppl[0]
                        time.sleep(0.5)
                        m = requests.post(MATCH, headers=HDR, json={"id": p.get("id")}, timeout=40)
                        reveals += 1
                        mp = (m.json().get("person") or {}) if m.status_code == 200 else {}
                        org = mp.get("organization") or p.get("organization") or {}
                        first = mp.get("first_name", "") or p.get("first_name", "")
                        last = mp.get("last_name", "") or p.get("last_name", "")
                        title = mp.get("title", "") or p.get("title", "")
                        email = mp.get("email", "")
                        estatus = mp.get("email_status", "")
                        li = mp.get("linkedin_url", "") or p.get("linkedin_url", "")
                        size = org.get("estimated_num_employees", "") or ""
                        result = "found" if email else "person-no-email"
                        if email:
                            found += 1
            except Exception as e:  # noqa: BLE001
                result = f"error: {str(e)[:40]}"
        w.writerow([company, first, last, title, email, estatus, li, size, domain, result])
        f.flush()
        if i % 10 == 0 or result == "found":
            print(f"[{i}/{len(rows)}] {company[:34]:<34} | {result} | {(first+' '+last).strip()} {('<'+email+'>') if email else ''}")
        time.sleep(0.4)

print(f"\nDONE {INP.name}: {len(rows)} firms | {found} with email | ~{reveals} reveal-credits used")
