// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import type { NullPii } from 'nullpii';

const PACKAGE_JSON = '../package.json';

/** The non-sensitive runtime metadata the authenticated sidecar status reports. */
export interface SidecarRuntimeInfo {
  readonly gatewayVersion: string;
  readonly nullpiiVersion: string;
  readonly backend: string;
  readonly model: {
    readonly revision: string | null;
    readonly filesPinned: boolean;
  };
}

function readVersion(url: URL): string {
  const pkg = JSON.parse(readFileSync(url, 'utf8')) as { version?: unknown };
  if (typeof pkg.version !== 'string') throw new Error('package.json has no version');
  return pkg.version;
}

/** Read this gateway's release without embedding a second version pin. */
export function gatewayVersion(): string {
  return readVersion(new URL(PACKAGE_JSON, import.meta.url));
}

/** Collect package and engine diagnostics for the sidecar status route. */
export function sidecarRuntimeInfo(np: NullPii): SidecarRuntimeInfo {
  const diagnostics = np.diagnostics();
  return {
    gatewayVersion: gatewayVersion(),
    nullpiiVersion: diagnostics.version,
    backend: diagnostics.backend,
    model: {
      revision: diagnostics.modelRevision ?? null,
      filesPinned: diagnostics.modelFilesPinned,
    },
  };
}
