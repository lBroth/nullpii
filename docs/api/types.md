# Types

## `PiiLabel` / `PiiCategory`

```ts
export const PII_LABELS = [
  'O',
  'account_number',
  'private_address',
  'private_date',
  'private_email',
  'private_person',
  'private_phone',
  'private_url',
  'secret',
] as const;

export type PiiLabel = (typeof PII_LABELS)[number];      // 9 entries
export type PiiCategory = Exclude<PiiLabel, 'O'>;        // 8 entries
```

## `PiiSpan`

```ts
interface PiiSpan {
  readonly start: number;        // inclusive char offset
  readonly end: number;          // exclusive char offset
  readonly label: PiiCategory;   // never 'O'
  readonly score: number;        // mean BIOES-token softmax score
  readonly text: string;         // text.slice(start, end)
}
```

## `SanitizeResult` / `RestoreResult`

```ts
interface SanitizeResult {
  readonly sessionId: string;
  readonly sanitized: string;
  readonly spans: readonly PiiSpan[];
}

interface RestoreResult {
  readonly restored: string;
  readonly replacements: number;
}
```

## `NullPiiConfig`

```ts
interface NullPiiConfig {
  readonly modelDir?: string;
  readonly backend?: BackendName;       // 'cpu' | 'mps' | 'cuda' | 'rocm' | 'auto'
  readonly variant?: ModelVariant;      // 'fp32' | 'fp16' | 'int8' | 'int4' | 'int4f16' | 'auto'
  readonly maxSequenceLength?: number;
  readonly downloadTimeoutMs?: number;
}
```

## `BackendProvider`

```ts
interface BackendProvider {
  readonly name: BackendName;
  readonly variant: ModelVariant;
  isAvailable(): Promise<boolean>;
  init(): Promise<void>;
  infer(inputs: InferenceInputs): Promise<InferenceOutputs>;
  dispose(): Promise<void>;
}

interface InferenceInputs {
  readonly inputIds: BigInt64Array;
  readonly attentionMask: BigInt64Array;
}

interface InferenceOutputs {
  readonly logits: Float32Array;        // [seqLen × numLabels] row-major
  readonly seqLen: number;
  readonly numLabels: number;
}
```

## Constants

```ts
export const MAX_SEQUENCE_LENGTH = 512;
export const DEFAULT_MODEL_DIR = './models/privacy-filter';
export const MODEL_DOWNLOAD_TIMEOUT_MS = 300_000;
export const PLACEHOLDER_REGEX = /\[\[NULLPII:([a-z_]+):(\d+)\]\]/g;
export function PLACEHOLDER_TEMPLATE(label: string, index: number): string;
```
