# GTM Lead Enrichment (UK accountancy firms)

Scripted, verified lead-enrichment tooling built on the `py-gtm` pipeline. Turns a list of
UK accountancy firms (from Companies House) into an **Apollo-ready** contact list:
verified company website + firm phone + decision-maker first/last/title where public.

## Scripts
- **`pull_firms.py`** — pull UK accountancy firms from Companies House (SIC 69201/69202/69203),
  dedupe, filter to accountancy-named, write a candidate CSV.
- **`enrich.py START N`** — the main one. For firms START..START+N of the candidate list:
  1. **Google Places** → firm phone + a candidate website
  2. **Brave Search + OpenAI** → reads the search results and picks the firm's *real* official
     accountancy website (handles trading names e.g. "TBD Accountants Ltd" → "Tidy Tax"; rejects
     wrong-entity matches and non-accountancy businesses). This is the accuracy guardrail.
  3. **Crawl** the verified site → **OpenAI** extracts named decision-makers (first/last/title/email).
  4. Appends an Apollo-ready row. `START==1` writes a fresh file with header; otherwise appends.
- **`sheet_push.py`** — push the output CSV into a tab of a Google Sheet (uses Project_y `sheets.py`).

## Output columns (Apollo-import friendly)
`company, first_name, last_name, title, email, domain, firm_phone, verified_by, other_decision_makers, flag`

## Requirements / setup
- Depends on the **`py-gtm`** repo (imports `core.config`, `crawl_sites`, `extract_people`, `enrich.serp`,
  `enrich._openai`). Edit the `REPO = ...` path at the top of each script to point at your `py-gtm` clone,
  and run with its `.venv` python (Python 3.12).
- API keys are read from `~/.config/projecty/*.env` (NEVER hardcoded): `GOOGLE_PLACES_API_KEY`,
  `BRAVE_API_KEY`, `OPENAI_API_KEY` (+ `OPENAI_EXTRACT_MODEL`).
- Input/output CSV paths are set at the top of each script — change them as needed.

## Typical run
```
python pull_firms.py                  # -> candidate CSV
python enrich.py 1 50                 # firms 1-50  (writes fresh Apollo-ready CSV)
python enrich.py 51 50                # firms 51-100 (appends)
python sheet_push.py                  # publish to the Google Sheet tab
```
Then upload the Apollo-ready CSV to Apollo to fill email / LinkedIn / phone / company size.

## Notes
- Verification is best-effort: rows are flagged `UNVERIFIED` (no confident site match) or carry notes
  like "no named DM on site" — eyeball flagged rows before outreach.
- Free-tier limits: Google Places ~1000 calls/mo, Brave ~2000/mo; OpenAI is pay-as-you-go (cents/firm).

## Apollo enrichment (decision-maker contacts by domain)
- **`apollo_enrich.py <csv>`** — for firms WITH a domain: Apollo People Search by domain + title -> reveal email (no phone, no waterfall). Appends to `apollo-found-people.csv`.
- **`apollo_enrich_byname.py`** — for firms with NO domain: find the company in Apollo by name -> get domain -> find a person.
- **Headcount filter:** both enforce an ICP size window via `SIZE_MIN`/`SIZE_MAX` at the top of the file (default **10-300** employees), passed to Apollo as `organization_num_employees_ranges`. Change those two numbers to adjust. NOTE: headcount only exists at the Apollo stage (Companies House + website crawl don't expose it), so size qualification lives here, not in `enrich.py`.
- Key: `APOLLO_USER_API_KEY` in `~/.config/projecty/keys.env`. Endpoints: `mixed_people/api_search` + `people/match`.
