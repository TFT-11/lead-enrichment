"""File 3 (name-only, no domain): find the company in Apollo BY NAME -> get its domain ->
find one decision-maker -> reveal email only. Name-match guard for accuracy. Appends to apollo-found-people.csv.
"""
import csv, pathlib, re, sys, time, urllib.parse
import requests
REPO = pathlib.Path(r"C:\Users\tahaf\Project_y\repos\py-gtm")
sys.path.insert(0, str(REPO))
from core.config import key  # noqa: E402

APOLLO = key("APOLLO_USER_API_KEY")
HDR = {"X-Api-Key": APOLLO, "Content-Type": "application/json", "Cache-Control": "no-cache"}
ORGSEARCH = "https://api.apollo.io/api/v1/mixed_companies/api_search"
PSEARCH = "https://api.apollo.io/api/v1/mixed_people/api_search"
MATCH = "https://api.apollo.io/api/v1/people/match"
TITLES = ["Owner", "Founder", "Co-Founder", "Director", "Managing Director", "Partner", "Principal", "CEO", "Manager"]
SENIOR = ["owner", "founder", "partner", "c_suite", "director"]
SIZE_MIN, SIZE_MAX = 10, 300                       # ICP headcount window (firms of 10-300 employees)
SIZE_RANGES = [f"{SIZE_MIN},{SIZE_MAX}"]           # Apollo company-size filter
STOP = {"limited","ltd","llp","accountants","accountant","accounting","accountancy","services","service",
        "tax","taxation","bookkeeping","audit","auditors","the","and","co","group","uk","solutions",
        "company","consultancy","consultants","financial","finance","associates","partners"}
def toks(s): return set(t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t and t not in STOP and len(t) >= 3)

INP = pathlib.Path(r"C:\Users\tahaf\Downloads\apollo-3-company-name-only.csv")
OUT = pathlib.Path(r"C:\Users\tahaf\Downloads\apollo-found-people.csv")
rows = list(csv.DictReader(open(INP, encoding="utf-8-sig")))
found = reveals = 0
with OUT.open("a", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    for i, fm in enumerate(rows, 1):
        company = fm.get("company", "")
        first = last = title = email = estatus = li = size = domain = ""
        result = ""
        ftok = toks(company)
        try:
            r = requests.post(ORGSEARCH, headers=HDR, json={"q_organization_name": company,
                "organization_num_employees_ranges": SIZE_RANGES, "page": 1, "per_page": 1}, timeout=40)
            orgs = (r.json().get("organizations") or r.json().get("accounts") or []) if r.status_code == 200 else []
            if r.status_code != 200:
                result = f"org-search HTTP {r.status_code}"
            elif not orgs:
                result = "no org in Apollo"
            else:
                o = orgs[0]
                oname = o.get("name", "")
                if ftok and not (ftok & toks(oname)):
                    result = f"org name mismatch ('{oname[:30]}')"
                else:
                    domain = o.get("primary_domain") or urllib.parse.urlparse(o.get("website_url", "")).netloc.replace("www.", "")
                    size = o.get("estimated_num_employees", "") or ""
                    if not domain:
                        result = "org found, no domain"
                    else:
                        time.sleep(0.4)
                        ps = requests.post(PSEARCH, headers=HDR, json={"q_organization_domains": domain,
                            "person_titles": TITLES, "person_seniorities": SENIOR,
                            "organization_num_employees_ranges": SIZE_RANGES, "page": 1, "per_page": 1}, timeout=40)
                        ppl = (ps.json().get("people") or []) if ps.status_code == 200 else []
                        if not ppl:
                            result = "org ok, no person"
                        else:
                            p = ppl[0]; time.sleep(0.4)
                            m = requests.post(MATCH, headers=HDR, json={"id": p.get("id")}, timeout=40); reveals += 1
                            mp = (m.json().get("person") or {}) if m.status_code == 200 else {}
                            first = mp.get("first_name", "") or p.get("first_name", "")
                            last = mp.get("last_name", "") or p.get("last_name", "")
                            title = mp.get("title", "") or p.get("title", "")
                            email = mp.get("email", ""); estatus = mp.get("email_status", "")
                            li = mp.get("linkedin_url", "") or p.get("linkedin_url", "")
                            result = "found" if email else "person-no-email"
                            if email: found += 1
        except Exception as e:  # noqa: BLE001
            result = f"error: {str(e)[:40]}"
        w.writerow([company, first, last, title, email, estatus, li, size, domain, result])
        f.flush()
        if result == "found": print(f"[{i}] {company[:32]:<32} {first} {last} <{email}>")
        time.sleep(0.4)
print(f"\nFile 3 done: {len(rows)} firms | {found} with email | ~{reveals} reveal-credits")
