# Errors

All errors thrown by the library extend `NullPiiError` and expose a stable
`code` for branching without string-matching messages.

```ts
class NullPiiError extends Error {
  readonly code: string;
}

class ModelNotFoundError extends NullPiiError {
  readonly code = 'NULLPII_MODEL_NOT_FOUND';
}
class BackendNotAvailableError extends NullPiiError {
  readonly code = 'NULLPII_BACKEND_NOT_AVAILABLE';
}
class ModelNotInitializedError extends NullPiiError {
  readonly code = 'NULLPII_NOT_INITIALIZED';
}
class TextTooLongError extends NullPiiError {
  readonly code = 'NULLPII_TEXT_TOO_LONG';
}
class SessionNotFoundError extends NullPiiError {
  readonly code = 'NULLPII_SESSION_NOT_FOUND';
}
class InvalidPathError extends NullPiiError {
  readonly code = 'NULLPII_INVALID_PATH';
}
```

## When each one fires

| Error                       | Thrown by                                                    |
| --------------------------- | ------------------------------------------------------------ |
| `ModelNotFoundError`        | `Backend.init()` when the ONNX file is missing on disk        |
| `BackendNotAvailableError`  | `selectBackend()` when the requested backend's probe fails    |
| `ModelNotInitializedError`  | `Backend.infer()` before `init()` (or after `dispose()`)      |
| `TextTooLongError`          | reserved — backends currently truncate silently               |
| `SessionNotFoundError`      | `Vault.sanitize` / `Vault.restore` on unknown `sessionId`     |
| `InvalidPathError`          | `paths.resolveSafePath` when a user path escapes its sandbox  |

## Cause chains

All errors accept `{ cause }` per the standard `Error` options bag:

```ts
try {
  await backend.init();
} catch (cause) {
  throw new ModelNotFoundError('/var/models/foo.onnx', { cause });
}
```
