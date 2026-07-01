# sa-graded — full SA accountancy-firm lead-gen WITH Dean's grade/size stage

This is the **grade-included** SA pipeline. Unlike the older `../kzn/` region scripts (which skip the
qualify/grade stage and only work on firms Dean had *already* graded `in_icp`), these run Dean's ACTUAL
pipeline end-to-end on **NEW, never-assessed firms**:

```
select_new_sa_candidates.py   NEW firms for a province (not in icp_assessment), deduped vs an
                              outreach-sheet exclusion list                       -> candidates.csv
        |
        v
enrich_new_sa_batch.py        per firm: crawl_one (deep crawl)
                              -> extract_profile (firm_profile incl team_size_signal + is_firm gate)   [PROFILE]
                              -> select.py RUBRIC grade (size ~5-200 is a weighted dimension)           [GRADE/SIZE]
                              -> extract_people on graded-IN firms                                      [CONTACTS]
                              -> contact-level master CSV
```

The engine is **Dean's** (`py-gtm/pipelines/accountancy-firms/` + `enrich/select.py`) — these two files
just orchestrate it. Only the **location** changes between runs; the grade is identical to Dean's.

## Prereqs
- A local clone of Dean's `py-gtm` (edit the `REPO = ...` path at the top of `enrich_new_sa_batch.py`).
- Run with the SAC-allowed system Python: `C:\Python314\python.exe` (the project `.venv` is blocked by
  Windows Smart App Control). One-time: `C:\Python314\python.exe -m pip install --user curl_cffi markdownify pyyaml`.
- Keys in `~/.config/projecty/*.env` (OPENAI_API_KEY funded, GOOGLE_PLACES_API_KEY free tier).
- The SA sourcing DB (`~/Downloads/sourcing-snapshot-copy.db`).
- An exclusion JSON: `[{"name": "...", "website": "...", "province": "..."}, ...]` of firms already worked
  (export from your outreach sheet) so you never re-enrich a spent lead.

## Run (any SA province — same commands, only the PROVINCE arg changes)
```bat
set PYTHONIOENCODING=utf-8
set OPENAI_PROFILE=1
REM 1) select 100 NEW firms for the province (Gauteng | Western Cape | KwaZulu)
C:\Python314\python.exe select_new_sa_candidates.py "%USERPROFILE%\Downloads\sourcing-snapshot-copy.db" cand.csv "Gauteng" 100 exclude.json
REM 2) run the full graded pipeline
C:\Python314\python.exe enrich_new_sa_batch.py cand.csv out_master.csv ZA 1 100
```
Then run the **mandatory** web-verification pass on the output before shipping (cross-check every
decision-maker vs the firm site + independent sources; drop wrong-entity/wrong-vertical/geo-fails).

## Run (UK — same grade engine, source = Companies House)
UK firms come from Companies House (no website on file → Places resolves it). `select_new_uk_candidates.py`
pulls + **ingests them into the store** so Dean's grade can read them, then the SAME `enrich_new_sa_batch.py`
runs with `REGION=UK`:
```bat
set PYTHONIOENCODING=utf-8
set OPENAI_PROFILE=1
C:\Python314\python.exe select_new_uk_candidates.py cand_uk.csv 100 uk_exclude.json 5
C:\Python314\python.exe enrich_new_sa_batch.py cand_uk.csv out_uk.csv UK 1 100
```
So all locations use ONE engine; only the *selector* + `REGION` arg differ (SA→`select_new_sa_candidates.py`,
UK→`select_new_uk_candidates.py`).

**Two UK caveats (read before a big run):**
1. Dean's grade RUBRIC is **SA-worded** (mentions Gauteng/WC, CA(SA)). It applies to UK — automatable-surface,
   distribution, reachability and **size (~5-200)** all score — but the geo bonus won't trigger for UK. Ask for a
   UK-geo rubric variant if you want UK place-names/ACA-ACCA tells (still Dean's logic).
2. Raw Companies House pulls skew to **micro/solo firms**, which Dean's rubric (correctly) grades low
   (`wrong_icp_now`), so UK `in_icp` yield is lower than SA. Pull more pages and/or larger firms. Also, with no
   website on file, Places sometimes resolves the wrong firm's site — the entity guard flags those.

## Cost
OpenAI `gpt-5.4-mini` only, ~$0.04–0.05/firm (~$5 per 100). Google Places free tier (UK uses ~1 Places call
per firm since CH has no websites — stay under the 1,000/mo free cap). No Apollo/Hunter.

## 2026-06-26 Gauteng + Western Cape run
200 firms -> 96 graded-in, 51 verified decision-makers, 22 emails, 96 phones.
