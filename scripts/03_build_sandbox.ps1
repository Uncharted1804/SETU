<#
    SETU 03_build_sandbox.ps1
    Builds setu-sandbox:py311, runs it under the EXACT security profile from
    blueprint section 10.2, then exports a tar and proves it loads offline.

    The test is the important part. It writes a real .xlsx with openpyxl under
    --read-only + --network=none + --user=65534, which is precisely where the
    stock python:3.11-slim image fails (F5).
#>

$ErrorActionPreference = 'Stop'

$root      = Split-Path -Parent $PSScriptRoot
$imageName = 'setu-sandbox:py311'
$tarPath   = Join-Path $root 'vendor\setu-sandbox-py311.tar'

Write-Host "=== SETU sandbox image build ===" -ForegroundColor Cyan

# --- 0. Docker must be running -------------------------------------------
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker info failed" }
} catch {
    Write-Host "ERROR: Docker daemon is not running. Start Docker Desktop." -ForegroundColor Red
    exit 1
}

# --- 1. Build ------------------------------------------------------------
Write-Host "`n[1/4] Building $imageName ..." -ForegroundColor Yellow
docker build -t $imageName (Join-Path $root 'sandbox')
if ($LASTEXITCODE -ne 0) { Write-Host "BUILD FAILED" -ForegroundColor Red; exit 1 }

$size = docker image inspect $imageName --format '{{.Size}}'
Write-Host ("  built, {0:N0} MB" -f ($size / 1MB)) -ForegroundColor Green

# --- 2. Test under the real run profile ----------------------------------
Write-Host "`n[2/4] Testing under the section 10.2 security profile ..." -ForegroundColor Yellow

$testDir = Join-Path $env:TEMP "setu-sandbox-test-$(Get-Random)"
$src = Join-Path $testDir 'src'; $inp = Join-Path $testDir 'input'; $out = Join-Path $testDir 'output'
New-Item -ItemType Directory -Path $src, $inp, $out -Force | Out-Null

@'
import sys, os, socket
import openpyxl
import numpy as np

print("python:", sys.version.split()[0])
print("openpyxl:", openpyxl.__version__)
print("numpy:", np.__version__)
print("uid:", os.getuid(), "gid:", os.getgid())

# Prove /out is writable and inputs are not
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Results"
ws.append(["reading", "value", "unit"])
for i, v in enumerate(np.array([12.4, 13.1, 11.8, 14.2]), start=1):
    ws.append([f"r{i}", float(v), "mm/s"])
ws.append(["mean", float(np.mean([12.4, 13.1, 11.8, 14.2])), "mm/s"])
wb.save("/out/result.xlsx")
print("wrote /out/result.xlsx")

# Prove inputs are read-only
try:
    open("/input/should_fail.txt", "w").close()
    print("FAIL: input mount was writable")
    sys.exit(2)
except OSError:
    print("OK: /input is read-only")

# Prove there is no network
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3)
    print("FAIL: network reachable")
    sys.exit(3)
except OSError:
    print("OK: no network reachable")
'@ | Set-Content -Path (Join-Path $src 'main.py') -Encoding utf8

'reference data' | Set-Content -Path (Join-Path $inp 'ref.txt') -Encoding utf8

# Exactly the fixed profile from the blueprint. The code agent never controls these.
docker run --rm `
    --network=none `
    --read-only `
    --tmpfs /tmp:rw,noexec,nosuid,size=64m `
    --memory=512m --memory-swap=512m `
    --cpus=1 --pids-limit=64 `
    --cap-drop=ALL `
    --security-opt=no-new-privileges `
    --user=65534:65534 `
    -e PYTHONDONTWRITEBYTECODE=1 `
    -e HOME=/tmp `
    -v "${inp}:/input:ro" `
    -v "${src}:/src:ro" `
    -v "${out}:/out:rw" `
    -w /src `
    $imageName `
    main.py

$testExit = $LASTEXITCODE
$produced = Join-Path $out 'result.xlsx'

if ($testExit -eq 0 -and (Test-Path $produced)) {
    Write-Host "  SANDBOX TEST PASSED" -ForegroundColor Green
    Write-Host ("  artifact: {0:N0} bytes" -f (Get-Item $produced).Length) -ForegroundColor Green
} else {
    Write-Host "  SANDBOX TEST FAILED (exit $testExit)" -ForegroundColor Red
    Write-Host "  Do not proceed. The spreadsheet demo depends on this." -ForegroundColor Red
    Remove-Item -Recurse -Force $testDir -ErrorAction SilentlyContinue
    exit 1
}
Remove-Item -Recurse -Force $testDir -ErrorAction SilentlyContinue

# --- 3. Export -----------------------------------------------------------
Write-Host "`n[3/4] Exporting to $tarPath ..." -ForegroundColor Yellow
docker save -o $tarPath $imageName
if ($LASTEXITCODE -ne 0) { Write-Host "SAVE FAILED" -ForegroundColor Red; exit 1 }
Write-Host ("  exported, {0:N0} MB" -f ((Get-Item $tarPath).Length / 1MB)) -ForegroundColor Green

# --- 4. Prove the tar reloads (blueprint: test docker load offline) ------
Write-Host "`n[4/4] Verifying docker load round-trip ..." -ForegroundColor Yellow
$digest = docker image inspect $imageName --format '{{index .RepoDigests 0}}' 2>$null
if (-not $digest) { $digest = docker image inspect $imageName --format '{{.Id}}' }

docker rmi $imageName 2>&1 | Out-Null
docker load -i $tarPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "  LOAD FAILED - your backup image is not restorable!" -ForegroundColor Red
    exit 1
}
$digest2 = docker image inspect $imageName --format '{{.Id}}'
Write-Host "  reload OK, image id $digest2" -ForegroundColor Green

# Record for the integrity allow-list (blueprint 12.6)
$root_cfg = Join-Path $root 'config'
New-Item -ItemType Directory -Path $root_cfg -Force | Out-Null
@{
    image       = $imageName
    image_id    = $digest2
    tar_path    = $tarPath
    tar_sha256  = (Get-FileHash $tarPath -Algorithm SHA256).Hash.ToLower()
    captured_at = (Get-Date -Format 'o')
} | ConvertTo-Json | Set-Content (Join-Path $root_cfg 'sandbox_image.json') -Encoding utf8

Write-Host "`nRecorded config\sandbox_image.json" -ForegroundColor Green
Write-Host "Done. Next: scripts\04_cache_wheels.ps1" -ForegroundColor Cyan
