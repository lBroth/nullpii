import { CLOUD_KEYS } from '../packages/recognizers-cloud/src/index.js';
import { FINANCE } from '../packages/recognizers-finance/src/index.js';
import { ITALIAN_IDS } from '../packages/recognizers-id-it/src/index.js';
import { NullPii } from '../src/index.js';

const np = new NullPii({ backend: 'cpu', variant: 'int8' });

// Bundled packs
for (const r of CLOUD_KEYS) np.addRecognizer(r);
for (const r of FINANCE) np.addRecognizer(r);
for (const r of ITALIAN_IDS) np.addRecognizer(r);

// Project-specific custom recognizer
np.addRecognizer({
  id: 'acme-employee-id',
  pattern: /\bACME-\d{6}\b/g,
  label: 'account_number',
  confidence: 0.99,
});

const text = `
  AKIAIOSFODNN7EXAMPLE leaked.
  Card 4242424242424242 charged.
  CF: RSSMRA80A01H501U
  Employee: ACME-123456
`;

const { sanitized, spans } = await np.sanitize(text);
console.log('spans:', spans.length);
console.log(sanitized);
await np.dispose();
