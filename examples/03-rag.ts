import { NullPii } from '../src/index.js';

interface Doc {
  readonly id: string;
  readonly text: string;
}

const corpus: Doc[] = [
  { id: 'd1', text: 'Customer Maria Rossi (maria.rossi@example.it) reported issue #1.' },
  { id: 'd2', text: 'Internal AWS key AKIAIOSFODNN7EXAMPLE was leaked in commit abc.' },
];

const np = new NullPii({ backend: 'cpu' });

for (const doc of corpus) {
  const { sanitized, sessionId, spans } = await np.sanitize(doc.text);
  // index `sanitized` (e.g. into Pinecone / pgvector / Lance);
  // store sessionId alongside doc id so retrieval restores the originals.
  console.log('doc', doc.id, 'spans=', spans.length, 'sessionId=', sessionId);
  console.log(' →', sanitized);
}

await np.dispose();
