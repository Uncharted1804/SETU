<#
    SETU 01_pull_models.ps1
    Pulls the three primary specialists plus their emergency fallbacks,
    then verifies each one actually loads and reports GPU placement.
    Blueprint section 6.1.

    Expect 30-60 minutes on a normal connection. ~20 GB total.
    Safe to re-run: ollama pull is idempotent.
#>

$ErrorActionPreference = 'Continue'

$models = @(
    @{ tag = 'qwen3:8b';            role = 'reasoning primary'; approx = '5.2 GB' },
    @{ tag = 'qwen2.5-coder:7b';    role = 'coding primary';    approx = '4.7 GB' },
    @{ tag = 'qwen3-vl:4b';         role = 'vision primary';    approx = '3.3 GB' },
    @{ tag = 'qwen3:4b-instruct';   role = 'reasoning fallback'; approx = '2.5 GB' },
    @{ tag = 'qwen2.5-coder:3b';    role = 'coding fallback';   approx = '1.9 GB' },
    @{ tag = 'qwen3-vl:2b';         role = 'vision fallback';   approx = '1.8 GB' }
)

Write-Host "=== SETU model pull ===" -ForegroundColor Cyan
Write-Host "Pulling $($models.Count) models, roughly 20 GB total." -ForegroundColor Cyan
Write-Host ""

# Confirm the server is up and on loopback before spending an hour downloading
try {
    $null = Invoke-WebRequest -Uri 'http://127.0.0.1:11434' -UseBasicParsing -TimeoutSec 5
} catch {
    Write-Host "ERROR: Ollama is not responding on 127.0.0.1:11434." -ForegroundColor Red
    Write-Host "Start Ollama from the system tray, then re-run this script." -ForegroundColor Red
    exit 1
}

$failed = @()
foreach ($m in $models) {
    Write-Host "--- $($m.tag)  [$($m.role), ~$($m.approx)]" -ForegroundColor Yellow
    ollama pull $m.tag
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  PULL FAILED: $($m.tag)" -ForegroundColor Red
        $failed += $m.tag
    }
    Write-Host ""
}

if ($failed.Count -gt 0) {
    Write-Host "Failed pulls: $($failed -join ', ')" -ForegroundColor Red
    Write-Host "If a qwen3-vl tag failed with an unknown architecture error," -ForegroundColor Yellow
    Write-Host "your Ollama build is too old. Update once, then re-freeze the version." -ForegroundColor Yellow
}

Write-Host "=== Installed models ===" -ForegroundColor Cyan
ollama list

Write-Host ""
Write-Host "=== Load verification (one model at a time) ===" -ForegroundColor Cyan
Write-Host "Watching for '100% GPU' in ollama ps. A CPU/GPU split means spill." -ForegroundColor Cyan
Write-Host ""

foreach ($m in $models) {
    if ($failed -contains $m.tag) { continue }

    Write-Host "--- loading $($m.tag)" -ForegroundColor Yellow

    # Minimal generation to force a real load into VRAM
    $body = @{
        model   = $m.tag
        prompt  = 'Reply with the single word: ok'
        stream  = $false
        options = @{ num_ctx = 8192; num_predict = 8; temperature = 0 }
    } | ConvertTo-Json -Depth 5

    try {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' `
                                  -Method Post -Body $body -ContentType 'application/json' `
                                  -TimeoutSec 300
        $sw.Stop()
        Write-Host ("  loaded + responded in {0:N1}s" -f $sw.Elapsed.TotalSeconds) -ForegroundColor Green
    } catch {
        Write-Host "  LOAD FAILED: $($_.Exception.Message)" -ForegroundColor Red
        continue
    }

    $ps = (ollama ps | Out-String)
    Write-Host $ps -ForegroundColor DarkGray
    if ($ps -match '100%\s+GPU') {
        Write-Host "  OK: fully on GPU" -ForegroundColor Green
    } elseif ($ps -match 'CPU') {
        Write-Host "  WARNING: CPU/GPU split detected. This model spills at 8k context." -ForegroundColor Red
        Write-Host "  Plan to demote this slot to its fallback (see benchmark_models.py)." -ForegroundColor Red
    }

    # Free VRAM before testing the next one
    $unload = @{ model = $m.tag; keep_alive = 0 } | ConvertTo-Json
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' `
                                  -Method Post -Body $unload -ContentType 'application/json' -TimeoutSec 30
    } catch { }
    Start-Sleep -Seconds 3
    Write-Host ""
}

Write-Host "Done. Next: scripts\02_fetch_embeddings.py" -ForegroundColor Cyan
