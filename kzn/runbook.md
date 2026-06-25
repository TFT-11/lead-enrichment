# Regional accountancy-firm enrichment runbook

How to produce a contact-level enriched lead list for a target **region/city/province**, reusing Dean's
profile engine (`pipelines/accountancy-firms/profile/`) store-free on Windows. First worked example:
**KwaZulu-Natal (Durban + KZN), June 2026.**

This is the "extend the SA campaign to a new area" workflow. Geography is a **parameter**, not a fork —
the same two scripts run for KZN, Gauteng, Western Cape, or the UK. (Dean's campaign originally worked
Gauteng + Western Cape only; the KZN firms were already sourced + graded in the store, just never
enriched.)

## What it does

```
select_region_candidates.py   DB (in_icp first) ──▶ candidates.csv
        │
        ▼
enrich_region_batch.py        per firm: on-file website (or Google Places fallback)
                              → crawl_one (deep crawl) → extract_people_from_md (OpenAI)
                              → region-aware entity guard → enriched-master.csv
        │
        ▼
web verification              cross-check each decision-maker against the firm site +
(Claude / agents)             independent sources; clean titles; drop admin/wrong-entity/
                              wrong-vertical/geo-fail; recover false entity rejections.
```

Engine reused as-is: `profile/crawl_sites.crawl_one` (deep crawl, robots-aware, people-page fallback) and
`profile/extract_people.extract_people_from_md` (LLM people pass: name + seniority + title, anti-confab —
a person is only emitted if their name literally appears on the crawled site). Keys via `core.config`
(`GOOGLE_PLACES_API_KEY`, `OPENAI_API_KEY`). **Read-only w.r.t. the store/Neon/Sheet** — output is a CSV.

## Prereqs

- `.venv` built (Python 3.12) — on Windows always launch with `.venv/Scripts/python.exe`.
- `~/.config/projecty/*.env` present with `OPENAI_API_KEY` (funded) and `GOOGLE_PLACES_API_KEY` (free tier).
- A sourcing DB with the region's firms. Canonical worker DB = `data/sourcing.db` (sync from Neon first —
  see `docs/CONTINUE-ENRICHMENT.md`). For the KZN run we used the shared snapshot
  `~/Downloads/sourcing-snapshot-copy.db` (8,398 firms; 497 KZN, 96 of them already `in_icp`).

## Run (KZN, 100 firms)

```bash
# 1) select candidates: 96 in_icp KZN + 4 best-seeded top-ups
.venv/Scripts/python.exe scripts/select_region_candidates.py \
    ~/Downloads/sourcing-snapshot-copy.db data/lists/kzn_candidates.csv KwaZulu 100

# 2) enrich (ZA region → .co.za is the HOME tld for the entity guard)
.venv/Scripts/python.exe scripts/enrich_region_batch.py \
    data/lists/kzn_candidates.csv data/lists/kzn-enriched-master.csv ZA 1 100

# 3) recover any firms the entity guard false-flagged (acronym domains etc.)
#    re-run only the WRONG-ENTITY rows with the guard bypassed, then web-verify the result.
ENTITY_BYPASS=1 .venv/Scripts/python.exe scripts/enrich_region_batch.py \
    data/lists/kzn_recover.csv data/lists/kzn-recover-out.csv ZA
```

A new city is just a different province filter, e.g. Gauteng:

```bash
.venv/Scripts/python.exe scripts/select_region_candidates.py \
    data/sourcing.db data/lists/gp_candidates.csv Gauteng 100
.venv/Scripts/python.exe scripts/enrich_region_batch.py \
    data/lists/gp_candidates.csv data/lists/gp-enriched-master.csv ZA
```

## Output

`<region>-enriched-master.csv`, contact-level, one row per firm:

| col | meaning |
|---|---|
| firm, province, location | firmographics (location can be corrected during verification) |
| website, firm_phone | resolved site host + firm phone (+27 / +44 normalised) |
| decision_maker, dm_title, dm_email | extracted senior contact (owner/founder/partner/director/CEO/MD) |
| other_decision_makers | other senior people found on the site |
| flag | engine note: `OpenAI-extracted`, `No decision-maker found`, `WRONG-ENTITY RISK`, etc. |

After web verification, finalise with two extra columns — `verification_status`
(`confirmed | corrected | caution | rejected_dm | geo_fail | wrong_vertical | no_dm_phone_only`) and
`notes` — and ship as `PY_<REGION>_enriched_<N>.csv`.

## Verification is mandatory (repo hard rule: self-audit the OUTPUT)

LLM extraction is high-recall but wrong-entity / wrong-role prone. Every decision-maker row must be
cross-checked against an INDEPENDENT source (the firm's own site + web search) before the list ships.
Watch for, and the KZN run actually hit, all of these:

- **Admin mistaken for a principal** (e.g. "Head of Administration" tagged decision_maker) → drop to phone-only.
- **Wrong entity** — domain belongs to a similar-named different firm (e.g. `l-inc.co.za` was Lockhat Inc,
  not "Coastal Accounting") → correct the firm name or drop.
- **Wrong vertical** — wealth-management / IT-support businesses caught under accounting codes → flag/drop.
- **Geo fail** — firm graded into the province but actually HQ'd elsewhere (e.g. an IBEC row was Johannesburg).
- **False entity rejections** — acronym/abbreviation domains the guard wrongly flagged (`o-as.co.za` =
  Osborn Accounting Solutions) → recover via `ENTITY_BYPASS=1`.
- **Messy titles** — raw sentence fragments ("Founded in 2016 by …") → rewrite to a clean job title.
- **Email-domain mismatches** — personal email on a different domain than the site → verify deliverability.
- **Reputational flags** — note any adverse findings (the run surfaced one firm with 2022 fraud charges).

## KZN run result (2026-06-24)

100 firms → **56 with a verified decision-maker, 13 with a direct DM email**.
Status: 39 confirmed · 10 corrected · 5 caution · 1 geo_fail (Gauteng) · 1 wrong_vertical · 2 dropped
(admin / wrong-entity) · 42 firm-phone-only (no DM published on site).
Deliverable: `PY_KZN_enriched_100.csv`.

## Known limitations

- `extract_people` runs on OpenAI; needs a funded `OPENAI_API_KEY`.
- Direct personal emails are the hardest field — most firms publish only `info@` (phone-only is still a
  usable lead). Paid enrichment (Apollo/Hunter) for the gaps stays budget-gated; not used here.
- Occasional name encoding artifacts on a few sites — eyeball during verification.
- Google Places resolution is only a fallback; with a DB seed that already has websites it is rarely called.
