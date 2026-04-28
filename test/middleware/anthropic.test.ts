// SPDX-License-Identifier: Apache-2.0
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { withNullPii } from '../../src/middleware/anthropic.js';

const ARTIFACT_MODEL_DIR = resolve(
  new URL('../../packages/convert/artifacts/model', import.meta.url).pathname,
);
const HAS_ARTIFACTS = existsSync(join(ARTIFACT_MODEL_DIR, 'onnx', 'model_quantized.onnx'));
const itIfArtifacts = HAS_ARTIFACTS ? it : it.skip;

const config = { modelDir: ARTIFACT_MODEL_DIR, backend: 'cpu' as const, variant: 'int8' as const };

interface MsgParams {
  readonly messages: ReadonlyArray<{ readonly role: string; readonly content: unknown }>;
  readonly [k: string]: unknown;
}
interface MsgResp {
  readonly content: ReadonlyArray<{ readonly type: string; readonly text?: string }>;
  readonly [k: string]: unknown;
}

function makeClient(impl: (params: MsgParams) => Promise<MsgResp>) {
  return { messages: { create: vi.fn(impl) } };
}

describe('withNullPii (Anthropic middleware)', () => {
  itIfArtifacts(
    'sanitizes outbound user content before the API call',
    async () => {
      const captured: MsgParams[] = [];
      const fake = makeClient(async (params) => {
        captured.push(params);
        return { content: [{ type: 'text', text: 'Hello' }] };
      });
      const safe = withNullPii(fake, config);
      await safe.messages.create({
        model: 'claude-test',
        max_tokens: 10,
        messages: [{ role: 'user', content: 'Hi, my name is John Smith.' }],
      });
      const seen = JSON.stringify(captured);
      expect(seen).not.toContain('John Smith');
    },
    180_000,
  );

  itIfArtifacts(
    'restores placeholders in the response back to original PII',
    async () => {
      const fake = makeClient(async (params) => {
        const first = params.messages[0];
        const text = typeof first?.content === 'string' ? first.content : '';
        const placeholder = text.match(/\[\[NULLPII:[^\]]+\]\]/)?.[0] ?? '';
        return { content: [{ type: 'text', text: `Hello ${placeholder}` }] };
      });
      const safe = withNullPii(fake, config);
      const reply = await safe.messages.create({
        model: 'claude-test',
        max_tokens: 10,
        messages: [{ role: 'user', content: 'My name is John Smith.' }],
      });
      const out = (reply.content[0] as { text: string }).text;
      expect(out).toContain('John');
      expect(out).not.toContain('NULLPII');
    },
    180_000,
  );

  itIfArtifacts(
    'destroys the vault session even if the API call throws',
    async () => {
      const boom = new Error('upstream error');
      const fake = makeClient(async () => {
        throw boom;
      });
      const safe = withNullPii(fake, config);
      await expect(
        safe.messages.create({
          model: 'claude-test',
          max_tokens: 1,
          messages: [{ role: 'user', content: 'My name is John.' }],
        }),
      ).rejects.toBe(boom);
      const fake2 = makeClient(async () => ({ content: [{ type: 'text', text: 'ok' }] }));
      const safe2 = withNullPii(fake2, config);
      const r = await safe2.messages.create({
        model: 'claude-test',
        max_tokens: 1,
        messages: [{ role: 'user', content: 'plain text' }],
      });
      expect(r).toBeDefined();
    },
    180_000,
  );
});
