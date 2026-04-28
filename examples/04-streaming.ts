// SPDX-License-Identifier: Apache-2.0
import Anthropic from '@anthropic-ai/sdk';
import { withNullPii } from '../src/middleware/anthropic.js';

const safe = withNullPii(new Anthropic());

const stream = (
  safe.messages as unknown as {
    stream: (params: unknown) => AsyncIterable<{ delta?: { text?: string } }>;
  }
).stream({
  model: 'claude-haiku-4-5',
  max_tokens: 200,
  messages: [{ role: 'user', content: 'Email John Smith at john@acme.com.' }],
});

for await (const ev of stream) {
  const text = ev.delta?.text;
  if (typeof text === 'string') process.stdout.write(text);
}
process.stdout.write('\n');
