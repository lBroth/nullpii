<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Local PII sanitization with a reversible in-memory vault. GLiNER ONNX + recognizer pack + adversarial-input preprocessor + base64 decoder. Zero cloud calls after the first model download.

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
| `private_phone` | int'l + IT / FR / ES domestic | model + regex |
| `private_address` | street, city, ZIP | model |
| `private_date` | birth / hire dates | model |
| `private_url` | `http(s)://`, `www.` | model + regex |
| `private_ip` | IPv4, IPv6 (RFC 1918 / 5737 / loopback filtered) | regex post-pass |
| `private_mac` | MAC addresses | regex post-pass |
| `account_number` | IBAN mod-97, cards (Luhn), SSN, MRN, BTC / ETH, DNI / CPF / CF / EIN | model + regex (validated) |
| `secret` | API keys (AWS / GitHub / OpenAI / Anthropic / Stripe / 30+), JWT, PEM, base64-wrapped PII | regex (50+) + base64 |

Add your own via `np.addRecognizer({ id, pattern, label, confidence, validate? })`. Validator-passing matches (`iban97`, `luhn`, `base58check`, `cpf`, `codiceFiscale`) win cross-label dedupe over ML mislabels.

## Benchmark

Mac M5 Pro, IoU ≥ 0.5 macro F1 (sklearn-standard — labels with no gt support are excluded, symmetric for every tool). Cap 5,000 / dataset, `--parallel-tools 1` fair-serial. 16-dataset matrix at [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv).

Two `nullpii` rows are reported:

- **`nullpii-bare`** — the ONNX in this repo + GLiNER decoder + chunking, no post-processing. What you get with the HF model alone.
- **`nullpii`** — the npm package (full runtime): same model + recognizer pack + adversarial preprocessor + base64 decoder + reversible vault.

v0.3.0 bench (in flight — `-` cells still computing):

| Dataset | n | **`nullpii`** | **`nullpii-bare`** | `nemotron-pii-raw` | `gliner-pii-large-v1` | `gliner-onnx-pii-fp32` | `deberta` | `piiranha` | `presidio` | `openai-privacy-filter` |
|---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `presidio-synthetic` | 5,000 | **0.9233** | 0.9045 | 0.7065 | 0.7397 | 0.7292 | 0.5087 | 0.3828 | 0.5746 § | – |
| `isotonic-en-heldout` | 5,000 | **0.7871** | 0.7602 | – | – | – | – | – | 0.4726 | – |
| `isotonic-de-heldout` | 5,000 | **0.7650** | 0.7458 | – | – | – | – | – | 0.4047 | – |
| `isotonic-fr-heldout` | 5,000 | **0.7788** | 0.7555 | – | – | – | – | – | 0.4129 | – |
| `isotonic-it-heldout` | 5,000 | **0.7782** | 0.7569 | – | – | – | – | – | 0.4133 | – |
| `tab-echr` ⚠ | 127 | 0.9254 | **0.9281** | 0.6027 | 0.4634 | 0.5125 | 0.2908 | 0.3163 | 0.7761 | – |
| `nullpii-bench` ⚠ self-authored | 2,271 | **0.5215** | 0.4600 | 0.4276 | 0.2860 | 0.2691 | 0.2609 | 0.2378 | 0.2001 | – |
| `nemotron-pii-test` ⚠ | 5,000 | **0.9543** | 0.9117 | – | – | – | – | – | 0.5222 | – |
| `ai4privacy-400k` ⚠ | 5,000 | 0.6807 | 0.6785 | 0.6797 | 0.6039 | 0.6191 | 0.5169 | **0.9548** ‡ | 0.3982 | – |
| `ai4privacy-300k` ⚠ | 5,000 | **0.5686** | 0.5543 | 0.5742 | 0.2534 | 0.3082 | 0.3065 | 0.3515 | 0.3584 | – |
| `ai4privacy-300k-heldout` | 5,000 | **0.5722** | 0.5614 | – | – | – | – | – | 0.2938 | – |
| `argilla-pii` | 2,000 | **0.7329** | 0.7291 | – | – | – | – | – | 0.4197 | – |
| `isotonic-en` ⚠ | 5,000 | **0.7876** | 0.7640 | 0.7399 | 0.6413 | 0.5907 | 0.7513 | 0.5804 | 0.4779 | – |
| `isotonic-de` ⚠ | 5,000 | **0.7671** | 0.7511 | 0.7037 | 0.6318 | 0.5741 | 0.4879 | 0.5694 | 0.3992 | – |
| `isotonic-fr` ⚠ | 5,000 | **0.7768** | 0.7539 | – | – | – | – | 0.5692 | 0.4146 | – |
| `isotonic-it` ⚠ | 5,000 | **0.7744** | 0.7521 | – | – | – | – | – | 0.4145 | – |
| **OOD (5)** held-out | — | **0.8065** | 0.7846 | – | – | – | – | – | 0.4556 | – |
| **Mixed (7)** OOD + ⚠ in-distribution | — | **0.7828** | 0.7587 | – | – | – | – | – | 0.4649 | – |

Legend:
- **bold** = best of the row
- ⚠ in-distribution row for at least one tool (project-authored / train/test overlap)
- ‡ self-bench on its own training distribution
- § presidio self-bench on Microsoft Presidio Evaluator
- `–` cell still computing in the v0.3.0 bench cycle

Reproduce:

```bash
NULLPII_MODEL_DIR=/path/to/lBroth-nullpii \
  python -u packages/eval/scripts/bench_full.py \
    --tools nullpii,nullpii-bare,deberta,piiranha,presidio,gliner-pii-large-v1,nemotron-pii-raw,openai-privacy-filter \
    --datasets all --backend cpu \
    --out-dir packages/eval/results/$(date +%Y%m%d)-bench
```

### Where the wins live

Concrete inputs where the runtime pipeline recovers PII the bare model misses:

| Surface | Input | Recovers |
|---|---|---|
| base64-wrapped secret | `(base64-encoded) c2stYW50LWFwaTAzLWFCY0RlRmcw…` | `sk-ant-api03-aBcDeFg012345…` |
| HTML-entity-encoded secret | `(html_entity-encoded) &#115;&#107;&#45;&#97;&#110;&#116;…` | `sk-ant-…` |
| double-URL-encoded email | `bob.jones%2540company.io` | `bob.jones@company.io` |
| zero-width-obfuscated address | `221B Baker St`U+200B`re`U+200B`et `U+200B`London` | `221B Baker Street London` |
| spaced-out email | `u s e r . 1 2 3 @ g m a i l . c o m` | `user.123@gmail.com` |
| Italian IBAN in prose | `IT60X0542811101000001023456` | mod-97 validated |
| Stripe live key in code | `api_key = 'sk_live_4eC39HqLyjWDarjtT1zdp7dc'` | matches Stripe regex |

Four layers: base64 decode-then-classify · iterative URL `%XX` + HTML numeric entity decode · zero-width strip with offset remap · 50+ validated regex pack.

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
