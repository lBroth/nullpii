// SPDX-License-Identifier: Apache-2.0
//
// Runtime configuration: every environment-variable read in nullpii.
// Adding a new env var? Put its name here AND a typed reader. Don't read
// `process.env` from anywhere else.
//
// (Static defaults live in `defaults.ts`; this file is for runtime env reads.)

const HUGGING_FACE_TOKEN = 'HUGGING_FACE_HUB_TOKEN';
const CUDA_PATH = 'CUDA_PATH';

/** True if `name` is set to a non-empty value. */
function isSet(name: string): boolean {
  const v = process.env[name];
  return v !== undefined && v !== '';
}

/** Whether the Windows CUDA toolkit is on this host (`CUDA_PATH` env). */
export function hasCudaPath(): boolean {
  return isSet(CUDA_PATH);
}

/** HuggingFace Hub token, if set. Used by the deferred mirror step. */
export function huggingFaceToken(): string | undefined {
  const v = process.env[HUGGING_FACE_TOKEN];
  return v !== undefined && v !== '' ? v : undefined;
}
