# SETU Benchmark Results

**Captured:** 2026-09-05T01:44:32+00:00  
**Machine:** NVIDIA RTX 4060 Laptop GPU, 8 GB VRAM  
**Runs per model:** 3  
**Gate:** blueprint section 6.5

**GPU reported:** NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB

## Measurements

| Model | Slot | Cold load | TTFT (med) | tok/s (med) | Total (med) | Peak VRAM | Placement | Structured | Tools |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| `qwen3:8b` | reasoning | 8.2s | 5.49s | 43.4 | 7.0s | 6349 MiB | 100% GPU | 5/5 | 5/5 |
| `qwen3:4b-instruct` | reasoning | 4.8s | 0.05s | 74.0 | 3.8s | 4125 MiB | 100% GPU | 5/5 | 5/5 |
| `qwen2.5-coder:7b` | coding | 6.6s | 0.06s | 49.0 | 4.6s | 5554 MiB | 100% GPU | 5/5 | 0/5 |
| `qwen2.5-coder:3b` | coding | 3.8s | 0.04s | 97.0 | 1.8s | 3126 MiB | 100% GPU | 5/5 | 0/5 |
| `qwen3-vl:4b` | vision | 7.8s | — | 73.7 | 4.1s | 5501 MiB | 100% GPU | 2/2 | n/a |
| `qwen3-vl:2b` | vision | 4.8s | — | 149.7 | 2.0s | 3716 MiB | 100% GPU | 2/2 | n/a |

## Gate decisions

### reasoning

- **`qwen3:8b`** — KEEP
- **`qwen3:4b-instruct`** — KEEP

**Selected: `qwen3:8b`**

### coding

- **`qwen2.5-coder:7b`** — KEEP
- **`qwen2.5-coder:3b`** — KEEP

**Selected: `qwen2.5-coder:7b`**

### vision

- **`qwen3-vl:4b`** — KEEP
- **`qwen3-vl:2b`** — KEEP

**Selected: `qwen3-vl:4b`**

> Note: the original 0/5 vision runs (structured output text-only tasks) were a
> benchmark-harness bug, not a model failure: `qwen3-vl` put the correct answer
> in Ollama's `thinking` field while the script only read `response`, and the
> shared STRUCTURED_TASKS list never sent an image in the first place. Fixed in
> `benchmark_models.py` (`extract_json_from_result` fallback + a vision-only
> `VISION_TASKS` list that sends a real image via `images`); re-run above with
> both fixes in place. `qwen2.5-coder`'s 0/5 tool-calling score is unrelated,
> separately diagnosed as a genuine model/template limitation, and does not
> affect this verdict since `verdict()` doesn't gate on `tool_pass`.

> **Caveat — small sample size.** The vision KEEP above rests on only 2
> synthetic test images (`VISION_TASKS`), not 5 varied ones like the
> reasoning/coding slots. Both are self-generated, similarly-formatted
> fixtures, not real scans, and not the chosen demo asset. Recommend
> re-benchmarking the vision slot with a larger, more varied task set (ideally
> including the actual demo scan and a couple of visually distinct samples)
> once that asset is chosen, and before T-3 -- this result should not be
> treated as a high-confidence pass yet.

## Frozen registry values

Copy into `config/models.yaml`:

```yaml
reasoning-primary:
  model: qwen3:8b
  context_limit: 8192
  keep_alive: 10m
coding-primary:
  model: qwen2.5-coder:7b
  context_limit: 8192
  keep_alive: 10m
vision-primary:
  model: qwen3-vl:4b
  context_limit: 4096
  keep_alive: 10m
```

> Blueprint: no model changes after T-3 except an emergency rollback with a recorded reason.
