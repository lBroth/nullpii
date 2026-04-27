// SPDX-License-Identifier: Apache-2.0
import Anthropic from '@anthropic-ai/sdk';
import { withNullPii } from '../src/middleware/anthropic.js';

const safe = withNullPii(new Anthropic());

const reply = await safe.messages.create({
  model: 'claude-haiku-4-5',
  max_tokens: 200,
  messages: [
    {
      role: 'user',
      content:
        'Draft a polite refund email to Maria Rossi (maria.rossi@example.it) about order #ACME-2026-04812.',
    },
  ],
});

const first = reply.content[0];
if (first?.type === 'text') console.log(first.text);
