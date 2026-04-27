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

const config = {
  modelDir: ARTIFACT_MODEL_DIR,
  backend: 'cpu' as const,
  variant: 'int8' as const,
};

interface Msgs {
  readonly messages: ReadonlyArray<{ readonly role: string; readonly content: unknown }>;
  readonly [k: string]: unknown;
}

describe('Anthropic middleware — conversationKey multi-turn', () => {
  itIfArtifacts(
    'follow-up call still resolves a placeholder introduced in turn 1',
    async () => {
      // The fake API always emits the placeholder `[[NULLPII:private_person:0]]`
      // in its reply — simulating a model that remembers the entity from
      // turn 1 and refers to it in turn 2 even though turn 2's user prompt
      // does not contain the original name.
      const fake = {
        messages: {
          create: vi.fn(async (_params: Msgs) => ({
            content: [{ type: 'text', text: 'Hello [[NULLPII:private_person:0]]' }],
          })),
        },
      };
      const safe = withNullPii(fake, { ...config, conversationKey: 'thread-A' });

      // Turn 1 — user introduces the name
      await safe.messages.create({
        model: 'claude-test',
        max_tokens: 50,
        messages: [{ role: 'user', content: 'My name is John Smith.' }],
      });

      // Turn 2 — user does NOT mention "John Smith" again, but the placeholder
      // returned by the model in this fake API is `[[NULLPII:private_person:0]]`.
      // The vault must still know that maps to "John Smith" because we share
      // the conversation across turns.
      const r2 = await safe.messages.create({
        model: 'claude-test',
        max_tokens: 50,
        messages: [{ role: 'user', content: 'Greet me again, please.' }],
      });
      const text = (r2.content[0] as { text: string }).text;
      expect(text).toContain('John');
    },
    180_000,
  );
});
