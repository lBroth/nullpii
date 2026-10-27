// SPDX-License-Identifier: Apache-2.0

/** Fixed, non-sensitive diagnostics for `/pii doctor`. No status value is
 * displayed until its shape and character set have been checked. */

const SAFE_VERSION = /^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/;
const SAFE_REVISION = /^[0-9a-f]{40}$/;
const BACKENDS: ReadonlySet<string> = new Set(['cpu', 'cuda', 'mps']);
const SIDECAR_FIX =
  'start it with npx or Docker (start Docker first), or enable "Start the sidecar"';
const PORT_FIX =
  'another program may hold the sidecar address: pick a free port in the "Sidecar URL" option (/plugin configure), or stop that program';
const NOT_CHECKED_FIX = 'fix the sidecar first (the first line)';
const RELEASE_FIX = 'restart the sidecar from the release the mod pins';
const MODEL_FIX =
  'use the default pinned model, without a model-directory override, and restart the sidecar';
const OLDER_FIX =
  'an older sidecar is still running: stop it (or the old Docker image) and let the mod start the pinned release';
const BACKEND_FIX = 'restart the sidecar with CPU, CUDA or MPS configured';
const POLICY_FIX = 'fix or remove the policy file with the nullpii CLI, then restart the sidecar';
const TOKEN_FIX =
  'set sidecar_token with /plugin configure, or set NULLPII_SIDECAR_TOKEN for the mod';

export type ModState = 'on' | 'starting' | 'paused' | 'blocking';

/** The validated subset of the sidecar status used by the doctor. */
export interface DoctorSidecarStatus {
  readonly gatewayVersion: string | undefined;
  readonly nullpiiVersion: string | undefined;
  readonly backend: string | undefined;
  readonly modelRevision: string | undefined;
  readonly modelFilesPinned: boolean | undefined;
  readonly policyLoaded: boolean | undefined;
}

export interface DoctorInput {
  readonly status: DoctorSidecarStatus | undefined;
  readonly sidecarReason: string | undefined;
  readonly expectedRelease: string;
  readonly tokenSet: boolean;
  readonly modState: ModState;
  readonly lastFailure: string | undefined;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function safeString(value: unknown, pattern: RegExp): string | undefined {
  return typeof value === 'string' && pattern.test(value) ? value : undefined;
}

/** Read only known, non-sensitive status fields; reject every display value
 * whose character set the mod does not control. */
export function readDoctorStatus(value: unknown): DoctorSidecarStatus | undefined {
  const status = record(value);
  if (status === undefined) return undefined;
  const model = record(status.model);
  const policy = record(status.policy);
  return {
    gatewayVersion: safeString(status.gatewayVersion, SAFE_VERSION),
    nullpiiVersion: safeString(status.nullpiiVersion, SAFE_VERSION),
    backend:
      typeof status.backend === 'string' && /^[a-z]+$/.test(status.backend)
        ? status.backend
        : undefined,
    modelRevision: safeString(model?.revision, SAFE_REVISION),
    modelFilesPinned: typeof model?.filesPinned === 'boolean' ? model.filesPinned : undefined,
    policyLoaded: typeof policy?.loaded === 'boolean' ? policy.loaded : undefined,
  };
}

/** The first line, which carries the reason once and its fix; a reason that
 * says another program answered at the address gets the fix for that. */
function unavailable(name: string, reason: string): string {
  const fix = reason.includes('did not prove it holds') ? PORT_FIX : SIDECAR_FIX;
  return `FAIL ${name}: sidecar unavailable (${reason}). Fix: ${fix}.`;
}

/** Every other line that needs the sidecar: short, since the first line
 * has the reason. */
function notChecked(name: string): string {
  return `FAIL ${name}: not checked, the sidecar did not answer. Fix: ${NOT_CHECKED_FIX}.`;
}

/** A sidecar from before the doctor reports none of the new fields at once. */
function olderSidecar(status: DoctorSidecarStatus): boolean {
  return (
    status.gatewayVersion === undefined &&
    status.nullpiiVersion === undefined &&
    status.backend === undefined &&
    status.modelRevision === undefined &&
    status.modelFilesPinned === undefined
  );
}

function olderLine(name: string): string {
  return `FAIL ${name}: this sidecar does not report it. Fix: ${OLDER_FIX}.`;
}

function releaseLine(input: DoctorInput): string {
  const { status } = input;
  if (status === undefined) return notChecked('Gateway and nullpii versions');
  if (olderSidecar(status)) return olderLine('Gateway and nullpii versions');
  const { gatewayVersion, nullpiiVersion, expectedRelease } = { ...status, ...input };
  if (gatewayVersion === undefined || nullpiiVersion === undefined) {
    return `FAIL Gateway and nullpii versions: not reported safely. Fix: ${RELEASE_FIX}.`;
  }
  if (gatewayVersion !== expectedRelease || nullpiiVersion !== expectedRelease) {
    return `FAIL Gateway and nullpii versions: gateway ${gatewayVersion}, nullpii ${nullpiiVersion}; pinned ${expectedRelease}. Fix: ${RELEASE_FIX}.`;
  }
  return `PASS Gateway and nullpii versions: ${gatewayVersion} (pinned)`;
}

function modelLine(input: DoctorInput): string {
  const { status } = input;
  if (status === undefined) return notChecked('Model');
  if (olderSidecar(status)) return olderLine('Model');
  if (status.modelRevision === undefined || status.modelFilesPinned !== true) {
    return `FAIL Model: the default revision and SHA-256 file pins were not reported. Fix: ${MODEL_FIX}.`;
  }
  return `PASS Model: revision ${status.modelRevision}; default files have SHA-256 pins`;
}

function backendLine(input: DoctorInput): string {
  const { status } = input;
  if (status === undefined) return notChecked('Backend');
  if (olderSidecar(status)) return olderLine('Backend');
  if (status.backend === 'auto') {
    return 'INFO Backend: auto (the actual provider is reported after the model loads)';
  }
  if (status.backend === undefined || !BACKENDS.has(status.backend)) {
    return `FAIL Backend: no supported actual backend reported. Fix: ${BACKEND_FIX}.`;
  }
  return `PASS Backend: ${status.backend}`;
}

function policyLine(input: DoctorInput): string {
  const { status } = input;
  if (status === undefined) return notChecked('Policy file');
  if (status.policyLoaded === undefined) {
    return `FAIL Policy file: load state not reported. Fix: ${POLICY_FIX}.`;
  }
  return status.policyLoaded
    ? 'PASS Policy file: loaded and parsed'
    : 'PASS Policy file: no file; built-in defaults loaded';
}

/** Format one plain-text line per doctor check, with a fix on every failure. */
export function formatDoctor(input: DoctorInput): string {
  const sidecar =
    input.status === undefined
      ? unavailable('Sidecar and token proof', input.sidecarReason ?? 'not checked')
      : 'PASS Sidecar and token proof: answered the challenge and authenticated status request';
  return [
    sidecar,
    releaseLine(input),
    modelLine(input),
    backendLine(input),
    input.tokenSet
      ? 'PASS Token: set (value not shown)'
      : `FAIL Token: not set. Fix: ${TOKEN_FIX}.`,
    policyLine(input),
    `INFO Mod state: ${input.modState}`,
    `INFO Last failure: ${input.lastFailure ?? 'none'}`,
  ].join('\n');
}
