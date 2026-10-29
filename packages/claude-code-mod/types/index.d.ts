// SPDX-License-Identifier: Apache-2.0
//
// The value this mod keeps in `$.state`: held by Claude Code for the
// process, in memory, and kept across a reload of the mod's module. Any
// plugin can read it, so it is never a secret.

/** A sidecar session key, as the mod names it: the Claude Code session id,
 * or the id with a suffix. Not a secret. */
export type SidecarKey = string;

declare module 'claude-code' {
  interface PluginState {
    /** `heldKey`: the sidecar session key this process holds open (not its
     * secret), or null once it is closed. A reloaded module, which has lost
     * the secret, names it to the sidecar as a key this window left. */
    nullpii: { heldKey: SidecarKey | null };
  }
}
