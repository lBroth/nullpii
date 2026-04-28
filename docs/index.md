---
layout: home
title: nullpii
hero:
  name: nullpii
  text: Stop leaking PII to LLMs.
  tagline: Local PII detection with OpenAI's `privacy-filter`. Reversible vault. Zero cloud calls. Apache 2.0.
  image:
    src: /logo-256.png
    alt: nullpii logo
  actions:
    - theme: brand
      text: Use it with Claude Code
      link: /guide/middleware/claude-code
    - theme: alt
      text: 5-minute quickstart
      link: /guide/getting-started
    - theme: alt
      text: GitHub
      link: https://github.com/lBroth/nullpii
features:
  - title: One line for Claude Code
    details: '`npm install -g @nullpii/claude-code`, add it to `.claude/settings.json`, done. Every prompt sanitized before it leaves your machine, every response restored before display.'
  - title: Reversible by default
    details: Each PII span becomes a typed placeholder; the original lives in an in-memory vault keyed by an opaque session id. Round-trip is byte-for-byte exact.
  - title: 100% permissive licenses
    details: MIT / Apache-2.0 / BSD / ISC / CC0 only. Zero LGPL / GPL / AGPL anywhere in the runtime tree. Audit table in `THIRD_PARTY_LICENSES.md`.
---

## What it does in 4 lines

```bash
npm install -g @nullpii/claude-code
# add the plugin to .claude/settings.json — done.
```

Now every Claude Code prompt is sanitized before leaving your machine,
and every response is restored before display.

## What gets caught

Eight categories from `openai/privacy-filter`: names, emails, phone
numbers, addresses, dates, URLs, account numbers, secrets. Decoded
from BIOES tags via a constrained Viterbi pass against char-level
offsets — no regex, no language-specific tweaks.

## How it stays cheap

- One ONNX file (~3 GiB fp16, default) cached in `~/.cache/nullpii/`.
  Pin `variant: 'int4f16'` (~772 MiB, ~6% F1 drop) for edge installs
- Backend auto-selects CUDA → MPS → ROCm → CPU
- ~33 ms / 512 tokens on Apple Silicon CPU (fp16); chunked above 512
- Zero outbound traffic for the detection step
