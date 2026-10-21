// SPDX-License-Identifier: Apache-2.0

import { ModelManager } from '../src/index.js';

// Run during CI / Docker build to bake the GLiNER artifact into the
// image: `model.onnx` (~1.2 GB fp32; `model_fp16.onnx` on CUDA) plus the
// tokenizer and GLiNER config (`SHARED_FILES` in src/model-manager.ts).
const manager = new ModelManager();
const result = await manager.ensure({
  onProgress: (p) => process.stdout.write(`\rprefetch ${(p * 100).toFixed(0)}%`),
});
process.stdout.write('\n');
process.stdout.write(`cached at: ${result.modelDir}\n`);
