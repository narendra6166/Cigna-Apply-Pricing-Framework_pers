# Cigna TRUE Apply Pricing automation

This package adds data-driven evaluation and reporting around the existing Bruno collection. Bruno remains the API execution layer; the JSON catalog is the single source of active expected-result rules. The catalog currently covers all 36 unique IDs in the updated October 16 scenario document. The collection files, environments, auth setup, and payloads are not replaced.

## Layout

| Path | Purpose |
|---|---|
| `rules/expected-results.json` | Scenario registry, input conditions, checks, source references, blockers, tolerances, and design decisions |
| `engine.py` | Loads Bruno reporter JSON, matches payloads, evaluates conditions/checks, and assigns status |
| `report.py` | Writes Excel, Word, CSV, and Markdown without copying request bodies or member/provider data |
| `design/` | Preserved Kishore pricing design PDF, October 16 scenario document, and traceability notes |
| `tests/` | Offline unit tests for catalog validation, scoring, and reporting |
| `requirements.txt` | Excel and Word output dependencies |

## Run from VS Code

Open the project root in VS Code and use its PowerShell terminal. To run Bruno's existing auth/collection flow with the DEV environment and then generate the reports:

```powershell
.\bruno\run_all_tests.ps1
```

The runner runs all payloads with no prompt. To refresh one payload from `DATA-FROM -MAINFRAME` without running the collection, use `.\bruno\update_payload.ps1` (prompts for a name) or `python .\bruno\update_payload_from_mainframe.py --payload "AP-013"`. Service-line and pricing-rule arrays are resized to the source detail count while retaining existing fields and structure.

The runner uses `bruno\environments\DEV.bru`, stores Bruno's reporter output in `bruno\results.json`, and writes:

- `bruno\TEST-RESULTS.xlsx`
- `bruno\TEST-RESULTS.docx`
- `bruno\TEST-RESULTS.csv`
- `bruno\EXECUTION-REPORT.md`
- `bruno\TEST-RESULTS.md` (compatibility copy)

This command makes live API calls. Use it only when Bruno (`bru`) is installed, the selected environment is configured, and running the collection against DEV is intended.

Before auth and the API run, this runner calls `bruno\_stamp_literal_today.py`. It updates `requestDate`, `claimReceiveDate`, `serviceFromDate`, and `serviceThruDate` in the Bruno request files and refreshes the DEV environment's `today` value. The Bruno collection pre-request hook also applies today's date at send time. To refresh the visible payload dates without running the API:

```powershell
python .\bruno\_stamp_literal_today.py
```

`bruno\_stamp_today_vars.py` is an alternate utility that changes those payload date literals to `{{today}}` placeholders; it is not part of the automated run. Do not run it immediately before `_stamp_literal_today.py` unless you want the payloads converted back to literal dates.

For offline report regeneration from existing results, run:

```powershell
python -m apply_pricing_framework --results "bruno\results.json"
```

Other useful commands:

```powershell
python -m apply_pricing_framework --help
python -m apply_pricing_framework --validate-only
python -m unittest discover -s apply_pricing_framework\tests -v
```

Install the Excel dependency only if it is unavailable:

```powershell
python -m pip install -r apply_pricing_framework\requirements.txt
```

For a Bruno run using another environment, continue to use Bruno's existing environment configuration; the framework evaluates the resulting JSON file and does not select or alter the environment.

## Add a scenario

1. Add the request to the existing Bruno collection and confirm its `.bru` payload works in Bruno.
2. From the project root, create a safe, blocked scaffold:

   ```powershell
   python -m apply_pricing_framework add-scenario --id AP-NEW --name "New business case" --payload "09-new-cases\AP-NEW.bru"
   ```

   The payload must already exist below `bruno\`. The new catalog entry has `readiness: design_pending`, so it is Blocked—not a false Pass—until its rule is authored.
3. Edit the new entry in `rules/expected-results.json`: set its source-derived `category`, `expected`, input `conditions`, response `checks`, and `design_refs`. Set `readiness` to `ready` only when its checks are complete. For an unresolved source-dependent condition, use `readiness: conditional`, define the `activation` check and explain `conditional_reason`.
4. Validate the catalog, run saved results, and inspect the generated report:

   ```powershell
   python -m apply_pricing_framework --validate-only
   python -m apply_pricing_framework --results "bruno\results.json"
   ```

Supported check and condition operators are implemented in `engine.py`; follow an existing catalog entry that uses the intended operation. New behavior should be added with an offline unit test.

## Change expected-result rules

Edit only `rules/expected-results.json` for a business-rule change. Each scenario entry should retain:

- A unique scenario ID and exact path(s) relative to `bruno\`.
- A concise expected behavior derived from the source—not captured current output.
- Conditions proving the request actually exercises the scenario.
- Checks for the expected response, including the appropriate `severity` (`critical` or `partial`).
- `design_refs` that identify its source document and case/page.

Do not convert unavailable dependencies, missing results, unresolved conditional crosswalk rules, or mismatched fixture inputs into Pass/Fail results. The engine marks unmet preconditions and dependency failures Blocked; absent mapped executions are Not Run. These statuses are separate from business Fail.

## What Blocked means

Blocked does **not** mean that an expected result is missing or that the API test failed. Runnable scenarios have a design-based expected behavior and source references. A Blocked execution has an expected-result definition, but its captured request/response cannot fairly be compared to it. Common reasons are:

| Block reason | Meaning | Next action |
|---|---|---|
| Dependency response (for example 1301) | The pricing engine did not produce a business result because an upstream member/plan dependency failed. | Resolve the environment/member-plan dependency and rerun; keep the business expectation unchanged. |
| HTTP 500 or “all service levels failed” | The request did not yield a usable pricing response. | Inspect Bruno/API execution and rerun after the execution issue is resolved. |
| Scenario preconditions not met | The payload does not exercise the designed case (for example, an excess scenario has no allowed-over-billed line). | Update/replace the fixture using source-backed data, or correct the scenario mapping; do not weaken the expected rule to match the current payload. |
| Design condition unresolved | Source material does not establish the required behavior (for example, a crosswalk error depends on `ERROR_CD`). | Keep it conditional until design evidence or an approved result is available. |

In the saved report dated 2026-10-16, the 20 Blocked payload executions are 10 dependency-code 1301 responses, 1 HTTP 500, 2 “all service levels failed” responses, and 7 payload/precondition mismatches. A separate DRGOP payload is Blocked while another execution for the same scenario ID is Partial Pass, so payload execution count and scenario ID count differ. AP-SC18 and OTROP-634 are **Not Run**, not Blocked: AP-SC18 is design-pending and OTROP-634 lacks its referenced Bruno payload. Their limitations are stated in the Expected Result cells.

Read the **Expected** and **Actual** columns together: Blocked rows retain the expected business behavior, while Actual explains why that particular run could not be scored. Do not derive expected rules from a dependency-error response or from a fixture that missed its trigger.

## How results are decided

1. Bruno runs the API requests and produces `results.json`. Bruno inline assertions remain independent.
2. The evaluator maps result filenames to the catalog's exact payload paths. Unmapped requests are listed separately and excluded from scenario totals.
3. Input conditions are checked before the expected response. If the payload does not exercise the case, its status is Blocked.
4. Configured checks compare response values, including per-line and claim-level values. APC/direct and grouped calculations derive expected amounts from request service lines rather than hard-coded test amounts.
5. A failed critical check produces Fail. If critical checks pass but a partial-severity check fails, status is Partial Pass. All checks passing produces Pass.
6. Reports show comments only when a check fails; Passed scenarios have empty comments.

`Execution Date & Time` uses a Bruno execution timestamp or the response `Date` header when present. When neither is available, it is explicitly labeled as report-generation time rather than presented as a known execution time.

## Reports

Excel includes Summary, Scenario Results, Unmapped Payloads, and Design Decisions sheets. The Word report contains an execution summary and a readable detail section for each scenario. CSV and Markdown contain the scenario outcomes and clear status counts. Reports contain no request bodies or member/provider identifiers. Each successful report run overwrites the same report filenames with the latest results. Close `TEST-RESULTS.xlsx` and `TEST-RESULTS.docx` before running again; if either file is open and locked, report generation stops with an error rather than silently leaving that report stale.

## Design alignment and limitations

The October 16 scenario document is the requested scenario inventory, but it does not fully specify expected results for every case. The catalog therefore ties each executable check to that document, the retained pricing PDF, and Kishore's detailed scenario guide as applicable. AP-SC18 remains design-pending, and OTROP-634 remains Not Run until its missing payload is added. Any rule not determined by those sources stays conditional or blocked; see `design/TRACEABILITY.md` for the comparison and conflicts.

The neighboring pytest-BDD project remains separate and unchanged. `bruno\update_payload_from_mainframe.py` updates a selected request fixture from its extracted mainframe source; it is separate from the expected-result engine.
