"""Regional accountancy-firm enrichment — Dean's profile engine, store-free, parameterised by region.

Reads a pre-selected candidates CSV (columns: name, suburb, province, website, phone [, lane]) and for
each firm runs the SAME engine the main pipeline uses (pipelines/accountancy-firms/profile/):

    on-file website (or Google Places fallback) -> crawl_one (deep crawl)
      -> extract_people_from_md (OpenAI) -> region-aware ENTITY GUARD
      -> append a contact-level row to the master CSV.

Geography is the REGION arg only — there is NO per-geo fork of this code. ZA (KwaZulu-Natal, Gauteng,
Western Cape, ...) and UK both run through here; the only difference is the home/foreign TLD set used by
the entity guard and the Places country bias.

Companion selector: scripts/select_region_candidates.py (DB -> candidates CSV).
Runbook: docs/runbooks/regional-enrichment.md

Usage:
    python scripts/enrich_region_batch.py <candidates_csv> <out_master_csv> <REGION> [START] [N]
    REGION in {ZA, UK}.  START/N batch over the candidates file (1-based, default all).

Env:
    ENTITY_BYPASS=1   force-crawl firms the entity guard would flag (recover false rejections);
                      such rows are tagged "(verify name vs site)" so they still get checked.

Keys come from core.config (GOOGLE_PLACES_API_KEY, OPENAI_API_KEY). Output is a deliverable CSV; this
script does NOT write to the store/Neon/Sheet (read-only w.r.t. shared data).
"""
import csv
import os
import pathlib
import re
import sys
import urllib.parse

import requests

REPO = pathlib.Path("C:/Users/tahaf/Project_y/repos/py-gtm")  # edit to your py-gtm clone
sys.path[:0] = [str(REPO), str(REPO / "pipelines" / "accountancy-firms"),
                str(REPO / "pipelines" / "accountancy-firms" / "profile")]

from core.config import key                                       # noqa: E402
from crawl_sites import crawl_one                                 # noqa: E402
from extract_people import extract_people_from_md, _live_llm      # noqa: E402

# --- region config: home TLDs are NOT foreign; a foreign TLD => wrong-entity risk -------------------
REGION_TLDS = {
    "ZA": {"home": (".co.za", ".org.za", ".net.za", ".za", ".com", ".net", ".org", ".africa"),
           "foreign": (".co.uk", ".com.au", ".co.nz", ".ie", ".de", ".fr", ".nl", ".es", ".in", ".us")},
    "UK": {"home": (".co.uk", ".org.uk", ".uk", ".com", ".net", ".org", ".scot", ".wales", ".cymru"),
           "foreign": (".co.za", ".in", ".com.au", ".co.nz", ".ie", ".de", ".fr", ".nl", ".es", ".us")},
}
COUNTRY = {"ZA": ("+27", ("South Africa", "ZA", "KwaZulu", "Durban", "Gauteng", "Cape")),
           "UK": ("+44", ("United Kingdom", "UK", "England", "Scotland", "Wales"))}
_STOP = {"limited", "ltd", "inc", "incorporated", "accountants", "accountant", "accounting", "accountancy",
         "services", "service", "tax", "taxation", "bookkeeping", "bookkeepers", "audit", "auditing",
         "auditors", "the", "and", "co", "group", "uk", "sa", "solutions", "company", "consultancy",
         "consultants", "consulting", "financial", "finance", "associates", "partners", "business"}


def entity_check(name, host, region):
    """Does the resolved website plausibly belong to THIS firm? -> (status, note).
    Guards against Google Places / DB returning a similarly-named but DIFFERENT company's site."""
    tl = REGION_TLDS[region]
    if not host:
        return "no_site", ""
    if any(host.endswith(s) for s in tl["foreign"]):
        return "foreign", f"foreign site ({host})"
    h = host.lower()
    for suf in sorted(tl["home"], key=len, reverse=True):
        if h.endswith(suf):
            h = h[:-len(suf)]
            break
    core = re.sub("[^a-z0-9]", "", h.split(".")[-1])
    toks = [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t and t not in _STOP and len(t) >= 2]
    joined = "".join(toks)
    if not toks:
        return "weak", "firm name too generic to verify"
    if any(t in core for t in toks) or (joined and (joined in core or core in joined)):
        return "match", ""
    acro = "".join(t[0] for t in toks)                       # acronym domains (o-as = Osborn Acc. Sol.)
    if len(acro) >= 2 and acro in core:
        return "match", ""
    return "mismatch", f"site '{host}' doesn't match firm name"


PLACES = "https://places.googleapis.com/v1/places:searchText"
MASK = "places.displayName,places.formattedAddress,places.websiteUri,places.internationalPhoneNumber"


def resolve(name, location, region):
    """Google Places fallback — only used when a firm has no website/phone on file."""
    hdr = {"Content-Type": "application/json", "X-Goog-Api-Key": key("GOOGLE_PLACES_API_KEY"),
           "X-Goog-FieldMask": MASK}
    cc, geo = COUNTRY[region]
    try:
        r = requests.post(PLACES, headers=hdr, json={"textQuery": f"{name}, {location}", "pageSize": 3}, timeout=30)
        if r.status_code != 200:
            return {}
    except Exception:  # noqa: BLE001
        return {}
    ps = r.json().get("places", [])
    local = [p for p in ps if cc in (p.get("internationalPhoneNumber") or "")
             or any(t in (p.get("formattedAddress") or "") for t in geo)]
    p = (local or ps or [{}])[0]
    return {"website": p.get("websiteUri", ""), "phone": p.get("internationalPhoneNumber", "")}


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    cand_csv = pathlib.Path(sys.argv[1])
    master = pathlib.Path(sys.argv[2])
    region = sys.argv[3].upper()
    if region not in REGION_TLDS:
        sys.exit(f"unknown REGION {region!r}; known: {sorted(REGION_TLDS)}")
    start = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 10_000
    bypass = os.environ.get("ENTITY_BYPASS") == "1"

    firms = list(csv.DictReader(cand_csv.open(encoding="utf-8-sig")))
    batch = firms[start - 1:start - 1 + n]
    print(f"{region} enrichment, firms {start}..{start + len(batch) - 1} of {len(firms)}"
          f"{'  [ENTITY_BYPASS]' if bypass else ''}\n")

    header = ["firm", "province", "location", "website", "firm_phone",
              "decision_maker", "dm_title", "dm_email", "other_decision_makers", "flag", "lane"]
    write_header = not master.exists() or master.stat().st_size == 0
    n_dm = n_email = 0
    with master.open("a", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        if write_header:
            w.writerow(header)
        for off, fm in enumerate(batch):
            gi = start + off
            name = fm["name"]
            loc = fm.get("suburb") or fm.get("province") or ""
            web = (fm.get("website") or "").strip()
            phone = (fm.get("phone") or "").strip()
            lane = fm.get("lane", "")
            if not web or not phone:                       # Places only fills genuine gaps
                rw = resolve(name, loc, region)
                web = web or rw.get("website", "")
                phone = phone or rw.get("phone", "")
            dm_name = dm_title = dm_email = others = flag = host = ""
            if not web:
                flag = "No website found - firm phone only" if phone else "No website or phone found"
            else:
                host = urllib.parse.urlparse(web).netloc.replace("www.", "") or web
                est, enote = entity_check(name, host, region)
                if est in ("foreign", "mismatch") and not bypass:
                    flag = "WRONG-ENTITY RISK: " + enote + " - unverified, no contact extracted"
                else:
                    try:
                        md, pages, cat, code = crawl_one(host)
                    except Exception as e:  # noqa: BLE001
                        md = ""; flag = f"crawl error: {str(e)[:60]}"
                    if not flag:
                        if not md or not md.strip():
                            flag = "Crawl returned no content - firm phone only"
                        else:
                            try:
                                people = extract_people_from_md(md, name, _live_llm)
                            except Exception as e:  # noqa: BLE001
                                people = []; flag = f"extract error: {str(e)[:60]}"
                            dms = [p for p in people if p.get("seniority") == "decision_maker"]
                            if dms:
                                top = next((p for p in dms if p.get("email")), dms[0])
                                dm_name = top.get("name", "")
                                dm_title = top.get("role", "")
                                dm_email = top.get("email", "")
                                others = "; ".join(f"{p.get('name','')} ({p.get('role','')})"
                                                   for p in dms if p is not top)[:300]
                                n_dm += 1
                                if dm_email:
                                    n_email += 1
                                note = " (verify name vs site)" if est in ("weak", "mismatch", "foreign") else ""
                                flag = (flag or "OpenAI-extracted") + note
                            elif not flag:
                                flag = "No decision-maker found on site - firm phone only"
            w.writerow([name, fm.get("province", ""), loc, host, phone,
                        dm_name, dm_title, dm_email, others, flag, lane])
            out.flush()
            print(f"[{gi}] {name[:36]:<36} | {host or '-':<26} | DM: {dm_name or '-'}"
                  f"{' <'+dm_email+'>' if dm_email else ''}")
    print(f"\nBatch done. +{n_dm} firms with a decision-maker, +{n_email} with a direct email.")


if __name__ == "__main__":
    main()
