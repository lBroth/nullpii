// SPDX-License-Identifier: Apache-2.0
//
// Single point for environment-driven test gating. Tests that need a
// local copy of `openai/privacy-filter` look here for the path + a
// boolean flag; absent artifacts → tests skip cleanly.

import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

/** Conventional path for a developer-downloaded model. Gitignored. */
export const TEST_MODEL_DIR = resolve(
  new URL('./.nullpii-test-artifacts/model', import.meta.url).pathname,
);

/** True when the local artifacts have the smallest fp16 variant. */
export const HAS_TEST_ARTIFACTS = existsSync(join(TEST_MODEL_DIR, 'onnx', 'model_fp16.onnx'));

/** True when the int8 / quantized variant is present (some CLI tests need it). */
export const HAS_TEST_QUANTIZED = existsSync(join(TEST_MODEL_DIR, 'onnx', 'model_quantized.onnx'));
