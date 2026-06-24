"""Brave + LLM-judged verification, then OpenAI extraction. Dean's guardrail done right:
Places (phone + candidate site) -> BRAVE search -> OpenAI READS the results and picks the firm's
REAL official site (handles trading names; rejects wrong-entity AND non-accountancy firms) ->
crawl verified site -> OpenAI extract first/last/title. Apollo-ready output.
Usage: enrich_v3.py START N   (START==1 writes fresh file w/ header)
"""
import csv
import pathlib
import re
import sys
import urllib.parse

import requests

REPO = pathlib.Path(r"C:\Users\tahaf\Project_y\repos\py-gtm")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipelines" / "accountancy-firms"))
sys.path.insert(0, str(REPO / "pipelines" / "accountancy-firms" / "profile"))

from core.config import key                                       # noqa: E402
from crawl_sites import crawl_one                                 # noqa: E402
from extract_people import extract_people_from_md, _live_llm      # noqa: E402
from enrich import serp, _openai                                  # noqa: E402

START = int(sys.argv[1]); N = int(sys.argv[2])
CAND = pathlib.Path(r"C:\Users\tahaf\Downloads\uk-firms-expanded.csv")
OUT = pathlib.Path(r"C:\Users\tahaf\Downloads\uk-apollo-ready.csv")
PLACES = "https://places.googleapis.com/v1/places:searchText"
MASK = "places.displayName,places.formattedAddress,places.websiteUri,places.internationalPhoneNumber"
COLS = ["company", "first_name", "last_name", "title", "email", "domain", "firm_phone",
        "verified_by", "other_decision_makers", "flag"]
DENY = ("linkedin.", "facebook.", "instagram.", "twitter.", "x.com", "yell.com", "yelp.",
        "gov.uk", "find-and-update", "trustpilot.", "indeed.", "glassdoor.", "checkatrade.",
        "google.", "bing.", "youtube.", "tiktok.", "companieshouse", "wikipedia.", "endole.",
        "company-information", "ukdata", "rocketreach", "apollo.io", "crunchbase")
VERIFY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["domain", "is_accountancy"],
                 "properties": {"domain": {"type": "string"}, "is_accountancy": {"type": "boolean"}}}


def places(name, location):
    hdr = {"Content-Type": "application/json", "X-Goog-Api-Key": key("GOOGLE_PLACES_API_KEY"), "X-Goog-FieldMask": MASK}
    try:
        r = requests.post(PLACES, headers=hdr, json={"textQuery": f"{name}, {location}", "pageSize": 3}, timeout=30)
        if r.status_code != 200:
            return "", ""
    except Exception:  # noqa: BLE001
        return "", ""
    ps = r.json().get("places", [])
    uk = [p for p in ps if "+44" in (p.get("internationalPhoneNumber") or "")
          or any(t in (p.get("formattedAddress") or "") for t in ("UK", "United Kingdom", "England", "Scotland", "Wales"))]
    p = (uk or ps or [{}])[0]
    return urllib.parse.urlparse(p.get("websiteUri", "")).netloc.replace("www.", "").lower(), p.get("internationalPhoneNumber", "")


def brave_candidates(name, location):
    town = location.split(",")[0].strip()
    cleaned = re.sub(r"\b(limited|ltd|llp)\b\.?", "", name, flags=re.I).strip()
    data = serp.live_fetch("brave", f"{cleaned} {town} accountants")
    out = []
    if isinstance(data, dict):
        for r in (data.get("web") or {}).get("results") or []:
            host = urllib.parse.urlparse(r.get("url", "")).netloc.replace("www.", "").lower()
            if not host or any(d in host for d in DENY) or host in [c["domain"] for c in out]:
                continue
            out.append({"domain": host, "title": (r.get("title") or "")[:120], "desc": (r.get("description") or "")[:200]})
            if len(out) >= 6:
                break
    return out


def verify_domain(name, location, p_host):
    """Brave + LLM: pick the firm's real official accountancy website from search results."""
    cands = brave_candidates(name, location)
    if p_host and p_host not in [c["domain"] for c in cands]:
        cands.insert(0, {"domain": p_host, "title": "(Google Places listing)", "desc": ""})
    if not cands:
        return "", "no-candidates"
    listing = "\n".join(f"{i+1}. {c['domain']} | {c['title']} | {c['desc']}" for i, c in enumerate(cands))
    prompt = (f"Registered company name: {name!r}\nLocation: {location!r}\n\n"
              "Below are website search results. Pick the ONE result that is THIS company's own official "
              "website AND belongs to an accountancy / bookkeeping / tax firm. The registered name often "
              "differs from the trading/brand name (e.g. 'TBD Accountants Ltd' trades as 'Tidy Tax'; a snippet "
              "mentioning the registered name, the town, or 'accountants' is strong evidence). Do NOT pick a "
              "directory, a different company, or a non-accountancy business. If none clearly belong to this "
              "firm, return an empty domain.\n\nResults:\n" + listing +
              "\n\nReturn the chosen domain exactly as written above (or empty), and is_accountancy true/false.")
    parsed, etype, emsg = _openai.chat_json(prompt, VERIFY_SCHEMA, schema_name="verify")
    if not parsed:
        return "", f"verify-failed:{etype}"
    dom = (parsed.get("domain") or "").strip().lower().replace("www.", "")
    if dom and parsed.get("is_accountancy") and any(dom == c["domain"] for c in cands):
        return dom, "brave+llm"
    return "", "no-confident-match"


firms = []
with CAND.open(encoding="utf-8-sig") as f:
    firms = list(csv.DictReader(f))

batch = firms[START - 1:START - 1 + N]
mode = "w" if START == 1 else "a"
print(f"Brave+LLM verified enrichment, firms {START}..{START + len(batch) - 1} of {len(firms)}\n")
n_dm = n_email = n_verified = 0
with OUT.open(mode, newline="", encoding="utf-8") as out:
    w = csv.writer(out)
    if mode == "w":
        w.writerow(COLS)
    for off, fm in enumerate(batch):
        gi = START + off
        name, loc = fm["name"], fm["location"]
        p_host, p_phone = places(name, loc)
        host, reason = verify_domain(name, loc, p_host)
        first = last = title = email = others = flag = ""
        phone = p_phone if (host and host == p_host) else ""
        if not host:
            flag = f"UNVERIFIED ({reason}) - enrich via Apollo by company name"
        else:
            n_verified += 1
            try:
                md, pages, cat, code = crawl_one(host)
            except Exception as e:  # noqa: BLE001
                md = ""; flag = f"crawl error: {str(e)[:50]}"
            if not flag:
                if not md or not md.strip():
                    flag = "crawl empty - company+domain+phone (use Apollo for people)"
                else:
                    try:
                        people = extract_people_from_md(md, name, _live_llm)
                    except Exception as e:  # noqa: BLE001
                        people = []; flag = f"extract error: {str(e)[:50]}"
                    dms = [p for p in people if p.get("seniority") == "decision_maker"]
                    if dms:
                        top = next((p for p in dms if p.get("email")), dms[0])
                        first = top.get("person_first", ""); last = top.get("person_last", "")
                        title = top.get("role", ""); email = top.get("email", "")
                        others = "; ".join(f"{p.get('name','')} ({p.get('role','')})" for p in dms if p is not top)[:300]
                        n_dm += 1
                        if email:
                            n_email += 1
                        flag = flag or "verified-extracted"
                    elif not flag:
                        flag = "no named DM on site - company+domain+phone (use Apollo for people)"
        w.writerow([name, first, last, title, email, host, phone, host and "brave+llm" or "", others, flag])
        out.flush()
        print(f"[{gi}] {name[:32]:<32} | {host or 'UNVERIFIED':<30} | {(first + ' ' + last).strip() or '-'}")

print(f"\nBatch: {n_verified}/{len(batch)} verified, +{n_dm} DM, +{n_email} email.")
