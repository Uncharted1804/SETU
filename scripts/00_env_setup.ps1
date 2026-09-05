<#
    SETU 00_env_setup.ps1
    Sets user-scope environment variables for the 8 GB VRAM resource plan.
    Blueprint sections 6.2 and 12.2.

    Run as your NORMAL user, not as administrator. User-scope variables are
    what the Ollama tray app inherits when it restarts.

    Linux equivalent: put the same KEY=VALUE lines in
    /etc/systemd/system/ollama.service.d/override.conf under [Service] as
    Environment="KEY=VALUE", then: sudo systemctl daemon-reload && sudo systemctl restart ollama
#>

$ErrorActionPreference = 'Stop'

Write-Host "=== SETU environment setup ===" -ForegroundColor Cyan

# HF_HUB_OFFLINE=1 below assumes vendor\models\hf_cache is already proven complete
# (02_fetch_embeddings.py has run successfully at least once on this machine).
# On a from-scratch machine following the documented run order (00 before 02),
# comment this out until after 02 succeeds, or that download will fail offline.
$vars = [ordered]@{
    'OLLAMA_HOST'              = '127.0.0.1:11434'  # loopback only - the R1 claim
    'OLLAMA_MAX_LOADED_MODELS' = '1'                # one resident model (F2)
    'OLLAMA_NUM_PARALLEL'      = '1'                # no per-request VRAM multiplication
    'OLLAMA_FLASH_ATTENTION'   = '1'                # required for KV quantization to apply
    'OLLAMA_KV_CACHE_TYPE'     = 'q8_0'             # ~halves KV cache VRAM
    'OLLAMA_KEEP_ALIVE'        = '10m'              # matches registry keep_alive
    'OLLAMA_NOHISTORY'         = '1'                # CLI hygiene, NOT an air-gap control
    'HF_HUB_DISABLE_TELEMETRY' = '1'
    'HF_HUB_DISABLE_SYMLINKS'  = '1'         # avoids WinError 1314 without Developer Mode/admin
    'HF_HUB_OFFLINE'           = '1'         # set once the embedding cache is proven complete (02_fetch_embeddings.py)
    'TOKENIZERS_PARALLELISM'   = 'false'
}

foreach ($k in $vars.Keys) {
    [Environment]::SetEnvironmentVariable($k, $vars[$k], 'User')
    Set-Item -Path "env:$k" -Value $vars[$k]
    Write-Host ("  set {0,-26} = {1}" -f $k, $vars[$k]) -ForegroundColor Green
}

Write-Host ""
Write-Host "NOTE ON OLLAMA_NO_CLOUD:" -ForegroundColor Yellow
Write-Host "  The blueprint lists OLLAMA_NO_CLOUD=1, but that is not a documented" -ForegroundColor Yellow
Write-Host "  Ollama variable. Do not present it as your air-gap control." -ForegroundColor Yellow
Write-Host "  Instead: sign out of Ollama in the desktop app, disable cloud models" -ForegroundColor Yellow
Write-Host "  in its settings, and rely on the disabled adapter + socket monitor." -ForegroundColor Yellow
Write-Host ""

# Create the runtime directory layout the blueprint expects (section 13)
$root = Split-Path -Parent $PSScriptRoot
$dirs = @(
    'vendor\wheels', 'vendor\installers', 'vendor\tessdata', 'vendor\models',
    'data\runtime', 'data\kb_corpus', 'data\demo_assets',
    'config', 'docs', 'sandbox'
)
foreach ($d in $dirs) {
    $p = Join-Path $root $d
    if (-not (Test-Path $p)) {
        New-Item -ItemType Directory -Path $p -Force | Out-Null
        Write-Host "  created $d" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "ACTION REQUIRED:" -ForegroundColor Cyan
Write-Host "  1. Quit Ollama completely from the system tray (right-click -> Quit)."
Write-Host "  2. Start it again. It reads these variables only at server start."
Write-Host "  3. Verify with:  ollama ps"
Write-Host ""

# Record versions for the freeze record
$versionFile = Join-Path $root 'docs\FROZEN_VERSIONS.txt'
"=== captured $(Get-Date -Format 'yyyy-MM-dd HH:mm') ===" | Out-File $versionFile -Append -Encoding utf8
foreach ($cmd in @('ollama --version', 'docker --version', 'python --version', 'node --version', 'tesseract --version')) {
    try {
        $out = (Invoke-Expression $cmd 2>&1 | Select-Object -First 1)
        "$cmd -> $out" | Out-File $versionFile -Append -Encoding utf8
        Write-Host ("  {0,-22} {1}" -f $cmd, $out) -ForegroundColor DarkGray
    } catch {
        "$cmd -> NOT FOUND" | Out-File $versionFile -Append -Encoding utf8
        Write-Host ("  {0,-22} NOT FOUND" -f $cmd) -ForegroundColor Red
    }
}
Write-Host ""
Write-Host "Versions appended to docs\FROZEN_VERSIONS.txt" -ForegroundColor Green
