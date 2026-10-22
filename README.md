<p align="center">
  <img src="https://raw.githubusercontent.com/lBroth/nullpii/main/assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Mask personal data and secrets before they reach an LLM, and put them back on the way out. Detection runs on your machine: a fine-tuned GLiNER model plus validated recognizers, with a reversible in-memory vault.

- **Measured on held-out data.** On five datasets chosen before any tool was run on them (four public sets and a synthetic coding-agent trace set built for this benchmark), with under 1% measured overlap with nullpii's training data and the public training sets the compared tools declare (a few declared sets were not compared; METHOD.md), nullpii ranks second on macro char-F2 among 15 open-source detectors, behind rizzo-pii (0.770): 0.756 with its five extended categories off, as the datasets do not label them, and 0.747 for its default configuration counted on the same labels. It lets less personal data through than any other tool's best-scoring configuration (recall 0.960). Much of its lead over the other 13 comes from one dataset, clinical notes in Greek and German: without it nullpii is third, and three more tools are within the interval. On English text alone it is fifth. Scored by us with the PIIMB leaderboard's method (not a submitted entry), its average F2 of 0.851 is above the 35 listed tools; without the one task from its training family it is 0.831, not clearly ahead. It gets there by masking generously: on precision-weighted scores most tools rank above it. [Results](#benchmark).
- **Works with any model.** Mask before your LLM call and restore after it. Or run the gateway in front of the Anthropic or OpenAI API, or the Claude Code mod.
- **Built for coding agents.** It masks tool output (files, logs, command results), not just prompts; it keeps public links to code hosts and documentation readable; and it keeps a hidden value masked where a shell could run it, or in a command that sends data off the machine (best effort: see SECURITY.md).

Status: pre-1.0. The API can still change between minor versions. nullpii pseudonymizes with a measured leak rate; it is not anonymization and not a compliance certification.

Documentation: [lbroth.github.io/nullpii](https://lbroth.github.io/nullpii/).

## Install

```bash
npm install nullpii onnxruntime-node
```

Node 22 or later. The first run downloads the model from Hugging Face into `~/.cache/nullpii/` (1.2 GB in fp32; on CUDA, 0.6 GB in fp16), and every file is checked against a SHA-256 pinned in the library. Pre-fetch it with `npx nullpii prefetch`, or point `NULLPII_MODEL_DIR` at a copy you staged.

On Linux x64, `onnxruntime-node`'s install script also downloads its CUDA execution provider from NuGet, without checking a hash. The CPU runtime is already in the npm package, so on a machine without an NVIDIA GPU skip that download:

```bash
ONNXRUNTIME_NODE_INSTALL=skip npm install nullpii onnxruntime-node
```

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

Keep one engine for the life of your process: loading the model (a file of about 1.2 GB) is its slowest step. The vault lives in memory only. A placeholder is bound to the session that minted it, so a placeholder from one conversation cannot be restored in another, and one value always gets the same placeholder within a session. Once a session has masked a value, every occurrence of it in that session's later calls is masked too, as a whole word of three characters or more, even where the detector misses it: a value restored into a tool call and echoed back in the tool's output stays masked.

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
- `urlAllowlist`: how much of a clean URL stays readable on each host (`full`, `host` or `mask`), or `"none"` to mask every URL. Code hosts, package registries and documentation stay readable by default; a URL with a credential in its query never does. A code-host URL can name a person or a private repository (`github.com/<user>/<repo>`): set that host to `host` or `mask` if that matters to you.
- `restoreTools`: the tools whose arguments get real values back (gateway and mod).

`npx nullpii config` validates the file and prints it. In code, `resolveConfigFile()` and `toEngineConfig()` load it, or pass the same options to `new NullPii({...})`.

## Gateway

An HTTP proxy for the Anthropic Messages API (`/v1/messages`) and the OpenAI Chat Completions API (`/v1/chat/completions`). Point your client's base URL at it and work as before: requests are masked before they leave your machine, and responses, streaming included, are restored before they reach you.

```bash
git clone https://github.com/lBroth/nullpii.git && cd nullpii
docker compose -f examples/claude-code/docker-compose.yml up -d   # listens on 127.0.0.1:8787
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
claude
```

The first request downloads the model (1.2 GB) into the container's cache volume and waits for it; [`examples/claude-code`](https://github.com/lBroth/nullpii/tree/main/examples/claude-code) shows how to fetch it beforehand. The image is also published as `ghcr.io/lbroth/nullpii-gateway`.

Your API key or Claude subscription login is passed through unchanged. For clients of the OpenAI Chat Completions API (the OpenAI SDKs, Aider, LiteLLM), set `OPENAI_BASE_URL=http://127.0.0.1:8787/v1`. The Responses API is not proxied.

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

With the gateway running and its sidecar token at hand ([set up](https://github.com/lBroth/nullpii/tree/main/packages/claude-code-mod#set-up)), install it at the prompt of a Claude Code session:

```text
/plugin marketplace add lBroth/nullpii@v0.5.0
/plugin install nullpii@nullpii
```

or from a shell with `claude plugin marketplace add lBroth/nullpii@v0.5.0`, then `claude plugin install nullpii@nullpii`. The `@v0.5.0` pins the mod to the release: without it you get whatever `main` holds.

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
- **Data:** five datasets, chosen by written criteria and frozen before any tool ran on them, with under 1% measured overlap with nullpii's training and tuning data and the public training sets the compared tools declare (several tools declare none, and a few declared sets were not compared): four public sets, REDACT, TonicAI's human-annotated Privacy-Bench, PIILO student essays and Greek and German clinical notes, and a synthetic coding-agent trace set built for this benchmark, from a generator written independently of nullpii to a specification we wrote.
- **Competitors:** each runs as its authors ship it (the few departures, such as windowing long texts, are listed in METHOD.md), at its default and at an operating point tuned on the same tuning set as nullpii; each is shown at its better row.
- **Confidence:** paired bootstrap, 95% intervals of nullpii minus the tool, the test fixed before the run; intervals corrected for multiple comparisons (Bonferroni, 99.67%), a check added afterwards, are in METHOD.md.

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
- **One dataset carries much of the lead.** Without the Greek and German clinical notes, nullpii is third (0.723): openai's privacy-filter (+0.032) and rizzo-pii (+0.028) are significantly ahead, and pii-identifier, OpenMed privacy-filter-multilingual-v2 and OpenMed large are within the confidence interval. Without the student essays, nullpii is first (0.844, rizzo-pii 0.037 behind).
- **rizzo-pii is ahead, on student essays.** On PIILO nullpii scores 0.407 against rizzo-pii's 0.623, with higher recall and much lower precision: it masks a lot the gold does not label. On the other four datasets nullpii is ahead of rizzo-pii. Over all five the gap, −0.013, is significant in the 95% test fixed before the run, [−0.021, −0.005]; with a Bonferroni correction added afterwards (99.67%) it is not, [−0.025, +0.001], while the 13 leads hold. nullpii's default configuration is further behind, −0.022, and significantly so in both tests: [−0.031, −0.013] at 95%, [−0.034, −0.008] corrected.
- **Precision.** nullpii's recall is the highest of any tool's best-scoring row (only rizzo-pii tuned for recall goes higher, 0.967, at F2 0.583), and its precision is among the lowest. Ranked by F0.5 on the rows above it is ninth (eight tools ahead); with each tool at its best F0.5 operating point, eleven are ahead.
- **Per dataset.** On PIILO, 8 of the 14 tools are ahead of nullpii; on Tonic, three are, by up to 0.008; on the clinical notes, gliner_multi_pii (0.913 against 0.887).
- **English documents only.** nullpii is fifth (0.713), behind openai's privacy-filter (0.746), rizzo-pii (0.742), OpenMed's privacy-filter-multilingual-v2 (0.717) and pii-identifier (0.714). The first two are significantly ahead; the next two, and ettin-68m and OpenMed large below it, are within the interval.
- **PIIMB** ([leaderboard](https://huggingface.co/spaces/piimb/pii-masking-benchmark-leaderboard), `sentences` subset, scored by us with the leaderboard's method, not a submitted entry): average F2 0.851, above all 35 listed tools; OpenMed's privacy-filter-multilingual-v2 is next at 0.836. One of the six tasks, nemotron-pii, is from nullpii's training family (2.5% of its sampled text overlaps nullpii's training corpus, 5.2% Nemotron-PII's); without it nullpii averages 0.831, against gliner-stream-pii's 0.826 and privacy-filter-multilingual-v2's 0.822, a lead the leaderboard's lack of intervals cannot call significant. nullpii trails on the ai4privacy and Gretel tasks, and on privy, where it over-masks.

The three reported (not gated) sets, the per-dataset numbers and the sensitivity checks are in [`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md).

### Latency

<!-- latency:begin -->
nullpii is not the fastest: it is seventh of 13 tools on GPU and fifth of 15 on CPU (at 30k, counting nullpii once and NVIDIA's two nemotron pipelines as one tool). Median time per call, in milliseconds, for texts of 2,000, 30,000 and 100,000 characters of coding-agent material (code, logs, prose, tool output); every tool times the same texts on the same idle machine, after a warm-up, at its default operating point. How the texts are chosen: [`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md).

**GPU** (Linux, NVIDIA RTX 4070 Ti; 60, 12 and 5 texts per size, three rounds). nullpii loads `model_fp16.onnx` on CUDA.

| Tool | 2k | 30k | 100k |
|---|---:|---:|---:|
| ettin-68m | 11 | 157 | 544 |
| openai privacy-filter | 24 | 205 | 716 |
| OpenMed privacy-filter-multilingual-v2 | 26 | 311 | 1,103 |
| piiranha | 25 | 342 | 1,177 |
| pii-identifier | 19 | 407 | 1,411 |
| gliner-stream-pii | 30 | 412 | 1,421 |
| **nullpii** (core labels) | **32** | **463** | **1,650** |
| **nullpii** (default configuration) | **34** | **489** | **1,747** |
| rizzo-pii | 27 | 494 | 1,715 |
| deberta PII | 35 | 631 | 2,268 |
| OpenMed PII Small | 46 | 794 | 3,423 |
| OpenMed PII Large | 80 | 1,209 | 5,126 |
| nemotron-pii (`nvidia/gliner-PII`, library) | 136 | 1,478 | 5,208 |
| gliner-pii-large-v1 | 83 | 1,892 | 6,550 |
| nemotron-pii (NVIDIA server pipeline) | 189 | 2,835 | 9,966 |

**CPU** (Linux, Intel Core i7-13700KF, every tool on CPU; 6, 6 and 3 texts per size, timed once, since the full plan takes hours per tool here).

| Tool | 2k | 30k | 100k |
|---|---:|---:|---:|
| Presidio | 35 | 511 | 2,209 |
| OpenMed PII Small | 207 | 2,603 | 5,279 |
| piiranha | 386 | 6,208 | 20,493 |
| pii-identifier | 326 | 6,609 | 24,116 |
| **nullpii** (core labels) | **394** | **6,984** | **24,674** |
| **nullpii** (default configuration) | **432** | **7,655** | **27,048** |
| ettin-68m | 535 | 8,882 | 29,640 |
| rizzo-pii | 413 | 10,962 | 32,918 |
| deberta PII | 654 | 11,933 | 42,702 |
| OpenMed PII Large | 1,228 | 14,291 | 22,324 |
| gliner_multi_pii (ONNX) | 1,300 | 15,549 | 55,069 |
| gliner-stream-pii | 1,351 | 20,613 | 69,957 |
| nemotron-pii (`nvidia/gliner-PII`, library) | 2,090 | 25,941 | 94,524 |
| gliner-pii-large-v1 | 1,336 | 35,183 | 116,889 |
| nemotron-pii (NVIDIA server pipeline) | 3,101 | 48,415 | 168,702 |
| OpenMed privacy-filter-multilingual-v2 | 9,133 | 132,528 | 448,206 |
| openai privacy-filter | 9,514 | 137,526 | 467,769 |

Presidio is fast because it is mostly patterns plus a small spaCy model; its macro char-F2 is 0.628. OpenMed Large's time depends strongly on the text (at 100k, a median of 22 s and a 95th percentile of 63 s), so its 100k figure, from three texts, is rough. On CPU nullpii's two references, at the start and at the end of the run, agree within 1% (0.2% at 2k, 0.3% at 30k, 0.7% at 100k). gliner_multi_pii (ONNX) runs on CPU only and Presidio has no GPU path, so they are not in the GPU table.
<!-- latency:end -->

## Backends

```ts
new NullPii({ backend: 'cpu' });   // ONNX Runtime on the CPU (the default)
new NullPii({ backend: 'cuda' });  // NVIDIA GPU, fp16 when the model ships it; falls back to the CPU
new NullPii({ backend: 'mps' });   // Apple Silicon through CoreML; slower than 'cpu' today, see below
```

`backend: 'cuda'` needs the CUDA libraries the installed `onnxruntime-node` was built against: for 1.30 on Linux x64, CUDA 13 (`libcudart.so.13`, `libcublas.so.13`, `libcublasLt.so.13`) and cuDNN 9, although its installer calls the build `cuda12`. When a session with the CUDA or CoreML provider cannot be created (a missing library, an unsupported graph, too little memory), nullpii runs on the CPU instead and emits a process warning with code `NULLPII_BACKEND_FALLBACK` that names the cause (listen with `process.on('warning', …)`). A model downloaded for CUDA holds only the fp16 file; the CPU runs it too, but the benchmark measures the fp32 file (accuracy on CUDA, the CPU latency table on the CPU).

On Apple Silicon use `cpu`: with CoreML the model was slower than on the CPU at every size measured (1.3 to 8 times, depending on the CoreML settings; measured on earlier builds), and its first call took 18 to 26 seconds while CoreML compiled the graph, which the GLiNER head's dynamic shapes split into many partitions (#51).

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
- Restoring a value into a shell command can inject, because the model never saw the value. The gateway keeps the placeholder, and the mod refuses the call, unless the command is written in a small grammar nullpii reads whole (no `$`, backticks, backslashes, parentheses, braces, comments or `&` other than `&&`), every program in it is on a short list of programs that read their arguments as data (`ls`, `grep`, `cat`, `git log`, …; SECURITY.md) and the value is one plain word that is not the program, a redirection target, an assignment or a `cd` argument, in a command that redirects output to no file but a document, or text in a heredoc that `cat` writes out or that `git commit -F -` reads as its message, not piped on (Claude Code's usual `"$(cat <<'EOF' …)"` commit form gets nothing). This is best effort; if you call `restore()` yourself, read [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md).

Report a vulnerability privately: [security advisories](https://github.com/lBroth/nullpii/security/advisories/new).

## License

Apache-2.0: see [LICENSE](https://github.com/lBroth/nullpii/blob/main/LICENSE) and [NOTICE](https://github.com/lBroth/nullpii/blob/main/NOTICE). What the model was trained on, and the attributions it carries: [`docs/WEIGHTS_PROVENANCE.md`](https://github.com/lBroth/nullpii/blob/main/docs/WEIGHTS_PROVENANCE.md).

## Credits

The detection model builds on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, Zaratiana et al., NAACL 2024, on Microsoft mDeBERTa-v3 base). Training data credits: NVIDIA (Nemotron-PII), the Allen Institute for AI and Common Crawl (C4), Microsoft (presidio-research) and Norsk Regnesentral (TAB).
