# Update ONE Bruno payload from DATA-FROM -MAINFRAME (does not run the collection)
# Usage:
#   .\bruno\update_payload.ps1                  # prompts for a payload name
#   .\bruno\update_payload.ps1 -Payload AP-015  # no prompt

param(
    [string]$Payload
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($Payload)) {
    Write-Host "Available payloads:" -ForegroundColor Cyan
    Get-ChildItem -Path $Root -Recurse -Filter "*.bru" |
        Where-Object { $_.Name -notin @("collection.bru", "folder.bru") -and $_.FullName -notmatch "environments|00-Auth" } |
        Sort-Object Name |
        ForEach-Object { Write-Host "  $($_.BaseName)" }
    Write-Host ""
    $Payload = Read-Host "Enter payload name or scenario ID (e.g. AP-015)"
}

if ([string]::IsNullOrWhiteSpace($Payload)) {
    throw "No payload name entered."
}

python (Join-Path $Root "update_payload_from_mainframe.py") --payload "$Payload"
if ($LASTEXITCODE -ne 0) {
    throw "Mainframe payload update failed with exit code $LASTEXITCODE."
}
