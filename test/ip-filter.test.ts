// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { DEFAULT_RECOGNIZERS } from '../src/defaults.js';
import { dropModelIpv4Spans } from '../src/ip-filter.js';
import { runRecognizers } from '../src/recognizers.js';
import { urlPolicy, urlRelease } from '../src/url-filter.js';

/** The model's span over the first occurrence of `value` in `text`. */
function spanOver(text: string, value: string, label: string) {
  const start = text.indexOf(value);
  return { label, start, end: start + value.length, score: 1 };
}

describe('dropModelIpv4Spans', () => {
  it('drops the labels the model puts on dotted quads', () => {
    // Labels the release model gave these texts.
    const cases: Array<[string, string, string]> = [
      ['server 93.184.216.34', '93.184.216.34', 'private_phone'],
      ['docs IP 203.0.113.7', '203.0.113.7', 'account_number'],
      ['ping 172.16.4.20', '172.16.4.20', 'secret'],
      ['DNS is 8.8.8.8', '8.8.8.8', 'private_ip'],
    ];
    for (const [text, ip, label] of cases) {
      expect(dropModelIpv4Spans([spanOver(text, ip, label)], text), text).toEqual([]);
    }
  });

  it('tolerates the stray punctuation span boundaries carry', () => {
    const text = 'from (93.184.216.34).';
    expect(dropModelIpv4Spans([spanOver(text, '(93.184.216.34).', 'private_phone')], text)).toEqual(
      [],
    );
  });

  it('keeps spans that are more than an address', () => {
    const cases: Array<[string, string, string]> = [
      ['call +39 345 987 6543', '+39 345 987 6543', 'private_phone'],
      ['version v1.2.3.4', 'v1.2.3.4', 'secret'],
      ['open http://93.184.216.34/admin', 'http://93.184.216.34/admin', 'private_url'],
      ['at 93.184.216.34:8443', '93.184.216.34:8443', 'private_ip'],
    ];
    for (const [text, value, label] of cases) {
      expect(dropModelIpv4Spans([spanOver(text, value, label)], text), text).toHaveLength(1);
    }
  });
});

describe('core:ipv4 after the model spans are dropped', () => {
  const ips = (text: string) =>
    runRecognizers(text, DEFAULT_RECOGNIZERS, [])
      .filter((s) => s.label === 'private_ip')
      .map((s) => text.slice(s.start, s.end));

  it('masks a public address as private_ip', () => {
    expect(ips('server 93.184.216.34')).toEqual(['93.184.216.34']);
  });

  it('leaves documentation, loopback, private and unspecified addresses readable', () => {
    for (const text of [
      'docs IP 203.0.113.7',
      'curl 127.0.0.1',
      'ping 172.16.4.20',
      'ssh 10.0.0.5',
      'listening on 0.0.0.0:3000',
    ]) {
      expect(ips(text), text).toEqual([]);
    }
  });
});

describe('URLs on this machine', () => {
  it('stay readable whole by default', () => {
    for (const u of [
      'http://127.0.0.1:8787/health',
      'http://localhost:3000/api/users',
      'http://[::1]:8080/',
      'http://0.0.0.0:5173/',
    ]) {
      expect(urlRelease(u, urlPolicy()), u).toBe('full');
    }
  });

  it('are masked once the defaults are replaced', () => {
    const policy = urlPolicy({ replaceDefaults: true, hosts: {} });
    expect(urlRelease('http://127.0.0.1:8787/health', policy)).toBe('mask');
  });
});
