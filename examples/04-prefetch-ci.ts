import { ModelManager } from '../src/index.js';

// Run during CI / Docker build to bake the unified GLiNER artifact into
// the image (~1.2 GB FP32: `model.onnx` + tokenizer + GLiNER config —
// see `src/model-manager.ts:UNIFIED_FILES`).
const manager = new ModelManager();
const result = await manager.ensure({
  onProgress: (p) => process.stdout.write(`\rprefetch ${(p * 100).toFixed(0)}%`),
});
process.stdout.write('\n');
process.stdout.write(`cached at: ${result.modelDir}\n`);
