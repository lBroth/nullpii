# Anthropic SDK middleware

```ts
import Anthropic from '@anthropic-ai/sdk';
import { withNullPii } from 'nullpii/middleware/anthropic';

const safe = withNullPii(new Anthropic(), {
  backend: 'auto',
  variant: 'auto',
});

const reply = await safe.messages.create({
  model: 'claude-haiku-4-5',
  max_tokens: 200,
  messages: [{ role: 'user', content: 'Hi, my name is John Smith.' }],
});
// reply.content has placeholders restored to original values.
```

## How it works

`withNullPii(client)` returns a `Proxy` that satisfies the same
TypeScript type as the original client. The proxy intercepts
`messages.create` and:

1. Opens a vault session.
2. Sanitizes every text field in `params.messages[*].content`
   (string content or array of `{ type: 'text', text }` blocks).
3. Forwards the sanitized request to Anthropic.
4. Restores text fields in the response.
5. **Always** destroys the session in a `finally` block — even if the
   API call throws.

## Conversation reuse

For multi-turn conversations, pass the same client across turns. Each
call gets its own session by default. To reuse a session across calls,
you must pin the conversation outside the middleware (planned).

## Streaming

Currently, only non-streaming responses are restored. Streaming support
is on the roadmap; until then, call `messages.create(...)` without
`stream: true`.

## Peer dependency

```bash
npm install @anthropic-ai/sdk
```

`@anthropic-ai/sdk` is an **optional peer dependency** of `nullpii`.
You only need it if you use this middleware.
