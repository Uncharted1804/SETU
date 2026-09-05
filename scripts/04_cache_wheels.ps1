<#
    SETU 04_cache_wheels.ps1
    Creates the venv, compiles an exact lock file, downloads every wheel into
    vendor\wheels\, then proves a clean --no-index install works.

    Blueprint F13. The final verification step is what makes the claim true:
    installing with --no-index means pip is forbidden from touching the network.
#>

$ErrorActionPreference = 'Stop'

$root     = Split-Path -Parent $PSScriptRoot
$venv     = Join-Path $root '.venv'
$wheels   = Join-Path $root 'vendor\wheels'
$reqIn    = Join-Path $root 'backend\requirements.in'
$reqLock  = Join-Path $root 'backend\requirements-lock.txt'

Write-Host "=== SETU dependency cache ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Path $wheels -Force | Out-Null

# --- 1. venv -------------------------------------------------------------
if (-not (Test-Path $venv)) {
    Write-Host "`n[1/5] Creating venv ..." -ForegroundColor Yellow
    python -m venv $venv
} else {
    Write-Host "`n[1/5] venv exists, reusing" -ForegroundColor DarkGray
}
$py = Join-Path $venv 'Scripts\python.exe'

& $py -m pip install --upgrade pip pip-tools

# --- 2. Compile the exact lock -------------------------------------------
Write-Host "`n[2/5] Compiling exact lock file ..." -ForegroundColor Yellow
& $py -m piptools compile `
    --output-file $reqLock `
    --strip-extras `
    --resolver=backtracking `
    $reqIn
if ($LASTEXITCODE -ne 0) { Write-Host "COMPILE FAILED" -ForegroundColor Red; exit 1 }

$pinned = (Get-Content $reqLock | Where-Object { $_ -match '^[a-zA-Z0-9]' -and $_ -match '==' }).Count
Write-Host "  locked $pinned packages to exact versions" -ForegroundColor Green

# --- 3. Install into the venv --------------------------------------------
Write-Host "`n[3/5] Installing into venv ..." -ForegroundColor Yellow
& $py -m pip install -r $reqLock
if ($LASTEXITCODE -ne 0) { Write-Host "INSTALL FAILED" -ForegroundColor Red; exit 1 }

# --- 4. Download every wheel ---------------------------------------------
Write-Host "`n[4/5] Downloading wheels to vendor\wheels ..." -ForegroundColor Yellow
& $py -m pip download -r $reqLock -d $wheels
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Some packages had no wheel and may need a source build." -ForegroundColor Yellow
    Write-Host "  Check the output above; sdists in the cache still work offline" -ForegroundColor Yellow
    Write-Host "  ONLY if build tools are present. Prefer wheel-only packages." -ForegroundColor Yellow
}
$count = (Get-ChildItem $wheels -File).Count
$mb    = ((Get-ChildItem $wheels -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host ("  cached {0} files, {1:N0} MB" -f $count, $mb) -ForegroundColor Green

# --- 5. Prove the offline install ----------------------------------------
Write-Host "`n[5/5] Verifying a clean --no-index install ..." -ForegroundColor Yellow
$testVenv = Join-Path $env:TEMP "setu-offline-test-$(Get-Random)"
python -m venv $testVenv
$testPy = Join-Path $testVenv 'Scripts\python.exe'

& $testPy -m pip install --no-index --find-links $wheels -r $reqLock
$offlineOk = ($LASTEXITCODE -eq 0)

if ($offlineOk) {
    # Import the packages that actually matter for the two demo paths
    & $testPy -c "import fastapi, fitz, docx, openpyxl, chromadb, sentence_transformers, cv2, psutil; print('all critical imports OK')"
    $offlineOk = ($LASTEXITCODE -eq 0)
}

Remove-Item -Recurse -Force $testVenv -ErrorAction SilentlyContinue

if ($offlineOk) {
    Write-Host "`n  OFFLINE INSTALL VERIFIED" -ForegroundColor Green
    Write-Host "  Restore command for a fresh machine:" -ForegroundColor Green
    Write-Host "    pip install --no-index --find-links vendor\wheels -r backend\requirements-lock.txt" -ForegroundColor Green
} else {
    Write-Host "`n  OFFLINE INSTALL FAILED" -ForegroundColor Red
    Write-Host "  Fix this now. On event day there is no network to fall back on." -ForegroundColor Red
    exit 1
}

Write-Host "`nCommit backend\requirements-lock.txt. Do NOT commit vendor\wheels (too large)" -ForegroundColor Cyan
Write-Host "-- put it on the backup drive instead." -ForegroundColor Cyan
