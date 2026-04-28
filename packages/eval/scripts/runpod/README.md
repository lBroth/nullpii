# nullpii bench on RunPod (5090) — operator runbook

Full comparison bench of nullpii vs competitors on every dataset,
serial across datasets, **parallel tools within each dataset**.
Designed for sub-12h publishable runs on a 5090 spot pod with
crash-resume (per-`(tool, dataset, idx)` checkpoints).

GPU default: **RTX 5090 32GB Blackwell** — fits 4-6 ML tools
loaded simultaneously. Override `RUNPOD_GPU_TYPE_ID` in `.env`
for 4090 / H100 / etc. (5090 needs CUDA 12.8 image —
`runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04`,
already the default).

## Prerequisites

1. **API key** in `<repo>/.env`:
   ```
   RUNPOD_API_KEY=rpa_…
   ```
   Copy template: `cp .env.example .env` and paste the key.

2. **SSH pubkey** at `~/.ssh/id_ed25519.pub` (or `id_rsa.pub`).
   Generate if missing:
   ```bash
   ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
   ```

3. **Optional** — `HUGGING_FACE_HUB_TOKEN` in `.env` for gated
   datasets (`ai4privacy/*`, `bigcode/bigcode-pii-dataset`).

## Flow

```
launch.sh  →  resume.sh  →  resume.sh tail   →  teardown.sh
   ↑              ↓                                 ↓
  pod up      sync+bench                       pod gone
```

### 1. Spin up pod

```bash
bash packages/eval/scripts/runpod/launch.sh
```

Bids `$0.40/h` on community-cloud 4090. Writes `.runpod-state` with
`POD_ID`, `SSH_HOST`, `SSH_PORT`. ~30-90s to schedule.

### 2. Sync code + start bench

```bash
bash packages/eval/scripts/runpod/resume.sh           # medium (per-dataset defaults, ~1 day)
bash packages/eval/scripts/runpod/resume.sh smoke     # 1k cap per dataset (~1h)
bash packages/eval/scripts/runpod/resume.sh full      # --no-cap, every dataset full (multi-day)
bash packages/eval/scripts/runpod/resume.sh bench-bundled,isotonic-en   # only those two datasets
```

**Modes**
- `smoke` — 1k cap everywhere. CI-style sanity, ~1h on 4090.
- `medium` (default) — per-dataset defaults from `bench_full.py`. Runs full on small ones, caps isotonic/ai4privacy at 30k each, planted at 5k. ~1 day on 4090.
- `full` — `--no-cap`. Includes 200k+ samples per isotonic locale and full ai4privacy. ~5-7 days.
- Any unknown value → passed through to `--datasets` for selective runs.

What it does:
- rsync repo (excludes node_modules, models, .venv)
- copy `.env` (separate scp — gitignored)
- run `setup-on-pod.sh` (idempotent: apt + venv + onnxruntime-gpu + gliner + transformers + spacy)
- pre-fetch nullpii ONNX from HF
- launch `bench-on-pod.sh` in background (`nohup`)

Bench writes to `packages/eval/results/runpod-YYYYMMDD/`:
- `matrix.json` — per-cell F1
- `matrix.csv` — pivot table
- `checkpoints/{tool}-{dataset}.{jsonl,state}` — for resume
- `run.log`

### 3. Watch progress

```bash
bash packages/eval/scripts/runpod/resume.sh tail
```

Or interactive:
```bash
bash packages/eval/scripts/runpod/resume.sh shell
```

### 4. Tear down (pulls results first)

```bash
bash packages/eval/scripts/runpod/teardown.sh             # rsync results back, terminate pod
bash packages/eval/scripts/runpod/teardown.sh --keep-pod  # only pull
bash packages/eval/scripts/runpod/teardown.sh --no-pull   # only terminate
```

## Resume after crash

If the pod dies (spot eviction, OOM, etc.), just call `resume.sh`
again — checkpoints are at `packages/eval/results/runpod-*/checkpoints`
and bench skips finished `(tool, dataset)` cells, then resumes the
in-flight one from last completed sample idx.

If the pod is gone entirely, run `launch.sh` (new pod), then
`resume.sh` rsyncs your last-pulled checkpoints back up and
continues.

## Cost / time estimates

5090 spot ~$0.65/h, parallel-tools=4. Total wall = max-tool
within each dataset (instead of sum), summed across datasets.

| Mode | Samples total | Wall on 5090 | Cost | Wall on 4090 (serial) | Cost (4090) |
|---|---|---|---|---|---|
| smoke  | ~17k    | ~30 min | ~$0.30 | ~1 h    | ~$0.50 |
| medium | ~280k   | ~2 h    | ~$1.50 | ~1 day  | ~$10 |
| full   | ~1.8M   | ~10-12 h | **~$8** | ~5-7 days | ~$50-70 |

Per-tool throughput on 5090 (FP16, parallel within dataset):
- nullpii fp16 ~50 samp/s
- gliner ~80 samp/s
- deberta ~100 samp/s
- piiranha ~100 samp/s
- presidio CPU ~80 samp/s
- regex ~10000 samp/s

`--parallel-tools 4` keeps all GPU tools running concurrently
(nullpii + gliner + deberta + piiranha share VRAM, ~19GB total
peak — fits 32GB with 13GB headroom). Per-tool wall reported in
`matrix.json[ds][tool].wall_s`.

## Disk requirements

Volume mount `/workspace` (RUNPOD_VOLUME_GB):

| item | size |
|---|---|
| nullpii fp16 ONNX | 3 GB |
| gliner-multi_pii | 1.2 GB |
| deberta-pii | 1.5 GB |
| piiranha | 1.5 GB |
| HF dataset cache (isotonic+ai4privacy+bigcode+enron+stackoverflow+thestack) | 15 GB |
| checkpoints (1.8M predictions × 6 tools) | 2-3 GB |
| logs + output JSON | 100 MB |
| **buffer** | 25 GB |
| **total** | **50 GB** |

Default `RUNPOD_VOLUME_GB=75` and `RUNPOD_CONTAINER_GB=30` give
headroom for HF cache pre-fetch and apt deps.

## Tunables (in `.env` or `bench-on-pod.sh`)

| var | default | notes |
|---|---|---|
| `RUNPOD_GPU_TYPE_ID` | `NVIDIA GeForce RTX 5090` | swap to `NVIDIA H100 PCIe` for ~1.5× faster |
| `RUNPOD_VOLUME_GB` | 75 | weights + dataset cache + checkpoints |
| `RUNPOD_CONTAINER_GB` | 40 | apt + venv + system |
| `RUNPOD_BID_PER_GPU` | 0.65 | spot bid USD/h (raise if sniping fails) |
| `OMP_NUM_THREADS` | 8 | ORT CPU thread cap |
| `--pool-size` | 4 | nullpii daemons (4× fp16 = ~12GB VRAM) |
| `--threads-each` | 4 | ORT threads per daemon |
| `--parallel-tools` | 4 | GPU tools concurrent within dataset (1=serial) |
| `--gliner-threshold` | 0.8 | iter-22 best |

## Publishable run protocol

For honest paper / blog numbers:

```bash
# 1. Spin up 5090
bash packages/eval/scripts/runpod/launch.sh

# 2. Smoke test FIRST — verifies parallel ML doesn't crash
bash packages/eval/scripts/runpod/resume.sh smoke

# 3. If smoke passes, run full
bash packages/eval/scripts/runpod/resume.sh full

# 4. Watch
bash packages/eval/scripts/runpod/resume.sh tail

# 5. Pull + tear down
bash packages/eval/scripts/runpod/teardown.sh
```

Outputs in `packages/eval/results/runpod-YYYYMMDD/`:
- `matrix.json` — F1 + wall + samples_per_s per (tool × dataset)
- `matrix.csv` — pivot table
- `confusion.json` — per-label TP/FP/FN per cell (8 labels × 7 tools × 18 datasets)
- `run.log` — full stdout for repro

## Known issues

- **Spot eviction** — RunPod community-cloud spot can preempt at any
  time. Re-launch + resume; checkpoints survive.
- **HF gate** — `bigcode/bigcode-pii-dataset` and ai4privacy require
  `HUGGING_FACE_HUB_TOKEN`. Set in `.env`. Without it, those datasets
  are skipped (logged but not fatal).
- **Slow first boot** — model pre-fetch is ~3 GB nullpii fp16 +
  ~2 GB gliner-multi_pii + ~1 GB deberta + ~1 GB piiranha. Subsequent
  resumes reuse `/root/.cache/huggingface` (volume-mounted).
- **`presidio_evaluator` not installed by default** — synthetic
  generator skips silently. Add to `requirements-eval.txt` if needed.
