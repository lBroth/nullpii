// SPDX-License-Identifier: Apache-2.0
//
// The e2e bridge (tests/e2e-bridge.ts) on its own, with no sidecar: it
// answers a challenge of the mod's only when it is the one the real
// sidecar answered, but for its nonce, and prints each one it answers,
// for the runner to check against the sidecar.

import { expect, test } from 'claude-code/testing';
import { expectedProof } from '../hooks/policy.ts';
import {
  type Bridge,
  CHALLENGE_PATH,
  type Exchange,
  type FetchCall,
  type WireStep,
  openBridge,
} from './e2e-bridge.ts';

const ORIGIN = 'http://127.0.0.1:8787';
const TOKEN = 'k'.repeat(64);
const SCENARIO = 'scenario';
/** The nonce of the recorded challenge, and a fresh one as the mod draws it. */
const RECORDED_NONCE = '0123456789abcdef'.repeat(4);
const NONCE = 'fedcba9876543210'.repeat(4);
const JSON_TYPE = { 'content-type': 'application/json' } as const;
const ANSWER_HEADERS = { 'content-type': 'application/json; charset=utf-8' } as const;
const HTTP_OK = 200;

/** The mod's first challenge, and the sidecar's answer: `status`, and the
 * proof for `proofNonce`. */
async function recordedChallenge(status = HTTP_OK, proofNonce = RECORDED_NONCE): Promise<WireStep> {
  return {
    request: {
      method: 'POST',
      path: CHALLENGE_PATH,
      headers: { ...JSON_TYPE },
      body: JSON.stringify({ nonce: RECORDED_NONCE }),
    },
    response: {
      status,
      headers: { ...ANSWER_HEADERS },
      text: JSON.stringify({ proof: await expectedProof(TOKEN, proofNonce) }),
    },
  };
}

function bridgeOf(challenge?: WireStep, print?: (line: string) => void): Bridge {
  const exchange: Exchange = {
    url: ORIGIN,
    token: TOKEN,
    run: 'run',
    ...(challenge !== undefined && { challenge }),
    steps: {},
  };
  return openBridge(exchange, SCENARIO, print);
}

/** A challenge as the mod sends it, with `change` made to it. */
function challenge(change: { path?: string; init?: FetchCall['init'] } = {}): FetchCall {
  return {
    url: ORIGIN + (change.path ?? CHALLENGE_PATH),
    init: {
      method: 'POST',
      headers: { ...JSON_TYPE },
      body: JSON.stringify({ nonce: NONCE }),
      ...change.init,
    },
  };
}

/** What the test's run throws once the bridge has answered; undefined
 * when it passes. */
async function runError(bridge: Bridge): Promise<string | undefined> {
  try {
    await bridge.wire.run(async () => undefined);
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
  return undefined;
}

/** Expect `call` refused, and the test failed for leaving the recorded
 * path with `why` in its message. */
async function expectOffPath(call: FetchCall, why: string, recorded?: WireStep): Promise<void> {
  const bridge = bridgeOf(recorded ?? (await recordedChallenge()));
  const answer = await bridge.fetch(call);
  expect('deny' in answer, 'the bridge answered a challenge it has no answer for').toBe(true);
  expect(bridge.wire.challenges).toBe(0);
  const error = await runError(bridge);
  expect(error).toContain('e2e bridge: ');
  expect(error).toContain(why);
}

test('a challenge before the sidecar answered one waits for the runner, and fails nothing', async () => {
  const bridge = bridgeOf();
  const answer = await bridge.fetch(challenge());
  expect(answer).toEqual({
    deny: 'nullpii e2e bridge: the sidecar has not answered this request yet',
  });
  expect(bridge.wire.challenges).toBe(0);
  expect(await runError(bridge)).toBeUndefined();
});

test('the recorded challenge but for its nonce gets the recorded answer, with the proof for its own nonce', async () => {
  const bridge = bridgeOf(await recordedChallenge());
  const answer = await bridge.fetch(challenge());
  if (!('value' in answer)) throw new Error(`refused: ${answer.deny}`);
  expect(answer.value.status).toBe(HTTP_OK);
  expect(answer.value.ok).toBe(true);
  expect(answer.value.headers).toEqual({ ...ANSWER_HEADERS });
  expect(JSON.parse(answer.value.text)).toEqual({ proof: await expectedProof(TOKEN, NONCE) });
  expect(bridge.wire.challenges).toBe(1);
  expect(await runError(bridge)).toBeUndefined();
});

test('the bridge prints each challenge it answers, with its answer, for the runner to send to the sidecar', async () => {
  const printed: string[] = [];
  const bridge = bridgeOf(await recordedChallenge(), (line) => printed.push(line));
  const answer = await bridge.fetch(challenge());
  if (!('value' in answer)) throw new Error(`refused: ${answer.deny}`);
  expect(printed).toHaveLength(1);
  const [line] = printed;
  expect(line?.startsWith('nullpii-e2e signed ')).toBe(true);
  expect(JSON.parse(line?.slice('nullpii-e2e signed '.length) ?? '')).toEqual({
    scenario: SCENARIO,
    request: {
      method: 'POST',
      path: CHALLENGE_PATH,
      headers: { ...JSON_TYPE },
      body: JSON.stringify({ nonce: NONCE }),
    },
    response: { status: HTTP_OK, headers: { ...ANSWER_HEADERS }, text: answer.value.text },
  });
});

test('a challenge whose nonce is in upper case is not the recorded one', async () => {
  const body = JSON.stringify({ nonce: NONCE.toUpperCase() });
  await expectOffPath(challenge({ init: { body } }), 'upper-case hex');
});

test('a challenge whose nonce is shorter is not the recorded one', async () => {
  const body = JSON.stringify({ nonce: NONCE.slice(0, NONCE.length / 2) });
  await expectOffPath(challenge({ init: { body } }), 'its nonce has 32 characters');
});

test('a challenge with a query is not the recorded one', async () => {
  await expectOffPath(challenge({ path: `${CHALLENGE_PATH}?x=1` }), `${CHALLENGE_PATH}?x=1`);
});

test('a challenge sent as a GET is not the recorded one', async () => {
  await expectOffPath(challenge({ init: { method: 'GET' } }), 'GET /v1/sidecar/challenge');
});

test('a challenge with another content type is not the recorded one', async () => {
  const headers = { 'content-type': 'text/plain' };
  await expectOffPath(challenge({ init: { headers } }), 'but for its nonce');
});

test('a challenge that sends the token is not the recorded one', async () => {
  const headers = { ...JSON_TYPE, authorization: `Bearer ${TOKEN}` };
  await expectOffPath(challenge({ init: { headers } }), 'but for its nonce');
});

test('a challenge whose body holds more than the nonce is not the recorded one', async () => {
  const body = JSON.stringify({ nonce: NONCE, extra: true });
  await expectOffPath(challenge({ init: { body } }), 'but for its nonce');
});

test('a challenge with no nonce is not the recorded one', async () => {
  await expectOffPath(challenge({ init: { body: '{}' } }), 'holds no nonce');
});

test('a sidecar that refused the recorded challenge answers no later one', async () => {
  await expectOffPath(challenge(), 'with 400, not 200', await recordedChallenge(400));
});

test('a sidecar whose proof is not the one the mod expects answers no later challenge', async () => {
  await expectOffPath(
    challenge(),
    'not the proof the mod expects',
    await recordedChallenge(HTTP_OK, NONCE),
  );
});
