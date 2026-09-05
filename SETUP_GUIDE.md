# SETU — Pre-Event Machine Setup Guide

**Target machine:** NVIDIA RTX 4060 Laptop GPU, 8 GB VRAM, Windows 11 + WSL2
**Covers:** blueprint §15.1 (T−7 → T−1), §6 (models), §10.3 (sandbox image), §12.2 (preflight), §12.6 (model integrity)
**Goal:** every byte SETU needs is on disk and proven to work with the Wi-Fi adapter disabled, before the event starts.

> If you are on Linux instead of Windows, every PowerShell script has an equivalent one-liner noted in the "Linux equivalent" callout inside it. The Docker and Python steps are identical.

---

## 0. Before you touch anything — budget check

| Item | Disk |
|---|---:|
| Primary models (qwen3:8b, qwen2.5-coder:7b, qwen3-vl:4b) | ~13.2 GB |
| Fallback models (qwen3:4b-instruct, qwen2.5-coder:3b, qwen3-vl:2b) | ~6.5 GB |
| Docker Desktop + WSL2 base + `setu-sandbox:py311` | ~6 GB |
| Sandbox image tar export (`docker save`) | ~0.2 GB |
| Python wheels cache (`vendor/wheels/`) | ~1 GB |
| Embedding model + Tesseract data | ~0.2 GB |
| Node modules + frontend build | ~0.5 GB |
| **Free space you should have before starting** | **50 GB** |

Also required:
- NVIDIA driver 550 or newer (`nvidia-smi` must run)
- Windows 11 with virtualization enabled in BIOS (for WSL2)
- An external SSD/USB drive of 64 GB+ for the T−1 backup

**Run everything in this guide while you still have internet.** The point is that afterwards you won't need it.

---

## 1. T−7 — Install the runtimes

### 1.1 Ollama

Download the Windows installer from ollama.com and **keep the installer file**. Copy it into `vendor/installers/`. Per blueprint §6.1, the Ollama version is frozen together with the model tags — if you reinstall on event day with a newer build, your benchmark results are void.

After install, record the version so it goes in your freeze record:

```powershell
ollama --version | Tee-Object -FilePath docs\FROZEN_VERSIONS.txt -Append
```

Qwen3-VL needs a reasonably recent Ollama build. If `ollama pull qwen3-vl:4b` fails with an unknown-architecture error, your Ollama is too old — update once, then re-freeze.

### 1.2 Docker Desktop

Install Docker Desktop with the WSL2 backend. Verify:

```powershell
docker run --rm hello-world
wsl --status
```

Set Docker Desktop to **not** start automatically at login only if you're comfortable starting it manually — otherwise leave autostart on, because a missing Docker daemon kills the coding demo (blueprint risk row: "Docker Desktop unavailable").

### 1.3 Python 3.11 and Node

```powershell
python --version   # want 3.11.x
node --version     # want 20.x LTS
```

Use Python 3.11 specifically, matching the sandbox image, so wheels in your cache are compatible with what you tested.

### 1.4 Tesseract OCR

Install the UB Mannheim Windows build. Keep the installer in `vendor/installers/`. Then:

```powershell
tesseract --version
tesseract --list-langs   # must include 'eng'
```

Copy `eng.traineddata` (and `osd.traineddata`, needed for deskew/orientation detection) into `vendor/tessdata/` so you can restore them offline.

---

## 2. T−7 — Configure Ollama for the 8 GB budget

Run `scripts\00_env_setup.ps1` as your normal user (not admin). It sets, at user scope:

```
OLLAMA_HOST=127.0.0.1:11434     loopback only — this is the R1 claim
OLLAMA_MAX_LOADED_MODELS=1      one resident model (blueprint F2)
OLLAMA_NUM_PARALLEL=1           no concurrent request memory multiplication
OLLAMA_FLASH_ATTENTION=1        required for KV cache quantization to apply
OLLAMA_KV_CACHE_TYPE=q8_0       roughly halves KV cache VRAM
OLLAMA_KEEP_ALIVE=10m           matches registry keep_alive
OLLAMA_NOHISTORY=1              CLI hygiene only, NOT an air-gap control
HF_HUB_OFFLINE=1                set only after §3 finishes downloading
HF_HUB_DISABLE_TELEMETRY=1
```

**One honest correction to the blueprint.** §6.2 lists `OLLAMA_NO_CLOUD=1`. That is not a documented Ollama environment variable, and you should not put it on a slide as your air-gap control — a judge who checks the docs will find nothing. What actually works:

1. Sign out of any Ollama account in the desktop app, and turn off cloud model access in its settings.
2. Never reference a cloud model tag in `config/models.yaml`.
3. Rely on the enforcement layers the blueprint already names in §12.3 — disabled adapter, `--network=none` sandbox, process-scoped socket monitoring, negative control.

The script sets the variable anyway (harmless, and it does no damage if a future Ollama release adds it), but your **claim** should rest on the adapter and the socket monitor. This is exactly the F3/§12.3 argument: configuration is a hint, enforcement is the proof.

After the script runs you must **fully quit and restart Ollama** from the system tray. It reads environment variables only at server start. Verify:

```powershell
ollama ps                                    # should respond, not error
(Invoke-WebRequest http://127.0.0.1:11434).StatusCode   # 200
```

---

## 3. T−7 — Pull and cache everything

Run in this order:

| Script | What it does | Rough time |
|---|---|---|
| `scripts\01_pull_models.ps1` | Pulls 3 primaries + 3 fallbacks, verifies each loads | 30–60 min |
| `scripts\02_fetch_embeddings.py` | Downloads `BAAI/bge-small-en-v1.5` into a local cache dir | 2 min |
| `scripts\03_build_sandbox.ps1` | Builds `setu-sandbox:py311`, exports tar, tests offline load | 5 min |
| `scripts\04_cache_wheels.ps1` | Creates venv, installs, freezes exact lock, downloads all wheels | 10 min |
| `scripts\make_allowlist.py` | Hashes model blobs + image digest into `model_allowlist.json` | 2 min |

The wheel cache is what makes blueprint F13 true. A `requirements.txt` with wildcards does not reproduce offline; `requirements-lock.txt` plus `vendor/wheels/` does.

### Frontend packages

```powershell
cd frontend
npm ci                       # generates/uses package-lock.json
npm run build                # confirm it builds
# then prove it works offline later, in §6
```

Commit `package-lock.json`. Do not delete `node_modules` before the event.

---

## 4. T−5 — The benchmark gate (do not skip this)

This is the single highest-value step in the whole setup, because it is where you find out whether `qwen3:8b` actually fits your 8 GB card under load.

```powershell
python scripts\benchmark_models.py --out docs\BENCHMARKS.md
```

It records, per blueprint §6.5: cold-load time, time to first token, tokens/sec, peak dedicated VRAM (via `nvidia-smi`), and whether `ollama ps` reports **100% GPU** or a CPU/GPU split.

### The number that decides your demo

`ollama ps` printing anything other than `100% GPU` for a model means part of it spilled into system RAM. On a laptop that typically costs you 3–10× throughput, and it is the most common cause of a hackathon demo stalling on stage. If `qwen3:8b` splits, move the reasoning slot to `qwen3:4b-instruct` and say so in `BENCHMARKS.md`. A 4B model that answers in 8 seconds beats an 8B model that answers in 90.

Rough VRAM arithmetic for your card, so you know what to expect:

```
qwen3:8b Q4_K_M weights              ~5.2 GB
KV cache, 8k ctx, q8_0               ~0.6 GB
compute/graph buffers                ~0.5 GB
                                     -------
                                     ~6.3 GB   of 8 GB
```

That leaves under 1.7 GB of headroom. **Chrome with hardware acceleration on will eat most of it.** Before every benchmark run and before the demo: close browsers, Discord, Teams, and any Electron app. Consider putting the laptop display on the integrated GPU so the 4060's VRAM stays free.

Keep the primary only if it fits without spill, starts cleanly 3× in a row, meets the timing budget, and returns valid structured output in 4 of 5 test cases. Otherwise demote to fallback and record the reason. **No model changes after T−3.**

---

## 5. T−5 — Freeze integrity baselines

```powershell
python scripts\make_allowlist.py --out config\model_allowlist.json
```

This walks the Ollama manifest directory, records each model's manifest and layer digests, hashes the actual blob files on disk, and records the `setu-sandbox:py311` image digest. Commit it.

Blueprint F10 is the point here: a manifest cannot verify itself. The allow-list is captured *now*, while you still trust the machine, and `preflight.py` re-checks blob hashes against it later. Your UI should therefore say **"matches approved local baseline"**, not "verified".

---

## 6. T−1 — The offline proof run

This is the rehearsal that matters. Do it exactly this way:

1. **Disable the Wi-Fi adapter** (Settings → Network → Wi-Fi → Disable, or `Disable-NetAdapter -Name "Wi-Fi"` in an admin shell). Unplug Ethernet.
2. Reboot. Confirm the adapter is still down.
3. Set `HF_HUB_OFFLINE=1` if you haven't already.
4. Run the preflight:

```powershell
python scripts\preflight.py
```

It refuses Sovereign Mode if any §12.2 condition fails: non-loopback Ollama host, missing model tags or digests, absent embedding cache, missing Docker image, workspace permission violation, or unindexed corpus.

5. Run the negative control:

```powershell
python scripts\offline_check.py
```

It attempts one ordinary external request (must fail), lists external sockets held by SETU processes (must be zero), and confirms `docker run --network=none` has no network interface. Screenshot this — it's demo evidence, not just a test.

6. Run both demo workflows **three times each**, restarting services between runs.
7. Record one clean screen capture of a successful run as the backup demo.
8. Copy to the external drive: repository, `~/.ollama/models`, `vendor/`, `config/model_allowlist.json`, `setu-sandbox-py311.tar`, embedding cache, Tesseract data, all installers, and the recording.

Re-enable networking afterwards only if you still need it.

---

## 7. Restoring on a different machine

If you have to rebuild on a spare laptop:

```powershell
# 1. Runtimes from vendor\installers\
# 2. Models: copy the saved models dir back to %USERPROFILE%\.ollama\models
# 3. Sandbox image:
docker load -i setu-sandbox-py311.tar
# 4. Python:
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install --no-index --find-links vendor\wheels -r backend\requirements-lock.txt
# 5. Re-run env setup, restart Ollama, run preflight
```

Then re-run the benchmark, because a different GPU invalidates every timing number you recorded.

---

## 8. Setup completion checklist

Tick all of these before you consider setup done:

- [ ] `ollama --version` recorded in `docs/FROZEN_VERSIONS.txt`, installer archived
- [ ] All 6 model tags present in `ollama list`
- [ ] Every model shows `100% GPU` in `ollama ps` at its configured context
- [ ] `docs/BENCHMARKS.md` written; final primary/fallback tags chosen and recorded
- [ ] `config/models.yaml` matches the benchmark decision
- [ ] `config/model_allowlist.json` committed, blob hashes verified once
- [ ] `setu-sandbox:py311` builds, exports, and `docker load`s offline
- [ ] Sandbox runs a real openpyxl script under the full §10.2 flag profile
- [ ] `requirements-lock.txt` installs from `vendor/wheels` with `--no-index`
- [ ] Frontend builds with the adapter disabled
- [ ] Tesseract resolves `eng` + `osd` offline
- [ ] Embedding model loads with `HF_HUB_OFFLINE=1` and `local_files_only=True`
- [ ] `preflight.py` returns all-green with Wi-Fi off
- [ ] `offline_check.py` shows zero external sockets and a failed negative control
- [ ] Both demos ran 3× offline after a reboot
- [ ] Backup drive written and verified by restoring one file from it

---

## 9. Known traps on this exact hardware

| Trap | Symptom | Fix |
|---|---|---|
| Browser holding VRAM | Model silently spills to CPU, 5× slower | Close all Chromium apps; check `nvidia-smi` before demo |
| Windows Update restarts Ollama | Env vars reload, model unloads mid-demo | Pause updates for 7 days before the event |
| Docker Desktop not started | Coding demo dies at first sandbox call | Add a Docker check to preflight; start it in your boot routine |
| `--read-only` + numpy/openpyxl temp writes | `Permission denied` inside sandbox | Keep `--tmpfs /tmp` and pass `-e HOME=/tmp` |
| `keep_alive` too short | Cold reload between demo steps, long pause on stage | 10m keep_alive, and pre-warm the first model before presenting |
| Laptop on battery | GPU clocks throttle, tokens/sec halves | Plugged in, Windows power mode = Best Performance |
| Model swap between agents | 10–20 s gap when router switches specialist | Show it as deliberate scheduling in the UI (blueprint §20 answer), don't hide it |
