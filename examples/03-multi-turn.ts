// SPDX-License-Identifier: Apache-2.0
import Anthropic from '@anthropic-ai/sdk';
import { withNullPii } from '../src/middleware/anthropic.js';

const safe = withNullPii(new Anthropic(), { conversationKey: 'thread-42' });

// Turn 1: introduces "John"
await safe.messages.create({
  model: 'claude-haiku-4-5',
  max_tokens: 100,
  messages: [{ role: 'user', content: 'Remember: John Smith is the customer.' }],
});

// Turn 2: model may quote back the placeholder; vault still resolves
const r2 = await safe.messages.create({
  model: 'claude-haiku-4-5',
  max_tokens: 100,
  messages: [
    { role: 'user', content: 'Remember: John Smith is the customer.' },
    { role: 'assistant', content: 'Got it.' },
    { role: 'user', content: 'What was the customer name again?' },
  ],
});
const first = r2.content[0];
if (first?.type === 'text') console.log(first.text); // should mention "John Smith"
