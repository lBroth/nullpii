// SPDX-License-Identifier: Apache-2.0

import { NullPii } from '../src/index.js';

interface Doc {
  readonly id: string;
  readonly text: string;
}

const corpus: Doc[] = [
  { id: 'd1', text: 'Customer Maria Rossi (maria.rossi@example.com) reported issue #1.' },
  { id: 'd2', text: 'Internal AWS key AKIAIOSFODNN7EXAMPLE was leaked in commit abc.' },
];

const np = new NullPii({ backend: 'cpu' });

// Index the masked text (e.g. into Pinecone / pgvector / Lance). The vault
// lives in this process's memory only and is never written anywhere, so
// the real values cannot be restored after a restart: index masked text
// that is useful as it is, and drop each session once it is indexed.
for (const doc of corpus) {
  const { sanitized, sessionId, spans } = await np.sanitize(doc.text);
  console.log('doc', doc.id, 'spans=', spans.length);
  console.log(' →', sanitized);
  np.destroySession(sessionId);
}

await np.dispose();
