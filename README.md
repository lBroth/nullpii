<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Local PII sanitization with a reversible in-memory vault. Unified GLiNER ONNX + recognizer pack + adversarial-input preprocessor + base64 decoder. Zero cloud calls after the first model download.

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

Placeholders: `{{PII_<LABEL>_<idx>_<sessionPrefix>}}`. The session prefix binds each placeholder to its minting session — `restore()` reports foreign-prefix and unknown-idx placeholders via `RestoreResult.foreignPlaceholders` / `.unknownPlaceholders` and (opt-in) throws under `{ strict: true }`.

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

Mac M5 Pro CPU, IoU ≥ 0.5 macro F1, cap 5,000 / dataset, `--parallel-tools 1` fair-serial. 16-dataset matrix: [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv). Run: `packages/eval/scripts/bench_full.py`.

| Tool | Held-out OOD F1 (5) | Mixed F1 (7) | samp/s | `nullpii-bench` F1 |
|---|---:|---:|---:|---:|
| **`nullpii`** | **0.7907** | **0.7487** | **32.0** | **0.5937** |
| `nemotron-pii-raw` | 0.6877 | 0.6226 | 4.0 | 0.4678 |
| `gliner-pii-large-v1` | 0.5876 | 0.4736 | 5.9 | 0.2769 |
| `deberta` | 0.5601 | 0.4688 | 36.3 | 0.3070 |
| `piiranha` | 0.5296 | 0.4374 | 24.9 | 0.2434 |
| `presidio` | 0.4556 | 0.4249 | 164.5 | 0.2303 |

- **Held-out OOD F1 (5)** — macro over 5 datasets the model never saw during training (`presidio-synthetic`, `isotonic-{en,de,fr,it}-heldout`). Headline.
- **Mixed F1 (7)** — adds two in-distribution diagnostic rows (`tab-echr`, `nullpii-bench`).
- **samp/s** — `Σ n / Σ wall_s` across the 15-dataset canonical surface (same hardware, fair-serial).
- **`nullpii-bench` F1** — project bench corpus (2,421 rows): adversarial-input surface where the runtime pipeline wins over bare ML.

Latency on the same host, `nullpii` only (n=50, model preloaded): **p50 81 ms** at 100 chars, **230 ms** at 1 KB, **2.15 s** at 10 KB.

Reproduce:

```bash
NULLPII_MODEL_DIR=/path/to/lBroth-nullpii \
  python -u packages/eval/scripts/bench_full.py \
    --tools nullpii,deberta,piiranha,presidio,gliner-pii-large-v1,nemotron-pii-raw \
    --datasets all --backend cpu --confusion \
    --out-dir packages/eval/results/$(date +%Y%m%d)-bench
```

### Where the wins live

Real inputs from `packages/eval/results/overnight-local-20260514/checkpoints/` where the runtime pipeline recovers PII the bare models miss:

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

`intraOpNumThreads` / `interOpNumThreads` forward to ORT.

## Known limitations

- **Biometric / genetic identifiers** (GDPR Art. 9, HIPAA #15-18) — no schema class, no detector. Layer a domain-specific pipeline upstream.
- **Free-text clinical content** — `account_number` catches MRN-shaped digit runs; nullpii is not a HIPAA de-identifier for diagnoses, ICD codes, dosages, or implied health attributes. Pair with Presidio + a medical NER stack.
- **`private_ip` / `private_mac` are regex-only** — the ML model is not trained on them.
- **Behavioural / quasi-identifiers** (fingerprints, device IDs, location traces) — out of scope.
- **Inputs > 1 MB** — refused upfront with `TextTooLongError('bytes')`. Chunk upstream.
- **Detection is best-effort** — defence in depth, not the sole privacy control.

## Privacy

- Detection **fully local** — no network socket after the first model download (HF Hub only, air-gappable via `modelDir` / `NULLPII_MODEL_DIR`).
- Vault is **in-memory only**, scoped to the `NullPii` instance, cleared on `dispose()`. `destroySession()` purges a single session early.
- Placeholders carry a 16-hex-char session prefix; `restore()` surfaces foreign-prefix + unknown-idx placeholders (default) or throws (`{ strict: true }`).
- Debug logs carry counts and short ids — never PII. See [SECURITY.md](SECURITY.md).

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Runtime tree is 100% permissive (MIT / Apache-2.0 / BSD / ISC / CC0); CI gates via `npm run license-check`.

Model weights on HuggingFace are a separate artifact with their own licence. v0.2 is trained on a permissive-only corpus; legal attribution lives in [NOTICE](NOTICE) and the [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) model card.

## Further reading

- [`CHANGELOG.md`](CHANGELOG.md) — release notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, architecture rules, release checklist
- [`packages/eval/README.md`](packages/eval/README.md) — bench harness
- [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md) — dataset schema + licences

## Citation

> nullpii contributors (2026). *nullpii: local PII sanitization with reversible vault.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) — GLiNER, Microsoft mDeBERTa-v3 base + GLiNER head, Zaratiana et al., NAACL 2024.
