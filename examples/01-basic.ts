// SPDX-License-Identifier: Apache-2.0
import { NullPii } from '../src/index.js';

const np = new NullPii({ backend: 'cpu', variant: 'int8' });

const text = 'Hi, my name is John Smith and my email is john@example.com.';
const out = await np.sanitize(text);
console.log('sanitized :', out.sanitized);
console.log('spans     :', out.spans);

const back = np.restore(out.sanitized, out.sessionId);
console.log('restored  :', back.restored);
console.log('round-trip:', back.restored === text ? 'OK' : 'FAIL');

await np.dispose();
