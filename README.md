<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Local PII sanitization with a reversible in-memory vault. GLiNER ONNX + recognizer pack + adversarial-input preprocessor + base64 decoder.

Night-hobby project. Engineering focus is the runtime pipeline + adversarial preprocessor, not state-of-the-art F1.

## Install

```bash
npm install nullpii onnxruntime-node
```

Node ≥ 22. `onnxruntime-node` is an optional peer (CPU / CoreML / CUDA). First call to `sanitize()` downloads ~1.2 GB from [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) into `~/.cache/nullpii/`. Pre-warm with `npx nullpii prefetch`; verify with `npx nullpii doctor`.

## Usage

```ts
import { sanitize, restore, wrapForLLM } from 'nullpii';

const safe = await sanitize('Email John Smith at john@acme.io about SSN 123-45-6789');
// safe.sanitized → 'Email {{PII_PRIVATE_PERSON_0_…}} at {{PII_PRIVATE_EMAIL_0_…}} about SSN {{PII_ACCOUNT_NUMBER_0_…}}'

// Optional: prefix prompt with the built-in preservation hint
const prompt = wrapForLLM(safe, 'Translate to Italian');

// … LLM call …

const back = restore(reply, safe.sessionId);
// back.restored → original text
```

Long-lived engine (e.g. gateway):

```ts
import { NullPii } from 'nullpii';
const np = new NullPii({ backend: 'auto' });
const { sessionId, sanitized } = await np.sanitize(text);
const { restored } = np.restore(reply, sessionId);
await np.dispose();
```

Streaming restore — buffers placeholders that straddle SSE chunk boundaries:

```ts
import { RestoreStream } from 'nullpii';
const stream = new RestoreStream(np, sessionId);
for await (const chunk of upstreamSse) emit(stream.push(chunk));
emit(stream.end().restored);
```

Placeholders: `{{PII_<LABEL>_<idx>_<sessionPrefix>}}`. The session prefix binds each placeholder to its minting session — `restore()` reports foreign-prefix and unknown-idx placeholders via `RestoreResult.foreignPlaceholders` / `.unknownPlaceholders` and (opt-in) throws under `{ strict: true }`.

## Gateway

`@nullpii/gateway` is a drop-in HTTP proxy for the Anthropic Messages API. The client SDK (Anthropic, Claude Code, anything that speaks the Messages API) flips its `baseURL` to the gateway; nothing else changes. The gateway sanitises every text content block in `system` + `messages` before forwarding, then restores placeholders in the response — streaming-safe (`{{...}}` straddling SSE deltas are buffered + reassembled via `RestoreStream`). Self-hosted, Apache-2.0, multi-arch Docker image (`linux/amd64,linux/arm64`).

### Claude Code quickstart

```bash
# 1. boot the gateway (first run downloads the GLiNER model into a named volume)
docker compose -f examples/claude-code/docker-compose.yml up -d

# 2. point Claude Code at it (or any Anthropic SDK)
export ANTHROPIC_BASE_URL=http://localhost:8787
export ANTHROPIC_API_KEY=sk-ant-…   # your real key, passed through

# 3. use Claude Code normally
claude "summarise the email I just wrote to John Doe at john@acme.io"
```

#### Alternative: persist via Claude Code settings

Prefer a per-project or per-user config file over `export`s? Drop the
same vars into Claude Code's settings file — they're picked up
automatically on every `claude` invocation, no shell wiring needed.

Project-local (checked into the repo, or git-ignored if it holds the key) — `.claude/settings.local.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8787",
    "ANTHROPIC_API_KEY": "sk-ant-…"
  }
}
```

User-global — `~/.claude/settings.json` uses the same shape. Project-local wins on conflict. Add `.claude/settings.local.json` to `.gitignore` if you keep the API key inline.

The gateway sees the raw prompt, runs GLiNER locally, replaces `John Doe` + `john@acme.io` with placeholders, forwards the sanitised text to `api.anthropic.com`, then restores the placeholders in the streamed response before Claude Code prints it.

Verify what's redacted by tailing the structured per-request log — counts only, never values (enforced at the type level by `LogFields` in core):

```bash
docker compose -f examples/claude-code/docker-compose.yml logs -f gateway
# {"msg":"anthropic.messages.streamed","replacements":3,"replacementsByLabel":{"private_person":1,"private_email":1,"private_address":1},...}
```

Full walk-through (host-mounted-model variant for air-gapped / pre-release, GPU notes, troubleshooting, multi-replica caveats): [`examples/claude-code/`](examples/claude-code/).

## What gets caught

| Label | Examples | Source |
|---|---|---|
| `private_person` | names | model |
| `private_email` | emails | model + regex |
| `private_phone` | int'l + IT / FR / ES / HIPAA-fax domestic | model + regex |
| `private_address` | street, city, ZIP | model |
| `private_date` | birth / hire dates | model |
| `private_url` | `http(s)://`, `www.` | model + regex |
| `private_ip` | IPv4, IPv6 (RFC 1918 / 5737 / loopback filtered) | regex post-pass |
| `private_mac` | MAC addresses (broadcast / multicast filtered) | regex post-pass |
| `private_passport` | US / IT / FR / ES / DE / UK + context-anchored generic (30 countries) | model (zero-shot) + regex post-pass |
| `private_driver_license` | US per-state + IT / EU per-country (context-anchored) | model (zero-shot) + regex post-pass |
| `private_vehicle_id` | VIN (ISO 3779 mod-11), plates IT / FR / DE / UK / ES / US | model (zero-shot) + regex (validated) |
| `private_geolocation` | lat/lon decimal pairs (range-validated) + DMS notation | model (zero-shot) + regex (validated) |
| `account_number` | IBAN mod-97, cards (Luhn), SSN, MRN, BTC / ETH, DNI / CPF / CF / EIN, Medicare MBI / HIC, NPI, insurance policy, IMEI | model + regex (validated) |
| `secret` | API keys (AWS / GitHub / OpenAI / Anthropic / Stripe / 30+), JWT, PEM, base64-wrapped PII | regex (50+) + base64 |

Coverage matches HIPAA 18-identifier scrubbing + GDPR Art. 4 identity core + general-purpose PII (passport / driver licence / vehicle / geolocation). Out of scope: GDPR Art. 9 special categories (race / religion / health conditions / political opinions) — those are sentiment-classification problems, not span-extraction.

Add your own via `np.addRecognizer({ id, pattern, label, confidence, validate? })`. Validator-passing matches (`iban97`, `luhn`, `base58check`, `cpf`, `codiceFiscale`, `vin`, `latLonPair`) win cross-label dedupe over ML mislabels.

## Benchmark

Mac M5 Pro, IoU ≥ 0.5 macro F1 (sklearn-standard — labels with no gt support are excluded, symmetric for every tool). Cap 5,000 / dataset, `--parallel-tools 1` fair-serial. 16-dataset matrix at [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv).

Two `nullpii` rows + one upstream-GLiNER row let readers isolate the model from the runtime:

- **`nullpii-bare`** — the published [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) ONNX (project-fine-tuned weights) consumed via the bare `gliner_v2_predictor`: GLiNER decoder + chunking, no recognizer pack, no preprocessor, no base64 decoder, no boundary refine, no never-PII filter. What the HF artifact alone delivers.
- **`gliner-onnx-pii-fp32`** — the unmodified upstream [`onnx-community/gliner_multi_pii-v1`](https://huggingface.co/onnx-community/gliner_multi_pii-v1) ONNX, same bare consumer. Baseline before any project fine-tuning.
- **`nullpii`** — the npm package (full runtime): published model + recognizer pack + adversarial preprocessor + base64 decoder + reversible vault.

v0.3.0 bench (M5 Pro CPU, 2026-05-18 + opf 2026-05-20, full 9×16 matrix). OOD macro for `nullpii` = **0.7784** (presidio-synthetic + isotonic-{en,de,fr,it}-heldout + ai4privacy-300k-heldout + tab-echr).

| Dataset | n | **`nullpii`** | **`nullpii-bare`** | `nemotron-pii-raw` | `gliner-pii-large-v1` | `gliner-onnx-pii-fp32` | `deberta` | `piiranha` | `presidio` | `opf` |
|---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `presidio-synthetic` | 5,000 | **0.9137** | 0.8487 | 0.7154 | 0.6749 | 0.5254 | 0.5111 | 0.3853 | 0.5511 § | 0.6530 |
| `isotonic-en-heldout` | 1,900 | 0.7197 | 0.5969 | **0.7518** | 0.6662 | 0.5485 | 0.6224 | 0.4124 | 0.4472 | 0.4095 |
| `isotonic-de-heldout` | 2,400 | **0.7297** | 0.6191 | 0.7271 | 0.6325 | 0.5432 | 0.3969 | 0.4112 | 0.3859 | 0.4155 |
| `isotonic-fr-heldout` | 2,800 | 0.7254 | 0.6001 | **0.7276** | 0.6663 | 0.5393 | 0.4824 | 0.4172 | 0.4042 | 0.4257 |
| `isotonic-it-heldout` | 2,200 | **0.7395** | 0.6148 | 0.7273 | 0.6605 | 0.5519 | 0.4509 | 0.4176 | 0.4057 | 0.4420 |
| `tab-echr` ⚠ | 127 | 0.9239 | **0.9275** | 0.6026 | 0.6346 | 0.6463 | 0.2908 | 0.3163 | 0.7761 | 0.4166 |
| `nullpii-bench` ⚠ ⚐ self-authored | 2,361 | **0.4228** | 0.3090 | 0.3065 | 0.2851 | 0.2936 | 0.1711 | 0.1669 | 0.1436 | 0.2488 |
| `nemotron-pii-test` ⚠ | 5,000 | 0.8063 | 0.6814 | **0.9286** ‡ | 0.7675 | 0.7352 | 0.4153 | 0.3286 | 0.4236 | 0.4005 |
| `ai4privacy-400k` ⚠ | 5,000 | 0.6410 | 0.6339 | 0.5962 | 0.6624 | 0.6256 | 0.4508 | **0.9532** ‡ | 0.3897 | 0.6367 |
| `ai4privacy-300k` ⚠ | 5,000 | **0.7094** | 0.5303 | 0.6554 | 0.3930 | 0.4691 | 0.3015 | 0.3203 | 0.5553 | 0.4583 |
| `ai4privacy-300k-heldout` | 5,000 | **0.6966** | 0.5241 | 0.6608 | 0.4306 | 0.5131 | 0.2183 | 0.3266 | 0.4882 | 0.4630 |
| `argilla-pii` | 2,096 | 0.6465 | 0.5549 | **0.6820** | 0.6035 | 0.5047 | 0.5694 | 0.4149 | 0.4506 | 0.3939 |
| `isotonic-en` ⚠ | 5,000 | 0.7428 | 0.6226 | **0.7720** | 0.6784 | 0.5573 | 0.6216 | 0.4235 | 0.4535 | 0.4178 |
| `isotonic-de` ⚠ | 5,000 | 0.7293 | 0.6300 | **0.7337** | 0.6510 | 0.5556 | 0.4069 | 0.4144 | 0.3913 | 0.4243 |
| `isotonic-fr` ⚠ | 5,000 | 0.7199 | 0.5970 | **0.7340** | 0.6714 | 0.5503 | 0.4728 | 0.4137 | 0.4029 | 0.4233 |
| `isotonic-it` ⚠ | 5,000 | **0.7306** | 0.6215 | 0.7225 | 0.6647 | 0.5697 | 0.4531 | 0.4137 | 0.4052 | 0.4333 |

Legend:
- **bold** = best F1 in the row
- ⚠ = the dataset overlaps the training distribution of at least one competitor in the row — read those cells with caution
- ⚐ = in-distribution for `nullpii` itself (regression cell, not an OOD claim). The held-out OOD headline is the macro over `presidio-synthetic` + `isotonic-{en,de,fr,it}-heldout` + `ai4privacy-300k-heldout` + `tab-echr`.
- ‡ = competitor benched on its own training distribution (best-case self-report)
- § = Presidio benched on its own evaluator dataset (best-case self-report)

Methodology disclosures (read these before drawing conclusions):

- **Threshold parity** — every GLiNER-family tool (`nullpii`, `nullpii-bare`, `gliner-pii-large-v1`, `gliner-onnx-pii-fp32`) runs at threshold **0.5**. `nemotron-pii-raw` runs at **0.3** per its [upstream model card](https://huggingface.co/nvidia/gliner-pii) which prescribes 0.3 as the production decision boundary. Running nemotron at 0.5 parity would disadvantage it relative to its published characteristic (~0.07 F1 drop avg across the matrix). Both thresholds disclosed for reader mental adjustment.
- **DeBERTa aggregation** — `first` strategy, A/B-logged against `simple` in `adapters.py`. No tuning, just picking the one HuggingFace ships as the documented default.
- **Per-tool chunking** — each tool uses **its upstream maintainers' recommended chunker** (`gliner_multi_pii-v1` model card → 140-word/30 for `nullpii`; `gliner` package default → 1400-char/200 for the upstream GLiNERs; piiranha model-card §Limitations → 1000-char/200 to dodge 256-token truncation). Full breakdown + rationale in [`packages/eval/README.md`](packages/eval/README.md#chunking-strategies). This is NOT hand-tuned in nullpii's favour: forcing a single normalised window would silently truncate piiranha, break DeBERTa's continuation handling, and drop Presidio's NER+anchor coordination — every baseline would lose F1.

Reproduce:

```bash
# CPU run — portable, slower; matches the M5 Pro headline numbers above.
NULLPII_MODEL_DIR=/path/to/lBroth-nullpii \
  python -u packages/eval/scripts/bench_full.py \
    --tools nullpii,nullpii-bare,deberta,piiranha,presidio,gliner-pii-large-v1,gliner-onnx-pii-fp32,nemotron-pii-raw,openai-privacy-filter \
    --datasets all --backend cpu \
    --out-dir packages/eval/results/$(date +%Y%m%d)-bench

# CUDA run — bench_full.py default; what RunPod 4090 / 5090 nodes use.
# `nullpii` itself stays on CPU (onnxruntime CUDA EP can't run the
# GLiNER MoE node on SM_120); transformer baselines benefit from GPU.
NULLPII_MODEL_DIR=/path/to/lBroth-nullpii \
  python -u packages/eval/scripts/bench_full.py \
    --tools nullpii,nullpii-bare,deberta,piiranha,presidio,gliner-pii-large-v1,gliner-onnx-pii-fp32,nemotron-pii-raw,openai-privacy-filter \
    --datasets all \
    --out-dir packages/eval/results/$(date +%Y%m%d)-bench
```

### Where the wins live

Concrete inputs where the runtime pipeline recovers PII the bare model misses:

| Surface | Input | Detected as |
|---|---|---|
| base64-wrapped secret | `(base64-encoded) c2stYW50LWFwaTAzLWFCY0RlRmcw…` | `sk-ant-api03-aBcDeFg012345…` (Anthropic key) |
| HTML-entity-encoded secret | `&#115;&#107;&#45;&#97;&#110;&#116;…` | `sk-ant-…` (Anthropic key) |
| double-URL-encoded email | `bob.jones%2540company.io` | `bob.jones@company.io` (email) |
| zero-width-obfuscated address | `221B Baker St`U+200B`re`U+200B`et `U+200B`London` | `221B Baker Street London` (address) |
| spaced-out email | `u s e r . 1 2 3 @ g m a i l . c o m` | `user.123@gmail.com` (email) |
| Cyrillic-homoglyph email | `pаyments@bank.com` (`а` = U+0430) | `payments@bank.com` (email) |
| fullwidth ASCII email | `ＵＳＥＲ．ＮＡＭＥ＠ｅｘａｍｐｌｅ．ｃｏｍ` | `USER.NAME@example.com` (email) |
| Italian IBAN in prose | `IT60X0542811101000001023456` | `IT60X0542811101000001023456` (account_number, mod-97 verified) |
| Stripe live key in code | `api_key = 'sk_live_4eC39HqLyjWDarjtT1zdp7dc'` | `sk_live_4eC39HqLyjWDarjtT1zdp7dc` (credential, Stripe prefix + regex) |

Five layers: NFKC + `any-ascii` translit (fullwidth, Cyrillic, Greek…) · base64 decode-then-classify · iterative URL `%XX` + HTML numeric entity decode · zero-width strip with offset remap · 50+ validated regex pack.

## Backends

```ts
new NullPii({ backend: 'cpu' });   // ['cpu']
new NullPii({ backend: 'cuda' });  // ['cuda', 'cpu']  — NVIDIA, falls back on CPU
new NullPii({ backend: 'mps' });   // ['coreml', 'cpu'] — Apple Silicon
new NullPii({ backend: 'auto' });  // currently 'cpu'
```

CPU thread tuning: pass `intraOpNumThreads` (parallelism inside a single op) and `interOpNumThreads` (parallelism across ops) to `new NullPii({...})`. Both are forwarded to the underlying ONNX Runtime session config.

## Known limitations

- Not a HIPAA de-identifier. Diagnoses, ICD codes, dosages, biometric / genetic identifiers, implied health attributes — out of scope. Pair with Presidio + a medical NER stack if you need those.
- `private_ip` / `private_mac` come from the regex pack, not the ML model.
- Inputs > 1 MB refused upfront with `TextTooLongError('bytes')`. Chunk upstream.
- Detection is best-effort. Defence in depth, not the sole privacy control.

## Privacy

- Detection **fully local** — no network socket after the first model download (HF Hub only, air-gappable via `modelDir` / `NULLPII_MODEL_DIR`).
- Vault is **in-memory only**, scoped to the `NullPii` instance, cleared on `dispose()`. `destroySession()` purges a single session early.
- Placeholders carry a 16-hex-char session prefix; `restore()` surfaces foreign-prefix + unknown-idx placeholders (default) or throws (`{ strict: true }`).
- Debug logs carry counts and short ids — never PII. See [SECURITY.md](SECURITY.md).

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Runtime tree is 100% permissive (MIT / Apache-2.0 / BSD / ISC / CC0); CI gates via `npm run license-check`. Model weights on HuggingFace are a separate artifact with their own licence (see Credits below).

## Further reading

- [`CHANGELOG.md`](CHANGELOG.md) — release notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, architecture rules, release checklist
- [`packages/eval/README.md`](packages/eval/README.md) — bench harness
- [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md) — dataset schema + licences

## Credits

The detection model builds on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, Zaratiana et al., NAACL 2024, mDeBERTa-v3 base). Model artifact + attribution: [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii). Licence notes: [NOTICE](NOTICE).
