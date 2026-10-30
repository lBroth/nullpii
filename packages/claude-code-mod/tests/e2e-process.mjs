// SPDX-License-Identifier: Apache-2.0
//
// What tests/e2e-run.mjs and tests/e2e-sidecar.mjs share about the
// processes they run: the signals that end a run early, how a child is
// stopped, and how a child is killed with every process it started.

import { setTimeout as sleep } from 'node:timers/promises';

/** A process ended by signal number n exits with this plus n, as a shell
 * reports it. */
export const SIGNAL_EXIT_BASE = 128;
/** The signals that end a run early, with their numbers: a hang-up (the
 * terminal closed, an SSH link dropped), Ctrl-C, and a kill. The default
 * action of each ends the process at once, with no cleanup run, so each
 * one gets a handler. */
export const EXIT_SIGNALS = { SIGHUP: 1, SIGINT: 2, SIGTERM: 15 };
const TIMED_OUT = Symbol('timed out');

/** Call `handler(signal, exitCode)` on each signal of `EXIT_SIGNALS`,
 * `exitCode` the one a process ended by that signal has. `on`, not
 * `once`: a second signal must find the handler again, not the default
 * action, which ends the process before the first handler is done. */
export function onExitSignals(handler) {
  for (const [signal, number] of Object.entries(EXIT_SIGNALS)) {
    process.on(signal, () => handler(signal, SIGNAL_EXIT_BASE + number));
  }
}

/** Kill with SIGKILL every process of the group `child` leads: `child`
 * must have been spawned with `detached: true`, which makes it the leader
 * of a group of its own. Its own children are in that group too, and so
 * is any process they start, unless one makes a group or session of its
 * own. A group already gone is not an error. POSIX only: Windows has no
 * process groups. */
export function killGroup(child) {
  if (child.pid === undefined) return;
  try {
    process.kill(-child.pid, 'SIGKILL');
  } catch (err) {
    if (err.code !== 'ESRCH') throw err;
  }
}

/** Stop `child` with SIGTERM, and kill it with SIGKILL when it has not
 * exited within `timeoutMs`; `exited` resolves once it exits. Resolves
 * with whether it had to be killed. The timer holds nothing up: while the
 * child runs, its own handle keeps this process alive, and once it is
 * gone, this process may exit at once. */
export async function stopChild(child, exited, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) return false;
  child.kill('SIGTERM');
  const stopped = await Promise.race([exited, sleep(timeoutMs, TIMED_OUT, { ref: false })]);
  if (stopped !== TIMED_OUT) return false;
  child.kill('SIGKILL');
  await exited;
  return true;
}
