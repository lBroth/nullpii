// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { printBanner } from '../src/banner.js';
import {
  logInboundResponse,
  logInboundSseChunk,
  logOutboundHeaders,
  logOutboundRequest,
} from '../src/traffic-log.js';
import { BASE_TEST_CONFIG } from './fixtures.js';

let out = '';
beforeEach(() => {
  out = '';
  vi.spyOn(process.stdout, 'write').mockImplementation((chunk: string | Uint8Array) => {
    out += String(chunk);
    return true;
  });
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe('traffic log', () => {
  it('dumps the sanitized request body and names the upstream', () => {
    logOutboundRequest(
      { messages: [{ content: '{{PII_PRIVATE_PERSON_0_ab}}' }] },
      'req-1',
      'openai',
    );
    expect(out).toContain('sanitized → openai');
    expect(out).toContain('[req-1]');
    expect(out).toContain('{{PII_PRIVATE_PERSON_0_ab}}');
  });

  it('masks credentials in the forwarded headers, keeping their length', () => {
    const key = 'sk-ant-api03-SECRETSECRETSECRET-abcdef';
    logOutboundHeaders({
      'x-api-key': key,
      Authorization: 'Bearer tok-123456',
      'anthropic-version': '2023-06-01',
    });
    expect(out).not.toContain(key);
    expect(out).not.toContain('Bearer tok-123456');
    expect(out).toContain(`len=${key.length}`);
    expect(out).toContain('2023-06-01');
  });

  it('truncates a large body and dumps SSE chunks with their size', () => {
    logInboundResponse('x'.repeat(70 * 1024), 'req-2');
    expect(out).toMatch(/…\[truncated \d+b\]/);
    out = '';
    logInboundSseChunk('data: {}\n\n', 'req-3');
    expect(out).toContain('← SSE');
    expect(out).toContain('10b');
  });
});

describe('startup banner', () => {
  it('prints the listen address, upstreams and how to point a client', () => {
    printBanner({ ...BASE_TEST_CONFIG, port: 8787, logTraffic: true }, 'dev');
    expect(out).toContain('http://127.0.0.1:8787');
    expect(out).toContain('ANTHROPIC_BASE_URL=http://127.0.0.1:8787');
    expect(out).toContain('OPENAI_BASE_URL=http://127.0.0.1:8787/v1');
    expect(out).toContain('wire dump on');
    expect(out).toContain('[dev]');
  });
});
