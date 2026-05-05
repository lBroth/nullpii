import { ModelManager } from '../src/index.js';

// Run during CI / Docker build to bake the full router stack into the
// image (~6 GB: 5 merged-LoRA ONNX + distiluse encoder + tokenizer +
// prototypes — see `src/model-manager.ts:ROUTER_FILES`).
const manager = new ModelManager();
const result = await manager.ensure({
  onProgress: (p) => process.stdout.write(`\rprefetch ${(p * 100).toFixed(0)}%`),
});
process.stdout.write('\n');
process.stdout.write(`cached at: ${result.modelDir}\n`);
