# Cigna TRUE Apply Pricing — clean framework workspace

This is the curated, self-contained workspace for running the existing Bruno Apply Pricing collection and generating centralized expected-result reports. The larger source folder remains unchanged; it contains historical extracts, working files, and other projects that are not needed to run this framework.

## Open this folder in VS Code

Open **`Cigna-Apply-Pricing-Framework`** itself as the VS Code folder. From VS Code, choose **File → Open Folder…** and select:

```text
C:\Users\c9q4wj\Cigna true apply pricing\Cigna-Apply-Pricing-Framework
```

The useful contents are:

| Folder/file | Purpose |
|---|---|
| `bruno\` | Bruno collection, requests, collection config, DEV/INT environments, runner, and current report files |
| `apply_pricing_framework\rules\expected-results.json` | Single source of expected-result rules for 36 design scenarios |
| `apply_pricing_framework\design\` | Kishore pricing design PDF, current scenario document, and traceability |
| `apply_pricing_framework\README.md` | Framework rules, status behavior, and how to extend it |
| `bruno\TEST-RESULTS.xlsx` and `bruno\TEST-RESULTS.docx` | Current Excel and Word reports |
| `bruno\EXECUTION-REPORT.md` | Current text report |

## Run from the VS Code terminal

Open **Terminal → New Terminal**. The terminal should start in this framework folder. For the full live Bruno collection run using the included DEV environment:

```powershell
.\bruno\run_all_tests.ps1
```

The runner runs all payloads directly with no prompt: it refreshes request dates, runs the collection, and generates the reports.

To update ONE payload from `DATA-FROM -MAINFRAME` (never runs the collection), pick or enter a payload name or scenario ID:

```powershell
.\bruno\update_payload.ps1
.\bruno\update_payload.ps1 -Payload "AP-013"
```

The updater keeps field names and object shape, and rebuilds `serviceLevel` and `pricingRules` to one entry per distinct source service line. If several source files match, choose one when prompted. Direct equivalent: `python .\bruno\update_payload_from_mainframe.py --payload "AP-013"`.

The selected source export can contain member and claim information. Keep it local and private; do not commit or share updated payloads containing real member data. The runner makes live API calls. Bruno CLI (`bru`) and Python must be available on PATH. Reports are written under `bruno\`: `TEST-RESULTS.xlsx`, `TEST-RESULTS.docx`, `TEST-RESULTS.csv`, `EXECUTION-REPORT.md`, and `TEST-RESULTS.md`. Each successful report run updates these same files using the latest results. Close the Excel and Word reports before running; if a report is open and locked, the runner reports the error instead of silently leaving it stale.

## Run requests from Bruno Desktop

Open the collection in `Cigna-Apply-Pricing-Framework\bruno`, then use the environment selector at the top right and choose **DEV** before sending requests. The collection's pre-request script reads `baseUrl` and the Okta token settings from the selected environment. If Bruno shows **No Environment**, `{{baseUrl}}` is empty and the request can fail with `Invalid URL`.

If **DEV** is not listed, close the currently opened collection and open the collection folder at `Cigna-Apply-Pricing-Framework\bruno` in Bruno Desktop so it loads the adjacent `environments\DEV.bru` file. The PowerShell runner above already supplies that environment file to Bruno CLI.

Before auth and the API run, this runner calls `bruno\_stamp_literal_today.py`. It updates `requestDate`, `claimReceiveDate`, `serviceFromDate`, and `serviceThruDate` in the copied request files and refreshes the DEV environment's `today` value. The Bruno collection pre-request hook also applies today's date at send time. To refresh the visible payload dates without running the API:

```powershell
python .\bruno\_stamp_literal_today.py
```

`bruno\_stamp_today_vars.py` is an alternate utility that changes those payload date literals to `{{today}}` placeholders; use it only if you specifically want variable-based payload text. Do not run it immediately before `_stamp_literal_today.py` unless you want the payloads converted back to literal dates.

To regenerate the reports offline from an existing `bruno\results.json`:

```powershell
python -m apply_pricing_framework --results "bruno\results.json"
```

The raw Bruno `results.json` is intentionally not copied into this clean workspace because it contains full claim/member request and response data. A new live run creates it. If you need offline evaluation, copy a trusted saved results file into `bruno\results.json` yourself; keep it private and do not commit or share it.

To verify the catalog and offline tests:

```powershell
python -m apply_pricing_framework --validate-only
python -m unittest discover -s apply_pricing_framework\tests -v
```

If report generation reports a missing dependency:

```powershell
python -m pip install -r apply_pricing_framework\requirements.txt
```

## Add or update a scenario

1. Add a Bruno `.bru` request under `bruno\` and validate it with Bruno.
2. Create a safe catalog scaffold:

   ```powershell
   python -m apply_pricing_framework add-scenario --id AP-NEW --name "New business case" --payload "09-new-cases\AP-NEW.bru"
   ```

3. Edit `apply_pricing_framework\rules\expected-results.json`: provide the design-backed `expected`, `conditions`, `checks`, and `design_refs`. Keep `readiness: design_pending` until the business behavior and checks are confirmed. Never set an expected value merely to match the current actual response.
4. Validate and produce a report using the commands above.

For an existing scenario, update its catalog entry in that same JSON file. Full documentation, the meaning of Blocked/Fail/Not Run, supported rule operations, and design conflicts are in `apply_pricing_framework\README.md` and `apply_pricing_framework\design\TRACEABILITY.md`.

## Environment and data safety

The original Bruno DEV and INT environment files are included so the collection setup is available. DEV configuration can contain authentication material and is excluded from Git by `.gitignore`; do not publish it. Raw execution JSON is also excluded because it includes full claim/member data. The existing parent project, source data, and Bruno collection are not removed or modified by this curated copy.
