# Run the existing Bruno collection -> data-driven Apply Pricing reports
# Usage:
#   cd "C:\Users\c9q4wj\Cigna true apply pricing\bruno"
#   .\run_all_tests.ps1
#
# Outputs:
#   results.json, TEST-RESULTS.xlsx, TEST-RESULTS.docx, TEST-RESULTS.csv,
#   EXECUTION-REPORT.md, TEST-RESULTS.md

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$EnvFile = Join-Path $Root "environments\DEV.bru"
if (-not (Test-Path $EnvFile)) {
    Write-Error "Missing $EnvFile - select/create DEV environment first."
}

Write-Host "=== 1) Update payload and DEV environment dates ===" -ForegroundColor Cyan
$DateScript = Join-Path $Root "_stamp_literal_today.py"
python $DateScript
if ($LASTEXITCODE -ne 0) {
    throw "Date stamping failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "=== 2) Refresh Okta token ===" -ForegroundColor Cyan
bru run "00-Auth" --env-file $EnvFile --sandbox developer
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Auth folder returned non-zero - continuing if token already in DEV.bru"
}

Write-Host ""
Write-Host "=== 3) Run all scenario folders ===" -ForegroundColor Cyan
$ResultsJson = Join-Path $Root "results.json"
$RunResultsJson = Join-Path $Root ("results-run-" + [guid]::NewGuid().ToString("N") + ".json")
try {
    bru run . -r --env-file $EnvFile --sandbox developer --reporter-json $RunResultsJson --output $RunResultsJson -f json
    $BrunoExitCode = $LASTEXITCODE
    if (-not (Test-Path $RunResultsJson) -or (Get-Item $RunResultsJson).Length -eq 0) {
        throw "Bruno did not produce a non-empty results file (exit code $BrunoExitCode); reports cannot be generated."
    }
    Move-Item -Path $RunResultsJson -Destination $ResultsJson -Force
}
finally {
    if (Test-Path $RunResultsJson) {
        Remove-Item -Path $RunResultsJson -Force
    }
}
if ($BrunoExitCode -ne 0) {
    Write-Warning "Bruno returned exit code $BrunoExitCode. Generating reports from the results it produced so failed tests are included."
}

Write-Host ""
Write-Host "=== 4) Evaluate results using the central scenario catalog ===" -ForegroundColor Cyan
$ProjectRoot = Split-Path -Parent $Root
Push-Location $ProjectRoot
try {
    python -m apply_pricing_framework --results "bruno\results.json" --output-dir "bruno"
    if ($LASTEXITCODE -ne 0) {
        throw "Apply Pricing report generation failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "Excel:     $Root\TEST-RESULTS.xlsx"
Write-Host "Word:      $Root\TEST-RESULTS.docx"
Write-Host "CSV:       $Root\TEST-RESULTS.csv"
Write-Host "Markdown:  $Root\EXECUTION-REPORT.md"
if ($BrunoExitCode -ne 0) {
    throw "Bruno collection run failed with exit code $BrunoExitCode. Reports were generated from the available results."
}
