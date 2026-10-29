// SPDX-License-Identifier: Apache-2.0
//
// What e2e.test.ts reads the real sidecar's answers from. As committed it
// holds none, so `claude plugin test` alone runs no end-to-end scenario.
// tests/e2e-run.mjs writes its own copy of this file, with the sidecar's
// address, token and answers, into a scratch copy of the mod that it tests,
// never into this folder (see e2e-bridge.ts for why).

export const EXCHANGE: unknown = undefined;
