// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import {
  InvalidPathError,
  ModelNotFoundError,
  ModelNotInitializedError,
  NullPiiError,
  OrtNotInstalledError,
  SessionMismatchError,
  SessionNotFoundError,
  TextTooLongError,
} from '../src/errors.js';

describe('NullPiiError base class', () => {
  it('is an Error and reports its constructor name', () => {
    const err = new NullPiiError('boom');
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(NullPiiError);
    expect(err.name).toBe('NullPiiError');
    expect(err.code).toBe('NULLPII_ERROR');
    expect(err.message).toBe('boom');
  });

  it('preserves the cause via Error options', () => {
    const cause = new Error('underlying');
    const err = new NullPiiError('wrapper', { cause });
    expect(err.cause).toBe(cause);
  });
});

describe('ModelNotFoundError', () => {
  it('throws with the offending path in the message', () => {
    expect(() => {
      throw new ModelNotFoundError('/var/models/foo.onnx');
    }).toThrow(/foo\.onnx/);
  });

  it('extends NullPiiError and exposes a stable code', () => {
    const err = new ModelNotFoundError('/x');
    expect(err).toBeInstanceOf(NullPiiError);
    expect(err.code).toBe('NULLPII_MODEL_NOT_FOUND');
  });
});

describe('ModelNotInitializedError', () => {
  it('throws and instructs the caller to call init()', () => {
    expect(() => {
      throw new ModelNotInitializedError();
    }).toThrow(/init\(\)/);
  });

  it('exposes a stable code', () => {
    expect(new ModelNotInitializedError().code).toBe('NULLPII_NOT_INITIALIZED');
  });
});

describe('TextTooLongError', () => {
  it('throws with both observed length and limit', () => {
    const err = new TextTooLongError(900, 512);
    expect(err.message).toContain('900');
    expect(err.message).toContain('512');
  });

  it('exposes a stable code', () => {
    expect(new TextTooLongError(1, 0).code).toBe('NULLPII_TEXT_TOO_LONG');
  });
});

describe('SessionNotFoundError', () => {
  it('throws with the session id', () => {
    expect(() => {
      throw new SessionNotFoundError('sess_42');
    }).toThrow(/sess_42/);
  });

  it('exposes a stable code', () => {
    expect(new SessionNotFoundError('x').code).toBe('NULLPII_SESSION_NOT_FOUND');
  });
});

describe('SessionMismatchError', () => {
  it('throws with both expected and found prefixes', () => {
    const err = new SessionMismatchError('aaaaaaaa', 'bbbbbbbb');
    expect(err.message).toContain('aaaaaaaa');
    expect(err.message).toContain('bbbbbbbb');
  });

  it('exposes a stable code', () => {
    expect(new SessionMismatchError('x', 'y').code).toBe('NULLPII_SESSION_MISMATCH');
  });
});

describe('OrtNotInstalledError', () => {
  it('exposes a stable code and a setup hint', () => {
    const err = new OrtNotInstalledError();
    expect(err.code).toBe('NULLPII_ORT_NOT_INSTALLED');
    expect(err.message).toMatch(/onnxruntime-node/);
  });
});

describe('InvalidPathError', () => {
  it('throws with the offending path', () => {
    expect(() => {
      throw new InvalidPathError('../../../etc/passwd');
    }).toThrow(/passwd/);
  });

  it('exposes a stable code', () => {
    expect(new InvalidPathError('/x').code).toBe('NULLPII_INVALID_PATH');
  });
});

describe('error codes are unique', () => {
  it('every error class has a distinct code', () => {
    const codes = new Set([
      new NullPiiError('').code,
      new ModelNotFoundError('').code,
      new ModelNotInitializedError().code,
      new TextTooLongError(0, 0).code,
      new SessionNotFoundError('').code,
      new SessionMismatchError('', '').code,
      new OrtNotInstalledError().code,
      new InvalidPathError('').code,
    ]);
    expect(codes.size).toBe(8);
  });
});
