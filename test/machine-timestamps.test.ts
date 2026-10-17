// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { dropDatesInsideMachineTimestamps } from '../src/machine-timestamps.js';

const date = (text: string, part: string) => {
  const start = text.indexOf(part);
  return { label: 'private_date', start, end: start + part.length };
};

describe('dropDatesInsideMachineTimestamps', () => {
  it('drops dates inside log event timestamps', () => {
    for (const ts of [
      '2026-10-16T09:41:07Z',
      '2026-10-16T09:41:07.123+02:00',
      '2026-10-16 09:41:07,123',
      '2026-10-16T09:41',
    ]) {
      const text = `${ts} INFO request done`;
      expect(dropDatesInsideMachineTimestamps([date(text, ts)], text), ts).toEqual([]);
      expect(dropDatesInsideMachineTimestamps([date(text, '2026-10-16')], text), ts).toEqual([]);
    }
  });

  it('needs a log level after the timestamp', () => {
    const text = '2026-10-16T09:41:07Z Mario Rossi signed the contract';
    expect(
      dropDatesInsideMachineTimestamps([date(text, '2026-10-16T09:41:07Z')], text),
    ).toHaveLength(1);
    const logged = '2026-10-16 09:41:07,123 - billing - WARNING - retry';
    expect(
      dropDatesInsideMachineTimestamps([date(logged, '2026-10-16 09:41:07,123')], logged),
    ).toEqual([]);
  });

  it('keeps a timestamp quoted inside prose', () => {
    const text = 'The interview with Ms. Ferri is at 2023-05-12T14:30:00 sharp.';
    expect(
      dropDatesInsideMachineTimestamps([date(text, '2023-05-12T14:30:00')], text),
    ).toHaveLength(1);
  });

  it('keeps a bare date, such as a birth date', () => {
    const text = 'DOB: 1984-03-12, member since 2019';
    expect(dropDatesInsideMachineTimestamps([date(text, '1984-03-12')], text)).toHaveLength(1);
  });

  it('keeps a date followed by a time without seconds and no T', () => {
    const text = 'appointment 2026-10-16 09:41 with Dr. Ferri';
    expect(dropDatesInsideMachineTimestamps([date(text, '2026-10-16 09:41')], text)).toHaveLength(
      1,
    );
  });

  it('never touches other labels', () => {
    const text = '2026-10-16T09:41:07Z user=mario.rossi@acme.io';
    const email = { label: 'private_email', start: 26, end: text.length };
    expect(dropDatesInsideMachineTimestamps([email], text)).toEqual([email]);
  });
});
