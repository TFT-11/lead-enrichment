"""Build a clean 3-tab Google Sheet (All Firms / Send-Ready / Call-Ready) from a master CSV.
Writes in RAW mode so '+44...' phone numbers stay text and don't become #ERROR! formulas.
Usage: make_clean_sheet.py [master_csv]   (default: Downloads/uk-master-final.csv)
"""
import csv, pathlib, sys
sys.path.insert(0, r"C:\Users\tahaf\Project_y")   # for sheets.py (Google auth)
import sheets

MASTER = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(r"C:\Users\tahaf\Downloads\uk-master-final.csv")
rows = list(csv.reader(open(MASTER, encoding="utf-8-sig")))
hdr, data = rows[0], rows[1:]
ei, pi = hdr.index("email"), hdr.index("firm_phone")
allr = [hdr] + data
send = [hdr] + [r for r in data if r[ei].strip()]
call = [hdr] + [r for r in data if not r[ei].strip() and r[pi].strip()]
svc = sheets.get_service()
sh = svc.spreadsheets().create(body={"properties": {"title": "Accountancy Leads - FINAL"},
    "sheets": [{"properties": {"title": "All Firms"}}, {"properties": {"title": "Send-Ready (email)"}},
               {"properties": {"title": "Call-Ready (phone)"}}]}).execute()
sid = sh["spreadsheetId"]
def raw(tab, vals):  # RAW so leading '+' in phones isn't parsed as a formula
    svc.spreadsheets().values().update(spreadsheetId=sid, range=f"'{tab}'!A1",
        valueInputOption="RAW", body={"values": vals}).execute()
raw("All Firms", allr); raw("Send-Ready (email)", send); raw("Call-Ready (phone)", call)
print("URL:", sh["spreadsheetUrl"])
print(f"All:{len(allr)-1} Send:{len(send)-1} Call:{len(call)-1}")
