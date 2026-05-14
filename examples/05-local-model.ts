import { NullPii } from '../src/index.js';

// Two ways to point at an unpacked model directory on disk instead of
// pulling `lBroth/nullpii` from HuggingFace:
//   1. set `NULLPII_MODEL_DIR=/path/to/model` — read by the library
//   2. pass `modelDir: '/path/to/model'` in `NullPiiConfig`
// Explicit `modelDir` in config wins over the env var; both skip the
// download path. The directory must contain the unified manifest:
//   model.onnx, tokenizer.json, gliner_config.json, tokenizer_config.json
//
// Useful for air-gapped hosts, pinning a specific model revision in CI,
// or evaluating a freshly trained candidate.
const np = new NullPii({
  // modelDir: '/explicit/path',  // uncomment to override env var
  backend: 'cpu',
});

const text = 'Drop a note to alice@acme.com or call 555-867-5309 about order 4111111111111111.';
const out = await np.sanitize(text);

console.log('sanitized  :', out.sanitized);
console.log('spans      :', out.spans.map((s) => `${s.label}=${s.text}`).join(' | '));
console.log('restored OK:', np.restore(out.sanitized, out.sessionId).restored === text);

await np.dispose();
