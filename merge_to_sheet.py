"""Merge the 500 base firms + File 1 Apollo export + File 2 Apollo results into one master,
then push to the 'Apollo-Ready' sheet tab. Apollo contact data preferred over crawl data.
"""
import csv, glob, pathlib, sys
sys.path.insert(0, r"C:\Users\tahaf\Project_y")
import sheets

D = pathlib.Path(r"C:\Users\tahaf\Downloads")
def norm(s): return (s or "").strip().upper()

base = list(csv.DictReader(open(D / "uk-apollo-ready.csv", encoding="utf-8")))
# File 1 Apollo export (most recent apollo-contacts-export*.csv)
f1file = max(glob.glob(str(D / "apollo-contacts-export*.csv")), key=lambda p: pathlib.Path(p).stat().st_mtime)
f1 = {}
for r in csv.DictReader(open(f1file, encoding="utf-8-sig")):
    if r.get("Email", "").strip():
        f1[norm(r.get("Company Name", ""))] = r
f2 = {}
for r in csv.DictReader(open(D / "apollo-found-people.csv", encoding="utf-8")):
    if r["result"] == "found":
        f2[norm(r["company"])] = r

COLS = ["company", "first_name", "last_name", "title", "email", "email_status", "linkedin",
        "company_size", "firm_phone", "domain", "contact_source", "flag"]
out = []
for b in base:
    c = norm(b["company"])
    rec = {k: "" for k in COLS}
    rec.update(company=b["company"], first_name=b.get("first_name", ""), last_name=b.get("last_name", ""),
               title=b.get("title", ""), email=b.get("email", ""), firm_phone=b.get("firm_phone", ""),
               domain=b.get("domain", ""), flag=b.get("flag", ""))
    rec["contact_source"] = "crawl" if (b.get("first_name") or b.get("last_name")) else "firm-only"
    if c in f1:
        a = f1[c]
        rec.update(first_name=a.get("First Name", ""), last_name=a.get("Last Name", ""), title=a.get("Title", ""),
                   email=a.get("Email", ""), email_status=a.get("Email Status", ""),
                   linkedin=a.get("Person Linkedin Url", ""), company_size=a.get("# Employees", ""),
                   contact_source="apollo")
    elif c in f2:
        a = f2[c]
        rec.update(first_name=a["first_name"], last_name=a["last_name"], title=a["title"], email=a["email"],
                   email_status=a["email_status"], linkedin=a["linkedin"], company_size=a["org_size"],
                   contact_source="apollo")
    out.append(rec)

OUT = D / "uk-master-final.csv"
with OUT.open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(out)

# stats
n = len(out)
full = sum(1 for r in out if r["first_name"] and r["last_name"] and r["email"])
emailed = sum(1 for r in out if r["email"])
phone = sum(1 for r in out if r["firm_phone"])
apollo = sum(1 for r in out if r["contact_source"] == "apollo")
print(f"master rows: {n} | fully-enriched (name+email): {full} | any email: {emailed} | phone: {phone} | apollo-contacts: {apollo}")

# push to sheet
SHEET = "1Aipd4ju21_F01EVXNVz3PgTWFY8wyQilUeB39bONy5c"; TAB = "Apollo-Ready"
svc = sheets.get_service()
if TAB in sheets.get_sheet_names(SHEET):
    svc.spreadsheets().values().clear(spreadsheetId=SHEET, range=f"'{TAB}'!A1:Z2000").execute()
rows = [COLS] + [[r[c] for c in COLS] for r in out]
sheets.write_sheet(SHEET, f"'{TAB}'!A1", rows)

def push_tab(tab, data):
    if tab not in sheets.get_sheet_names(SHEET):
        svc.spreadsheets().batchUpdate(spreadsheetId=SHEET, body={"requests": [{"addSheet": {"properties": {"title": tab}}}]}).execute()
    else:
        svc.spreadsheets().values().clear(spreadsheetId=SHEET, range=f"'{tab}'!A1:Z2000").execute()
    sheets.write_sheet(SHEET, f"'{tab}'!A1", [COLS] + [[r[c] for c in COLS] for r in data])

send = [r for r in out if r["email"]]
call = [r for r in out if not r["email"] and r["firm_phone"]]
push_tab("Send-Ready", send)
push_tab("Call-Ready", call)
print(f"pushed {len(rows)} to '{TAB}'. Send-Ready: {len(send)} | Call-Ready: {len(call)}. Local: {OUT}")
