<#
.SYNOPSIS
    Run the CI gate locally, then commit and push the current work to origin/main.

.DESCRIPTION
    Mirrors the check subset in .github/workflows/python-ci.yml before touching the
    remote. Commits are made with the generic public-repository identity required by
    scripts/test_public_repo_privacy.py, without changing the global git config.

.EXAMPLE
    .\scripts\push_to_main.ps1 -Message "Fix options refresh state"

.EXAMPLE
    .\scripts\push_to_main.ps1 -Message "Update theme tokens" -SkipTests
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Message,

    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$env:QT_QPA_PLATFORM = 'offscreen'

$commitName = 'Budget Terminal Maintainers'
$commitEmail = 'maintainers@budget-terminal.invalid'

function Invoke-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE)" }
}

$backendSmokes = @(
    'test_backend_analysis_services', 'test_cache_identifiers', 'test_data_service_transport',
    'test_economic_service', 'test_fundamentals_compare_service', 'test_market_data_foundation',
    'test_persistence_safety', 'test_portfolio_margin_settlement', 'test_quant_analytics'
)

$desktopSmokes = @(
    'test_tab_picker_search', 'test_refresh_control', 'test_batched_render',
    'test_calendar_refresh_async', 'test_dashboard_hidden_page_updates',
    'test_refresh_hidden_result_deferral', 'test_refresh_route_inventory',
    'test_refresh_responsiveness', 'test_navigation_responsiveness',
    'test_bulk_render_responsiveness', 'test_networth_fx_hidden_render',
    'test_portfolio_positions_row_stability', 'test_portfolio_margin_settlement_ui',
    'test_portfolio_editing_safety', 'test_options_refresh_responsiveness',
    'test_charts_refresh_responsiveness', 'test_charts_options_top_volume_page',
    'test_youtube_refresh_responsiveness', 'test_launch_stability'
)

Invoke-Step 'Privacy scan (working tree)' { & $python scripts\test_public_repo_privacy.py --tree-only }
Invoke-Step 'Lint' { & $python -m ruff check budget_terminal.py budget_terminal_app scripts }
Invoke-Step 'Compile' { & $python -m compileall -q budget_terminal.py budget_terminal_app }

if (-not $SkipTests) {
    foreach ($smoke in ($backendSmokes + $desktopSmokes)) {
        Invoke-Step $smoke { & $python "scripts\$smoke.py" }
    }
    Invoke-Step 'test_startup_profile' { & $python scripts\test_startup_profile.py --offscreen }
}

Invoke-Step 'Stage changes' { git add -A }

if ((git diff --cached --name-only).Length -eq 0) {
    Write-Host 'Nothing staged; working tree already matches HEAD.' -ForegroundColor Yellow
} else {
    Invoke-Step 'Commit' {
        git -c "user.name=$commitName" -c "user.email=$commitEmail" commit -m $Message
    }
}

Invoke-Step 'Fetch origin' { git fetch origin main }
Invoke-Step 'Rebase onto origin/main' { git rebase origin/main }
Invoke-Step 'Push' { git push origin HEAD:main }

Write-Host 'Pushed to origin/main.' -ForegroundColor Green
