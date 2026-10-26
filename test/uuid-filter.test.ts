// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { resolveUuidAccountNumbers } from '../src/uuid-filter.js';

const UUID = '42721e36-cd98-43e0-945c-b0e97f58532e';

/** The model's span over the first occurrence of `value` in `text`. */
function spanOver(text: string, value: string, label = 'account_number') {
  const start = text.indexOf(value);
  return { label, start, end: start + value.length, score: 0.97 };
}

function resolve(text: string, value = UUID, label = 'account_number') {
  return resolveUuidAccountNumbers([spanOver(text, value, label)], text);
}

describe('resolveUuidAccountNumbers', () => {
  it('drops a UUID in a path, a log line or a command: an id software minted', () => {
    for (const text of [
      `/private/tmp/claude-501/${UUID}/scratchpad/work/customers.csv`,
      `request id ${UUID} failed with 500`,
      `session_id: ${UUID}`,
      `kubectl delete job ${UUID.toUpperCase()}`,
    ]) {
      expect(resolve(text, text.includes(UUID) ? UUID : UUID.toUpperCase()), text).toEqual([]);
    }
  });

  it('tolerates the stray punctuation span boundaries carry', () => {
    const text = `id=(${UUID}).`;
    expect(resolve(text, `(${UUID}).`)).toEqual([]);
  });

  it('keeps a UUID after a credential-named key masked, as a secret', () => {
    for (const text of [
      `HEROKU_API_KEY=${UUID}`,
      `  "client_secret": "${UUID}",`,
      `Authorization: Bearer ${UUID}`,
      `X-Auth-Token: ${UUID}`,
      `password => '${UUID}'`,
    ]) {
      expect(
        resolve(text).map((s) => s.label),
        text,
      ).toEqual(['secret']);
    }
  });

  it('looks for the key on the same line only', () => {
    const text = `api_key:\n${UUID}`;
    expect(resolve(text)).toEqual([]);
  });

  it('leaves spans that are not a UUID, or not account_number, as they are', () => {
    const iban = 'IT60X0542811101000000123456';
    expect(resolve(`IBAN ${iban}`, iban)).toHaveLength(1);
    const path = `${UUID}.jsonl`;
    expect(resolve(`cat ${path}`, path)).toHaveLength(1);
    const secret = resolve(`token ${UUID}`, UUID, 'secret');
    expect(secret.map((s) => s.label)).toEqual(['secret']);
  });
});
