import { ModelManager } from '../src/index.js';

// Run during CI / Docker build to bake the model into the image.
const manager = new ModelManager();
const result = await manager.ensure({
  variant: 'int4f16',
  onProgress: (p) => process.stdout.write(`\rprefetch ${(p * 100).toFixed(0)}%`),
});
process.stdout.write('\n');
process.stdout.write(`cached at: ${result.modelDir}\n`);
