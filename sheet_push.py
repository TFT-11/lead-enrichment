"""Push the enriched master CSV into a dedicated tab of the user's Google Sheet.
Idempotent: creates the tab if missing, then overwrites it with the current CSV.
Uses the user's existing Google auth (Project_y/sheets.py, spreadsheets scope).
"""
import csv
import pathlib
import sys

sys.path.insert(0, r"C:\Users\tahaf\Project_y")
import sheets  # noqa: E402

SHEET_ID = "1Aipd4ju21_F01EVXNVz3PgTWFY8wyQilUeB39bONy5c"
TAB = "Enriched (Claude)"
CSV = pathlib.Path(r"C:\Users\tahaf\Downloads\uk-enriched-master.csv")

rows = list(csv.reader(CSV.open(encoding="utf-8-sig")))

svc = sheets.get_service()
existing = sheets.get_sheet_names(SHEET_ID)
if TAB not in existing:
    svc.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": TAB}}}]},
    ).execute()
    print(f"created tab: {TAB}")
else:
    # clear existing content so re-pushes don't leave stale rows
    svc.spreadsheets().values().clear(spreadsheetId=SHEET_ID, range=f"'{TAB}'!A1:Z1000").execute()
    print(f"tab exists, cleared: {TAB}")

sheets.write_sheet(SHEET_ID, f"'{TAB}'!A1", rows)
print(f"wrote {len(rows)} rows (incl header) to '{TAB}'")
print(f"enriched-with-decision-maker: {sum(1 for r in rows[1:] if r[3].strip())}")
print(f"with direct DM email: {sum(1 for r in rows[1:] if len(r) > 5 and r[5].strip())}")
print(f"with firm phone: {sum(1 for r in rows[1:] if r[2].strip())}")
