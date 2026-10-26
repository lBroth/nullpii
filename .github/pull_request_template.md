## What and why

<!-- One paragraph. Link the issue. -->

## Checks

- [ ] Tests cover the happy path, an edge case and an error case.
- [ ] `npm run lint && npm run typecheck && npm test` pass locally.
- [ ] CHANGELOG updated for user-visible changes.

## Privacy and security

- [ ] No real personal data anywhere: fixtures use reserved values only (see CONTRIBUTING.md, "Test data").
- [ ] No real secret, token or key, not even revoked ones. Fake secrets in tests use the documented examples or an obviously fake body.
- [ ] Logs and errors carry counts and short ids only, never a detected value.
- [ ] Nothing from `packages/eval/private/` or `packages/eval/results/`, no model weights, no local paths.
- [ ] Detection changes: the leak rate (char recall) was measured before and after, and did not get worse.
