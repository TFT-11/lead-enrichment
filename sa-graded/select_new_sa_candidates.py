"""Select NEW (never-assessed, never-enriched) accountancy-firm candidates for a SA province,
excluding both the in-store assessed set (the spent 408 + others) AND an outreach-sheet dedup list.

Read-only on the DB. Output columns match enrich_region_batch.py: org_key,name,suburb,province,website,phone,lane

Usage:
    python scripts/select_new_sa_candidates.py <sqlite_db> <out_csv> <PROVINCE_LIKE> <N> <exclude_json>
"""
import csv, json, pathlib, re, sqlite3, sys

TRACK = "accountancy-firms"

def norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    stop = {"the","and","co","ltd","limited","inc","incorporated","pty","accountants","accountant",
            "accounting","accountancy","chartered","ca","sa","services","tax","audit","auditors",
            "bookkeeping","bookkeepers","group","financial","finance","consulting","consultants","associates"}
    return " ".join(t for t in s.split() if t not in stop).strip()

def host_of(url):
    u = (url or "").lower().strip()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("/")[0].strip()

def main():
    db, out, prov, n, exj = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5]
    excl = json.loads(pathlib.Path(exj).read_text(encoding="utf-8"))
    ex_names = {norm_name(e["name"]) for e in excl if norm_name(e.get("name",""))}
    ex_hosts = {host_of(e["website"]) for e in excl if host_of(e.get("website",""))}

    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    like = f"%{prov}%"
    rows = c.execute(
        f"""SELECT co.org_key, co.name, co.suburb, co.province, co.website, co.phone
            FROM companies co
            WHERE co.track=? AND (co.province LIKE ? OR co.province LIKE ?)
              AND COALESCE(co.website,'')!=''
              AND co.org_key NOT IN (SELECT org_key FROM icp_assessment)
            ORDER BY (COALESCE(co.phone,'')!='') DESC, co.name""",
        (TRACK, like, like.replace("-", " "))).fetchall()

    chosen, seen_names, seen_hosts = [], set(), set()
    skipped_sheet = skipped_dup = 0
    for r in rows:
        if len(chosen) >= n:
            break
        nm, hs = norm_name(r["name"]), host_of(r["website"])
        if (nm and nm in ex_names) or (hs and hs in ex_hosts):
            skipped_sheet += 1; continue
        if (nm and nm in seen_names) or (hs and hs in seen_hosts):  # intra-pool dedup
            skipped_dup += 1; continue
        chosen.append(r)
        if nm: seen_names.add(nm)
        if hs: seen_hosts.add(hs)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["org_key","name","suburb","province","website","phone","lane"])
        for r in chosen:
            w.writerow([r["org_key"], r["name"], r["suburb"] or "", r["province"] or "",
                        r["website"] or "", r["phone"] or "", "new"])
    wphone = sum(1 for r in chosen if r["phone"])
    print(f"{prov}: pool(new,web)={len(rows)}  selected={len(chosen)}  "
          f"(skipped: {skipped_sheet} in-sheet, {skipped_dup} intra-dup)  phone-on-file={wphone}/{len(chosen)} -> {out}")
    c.close()

if __name__ == "__main__":
    main()
