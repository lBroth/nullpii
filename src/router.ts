import debug from 'debug';
import type { SessionThreads } from './backend/ort-backend.js';
import { BACKEND_AUTO_PRIORITY, DEFAULT_BACKEND, DEFAULT_VARIANT } from './defaults.js';
import { BackendNotAvailableError } from './errors.js';
import type { BackendName, BackendProvider, ModelVariant, NullPiiConfig } from './types/index.js';

const log = debug('nullpii:router');

type BackendCtor = new (
  modelDir: string,
  variant: ModelVariant,
  threads?: SessionThreads,
) => BackendProvider;

async function loadBackend(name: Exclude<BackendName, 'auto'>): Promise<BackendCtor> {
  switch (name) {
    case 'cpu': {
      const m = await import('./backend/cpu-backend.js');
      return m.CpuBackend as BackendCtor;
    }
    case 'mps': {
      const m = await import('./backend/mps-backend.js');
      return m.MpsBackend as BackendCtor;
    }
    case 'cuda': {
      const m = await import('./backend/cuda-backend.js');
      return m.CudaBackend as BackendCtor;
    }
  }
}

/**
 * Pick the best available backend for `config`.
 *
 * @param modelDir local directory holding the model artifacts.
 * @param config user configuration. `backend` defaults to `'auto'`.
 * @returns an instantiated backend (not yet `init()`-ed).
 * @throws {BackendNotAvailableError} if the explicit backend is unavailable
 *   or if `'auto'` finds nothing usable.
 */
export async function selectBackend(
  modelDir: string,
  config: NullPiiConfig = {},
): Promise<BackendProvider> {
  const variant: ModelVariant = config.variant ?? DEFAULT_VARIANT;
  const requested = config.backend ?? DEFAULT_BACKEND;
  const threads: { -readonly [K in keyof SessionThreads]: SessionThreads[K] } = {};
  if (config.intraOpNumThreads !== undefined) threads.intraOpNumThreads = config.intraOpNumThreads;
  if (config.interOpNumThreads !== undefined) threads.interOpNumThreads = config.interOpNumThreads;

  if (requested !== 'auto') {
    const Ctor = await loadBackend(requested);
    const backend = new Ctor(modelDir, variant, threads);
    if (!(await backend.isAvailable())) {
      throw new BackendNotAvailableError(requested);
    }
    log('selected backend (explicit): %s', requested);
    return backend;
  }

  for (const name of BACKEND_AUTO_PRIORITY) {
    const Ctor = await loadBackend(name);
    const backend = new Ctor(modelDir, variant, threads);
    if (await backend.isAvailable()) {
      log('selected backend (auto): %s', name);
      return backend;
    }
  }
  throw new BackendNotAvailableError('auto');
}
