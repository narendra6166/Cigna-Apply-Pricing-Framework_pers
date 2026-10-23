# Design and rule traceability

## Source precedence

1. `CCAC-4226-PTTC-4106-Apply-Pricing-System-Test-Scenarios-10-16-2026.docx` defines the active scenario inventory requested for the framework (36 unique IDs in the current source).
2. `CIGNA True_applypricing-design.pdf` is the primary pricing behavior/design source, especially its MVP2 pricing sections (PDF pages 3–5).
3. `../../Apply-Pricing-Clear-System-Test-Scenarios.md` supplies detailed case-level setup and expected behavior where the October 16 inventory is sparse.
4. Bruno payloads and captured results establish the available fixture/response evidence, not the business rule. A fixture that does not meet the design trigger is Blocked, not treated as the rule.

The October 16 document contains scenario names and conditions but leaves expected results blank or incomplete for many cases. Therefore, the catalog does not claim every expected result came directly from that document: each entry links the scenario inventory to the applicable pricing-design and detailed-case source. If the documents disagree or leave a mapping unresolved, the entry records the conflict and avoids inventing a value.

## Where traceability lives

`../rules/expected-results.json` is the only runtime expected-result source. Each scenario's `design_refs` links its rules to a scenario ID and source section/page. The catalog's top-level `design_conflicts` array records cross-document or fixture conflicts; it is also reproduced in the Excel Design Decisions sheet. This document explains source precedence and the key resolutions, not a second copy of the rules.

## Cross-document decisions and open questions

| Catalog ID | Topic | Comparison and treatment |
|---|---|---|
| DC-01 | Successful pricing status | October 16 lists 1005 for AP-001; the detailed guide records DEV 200 and allows 1005 for mainframe. Accept request status 200 or 1005 and validate response success. Confirm environment contract before narrowing. |
| DC-02 | Pricer type / schedule | PDF and detailed scenario guide reverse APCOP/ASCOP schedule-attribute mapping. Do not assert the disputed schedule attribute; validate request routing and observable outputs. |
| DC-03 | OTROP / DRG payload identity | The updated scenario inventory names OTROP-634, but its referenced request is absent from the current Bruno collection. Older OTROP-453 candidates use method 01/MS rather than the design's 10/AR, so they are not silently substituted. Keep OTROP-634 Not Run until its matching payload is supplied. |
| DC-04 | AP-015 over-allowed fixture | Design requires `ovragCfg=Y` and an allowed amount above billed. The captured request lacks this trigger; the observed run is Blocked until a matching fixture exists. |
| DC-05 | Crosswalk fallback/error values | Detailed cases expect AP-045 fallback `ppoDiscReason=2002` and AP-044 7004 only for positive crosswalk `ERROR_CD`; the PDF leaves some crosswalk outcomes unresolved. Keep AP-044 conditional and assert only source-confirmed AP-045 behavior. |
| DC-06 | AP-SC18 all-excluded case rate | The scenario inventory and supplementary pack both leave the outcome as designer TBD. Include it in the catalog, but keep it design-pending and Not Run until the expected behavior is approved and a payload exists. |
| DC-07 | AP-031 plan-limit fixture | The design requires a finite plan limit below billed. The current payload has plan limits of 2000 on lines billed 816.71 and 359, so it does not exercise the stated trigger. The evaluator blocks this fixture; the case-rate rule derives expected NC from the finite limit and `allowedCharges` when a matching fixture is used. |
| DC-08 | ASCOP evidence fixture | The Bruno file named `ASCOP with NC.bru` is currently a pricerType S / groupMethod 10 request, not the design's pricerType 64 ASC direct-pricing case. Its AP route preconditions prevent it from being scored as ASCOP success. |

The catalog has 36 entries matching the updated October 16 inventory. It keeps the document's three names `DRGOP`, `Error-7003`, and `OTROP-634`; the OTROP-634 scenario currently has no Bruno payload and is Not Run. The prior supplementary LIVE-OTROP-453 mapping is no longer part of this version of the active design inventory; its Bruno files remain untouched and are reported as unmapped. Fixture-specific blockers (for example AP-015, AP-024, AP-026, AP-ASC-GT, and AP-OTROP-ALLOC) are conditions, not silently altered business rules. Dependency responses such as member-plan lookup 1301 are Blocked because no pricing result is available to compare.

## Rule-to-code traceability

| Rule area | Catalog / implementation |
|---|---|
| Scenario-to-payload identity | Each scenario `payloads` entry; exact relative path matching in `engine.py` |
| Scenario input requirements | Each scenario `conditions`; `_precondition` in `engine.py` |
| Pricing response and line checks | Each scenario `checks`; `_comparison` in `engine.py` |
| Direct APC / ASC line calculations | `direct_amounts_reconcile`; request-derived billed, allowed, NC, and excess |
| Grouped DRG / OTROP proration | `grouped_amounts_reconcile`; request-derived included/excluded totals |
| Design activation gates | `readiness: conditional` with an `activation` check |
| Missing / dependency-blocked / unlisted requests | `_response_blocker` and `run_catalog`; displayed separately from business failures |
| Business-readable record and traceability | `Outcome` fields in `engine.py`; Excel/CSV/Markdown in `report.py` |

Rule changes should be made in the JSON catalog, not duplicated into the runner or report scripts. Add unit tests when introducing a new evaluator operation or changing a pricing formula.
