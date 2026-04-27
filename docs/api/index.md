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
