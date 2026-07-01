# Spec: UK accountancy-firm lead pipeline — v1

_Authored 2026-06-22 via gstack `/spec`. Owner: Taha. Status: ready to build (blocked on API key + Python env). Reuses the existing `pipelines/accountancy-firms/` SA pipeline; this is an adaptation, not a new build._

## Context

Dean assigned UK accountancy firms as the next market (Jun 19 sync); `docs/DECISIONS.md` already names UK as the priority geo after South Africa. PY sales needs UK firms to run the accountancy-firm partnership motion. The SA pipeline already produces ranked, contactable firm lists; the UK is the same machine pointed at UK firms. Most of the infrastructure already exists — the Companies House adapter, the geo-agnostic enrichment engine, and an ICP that already names UK bodies/registers — so this is a small adaptation plus a run, not a from-scratch build.

## Goal (definition of done)

A list of **200 UK accountancy firms that pass the existing ICP**, each with a **decision-maker contact**, produced by the same flow as SA, contacts pulled **free-first**.

A firm counts toward the 200 when it is in-ICP (or a clear later-prospect) AND meets one of Dean's two readiness tiers (`docs/CONTINUE-ENRICHMENT.md`):
- **`dm_email_phone`** (best): named founder/partner/director/owner/MD/CEO with a real direct email + a valid phone.
- **`senior_firm_email_phone`** (acceptable fallback): named senior person + firm generic email + valid firm phone.

Firms where free enrichment cannot reach a direct decision-maker contact are **flagged `run_paid_enrichment`** (queued for Apollo/Hunter pending Dean's budget approval), never silently dropped. Phone-only/incomplete rows go to the graded review surface flagged as review rows, not counted in the 200.

## Targeting & qualification (unchanged — Dean's ICP, `data/icp_definitions/accountancy-firms-partnership.yaml`)

- **Target firms:** accountancy / bookkeeping / outsourced-finance / tax firms; ~5–200 staff; independents + regional.
- **Grade rubric (weighted):** automatable surface 40 (bookkeeping/outsourced-finance/virtual-CFO/FD/payroll/advisory) · distribution value 25 (multi-client SME base / growing) · reachable named owner/partner/MD 15 · size 10 · software badges 10 (minor).
- **Anti-fit (disqualify, score ≤30):** Big-4 / large networks, pure audit-only, solo practitioners with no growth intent, compliance/tax-return mills with no advisory, not-an-accountancy-firm (bank, insurer, asset manager, software vendor, gov body, directory).

## Current state (verified 2026-06-22)

| Capability | Status | Evidence |
|---|---|---|
| UK firm registry adapter (Companies House) | ✅ built, free | `core/lib/companies_house.py` — SIC 69201/69202/69203; needs `COMPANIES_HOUSE_API_KEY` |
| Enrichment engine (crawl → people → email → phone), free-first then paid lane | ✅ built, geo-agnostic | `pipelines/accountancy-firms/enrich/`, `profile/` |
| ICP incl. UK targeting | ✅ built | ICP yaml lists `GB`, ICAEW/ACCA, Companies House SIC codes |
| Grading, QA gate, readiness tiers, Sheet export | ✅ built, reused | `crm/`, `scripts/continue_enrichment.py`, `scripts/publish_sheet.py` |
| Region normalization (GB-aware) | ✅ built | `core/contract.py` |
| Companies House wired into the firm config | ❌ not wired for GB | `pipelines/accountancy-firms/config.yaml` (SA adapters only) |
| Free people-discovery sources for UK | ❌ SA-specific | query-set uses `press_sites_za` (Moneyweb/SAICA/IRBA) |
| Phone handling for UK (+44) | ❌ +27 only | `core/validate.py` |
| UK credential recognition (ACA/ACCA/CTA) | ❌ SA credentials only | `pipelines/accountancy-firms/profile/extract_people.py` |
| Multi-geo run wiring | ⚠️ verify | `pipelines/accountancy-firms/run.py` (may be ZA-hardcoded) |

**Companies House gives firms, not people.** Firm name/website/region come from the API key; decision-maker name + email + phone come from the enrichment stage. This is why free-vs-paid matters and why not all 200 will reach `dm_email_phone` from free sources alone.

## Proposed change — build tasks (the only new work)

1. **Wire Companies House into the firm config** for GB — `pipelines/accountancy-firms/config.yaml`: add a `companies_house` adapter (SIC 69201/69202/69203, status=active, GB) + confirm `run.py` runs a GB sourcing pass writing `region=GB`.
2. **Create UK query-set** — `data/icp_definitions/accountancy-firms-partnership-query-set-gb.yaml`: clone the SA query-set, replace `press_sites_za` with UK sources (icaew.org.uk, accaglobal.com/acca.org.uk, accountancyage.com, icas.com); keep the generic firm/person/email/phone queries.
3. **Add +44 phone handling** — `core/validate.py`: normalize/validate UK landline + mobile numbers alongside +27 (directly required: the deliverable needs phone numbers).
4. **Recognize UK credentials** — `profile/extract_people.py`: add ACA, ACCA, FCCA, CTA, CA(GB) to seniority/decision-maker detection; extend the org/credential false-positive filter (the SA `SARS`/`SAIBA` guard) to UK bodies (ICAEW, ACCA, HMRC).

## Acceptance criteria (pass/fail)

1. `python pipelines/accountancy-firms/run.py` (GB) sources UK firms from Companies House, deduped, written to the store tagged `region=GB`; count verifiable via `sqlite3 data/sourcing.db "select region,count(*) from companies where track='accountancy-firms' group by region;"`.
2. Free-first enrichment yields **≥200 shippable UK firms**, each in-ICP/later-prospect AND meeting `dm_email_phone` or `senior_firm_email_phone`.
3. Every shippable row has a valid `+44`-normalized phone; no SA `+27` mis-normalization on UK numbers.
4. **Zero SA rows modified.** UK rows are `region=GB` and exported to a **new** Google Sheet; the existing SA stable Sheet is untouched.
5. A 10-row QA sample passes Dean's defect checks (no org-as-person, no fabricated `first.last@domain`, no admin/reception presented as decision-maker, correct-country, normalized phones).
6. Firms where free can't reach a direct DM contact are flagged `run_paid_enrichment` (queued), not dropped.

## Testing plan

| Layer | What | Count |
|---|---|---|
| Unit | +44 phone normalize/validate; UK credential parse; GB query-set loads | +5 |
| Integration | Companies House fetch → store `region=GB`; one firm end-to-end free enrich | +2 |
| E2E | run (GB) → enrich batch → QA sample → publish new Sheet | +1 |

## Rollback plan

All UK work is additive: a new config block, a new query-set file, `+44` added to phone logic, UK credentials added to people extraction, `region=GB` rows in local SQLite, a new Sheet. Rollback = don't publish, delete `region=GB` rows from local SQLite (never synced to Neon until QA-clean), revert the 4 edits. SA data and Sheet are never touched.

## Effort estimate

~1 day of build + a run: config 1h · GB query-set 1h · +44 phone 2h · UK credentials 2h · run/region wiring 1h · run + QA + iterate to 200 (depends on Companies House volume and free contact hit-rate).

## Files reference

| File | Change |
|---|---|
| `pipelines/accountancy-firms/config.yaml` | Add Companies House GB adapter |
| `pipelines/accountancy-firms/run.py` | Confirm/enable GB sourcing pass (region=GB) |
| `data/icp_definitions/accountancy-firms-partnership-query-set-gb.yaml` | NEW — UK press/bodies query-set |
| `core/validate.py` | Add +44 phone normalize/validate |
| `pipelines/accountancy-firms/profile/extract_people.py` | UK credentials + UK org false-positive guard |

## Dependencies / blockers

1. **`COMPANIES_HOUSE_API_KEY`** — free key from developer.company-information.service.gov.uk (Taha obtaining).
2. **Working Python env** for the pipeline (`.venv` per `docs/reference/environments.md`; the repo's setup is macOS-oriented — Windows setup must be verified before the first run).

## Out of scope (v1)

- Paid enrichment (Apollo/Hunter) — queued, needs Dean's budget approval (locked at $0).
- Extra UK directory adapters (Xero-UK, ICAEW, ACCA scrapers) — Companies House only for v1.
- Outreach / LGM / Sheet auto-send — nothing sends without human approval.
- Pushing this work to Dean's repo — Taha is read-only; forking disabled.

## Related

- `docs/DECISIONS.md` (UK = priority geo after SA)
- `docs/CONTINUE-ENRICHMENT.md` (operator flow + readiness tiers)
- `docs/goal-packs/starter-50-goal-pack.md` (the SA starter-batch pattern this mirrors)
