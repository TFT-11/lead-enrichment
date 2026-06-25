# KZN / South Africa lead enrichment

The South African counterpart to the UK tooling in the repo root — extending Dean's `py-gtm` accountancy-firm
campaign to a new area (**KwaZulu-Natal / Durban**), reusing the same crawl + extract engine.

Key difference from the root UK scripts: these are **region-parameterised** (one `REGION` arg, `ZA` or `UK`)
rather than hardcoded to one country, and they read firms from the existing **sourcing store** (firms Dean
already sourced + graded) instead of pulling fresh from a registry. The entity guard treats `.co.za` as a
home TLD for ZA (the UK script wrongly treated it as foreign).

## Scripts
- **`select_region_candidates.py <db> <out.csv> <PROVINCE_LIKE> <N>`** — pull a province's firms from the
  sourcing store, `in_icp` (already-qualified) first, then best-seeded top-ups → candidate CSV. Read-only.
- **`enrich_region_batch.py <candidates.csv> <out-master.csv> <REGION> [START] [N]`** — per firm: on-file
  website (Google Places fallback) → `crawl_one` deep crawl → `extract_people_from_md` (OpenAI) →
  region-aware entity guard → contact-level CSV row. `ENTITY_BYPASS=1` recovers false entity rejections.
- **`runbook.md`** — full operating guide + the **mandatory web-verification step** (cross-check every
  decision-maker before shipping) and the KZN run results.

## Requirements
Same as the root: depends on the **`py-gtm`** repo (imports `core.config`, `crawl_sites`, `extract_people`).
Edit the `REPO = ...` path at the top of `enrich_region_batch.py` to your `py-gtm` clone and run with its
`.venv` python (3.12). Keys from `~/.config/projecty/*.env` (`GOOGLE_PLACES_API_KEY`, `OPENAI_API_KEY`).

## Typical run (KwaZulu-Natal, 100 firms)
```
python select_region_candidates.py ~/Downloads/sourcing-snapshot-copy.db kzn_candidates.csv KwaZulu 100
python enrich_region_batch.py kzn_candidates.csv kzn-enriched-master.csv ZA 1 100
# then web-verify every decision-maker (see runbook.md) before shipping
```
A new city is just a different `PROVINCE_LIKE` (e.g. `Gauteng`). Same scripts, no fork.

## Output & data handling
Output is a contact-level CSV (`firm, province, location, website, firm_phone, decision_maker, dm_title,
dm_email, ...`). **CSVs are gitignored** — lead data with personal contact details stays local and is
never committed to this public repo.

## First KZN run (2026-06-24)
100 firms → 56 verified decision-makers, 13 direct emails. See `runbook.md` for the full breakdown and the
verification defects it caught (admin-as-DM, wrong-entity domains, wrong-vertical, geo-fail, etc.).
