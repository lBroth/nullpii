<p align="center">
  <img src="https://raw.githubusercontent.com/lBroth/nullpii/main/assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

<p align="center">
  <a href="https://lbroth.github.io/nullpii/"><img src="https://img.shields.io/badge/docs-lbroth.github.io%2Fnullpii-0d9488?style=for-the-badge" alt="Documentation: lbroth.github.io/nullpii" /></a>
  <a href="https://lbroth.github.io/nullpii/start"><img src="https://img.shields.io/badge/get_started-Claude_Code_mod-0d9488?style=for-the-badge" alt="Get started with the Claude Code mod" /></a>
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/nullpii"><img src="https://img.shields.io/npm/v/nullpii" alt="npm version" /></a>
  <a href="https://github.com/lBroth/nullpii/actions/workflows/ci.yml"><img src="https://github.com/lBroth/nullpii/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://huggingface.co/lBroth/nullpii"><img src="https://img.shields.io/badge/model-Hugging_Face-blue" alt="Model on Hugging Face" /></a>
  <a href="https://www.npmjs.com/package/nullpii"><img src="https://img.shields.io/node/v/nullpii" alt="Node version" /></a>
  <a href="https://github.com/lBroth/nullpii/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License: Apache-2.0" /></a>
</p>

nullpii hides personal data and secrets before your text goes to an LLM, and puts the real values back in the reply. It runs on your machine. A fine-tuned GLiNER model and a set of pattern recognizers find the values, and an in-memory vault swaps each one for a placeholder and back.

![How nullpii works: text from your app or Claude Code is decoded, scanned by the model and the recognizers, and each value the policy masks becomes a placeholder kept in an in-memory vault. The LLM provider sees only placeholders. The reply gets the real values back, file tools get real values, shell commands keep the placeholders.](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/how-it-works.svg)

- **Built for coding agents.** It masks tool output (files, logs, command output), not only prompts. It keeps links to code hosts and documentation readable. It never puts a real value into a shell command (see SECURITY.md). It is built and tested with Claude Code, through the mod (recommended) or the gateway.
- **Works with any model.** Mask before your LLM call and restore after it. Or run the gateway in front of the Anthropic Messages API or OpenAI Chat Completions. The Codex CLI only speaks the Responses API, so it cannot use the gateway.
- **Measured, losses included.** On coding-agent traffic it lets 9.5% of the values that must be hidden through, and keeps 85.4% of the values that must stay readable. Only rizzo-pii lets fewer through (8.1%), but it keeps only 44.5% readable. On five held-out document sets it is second of 15 tools, and fifth on English text alone. [Benchmark](#benchmark).

Status: before 1.0, so the API can still change between minor versions. nullpii replaces values with placeholders it can reverse, and it misses some values. This is pseudonymisation, not anonymisation, and not a compliance certification.

## Quick start: Claude Code

At the prompt of a Claude Code session (2.1.287 or later, with Node 22 or later):

```text
/plugin marketplace add lBroth/nullpii@v0.5.4
/plugin install nullpii@nullpii
```

When Claude Code asks for the plugin's options, paste a new token from `openssl rand -hex 32` into **Sidecar token**, then restart Claude Code. The mod starts a local nullpii sidecar, which downloads the model (1.2 GB) on its first start. [Get started](https://lbroth.github.io/nullpii/start) has a prompt that lets Claude Code do this for you, and how to check that it works. The full reference is under [Claude Code mod](#claude-code-mod).

## Install

```bash
npm install nullpii onnxruntime-node
```

You need Node 22 or later. On first use nullpii downloads the model from Hugging Face into `~/.cache/nullpii/`: 1.2 GB in fp32, or 0.6 GB in fp16 on CUDA. It checks every file it downloads against a SHA-256 written into the library. To download the model ahead of time, run `npx nullpii prefetch`, or point `NULLPII_MODEL_DIR` at a copy you put there yourself. nullpii does not check the files in `NULLPII_MODEL_DIR`: compare them with the hashes in the [model card](https://huggingface.co/lBroth/nullpii).

On Linux x64, the install script of `onnxruntime-node` also downloads its CUDA support from NuGet, without checking a hash. The CPU runtime is already in the npm package, so on a machine without an NVIDIA GPU, skip that download:

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

Keep one engine for the whole life of your process: loading the model (about 1.2 GB) is the slowest step. How the vault works:

- It lives in memory only.
- A placeholder belongs to the session that made it. You cannot restore it in another session.
- In one session, one value always gets the same placeholder.
- Once a session has masked a value, nullpii masks it again in that session's later calls, even where the detector misses it (for a whole word of three characters or more). So a value restored into a tool call and echoed in the tool's output stays masked.

Streaming restore, for replies that arrive in chunks:

```ts
import { RestoreStream } from 'nullpii';
const stream = new RestoreStream(np, safe.sessionId);
for await (const chunk of yourLlmStream(prompt)) process.stdout.write(stream.push(chunk));
process.stdout.write(stream.end().restored);
```

`safe.modelUnscannedWords` counts the words the model could not read, such as one very long minified blob. The recognizers still scanned them.

## Choose what gets masked

One JSON file sets the policy for the library, the CLI, the gateway and the Claude Code mod. It is `~/.config/nullpii/config.json`, or the file that `NULLPII_CONFIG` names.

```json
{
  "disabledCategories": ["private_organization", "private_occupation"],
  "categories": { "private_url": "ask" },
  "urlAllowlist": { "hosts": { "*.github.com": "host" } }
}
```

- `disabledCategories`: the categories left readable. It replaces the default list: dates, companies, jobs, honorifics, and demographic and sensitive attributes. `[]` masks every category.
  A category you leave readable stays in the model's prompt, because the set of categories the model is asked about changes what it finds. When you leave readable a category nullpii masks by default and keep secrets masked (the secrets-only preset, `/pii allow url`), the model reads each text a second time for secrets, asked about the categories you mask and no other, so a credential the model would otherwise file under a readable category (a token in a URL, a key it takes for an account number) stays masked. Under such a policy a text costs a second model pass wherever the first pass or a recognizer found something, or a word was too long to read.
- `categories`: a mode for each category you name: `mask`, `ask` or `off` (readable). It wins over `disabledCategories` for those categories. `ask` works in the Claude Code mod: before your prompt is sent, the mod asks you about each value of that category. The value stays masked unless you choose to send it readable (see below).
- `categoryThresholds`, `threshold`: confidence cuts between 0 and 1. Lower masks more.
- `urlAllowlist`: how much of a clean URL stays readable on each host: `full`, `host` or `mask`. Use `"none"` to mask every URL. By default, code hosts, package registries and documentation stay readable. A URL with a credential in its query is always masked. A code-host URL can name a person or a private repository (`github.com/<user>/<repo>`); if that matters to you, set that host to `host` or `mask`.
- `restoreTools`: the tools whose arguments get real values back (gateway and mod).

`npx nullpii config` checks the file and prints it. In code, load it with `resolveConfigFile()` and `toEngineConfig()`, or pass the same options to `new NullPii({...})`.

## Gateway

An HTTP proxy for the Anthropic Messages API (`/v1/messages`) and the OpenAI Chat Completions API (`/v1/chat/completions`). Point your client's base URL at it and work as before. It masks requests before they leave your machine, and it restores responses, streaming included, before they reach you.

```bash
git clone https://github.com/lBroth/nullpii.git && cd nullpii
docker compose -f examples/claude-code/docker-compose.yml up -d   # listens on 127.0.0.1:8787
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
claude
```

The first request downloads the model (1.2 GB) into the container's cache volume and waits for it. [`examples/claude-code`](https://github.com/lBroth/nullpii/tree/main/examples/claude-code) shows how to download it first. The image is also published as `ghcr.io/lbroth/nullpii-gateway`.

Your API key or Claude subscription login passes through unchanged. For OpenAI Chat Completions clients (the OpenAI SDKs, Aider, LiteLLM), set `OPENAI_BASE_URL=http://127.0.0.1:8787/v1`. The gateway does not proxy the Responses API, so the Codex CLI, which refuses to speak Chat Completions, cannot use it.

- Real values go back only into the tools in the policy's `restoreTools`. By default these are the file tools that run on your machine (`Read`, `Edit`, `Write`, `Grep`, `Glob`, …).
- A tool that runs a shell (`Bash`, `PowerShell`, …) never gets a real value back, whatever the policy says. Web and MCP tools, and tools the upstream runs itself, keep the placeholders too.
- The request log has counts, never values.
- The gateway has no authentication of its own. Keep it on `127.0.0.1`.
- It reads the policy at startup. A change sent through the sidecar (`PUT /v1/sidecar/policy`, which the mod's `/pii` uses) applies to the running gateway at once.

Details, the full list of scanned fields, and the sidecar API: [`packages/gateway`](https://github.com/lBroth/nullpii/tree/main/packages/gateway). A worked Claude Code setup: [`examples/claude-code`](https://github.com/lBroth/nullpii/tree/main/examples/claude-code).

## Claude Code mod

[`packages/claude-code-mod`](https://github.com/lBroth/nullpii/tree/main/packages/claude-code-mod) masks inside Claude Code itself:

- It masks prompts, tool results, @-mentioned files and `CLAUDE.md` before Claude reads them.
- It shows your prompts and Claude's replies on screen with the real values.
- It puts real values back into the tools the policy lists (by default the local file tools). Any other tool gets a real value only on your answer to a dialog (Block, Send once, Allow all); in `claude -p`, where no one can answer, such a call is refused unless Allow all was given, and a shell command never gets one.
- A band above the prompt shows what was masked, by type. `/pii` shows the counts and the policy in effect.

The mod talks to the gateway's local sidecar. If no sidecar answers, it starts one for the session. If it cannot reach the sidecar, it sends nothing unmasked.

`/pii` changes the policy at once and saves the change in the policy file:

- `/pii preset agent` (the default), `/pii preset secrets` (secrets only) or `/pii preset all` (every category). `/pii reset` goes back to `agent`.
- `/pii mask <category…>`, `/pii allow <category…>` (readable) and `/pii ask <category…>` set one mode for each category you name.

For a category in `ask` mode, the mod asks you about each of its values in your own prompt before the prompt is sent. You can mask it, send it readable, or send it readable and stop asking for that category. If you close the question, or no one can answer it (`claude -p`), the value stays masked. Apart from that, values in a tool's result follow the policy without a question; the mod asks before a masked value goes out in clear to a tool outside the policy's list, or a masked object key of such a tool's result goes to Claude in clear ([Ask before a value leaves](https://github.com/lBroth/nullpii/tree/main/packages/claude-code-mod#ask-before-a-value-leaves)). Categories: `person`, `email`, `phone`, `address`, `url`, `ip`, `mac`, `location`, `passport`, `license`, `vehicle`, `account`, `secret`, `date`, `organization`, `occupation`, `demographic`, `sensitive`, `title`.

To install it you need a sidecar token ([set up](https://github.com/lBroth/nullpii/tree/main/packages/claude-code-mod#set-up); the mod starts the gateway itself when none answers). Then, at the prompt of a Claude Code session:

```text
/plugin marketplace add lBroth/nullpii@v0.5.4
/plugin install nullpii@nullpii
```

Or from a shell: `claude plugin marketplace add lBroth/nullpii@v0.5.4`, then `claude plugin install nullpii@nullpii`. The `@v0.5.4` pins the mod to this release. Without it you get whatever `main` holds.

## What gets caught

| Label | Examples | Source |
|---|---|---|
| `private_person` | names | model |
| `private_email` | emails | model + regex |
| `private_phone` | international (with `+`) and IT / FR / ES formats; US numbers without `+1` by the model only | model + regex |
| `private_address` | street, city, postcode | model |
| `private_date` | birth and other personal dates | model |
| `private_url` | `http(s)://`, `www.` | model + regex |
| `private_ip` | IPv4, IPv6 (private, documentation and loopback ranges left alone) | regex |
| `private_mac` | MAC addresses (broadcast and multicast left alone) | regex |
| `private_passport` | US / IT / FR / ES / DE / UK, and a context-anchored generic form | model + regex |
| `private_driver_license` | US states, IT and EU countries, context-anchored | model + regex |
| `private_vehicle_id` | VIN (checksum), plates IT / FR / DE / UK / ES / US | model + regex |
| `private_geolocation` | coordinate pairs (range-checked), DMS notation | model + regex |
| `account_number` | IBAN (mod-97), cards (Luhn), SSN, crypto addresses, national and tax ids (DNI, CPF, EIN, codice fiscale, Partita IVA), Medicare, NPI, insurance policy, IMEI; medical record numbers by the model only | model + regex (validated) |
| `secret` | API keys (AWS, GitHub, OpenAI, Anthropic, Stripe and 30+ more), JWTs, private keys, passwords and PINs in context, base64-wrapped values | model + regex + base64 |
| `private_organization` | employers, company names | model |
| `private_occupation` | job titles, employment status, education | model |
| `private_demographic` | gender, age, ethnicity, nationality, language | model |
| `private_sensitive` | religion, political views, sexual orientation, health, when stated | model |
| `private_title` | honorifics and titles before a name | model |

By default nullpii masks what is risky to give to a coding agent's model: names, contact details and addresses, ids and accounts, secrets. It leaves readable what the agent needs and what rarely identifies someone on its own: `private_date` (the model cannot tell a birth date from a deadline) and the last five categories in the table. `DEFAULT_DISABLED_CATEGORIES` lists these six. Health, religion or sexual orientation written in your text reaches the model by default; `/pii mask sensitive` (or `disabledCategories`) changes that. Set `disabledCategories` to change the list; `[]` masks every category. nullpii finds values that are written out. It does not infer a health condition or a belief from indirect wording. Add your own patterns with `np.addRecognizer({ id, pattern, label, confidence, validate? })`.

nullpii decodes hidden input before it looks for values: Unicode look-alikes and fullwidth characters, zero-width characters, spaced-out text, percent-encoding (two levels deep), numeric HTML entities (`&#64;`, `&#x40;`), and base64 blobs.

## Benchmark

Every test was fixed before the run, except one AB-1 scoring rule changed afterwards (see below). The results include the cases nullpii loses. How the numbers are made: [`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md).

### Agent traffic (AB-1)

AB-1 checks two things in a coding agent's traffic. What the agent must not give to the model (secrets, contact details and addresses, ids and account numbers, names) should be masked. What it needs to read (dates, versions, paths, hostnames of public services, placeholders, code identifiers) should stay readable. Each item is scored: the leak rate on items that must be hidden, and the keep rate on items that must stay readable. There is no combined score. Every tool ran on the frozen test set, and the run was redone once for every tool after an adapter fix; nullpii's rows are from the release build, which includes three rules found in end-to-end testing (below). Method and limits: [AB-1 in METHOD.md](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md#agent-traffic-benchmark-ab-1).

![Agent traffic, 966 documents, leak rate and keep rate per tool: rizzo-pii 8.1% and 44.5%, nullpii 0.5 9.5% and 85.4%, then openai privacy-filter 14.5% and 77.9%; every other tool lets 15.7% to 55.1% through. The table below has every value.](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/ab1-agent-traffic.svg)

- **Only rizzo-pii lets fewer through** (8.1%; the gap is within the margin of error), and it masks more than half of what the agent needs to read. Every other tool lets 5 to 46 points more through. Only gliner-pii-large keeps as much readable (85.5%, too close to call), and it lets 15.9% through.
- **Weakest categories:** person names (24% let through) and URLs (31%). On names, 11 of the 15 other tools let fewer through; on URLs, 5 do.
- **On secrets alone, nullpii does not lead.** On CredData it lets 24.5% through, and 7 of the 15 other tools let fewer through; openai's privacy-filter lets 13.2% through and keeps more readable (77.1% against 64.8%). More than half of nullpii's leaks there (268 of 490) are UUIDs: CredData counts 294 UUIDs as credentials, mostly after keys that name ids (`id`, `uid`, `_postman_id`) or after no key, while nullpii, and AB-1's own specification, treat a UUID as an id to keep readable. Without them nullpii lets 13.0% through, the fewest of all tools (an analysis made after the scores were read). On secrets in GitHub issues, openai's privacy-filter lets fewer through (8.2% against 11.5%), and nullpii keeps more readable (77.2% against 74.6%).
- **nullpii was measured again after three rules found in end-to-end testing,** added after the first run: a UUID is an id, not an account number; an IP address is labelled as one, so documentation, private and local addresses stay readable; "Claude" is a product, not a person. They raised its keep rate (A: 81.9% → 85.4%; issues: 69.2% → 77.2%) and its CredData leak rate (14.6% → 24.5%, the UUIDs above). The other tools' rows are unchanged.
- **One scoring rule was changed after the scores were first read, and the change works against nullpii.** Punctuation left between masked pieces of a value (like the comma between a street and a city) no longer counts as a leak. With the first rule nullpii led (11.0% against rizzo-pii's 15.0%). The first scoring's files are kept in the repository's history ([`strict-rule/`](https://github.com/lBroth/nullpii/tree/230ce9fd1933f5df5263ca9c87d248e064eddc77/packages/eval/published-bench/ab1/strict-rule)).

<details>
<summary>Table, with the intervals</summary>

<!-- ab1-a:begin -->
966 documents, 3,386 items that must be masked and 5,676 that must stay readable.

| Tool | Leak rate | Keep rate | Docs with a leak | nullpii − tool, leak | nullpii − tool, keep |
|---|---:|---:|---:|---|---|
| rizzo-pii (tuned, +agent) | **8.1%** | 44.5% | **25.1%** | [−0.0, +2.6] | [+38.7, +43.4] |
| **nullpii 0.5 (agent default)** | 9.5% | 85.4% | 27.0% | — | — |
| openai privacy-filter (tuned, +agent) | 14.5% | 77.9% | 33.6% | [−6.9, −3.2] | [+5.0, +9.9] |
| OpenMed PII Large (tuned, +agent) | 15.7% | 82.2% | 39.7% | [−8.2, −4.4] | [+1.6, +5.0] |
| gliner-pii-large (tuned, +agent) | 15.9% | **85.5%** | 37.8% | [−8.5, −4.4] | [−1.9, +1.6] |
| nemotron-pii, NVIDIA's server (tuned, +agent) | 16.0% | 75.8% | 42.8% | [−8.2, −4.9] | [+7.7, +11.9] |
| OpenMed PII Small (tuned, +agent) | 16.1% | 83.0% | 40.4% | [−8.3, −4.9] | [+0.8, +4.1] |
| gliner-stream-pii (tuned, +agent) | 16.4% | 67.5% | 43.3% | [−9.0, −4.9] | [+15.9, +19.9] |
| nemotron-pii, library (tuned, +agent) | 17.6% | 68.4% | 47.9% | [−9.9, −6.3] | [+14.6, +19.4] |
| ettin-68m (tuned, +agent) | 17.7% | 65.3% | 43.6% | [−10.1, −6.3] | [+18.0, +22.4] |
| pii-identifier (tuned, +agent) | 18.8% | 77.7% | 52.5% | [−11.0, −7.7] | [+5.7, +9.8] |
| gliner_multi_pii (ONNX) (tuned, +agent) | 19.2% | 56.9% | 44.2% | [−11.6, −7.9] | [+26.0, +31.2] |
| OpenMed privacy-filter-multilingual-v2 (tuned, +agent) | 20.1% | 81.6% | 48.3% | [−12.0, −9.1] | [+2.2, +5.6] |
| piiranha (tuned, +agent) | 23.8% | 68.8% | 56.5% | [−16.5, −12.3] | [+14.5, +18.8] |
| Presidio (tuned, +agent) | 40.6% | 82.3% | 77.9% | [−33.2, −29.0] | [+1.4, +5.1] |
| deberta PII (tuned, +agent) | 55.1% | 64.2% | 81.2% | [−48.7, −42.4] | [+18.0, +24.3] |
<!-- ab1-a:end -->

Each row is the tool at its tuned setting, with the agent-policy filter. Bold marks nullpii's name and the best value in each column. [`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md#results) has every other row, B1 (CredData), B2 (issue secrets), the leak rate per category, and the secrets split by recognizer coverage. The raw numbers are in [`published-bench/ab1/`](https://github.com/lBroth/nullpii/blob/main/packages/eval/published-bench/ab1).

</details>

### Documents (R3)

R3 measures document anonymisation, a different job from agent traffic. It uses five datasets, frozen before any tool ran on them: REDACT, TonicAI's human-annotated Privacy-Bench, PIILO student essays, Greek and German clinical notes, and a synthetic coding-agent trace set built for this benchmark from a specification we wrote. Each has under 1% measured overlap with nullpii's training data and with the public training sets the other tools declare (three declared sources, among them rizzo-pii's Italian sets, were not compared). The score is per character and ignores labels. F2 counts recall twice as much as precision, because a missed character leaks. nullpii's rows are from the release build, with the three rules described under AB-1; they changed only documents that hold a UUID, an IP address, a loopback host or the word "Claude".

![Documents, macro char-F2 per tool over five sets and over English documents only: rizzo-pii 0.770 and 0.742, nullpii 0.758 and 0.714, nvidia/gliner-PII 0.720 and 0.672, OpenMed privacy-filter-multilingual-v2 0.717 and 0.717, openai privacy-filter 0.693 and 0.746. The table below has every value.](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/r3-documents.svg)

- **Second of 15** (counting NVIDIA's two nemotron pipelines as one tool; the chart shows both). rizzo-pii is ahead (0.770 against 0.758), all of it on PIILO's student essays (0.623 against 0.407). There nullpii masks a lot that the gold does not label, and 8 of the 14 other tools are ahead of it. The gap to rizzo-pii is significant in the 95% test fixed before the run, but not with a Bonferroni correction added later.
- **One dataset carries much of the lead.** Without the clinical notes, nullpii is third (0.725), and two more tools are too close to call. On English documents alone it is fifth (0.714).
- **It favours recall.** Its recall is the highest of any tool's best row (0.958), and its precision is below most tools' (10th of 15). Ranked by F0.5, which favours precision, it is ninth.
- **PIIMB**, scored by us with the leaderboard's method (not a submitted entry), with every category masked: average F2 0.851, above the 35 listed tools. Without the one task from its training family it is 0.831, not clearly ahead.

Two things compared here are built for documents: PIILO, where only the students' own names count as gold, and rizzo-pii, a document anonymiser (we run its app's own `analyze()`; its model and training data are Italian-first).

<details>
<summary>Table, with the intervals, and how the tools were run</summary>

- **Competitors:** each tool runs the way its authors ship it. METHOD.md lists the few changes, such as splitting long texts into windows. Each tool runs at its default and at a setting tuned on the same tuning set as nullpii, and is shown at its better one. Nine of the thirteen compared models (Presidio, a library, aside) declare English only on their cards (openai's privacy-filter says "primarily English"). Every tool still runs on every document; METHOD.md lists the languages.
- **Confidence:** paired bootstrap, 95% intervals of nullpii minus the tool. This test was fixed before the run. METHOD.md also has intervals corrected for multiple comparisons (Bonferroni, 99.67%), a check added later.

<!-- matrix:begin -->
| Tool | Macro char-F2 | F0.5 | Recall | Precision | CI of nullpii − tool (F2) |
|---|---:|---:|---:|---:|---|
| rizzo-pii (default) | **0.770** | **0.633** | 0.869 | **0.608** | [−0.020, −0.003] |
| **nullpii** | 0.758 | 0.534 | **0.958** | 0.490 | — |
| nemotron-pii (`nvidia/gliner-PII`, library) | 0.720 | 0.612 | 0.808 | 0.591 | [+0.025, +0.051] |
| OpenMed privacy-filter-multilingual-v2 | 0.717 | 0.585 | 0.841 | 0.560 | [+0.031, +0.049] |
| pii-identifier | 0.701 | 0.583 | 0.809 | 0.569 | [+0.044, +0.070] |
| ettin-68m | 0.699 | 0.563 | 0.825 | 0.545 | [+0.050, +0.068] |
| openai privacy-filter | 0.693 | 0.591 | 0.767 | 0.587 | [+0.052, +0.079] |
| OpenMed PII Large | 0.682 | 0.587 | 0.783 | 0.578 | [+0.060, +0.090] |
| OpenMed PII Small | 0.673 | 0.512 | 0.807 | 0.478 | [+0.069, +0.099] |
| gliner-pii-large | 0.656 | 0.571 | 0.811 | 0.555 | [+0.085, +0.119] |
| piiranha | 0.651 | 0.465 | 0.840 | 0.428 | [+0.092, +0.120] |
| gliner_multi_pii (ONNX) | 0.648 | 0.495 | 0.845 | 0.462 | [+0.098, +0.122] |
| Presidio | 0.628 | 0.492 | 0.790 | 0.465 | [+0.116, +0.142] |
| gliner-stream-pii | 0.568 | 0.522 | 0.714 | 0.528 | [+0.174, +0.203] |
| deberta PII (default) | 0.464 | 0.254 | 0.802 | 0.225 | [+0.282, +0.305] |
| mask everything | 0.260 | | | | |
<!-- matrix:end -->

Bold marks nullpii's name and the best value in each column.

nullpii is measured with its five extended categories off, because the datasets do not label them. With every category masked (the default before 0.5), it scores 0.748 on the same labels, and 0.653 when everything it masks counts, because masking organisations, occupations and the like counts as over-masking here. The 0.5 default for coding agents leaves those five categories and dates readable. That default is measured on agent traffic (AB-1, above), not on these datasets, which label dates.

**Where nullpii is not ahead, in detail.**
- **One dataset carries much of the lead.** Without the Greek and German clinical notes, nullpii is third (0.725). openai's privacy-filter (+0.030) and rizzo-pii (+0.027) are significantly ahead. pii-identifier and OpenMed privacy-filter-multilingual-v2 are too close to call. Without the student essays, nullpii is first (0.845; rizzo-pii is 0.039 behind).
- **rizzo-pii is ahead on student essays.** On PIILO nullpii scores 0.407 and rizzo-pii 0.623. nullpii has higher recall and much lower precision there, because it masks a lot the gold does not label. On the other four datasets nullpii is ahead of rizzo-pii. Over all five the gap is −0.012. It is significant in the 95% test fixed before the run, [−0.020, −0.003], but not with a Bonferroni correction added later (99.67%), [−0.024, +0.002]; the 13 leads still hold with it. With every category masked, nullpii is further behind (−0.022), and that gap is significant in both tests: [−0.030, −0.012] at 95%, [−0.034, −0.007] corrected.
- **Precision.** nullpii's recall is the highest of any tool's best row; only rizzo-pii at its tuned setting goes higher (0.967, at F2 0.583). Its precision is among the lowest. Ranked by F0.5 on the rows above, it is ninth (eight tools ahead). With each tool at its best F0.5 setting, eleven are ahead.
- **Per dataset.** On PIILO, 8 of the 14 other tools are ahead of nullpii. On Tonic, three are, by up to 0.008. On the clinical notes, gliner_multi_pii is ahead (0.913 against 0.887).
- **English documents only.** nullpii is fifth (0.714), behind openai's privacy-filter (0.746), rizzo-pii (0.742), OpenMed's privacy-filter-multilingual-v2 (0.717) and pii-identifier (0.714). The first two are significantly ahead. The next two, and ettin-68m and OpenMed Large below nullpii, are too close to call.
- **PIIMB** ([leaderboard](https://huggingface.co/spaces/piimb/pii-masking-benchmark-leaderboard), `sentences` subset, scored by us with the leaderboard's method, not a submitted entry, with every category masked): average F2 0.851, above all 35 listed tools. Next is OpenMed's privacy-filter-multilingual-v2 at 0.836. One of the six tasks, nemotron-pii, comes from nullpii's training family: 2.5% of its sampled text overlaps nullpii's training data, and 5.2% overlaps Nemotron-PII's. Without that task nullpii averages 0.831, against 0.827 for gliner-stream-pii and 0.822 for privacy-filter-multilingual-v2. The leaderboard gives no intervals, so this lead cannot be called significant. nullpii trails on the ai4privacy, nemotron-pii and Gretel tasks, and on privy, where it masks too much.

[`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md) has the three reported (not gated) sets, the numbers per dataset, and the sensitivity checks.

</details>

### Latency

![GPU latency at 30,000 characters, median milliseconds per call: from ettin-68m at 157 to NVIDIA's nemotron server pipeline at 2,835; nullpii 463 with its core labels and 489 with every category masked, seventh of 13 tools. The tables below have every value.](https://raw.githubusercontent.com/lBroth/nullpii/main/assets/readme/latency-gpu.svg)

nullpii is not the fastest: it is seventh of 13 tools on GPU and fifth of 15 on CPU, at 30,000 characters. Every tool runs the same coding-agent texts on the same idle machine, after a warm-up, at its default setting. nullpii has two rows: its core labels (the five extended categories off, dates on) and every category masked. Its 0.5 default, which also leaves dates readable and so asks the model for fewer labels, takes the same time as the core labels on GPU (458 ms at 30,000 characters) and about 13% less on CPU (6,104 ms); it was timed with the release build, which also matched the other nullpii rows to within 2% ([METHOD](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md)).

<details>
<summary>Tables: GPU and CPU, 2,000 to 100,000 characters</summary>

<!-- latency:begin -->
The tables show the median time per call, in milliseconds, for texts of 2,000, 30,000 and 100,000 characters of coding-agent material (code, logs, prose, tool output). The ranks above count nullpii once and NVIDIA's two nemotron pipelines as one tool. Bold marks nullpii's name and the fastest value in each column. How the texts are chosen: [`METHOD.md`](https://github.com/lBroth/nullpii/blob/main/packages/eval/METHOD.md).

**GPU** (Linux, NVIDIA RTX 4070 Ti; 60, 12 and 5 texts per size, three rounds). nullpii loads `model_fp16.onnx` on CUDA.

| Tool | 2k | 30k | 100k |
|---|---:|---:|---:|
| ettin-68m | **11** | **157** | **544** |
| openai privacy-filter | 24 | 205 | 716 |
| OpenMed privacy-filter-multilingual-v2 | 26 | 311 | 1,103 |
| piiranha | 25 | 342 | 1,177 |
| pii-identifier | 19 | 407 | 1,411 |
| gliner-stream-pii | 30 | 412 | 1,421 |
| **nullpii** (core labels) | 32 | 463 | 1,650 |
| **nullpii** (every category masked) | 34 | 489 | 1,747 |
| rizzo-pii | 27 | 494 | 1,715 |
| deberta PII | 35 | 631 | 2,268 |
| OpenMed PII Small | 46 | 794 | 3,423 |
| OpenMed PII Large | 80 | 1,209 | 5,126 |
| nemotron-pii (`nvidia/gliner-PII`, library) | 136 | 1,478 | 5,208 |
| gliner-pii-large-v1 | 83 | 1,892 | 6,550 |
| nemotron-pii (NVIDIA server pipeline) | 189 | 2,835 | 9,966 |

**CPU** (Linux, Intel Core i7-13700KF, every tool on CPU; 6, 6 and 3 texts per size, timed once, because the full plan takes hours per tool here).

| Tool | 2k | 30k | 100k |
|---|---:|---:|---:|
| Presidio | **35** | **511** | **2,209** |
| OpenMed PII Small | 207 | 2,603 | 5,279 |
| piiranha | 386 | 6,208 | 20,493 |
| pii-identifier | 326 | 6,609 | 24,116 |
| **nullpii** (core labels) | 394 | 6,984 | 24,674 |
| **nullpii** (every category masked) | 432 | 7,655 | 27,048 |
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

Presidio is fast because it is mostly patterns plus a small spaCy model; its macro char-F2 is 0.628. OpenMed Large's time depends a lot on the text, so its 100k figure, from three texts, is rough. gliner_multi_pii (ONNX) runs on CPU only, and Presidio has no GPU path, so neither is in the GPU table.
<!-- latency:end -->

</details>

## Backends

```ts
new NullPii({ backend: 'cpu' });   // ONNX Runtime on the CPU (the default)
new NullPii({ backend: 'cuda' });  // NVIDIA GPU, fp16 when the model ships it; falls back to the CPU
new NullPii({ backend: 'mps' });   // Apple Silicon through CoreML; slower than 'cpu' today, see below
```

`backend: 'cuda'` needs the CUDA libraries that the installed `onnxruntime-node` was built with. For 1.30 on Linux x64 that is CUDA 13 (`libcudart.so.13`, `libcublas.so.13`, `libcublasLt.so.13`) and cuDNN 9, even though its installer calls the build `cuda12`. If nullpii cannot start a CUDA or CoreML session (a missing library, an unsupported graph, too little memory), it runs on the CPU instead. It then emits a process warning with code `NULLPII_BACKEND_FALLBACK` that names the cause (listen with `process.on('warning', …)`). A model downloaded for CUDA has only the fp16 file. The CPU can run it too, but the benchmark measures the fp32 file (accuracy on CUDA, the CPU latency table on the CPU).

On Apple Silicon, use `cpu`. With CoreML the model was slower than on the CPU at every size measured (1.3 to 8 times slower, depending on the CoreML settings; measured on earlier builds). Its first call also took 18 to 26 seconds while CoreML compiled the graph, which the GLiNER head's dynamic shapes split into many parts (#51).

`intraOpNumThreads` and `interOpNumThreads` are passed to ONNX Runtime.

## What it doesn't do

- **It does not catch everything.** Detection is statistical, and the benchmark shows how much leaks. Do not make it your only privacy control.
- **It is not a HIPAA or GDPR tool.** It finds values that are written out, not facts inferred from context.
- **Images and other binary attachments** pass through the gateway without a scan. The gateway counts them.
- **Long inputs are slow, not refused.** nullpii reads a text over 1,000,000 characters in overlapping windows of up to that size, and masks it once. Expect about 25 seconds per 100,000 characters on CPU, and under 2 seconds on GPU. In the Claude Code mod, if masking takes longer than Claude Code waits, the mod withholds the text and says the sidecar took too long.

## Privacy and security

- Detection runs on your machine. nullpii sends your text nowhere. Its only network call is the model download.
- The vault lives in memory and is never written to disk.
- Logs have counts and short ids, never values. One exception: the gateway's `NULLPII_LOG_TRAFFIC=wire` debug dump prints what was sent upstream, including anything the detector missed (see SECURITY.md).
- Putting a real value into a shell command can inject code, because the model never saw the value. So no shell command gets a real value back. The gateway keeps the placeholder. The mod refuses the call and points Claude to `Grep`, `Read`, `Edit` or `Write`, which do get real values. If you add a shell tool under another name to `restoreTools`, nullpii does not recognise it and gives it every value, so do not add one. If you call `restore()` yourself, read [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md).

Report a vulnerability privately: [security advisories](https://github.com/lBroth/nullpii/security/advisories/new).

## License

Apache-2.0: see [LICENSE](https://github.com/lBroth/nullpii/blob/main/LICENSE) and [NOTICE](https://github.com/lBroth/nullpii/blob/main/NOTICE). What the model was trained on, and the attributions it carries: [`docs/WEIGHTS_PROVENANCE.md`](https://github.com/lBroth/nullpii/blob/main/docs/WEIGHTS_PROVENANCE.md).

## Credits

The detection model builds on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, Zaratiana et al., NAACL 2024, on Microsoft mDeBERTa-v3 base). Training data credits: NVIDIA (Nemotron-PII), the Allen Institute for AI and Common Crawl (C4), Microsoft (presidio-research) and Norsk Regnesentral (TAB).
