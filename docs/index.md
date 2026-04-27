---
layout: home
title: nullpii
hero:
  name: nullpii
  text: Stop leaking PII to LLMs.
  tagline: Local PII detection with OpenAI's `privacy-filter`. Reversible vault. Zero cloud calls. Apache 2.0.
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
  - title: Drop-in for any SDK
    details: '`withNullPii(client)` for `@anthropic-ai/sdk`. Same TypeScript surface as the original client.'
  - title: Reversible by default
    details: Each PII span becomes a typed placeholder; the original lives in an in-memory vault keyed by an opaque session id. Round-trip is byte-for-byte exact.
  - title: 100% permissive licenses
    details: MIT / Apache-2.0 / BSD / ISC / CC0 only. Zero LGPL / GPL / AGPL anywhere in the runtime tree. Audit table in `THIRD_PARTY_LICENSES.md`.
---

## What it does in 4 lines

```ts
import Anthropic from '@anthropic-ai/sdk';
import { withNullPii } from 'nullpii/middleware/anthropic';

const safe = withNullPii(new Anthropic());

const reply = await safe.messages.create({
  model: 'claude-haiku-4-5',
  max_tokens: 200,
  messages: [
    { role: 'user', content: 'Email John Smith at john@acme.com about his SSN.' },
  ],
});
// The Anthropic API saw `[[NULLPII:private_person:0]]` and `[[NULLPII:private_email:0]]`.
// `reply` reads as natural English with the originals restored.
```

## What gets caught

Eight categories from `openai/privacy-filter`: names, emails, phone
numbers, addresses, dates, URLs, account numbers, secrets. Decoded
from BIOES tags via a constrained Viterbi pass against char-level
offsets — no regex, no language-specific tweaks.

## How it stays cheap

- One ONNX file (~1.5 GiB int8) cached in `~/.nullpii/models/`
- Backend auto-selects CUDA → MPS → ROCm → CPU
- ~60 ms / 512 tokens on Apple Silicon CPU (int8)
- Zero outbound traffic for the detection step
