<p align="center">
  <img src="https://raw.githubusercontent.com/lBroth/nullpii/main/assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Mask personal data and secrets before they reach an LLM, and put them back on the way out. Detection runs on your machine: a fine-tuned GLiNER model plus validated recognizers, with a reversible in-memory vault.

- **Measured on held-out data.** On five public datasets chosen before any tool was run on them, and absent from the training data nullpii and the compared tools declare, nullpii ranks second on macro char-F2 (0.756) among 15 open-source detectors, behind rizzo-pii (0.770), and lets less personal data through than any other tool's best-scoring configuration (recall 0.960). Its margin over the other 13 rests on one of the five datasets, clinical notes in Greek and German. Scored with the PIIMB leaderboard's own method, it would rank first of 36 (average F2 0.851). It gets there by masking generously: on precision-weighted scores most tools rank above it. [Results](#benchmark).
- **Works with any model.** Mask before your LLM call and restore after it. Or run the gateway in front of the Anthropic or OpenAI API, or the Claude Code mod.
- **Built for coding agents.** It masks tool output (files, logs, command results), not just prompts; it keeps public links to code hosts and documentation readable; and it keeps a hidden value masked where a shell could run it, or in a command that sends data off the machine (best effort: see SECURITY.md).

Status: pre-1.0. The API can still change between minor versions. nullpii pseudonymizes with a measured leak rate; it is not anonymization and not a compliance certification.

## Install

```bash
npm install nullpii onnxruntime-node
```

Node 22 or later. The first run downloads the model from Hugging Face into `~/.cache/nullpii/` (1.2 GB in fp32; on CUDA, 0.6 GB in fp16), at a pinned revision whose files are checked by SHA-256. Pre-fetch it with `npx nullpii prefetch`, or point `NULLPII_MODEL_DIR` at a copy you staged.

## Usage

```ts
import { NullPii, wrapForLLM } from 'nullpii';

const np = new NullPii();
const safe = await np.sanitize('Email John Smith at john@acme.io about SSN 123-45-6789');
// safe.sanitized → 'Email {{PII_PRIVATE_PERSON_0_…}} at {{PII_PRIVATE_EMAIL_0_…}} about SSN {{PII_ACCOUNT_NUMBER_0_…}}'

// Optional: tell the model to keep the placeholders as they are
const prompt = wrapForLLM(safe, 'Translate to Italian');

// … your LLM call: OpenAI, Anthropic, Gemini, Ollama, anything …

const reply = await yourLlm(prompt);            // returns text with the placeholders
const back = np.restore(reply, safe.sessionId);
// back.restored → the reply with the real values

np.destroySession(safe.sessionId); // drop the session's values from memory
await np.dispose();                // when you are done with the engine
```

Keep one engine for the life of your process: loading the model takes about two seconds. The vault lives in memory only. A placeholder is bound to the session that minted it, so a placeholder from one conversation cannot be restored in another, and one value always gets the same placeholder within a session.

Streaming restore, for replies that arrive in chunks:

```ts
import { RestoreStream } from 'nullpii';
const stream = new RestoreStream(np, safe.sessionId);
for await (const chunk of yourLlmStream(prompt)) process.stdout.write(stream.push(chunk));
process.stdout.write(stream.end().restored);
```

`safe.modelUnscannedWords` counts words the model could not read (a single word longer than its input budget, such as a minified blob); the recognizers still scanned them.

## Choose what gets masked

One JSON file sets the policy for the library, the CLI, the gateway and the Claude Code mod: `~/.config/nullpii/config.json`, or the file `NULLPII_CONFIG` names.

```json
{
  "disabledCategories": ["private_organization", "private_occupation"],
  "urlAllowlist": { "hosts": { "*.github.com": "host" } }
}
```

- `disabledCategories`: categories left readable.
- `categoryThresholds`, `threshold`: confidence cuts in `[0, 1]`; lower masks more.
- `urlAllowlist`: how much of a clean URL stays readable on each host (`full`, `host` or `mask`), or `"none"` to mask every URL. Code hosts, package registries and documentation stay readable by default; a URL with a credential in its query never does.
- `restoreTools`: the tools whose arguments get real values back (gateway and mod).

`npx nullpii config` validates the file and prints it. In code, `resolveConfigFile()` and `toEngineConfig()` load it, or pass the same options to `new NullPii({...})`.

## Gateway

An HTTP proxy for the Anthropic Messages API (`/v1/messages`) and the OpenAI Chat Completions API (`/v1/chat/completions`). Point your client's base URL at it and work as before: requests are masked before they leave your machine, and responses, streaming included, are restored before they reach you.

```bash
docker compose -f examples/claude-code/docker-compose.yml up -d   # listens on 127.0.0.1:8787
export ANTHROPIC_BASE_URL=http://localhost:8787
claude
```

Your API key or Claude subscription login is passed through unchanged. For clients of the OpenAI Chat Completions API (the OpenAI SDKs, Aider, LiteLLM), set `OPENAI_BASE_URL=http://localhost:8787/v1`. The Responses API is not proxied.

- Real values go back only into the tools listed in the policy's `restoreTools`, by default the tools that run on your machine (`Bash`, `Read`, `Edit`, `Write`, …). Web and MCP tools, and tools the upstream runs itself, keep the placeholders.
- The request log carries counts, never values.
- The gateway has no authentication of its own: keep it on `127.0.0.1`.

Details, the full list of scanned fields, and the sidecar API: [`packages/gateway`](https://github.com/lBroth/nullpii/tree/main/packages/gateway). A worked Claude Code setup: [`examples/claude-code`](https://github.com/lBroth/nullpii/tree/main/examples/claude-code).

## Claude Code mod

[`packages/claude-code-mod`](https://github.com/lBroth/nullpii/tree/main/packages/claude-code-mod) masks inside Claude Code itself:

- prompts, tool results, @-mentioned files and `CLAUDE.md` are masked before Claude reads them;
- your prompts and Claude's replies are drawn on screen with the real values;
- real values go back only into the tools the policy lists;
- a band above the prompt shows what was masked, by type, and `/pii` shows the counts and the policy in effect.

It talks to the gateway's local sidecar and fails closed when the sidecar is down: nothing is sent unmasked.

## What gets caught

| Label | Examples | Source |
|---|---|---|
| `private_person` | names | model |
| `private_email` | emails | model + regex |
| `private_phone` | international and IT / FR / ES / US formats | model + regex |
| `private_address` | street, city, postcode | model |
| `private_date` | birth and other personal dates | model |
| `private_url` | `http(s)://`, `www.` | model + regex |
| `private_ip` | IPv4, IPv6 (private, documentation and loopback ranges left alone) | regex |
| `private_mac` | MAC addresses (broadcast and multicast left alone) | regex |
| `private_passport` | US / IT / FR / ES / DE / UK, and a context-anchored generic form | model + regex |
| `private_driver_license` | US states, IT and EU countries, context-anchored | model + regex |
| `private_vehicle_id` | VIN (checksum), plates IT / FR / DE / UK / ES / US | model + regex |
| `private_geolocation` | coordinate pairs (range-checked), DMS notation | model + regex |
| `account_number` | IBAN (mod-97), cards (Luhn), SSN, MRN, crypto addresses, national and tax ids (DNI, CPF, EIN, codice fiscale, Partita IVA), Medicare, NPI, insurance policy, IMEI | model + regex (validated) |
| `secret` | API keys (AWS, GitHub, OpenAI, Anthropic, Stripe and 30+ more), JWTs, private keys, passwords and PINs in context, base64-wrapped values | model + regex + base64 |
| `private_organization` | employers, company names | model |
| `private_occupation` | job titles, employment status, education | model |
| `private_demographic` | gender, age, ethnicity, nationality, language | model |
| `private_sensitive` | religion, political views, sexual orientation, health, when stated | model |
| `private_title` | honorifics and titles before a name | model |

The last five categories are on by default; turn off the ones your text needs readable (`disabledCategories`). They find what is written out: nullpii does not infer a health condition or a belief from indirect wording. Add your own patterns with `np.addRecognizer({ id, pattern, label, confidence, validate? })`.

Obfuscated input is decoded before detection: Unicode look-alikes and fullwidth characters, zero-width characters, spaced-out text, percent-encoding (two levels deep), HTML entities, and base64 blobs.

## Benchmark

How the numbers are produced, and every rule that keeps them honest: [`packages/eval/METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md).

- **Metric:** character level and label-agnostic. A character of personal data counts as protected if any span covers it, whatever the label. F2 counts recall as twice as important as precision (β = 2), because a missed character leaks; F0.5, which favours precision, is shown next to it.
- **Data:** five public datasets, chosen by written criteria and frozen before any tool ran on them, none in the training or tuning data nullpii and the compared tools declare (measured overlap with the known sets under 1%): REDACT, TonicAI's human-annotated Privacy-Bench, PIILO student essays, Greek and German clinical notes, and synthetic coding-agent traces from an independent generator.
- **Competitors:** each runs as its authors ship it, at its default and at an operating point tuned on the same tuning set as nullpii; each is shown at its better row.
- **Confidence:** paired bootstrap, 95% intervals of nullpii minus the tool.

<!-- matrix:begin -->
| Tool | Macro char-F2 | F0.5 | Recall | Precision | CI of nullpii − tool (F2) |
|---|---:|---:|---:|---:|---|
| rizzo-pii (default) | 0.770 | 0.633 | 0.869 | 0.608 | [−0.021, −0.005] |
| **nullpii** | **0.756** | 0.529 | **0.960** | 0.485 | — |
| nemotron-pii (`nvidia/gliner-PII`, library) | 0.720 | 0.612 | 0.808 | 0.591 | [+0.024, +0.050] |
| OpenMed privacy-filter-multilingual-v2 | 0.717 | 0.585 | 0.841 | 0.560 | [+0.030, +0.048] |
| pii-identifier | 0.701 | 0.583 | 0.809 | 0.569 | [+0.043, +0.069] |
| ettin-68m | 0.699 | 0.563 | 0.825 | 0.545 | [+0.049, +0.067] |
| openai privacy-filter | 0.693 | 0.591 | 0.767 | 0.587 | [+0.051, +0.077] |
| OpenMed PII Large | 0.682 | 0.587 | 0.783 | 0.578 | [+0.059, +0.088] |
| OpenMed PII Small | 0.673 | 0.512 | 0.807 | 0.478 | [+0.068, +0.098] |
| gliner-pii-large | 0.656 | 0.571 | 0.811 | 0.555 | [+0.084, +0.118] |
| piiranha | 0.651 | 0.465 | 0.840 | 0.428 | [+0.091, +0.119] |
| gliner_multi_pii (ONNX) | 0.648 | 0.495 | 0.845 | 0.462 | [+0.097, +0.120] |
| Presidio | 0.628 | 0.492 | 0.790 | 0.465 | [+0.115, +0.141] |
| gliner-stream-pii | 0.568 | 0.522 | 0.714 | 0.528 | [+0.174, +0.202] |
| deberta PII (default) | 0.464 | 0.254 | 0.802 | 0.225 | [+0.281, +0.303] |
| mask everything | 0.260 | | | | |
<!-- matrix:end -->

nullpii is measured with its five extended categories off, as the datasets do not label them. Its default configuration, which masks them too, scores 0.747 counted on the same labels and 0.653 as shipped, since masking organisations, occupations and the like counts as over-masking here.

**Where nullpii is not ahead.**
- **One dataset carries the margin over the rest.** Without the Greek and German clinical notes, nullpii is third (0.724): openai's privacy-filter (+0.032) and rizzo-pii (+0.029) are ahead, and pii-identifier, OpenMed privacy-filter-multilingual-v2 and ettin-68m come within 0.012. Without the student essays, nullpii is first (0.844, rizzo-pii 0.037 behind).
- **rizzo-pii is significantly ahead, on student essays.** On PIILO nullpii scores 0.407 against rizzo-pii's 0.623, with higher recall and much lower precision: it masks a lot the gold does not label. On the other four datasets nullpii is ahead of rizzo-pii.
- **Precision.** nullpii's recall is the highest of any tool's best-scoring row (only rizzo-pii tuned for recall goes higher, 0.967, at F2 0.583), and its precision is among the lowest. Ranked by F0.5, most tools are ahead of it.
- **Per dataset.** On PIILO, 8 of the 14 tools are ahead of nullpii; on Tonic, three are, by up to 0.008; on the clinical notes, gliner_multi_pii (0.913 against 0.887).
- **English documents only.** nullpii is fifth (0.713), behind openai's privacy-filter (0.746), rizzo-pii (0.742), OpenMed's privacy-filter-multilingual-v2 (0.717) and pii-identifier (0.714).
- **PIIMB** ([leaderboard](https://huggingface.co/spaces/piimb/pii-masking-benchmark-leaderboard), `sentences` subset, scored by us with the leaderboard's method, not a submitted entry): average F2 0.851, above all 35 listed tools; OpenMed's privacy-filter-multilingual-v2 is next at 0.836. One of the six tasks, nemotron-pii, is from nullpii's training family; without it nullpii averages 0.831, against gliner-stream-pii's 0.826 and privacy-filter-multilingual-v2's 0.822, a lead the leaderboard's lack of intervals cannot call significant. nullpii trails on the ai4privacy and Gretel tasks, and on privy, where it over-masks.

The three reported (not gated) sets, the per-dataset numbers and the sensitivity checks are in [`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md).

### Latency

<!-- latency:begin -->
Latency tables are added from the final runs.
<!-- latency:end -->

## Backends

```ts
new NullPii({ backend: 'cpu' });   // ONNX Runtime on the CPU (the default)
new NullPii({ backend: 'cuda' });  // NVIDIA GPU, fp16 when the model ships it; falls back to the CPU
new NullPii({ backend: 'mps' });   // Apple Silicon through CoreML
```

`intraOpNumThreads` and `interOpNumThreads` are passed to ONNX Runtime.

## What it doesn't do

- **It does not catch everything.** Detection is statistical; the benchmark shows the leak rate. Don't make it your only privacy control.
- **It is not a HIPAA or GDPR tool.** It finds explicit spans, not facts inferred from context.
- **Images and other binary attachments** pass through the gateway unscanned, and are counted.
- **Inputs over 1,000,000 characters are refused.** Split them yourself.

## Privacy and security

- Detection runs on your machine. nullpii sends your text nowhere; its one network call is the model download.
- The vault lives in memory and is never written to disk.
- Logs carry counts and short ids, never values. The exception is the gateway's `NULLPII_LOG_TRAFFIC=wire` debugging dump, which prints what was sent upstream, including anything the detector missed (see SECURITY.md).
- Restoring a value into a shell command can inject, because the model never saw the value. The gateway keeps the placeholder, and the mod refuses the call, where the value is unsafe or the command sends data off the machine. This is best effort; if you call `restore()` yourself, read [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md).

Report a vulnerability privately: [security advisories](https://github.com/lBroth/nullpii/security/advisories/new).

## License

Apache-2.0: see [LICENSE](https://github.com/lBroth/nullpii/blob/main/LICENSE) and [NOTICE](https://github.com/lBroth/nullpii/blob/main/NOTICE). What the model was trained on, and the attributions it carries: [`docs/WEIGHTS_PROVENANCE.md`](https://github.com/lBroth/nullpii/blob/main/docs/WEIGHTS_PROVENANCE.md).

## Credits

The detection model builds on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, Zaratiana et al., NAACL 2024, on Microsoft mDeBERTa-v3 base). Training data credits: NVIDIA (Nemotron-PII), the Allen Institute for AI and Common Crawl (C4), Microsoft (presidio-research) and Norsk Regnesentral (TAB).
