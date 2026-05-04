# SOC 2 Type II readiness — `nullpii` cloud / managed offering

> **Disclaimer.** This is engineering pre-work, not an audit substitute. SOC 2 Type II requires an independent auditor over a 6–12 month observation window. Engage AICPA-registered auditor before claiming SOC 2 publicly.

## Scope

SOC 2 applies to the **cloud / managed offering** (`nullpii.cloud` SaaS), not to the npm library. The library deploys in-process on the customer's infrastructure; SOC 2 obligations stay with the customer.

If shipping the cloud offering:
- **Trust Services Criteria** in scope: Security (mandatory) + Confidentiality (likely) + Privacy (if processing personal data on behalf of customers).
- **Type II** = controls observed for ≥ 6 months continuously. Type I (point-in-time) is cheaper but lower-assurance.

## Pre-audit engineering checklist

### Security (CC1–CC9)

- [ ] **CC2 — Communication**: published security policy, incident-response playbook, customer-facing vulnerability disclosure (`security.txt`).
- [ ] **CC3 — Risk assessment**: documented threat model. Specific concerns: prompt-leakage during sanitisation, vault-state attacks, model supply-chain (HF weights), tenant isolation.
- [ ] **CC4 — Monitoring**: centralised log aggregation, anomaly detection on per-tenant request rates, alerts on auth failures.
- [ ] **CC5 — Control activities**: change management (PR approvals, signed commits, semver), access review (quarterly).
- [ ] **CC6 — Logical access**: SSO (SAML / OIDC) for control plane, scoped API tokens for data plane, MFA on production access, no shared credentials.
- [ ] **CC7 — System operations**: backup + restore tested, incident response runbook, on-call rotation.
- [ ] **CC8 — Change management**: code review on every change, automated CI tests, staged deployments, rollback playbook.
- [ ] **CC9 — Risk mitigation**: vendor risk assessments (HF, ONNX runtime, cloud providers), supply-chain pinning + verification.

### Confidentiality (C1.x)

- [ ] **C1.1 — Data identification**: data classification scheme (public / internal / customer-confidential / regulated PHI).
- [ ] **C1.2 — Data protection**: TLS 1.3 in transit, AES-256 at rest, customer-key encryption option for high-tier customers.

### Privacy (P1–P8) — only if processing personal data on customer's behalf

- [ ] **P1 — Notice**: privacy notice published, clear about what nullpii does + does not do (e.g. no Art. 9 detection — see DPIA).
- [ ] **P2 — Choice and consent**: customer-driven processing; nullpii does not collect personal data on its own initiative.
- [ ] **P3 — Collection**: minimisation by design (vault is in-memory, no persistence by default).
- [ ] **P4 — Use, retention, disposal**: in-memory vault auto-disposed at end-of-request. Documented in DPIA.
- [ ] **P5 — Access**: customer-facing data-subject-request workflow (DSR / GDPR Art. 15).
- [ ] **P6 — Disclosure to third parties**: subprocessor list published + reviewed quarterly.
- [ ] **P7 — Quality**: data-quality controls (rate-limiting, malformed-input rejection).
- [ ] **P8 — Monitoring + enforcement**: privacy training for engineers, breach-notification protocol, customer DPA on file.

### Engineering pre-work

- [ ] **Provenance**: HF model weights pinned by hash, signed releases.
- [ ] **Reproducibility**: bench harness deterministic given seed + dataset version pin.
- [ ] **Latency / availability SLA**: p99 latency target per profile published; uptime ≥ 99.9% target documented.
- [ ] **Tenant isolation**: per-tenant vault scoping, per-tenant rate limits, per-tenant logging.
- [ ] **Secrets management**: KMS-backed API key storage, no secrets in repo.

## Audit timeline (typical)

| Phase | Duration | Notes |
|---|---|---|
| Readiness assessment | 1–2 months | Internal gap analysis vs the checklist above |
| Remediation | 2–4 months | Close gaps |
| Type I observation | 1–2 weeks | Auditor confirms controls exist as of a date |
| Type II observation | 6–12 months | Auditor monitors controls continuously |
| Type II report | 1 month | Final report issued |

**Realistic Type II from cold start**: 9–14 months total. Plan for it before promising it to enterprise customers.

## Reading list

- AICPA SOC 2 guidance: https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2
- CIS Controls v8 (ops baseline): https://www.cisecurity.org/controls
- ISO 27001 → SOC 2 mapping: useful if pursuing both certifications.

## Sign-off

Created: 2026-05-03. To be reviewed by CISO + privacy counsel before any SOC 2 marketing claim.
