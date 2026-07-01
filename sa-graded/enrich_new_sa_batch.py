"""Full SA accountancy-firm enrichment for NEW (ungraded) firms — composes Dean's ACTUAL pipeline
stages end-to-end, INCLUDING the qualify/grade (size) stage that the region scripts skip:

  per firm:  on-file website (Google Places fallback) -> entity guard
             -> crawl_one (Dean's deep crawl)
             -> extract_profile PROMPT_TEMPLATE + PROFILE_SCHEMA via OpenAI -> persist(firm_profile)   [PROFILE]
  then:      select.py RUBRIC LLM grade over the just-profiled firms -> icp_assessment                 [GRADE/SIZE]
  then:      extract_people_from_md on graded-IN firms (in_icp/later_prospect) -> decision-makers      [CONTACTS]
  -> contact-level master CSV (+ grade score/status/reason + team_size_signal).

Writes firm_profile + icp_assessment to a LOCAL working DB copy (data/sourcing.db, seeded from the
snapshot); never touches Neon or the shared sheet. OpenAI only (gpt-5.4-mini); Google Places free-tier
fallback. No Apollo/Hunter. Verification of the OUTPUT is a separate mandatory step (repo hard rule).

Usage:
    OPENAI_PROFILE=1 python scripts/enrich_new_sa_batch.py <candidates_csv> <out_master_csv> <REGION> [START] [N]
"""
import csv, os, pathlib, shutil, sys, urllib.parse

REPO = pathlib.Path("C:/Users/tahaf/Project_y/repos/py-gtm")  # <- edit to your py-gtm clone
sys.path[:0] = [str(REPO), str(REPO / "scripts"),
                str(REPO / "pipelines" / "accountancy-firms"),
                str(REPO / "pipelines" / "accountancy-firms" / "profile")]

os.environ.setdefault("OPENAI_PROFILE", "1")     # force the OpenAI API profile path (not codex)

from core.store import Store                                                  # noqa: E402
from crawl_sites import crawl_one                                            # noqa: E402
from extract_people import extract_people_from_md, _live_llm                 # noqa: E402
import extract_profile as ep                                                 # noqa: E402
from enrich.select import load_candidates, select, default_judge, ICP_ID     # noqa: E402
# reuse the region script's site resolver + entity guard (Dean's KZN-proven helpers)
from enrich_region_batch import resolve, entity_check                        # noqa: E402

SNAPSHOT = pathlib.Path.home() / "Downloads" / "sourcing-snapshot-copy.db"
WORKDB = REPO / "data" / "sourcing.db"


def ensure_workdb():
    if not WORKDB.exists():
        WORKDB.parent.mkdir(parents=True, exist_ok=True)
        print(f"  seeding working DB from snapshot -> {WORKDB}")
        shutil.copy2(SNAPSHOT, WORKDB)


def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    cand_csv = pathlib.Path(sys.argv[1]); master = pathlib.Path(sys.argv[2]); region = sys.argv[3].upper()
    start = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 10_000
    bypass = os.environ.get("ENTITY_BYPASS") == "1"

    ensure_workdb()
    st = Store(str(WORKDB))
    firms = list(csv.DictReader(cand_csv.open(encoding="utf-8-sig")))
    batch = firms[start - 1:start - 1 + n]
    print(f"{region} NEW-firm enrichment, firms {start}..{start + len(batch) - 1} of {len(firms)}\n")

    # ---------- PASS 1: resolve -> crawl -> profile (firm_profile) ----------
    md_cache, info = {}, {}
    for off, fm in enumerate(batch):
        gi = start + off
        ok = fm["org_key"]; name = fm["name"]
        loc = fm.get("suburb") or fm.get("province") or ""
        web = (fm.get("website") or "").strip(); phone = (fm.get("phone") or "").strip()
        if not web or not phone:
            rw = resolve(name, loc, region); web = web or rw.get("website", ""); phone = phone or rw.get("phone", "")
        host = urllib.parse.urlparse(web).netloc.replace("www.", "") or web if web else ""
        flag = ""
        if host:
            est, enote = entity_check(name, host, region)
            if est in ("foreign", "mismatch") and not bypass:
                flag = "WRONG-ENTITY RISK: " + enote
        md = ""
        if host and not flag:
            try:
                md, pages, cat, code = crawl_one(host)
            except Exception as e:  # noqa: BLE001
                flag = f"crawl error: {str(e)[:60]}"
        prof_status = ""
        if md and md.strip():
            content = ep.clean_md(md)
            prompt = ep.PROMPT_TEMPLATE.replace("{content}", content)
            profile, et, em = ep._profile_llm(prompt, ep.PROFILE_SCHEMA)
            if profile is not None:
                ep.persist(st, ok, profile, web)
                prof_status = "is_firm" if profile.get("is_firm") else "NOT-FIRM"
            else:
                flag = flag or f"profile error: {et} {em[:40]}"
        elif not flag:
            flag = "no crawl content - phone only"
        md_cache[ok] = md
        info[ok] = {"name": name, "province": fm.get("province", ""), "suburb": loc,
                    "website": host, "phone": phone, "flag": flag, "prof": prof_status}
        print(f"[{gi}] {name[:34]:<34} | {host or '-':<26} | profile={prof_status or flag[:24]}")

    # ---------- PASS 2: GRADE (Dean's select.py RUBRIC; size is dimension #4) ----------
    print("\n== GRADE (select.py RUBRIC, gpt-5.4-mini) ==")
    batch_keys = {fm["org_key"] for fm in batch}
    judge_fn, backend = default_judge()
    cands = [c for c in load_candidates(st) if c["org_key"] in batch_keys]   # only this batch's profiled firms
    res = select(st, judge_fn, top_n=len(cands) or 1, candidates=cands, workers=4, resume=True,
                 db_path=str(WORKDB))
    print(f"  graded={res['scored']} skipped={res['skipped']} in_icp={res['in_icp']}")

    grade = {}
    for ok in batch_keys:
        row = st.get_icp_assessment(ok, ICP_ID)
        if row:
            grade[ok] = (row["status"], row["score"] or 0.0, (row["reasoning"] or "")[:200])

    # ---------- PASS 3: CONTACTS on graded-IN firms ----------
    print("\n== CONTACTS (extract_people on in_icp/later_prospect) ==")
    header = ["firm", "province", "suburb", "website", "firm_phone", "grade_status", "grade_score",
              "team_size", "is_firm", "decision_maker", "dm_title", "dm_email", "other_dms",
              "grade_reason", "flag"]
    n_dm = n_email = n_kept = 0
    with master.open("w", newline="", encoding="utf-8") as out:
        w = csv.writer(out); w.writerow(header)
        for fm in batch:
            ok = fm["org_key"]; m = info[ok]
            gstatus, gscore, greason = grade.get(ok, ("", 0.0, ""))
            fp = st.db.execute("SELECT team_size_signal, is_firm FROM firm_profile WHERE org_key=?",
                               (ok,)).fetchone()
            team = fp["team_size_signal"] if fp else ""; isfirm = fp["is_firm"] if fp else ""
            dm = dt = de = others = ""
            if gstatus in ("in_icp", "later_prospect") and md_cache.get(ok):
                n_kept += 1
                try:
                    people = extract_people_from_md(md_cache[ok], m["name"], _live_llm)
                except Exception as e:  # noqa: BLE001
                    people = []; m["flag"] = (m["flag"] + f"; people err {str(e)[:30]}").strip("; ")
                dms = [p for p in people if p.get("seniority") == "decision_maker"]
                if dms:
                    top = next((p for p in dms if p.get("email")), dms[0])
                    dm, dt, de = top.get("name", ""), top.get("role", ""), top.get("email", "")
                    others = "; ".join(f"{p.get('name','')} ({p.get('role','')})" for p in dms if p is not top)[:300]
                    n_dm += 1
                    if de: n_email += 1
            w.writerow([m["name"], m["province"], m["suburb"], m["website"], m["phone"], gstatus,
                        round(gscore, 1), team, isfirm, dm, dt, de, others, greason, m["flag"]])
    st.close()
    kept_in = sum(1 for v in grade.values() if v[0] in ("in_icp", "later_prospect"))
    print(f"\nDone. profiled={len(batch)} graded_in={kept_in} | DM firms=+{n_dm} | direct-email firms=+{n_email}")
    print(f"-> {master}")


if __name__ == "__main__":
    main()
