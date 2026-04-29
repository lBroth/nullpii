---
description: Control the nullpii daemon (status / on / off)
argument-hint: status | on | off
---

# nullpii daemon control

Toggle the nullpii sanitizing proxy live. Argument: `$ARGUMENTS`. Default to `status` if empty.

The daemon stays up. `on`/`off` flip a sanitize flag inside the daemon — no restart, no env change.

## Actions

**`status`**: Check daemon + sanitize flag.
- Run: `curl -sf http://localhost:7330/control/status`
- Run: `lsof -nP -iTCP:7330 -sTCP:LISTEN 2>/dev/null`
- Report: daemon pid, port LISTEN, `sanitize: true|false`.
- If curl fails, daemon is down — suggest restarting Claude Code.

**`on`**: Enable sanitization.
- Run: `curl -sf -X POST http://localhost:7330/control/on`
- Confirm response shows `{"sanitize":true}`.

**`off`**: Disable sanitization (passthrough mode).
- Run: `curl -sf -X POST http://localhost:7330/control/off`
- Confirm response shows `{"sanitize":false}`.
- WARN: PII no longer redacted. Daemon still in path but forwards bytes unchanged.
