/**
 * Base class for every error thrown by `nullpii`.
 *
 * Consumers can write `if (err instanceof NullPiiError)` to distinguish
 * library errors from arbitrary `Error` instances. Each subclass exposes
 * a stable `code` so callers can branch without string-matching the
 * message (which is for humans and may change).
 */
export class NullPiiError extends Error {
  /** Stable machine-readable identifier for this error class. */
  readonly code: string = 'NULLPII_ERROR';

  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = new.target.name;
  }
}

/** Thrown when a required model file is not present on disk. */
export class ModelNotFoundError extends NullPiiError {
  override readonly code = 'NULLPII_MODEL_NOT_FOUND';
  /** @param path absolute path that was checked */
  constructor(path: string, options?: { cause?: unknown }) {
    super(`model artifact not found at: ${path}`, options);
  }
}

/** Thrown when the requested backend cannot run on this system. */
export class BackendNotAvailableError extends NullPiiError {
  override readonly code = 'NULLPII_BACKEND_NOT_AVAILABLE';
  /** @param backend identifier of the unavailable backend */
  constructor(backend: string, options?: { cause?: unknown }) {
    super(`backend not available on this system: ${backend}`, options);
  }
}

/** Thrown when an inference is attempted before `init()` resolved. */
export class ModelNotInitializedError extends NullPiiError {
  override readonly code = 'NULLPII_NOT_INITIALIZED';
  constructor(options?: { cause?: unknown }) {
    super('model is not initialized — call init() first', options);
  }
}

/** Thrown when input would exceed the configured token cap. */
export class TextTooLongError extends NullPiiError {
  override readonly code = 'NULLPII_TEXT_TOO_LONG';
  /**
   * @param tokenCount actual length of the encoded input
   * @param limit configured `MAX_SEQUENCE_LENGTH`
   */
  constructor(tokenCount: number, limit: number, options?: { cause?: unknown }) {
    super(`input too long: ${tokenCount} tokens > limit ${limit}`, options);
  }
}

/** Thrown when `restore()` is called with an unknown or evicted session. */
export class SessionNotFoundError extends NullPiiError {
  override readonly code = 'NULLPII_SESSION_NOT_FOUND';
  /** @param sessionId opaque session id from `SanitizeResult` */
  constructor(sessionId: string, options?: { cause?: unknown }) {
    super(`vault session not found: ${sessionId}`, options);
  }
}

/** Thrown when a user-provided path resolves outside its allowed sandbox. */
export class InvalidPathError extends NullPiiError {
  override readonly code = 'NULLPII_INVALID_PATH';
  /** @param path the offending path, as provided */
  constructor(path: string, options?: { cause?: unknown }) {
    super(`unsafe or invalid path: ${path}`, options);
  }
}
