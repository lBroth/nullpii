# API Reference

## `NullPii`

The main public class.

```ts
class NullPii {
  constructor(config?: NullPiiConfig);

  /** Lazy-init: download the model, select & load a backend, build the
   * tokenizer. Idempotent and concurrency-safe (singleton promise). */
  init(): Promise<void>;

  /** Detect PII in `text` and replace each span with a vault placeholder.
   * Auto-calls `init()` if not yet initialized. */
  sanitize(text: string, sessionId?: string): Promise<SanitizeResult>;

  /** Replace placeholders in `text` with the originals from `sessionId`. */
  restore(text: string, sessionId: string): RestoreResult;

  /** Wipe the vault entry for `sessionId`. Safe on unknown ids. */
  destroySession(sessionId: string): void;

  /** Release native resources (ORT session). After this, sanitize throws. */
  dispose(): Promise<void>;
}
```

## Functional wrappers

```ts
import { sanitize, restore } from 'nullpii';

const out = await sanitize('My name is John', { backend: 'cpu' });
const back = restore(out.sanitized, out.sessionId);
```

The functional wrappers share a process-wide instance per `config`
(keyed by `JSON.stringify(config)`). For tight control, prefer the
class.

## Default pipeline

`new NullPii()` with no config gives you the full default pipeline:

| Stage | What runs by default | Override |
|---|---|---|
| **Backend** | `auto` → CUDA → MPS → ROCm → CPU | `backend: 'cpu' \| 'mps' \| 'cuda' \| 'rocm'` |
| **Variant** | `auto` → fp16 (~3 GB) | `variant: 'fp32' \| 'fp16' \| 'int8' \| 'int4' \| 'int4f16'` |
| **Chunking** | sliding window 512 tokens, 64 overlap | `maxSequenceLength`, `chunkOverlap`, `strictLength` |
| **Viterbi BIOES decode** | constrained transitions, posterior scores | `transitionBiases`, `threshold`, `categoryThresholds` |
| **Recognizer pack** | `DEFAULT_RECOGNIZERS` (URL, email, AWS / GitHub / Stripe / OpenAI / Anthropic keys, IBAN, SSN) | `recognizers: 'none'` to disable; `recognizers: [...]` to replace |
| **Boundary refinement** | trim whitespace + punctuation from span edges | `boundaryRefine: false` |
| **Vault** | new in-memory `Map` per instance | per-call `sessionId` for multi-turn |

All defaults live in `src/defaults.ts`. Adding a new default? Put it
there. Reading one elsewhere? Import from there. No `?? 'auto'`
scattered across modules.

```ts
// Inspect or extend the built-in recognizer pack:
import { DEFAULT_RECOGNIZERS } from 'nullpii';

const np = new NullPii({
  recognizers: [...DEFAULT_RECOGNIZERS, myCustomRecognizer],
});
```

## Backends

```ts
import { CpuBackend } from 'nullpii/backend/cpu';
import { MpsBackend } from 'nullpii/backend/mps';
import { CudaBackend } from 'nullpii/backend/cuda';
import { RocmBackend } from 'nullpii/backend/rocm';
```

All backends implement `BackendProvider`. See
[Types](/api/types#backendprovider).

## Router

```ts
import { selectBackend } from 'nullpii';

const backend = await selectBackend('/path/to/modelDir', {
  backend: 'auto',
  variant: 'int8',
});
```

## Vault

```ts
import { PiiVault } from 'nullpii';

const vault = new PiiVault();
const id = vault.createSession();
const r = vault.sanitize(text, spans, id);
const back = vault.restore(r.sanitized, id);
vault.destroySession(id);
```
