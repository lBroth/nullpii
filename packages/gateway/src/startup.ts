// SPDX-License-Identifier: Apache-2.0

import type { InitProgress } from 'nullpii';

/** One step of the engine's first start-up, as `GET /v1/sidecar/status`
 * reports it while `startServer` warms the model up. */
export type StartupPhase = 'downloading' | 'loading' | 'ready' | 'failed';

/** The `startup` field of the status answer. Absent on a gateway built
 * without a tracker (a server with a pre-built engine, as in tests). */
export interface StartupView {
  readonly phase: StartupPhase;
  /** The model file downloading (while `phase` is `downloading`). */
  readonly file?: string;
  /** Bytes of it received so far. */
  readonly received?: number;
  /** Its full size, when the hub names it. */
  readonly total?: number;
  /** The step that was running when a failed warmup failed, for a
   * message that says which one (the model manager logs the error). */
  readonly while?: 'downloading' | 'loading';
}

/**
 * Tracks the engine's first start-up for the status route: the model
 * files downloading, the ONNX session loading, then ready — or which
 * step was running when the warmup failed.
 */
export class StartupTracker {
  // Before any report, the first `ensure` is fetching or verifying the
  // model files, which on a cold cache is the download.
  private view: StartupView = { phase: 'downloading' };

  /** Record one step of `NullPii.warmup`. */
  report(progress: InitProgress): void {
    this.view =
      progress.phase === 'downloading'
        ? {
            phase: 'downloading',
            file: progress.file,
            received: progress.received,
            ...(progress.total !== undefined && { total: progress.total }),
          }
        : { phase: progress.phase };
  }

  /** Record that the warmup failed while it was in the step last
   * reported; the error itself is logged, not sent to callers. */
  failed(): void {
    this.view = {
      phase: 'failed',
      while: this.view.phase === 'loading' ? 'loading' : 'downloading',
    };
  }

  /** The step the warmup is in now, as the status route answers it. */
  get current(): StartupView {
    return this.view;
  }
}
