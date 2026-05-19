// SPDX-License-Identifier: Apache-2.0

import { SESSION_PREFIX_LEN } from './types/index.js';

/** Derive the placeholder session prefix from a session UUID:
 * strip hyphens, take the first {@link SESSION_PREFIX_LEN} hex chars,
 * lowercase. Single source of truth for vault + RestoreStream. */
export function sessionPrefixOf(sessionId: string): string {
  return sessionId.replace(/-/g, '').slice(0, SESSION_PREFIX_LEN).toLowerCase();
}
