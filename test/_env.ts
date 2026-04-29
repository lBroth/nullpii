// SPDX-License-Identifier: Apache-2.0
//
// Single point for environment-driven test gating. Every other test file
// imports from here — never reads `process.env` directly.

import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ENV_TEST_MODEL_DIR = 'NULLPII_TEST_MODEL_DIR';
const ENV_NETWORK = 'NULLPII_E2E';

function readEnv(name: string): string | undefined {
  const v = process.env[name];
  return v !== undefined && v !== '' ? v : undefined;
}

/** Path to a local copy of `openai/privacy-filter` for gated tests. */
export const TEST_MODEL_DIR = resolve(
  readEnv(ENV_TEST_MODEL_DIR) ??
    new URL('./.nullpii-test-artifacts/model', import.meta.url).pathname,
);

/** True when the local test artifacts directory has the smallest fp16 variant. */
export const HAS_TEST_ARTIFACTS = existsSync(join(TEST_MODEL_DIR, 'onnx', 'model_fp16.onnx'));

/** Same dir but gated on the int8 / quantized variant (some CLI tests need it). */
export const HAS_TEST_QUANTIZED = existsSync(join(TEST_MODEL_DIR, 'onnx', 'model_quantized.onnx'));

/** Opt-in for tests that hit the network (`NULLPII_E2E=1`). */
export const NETWORK_OK = readEnv(ENV_NETWORK) === '1';
