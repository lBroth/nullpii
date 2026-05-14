import type { Recognizer } from 'nullpii';

/** AWS access key id (`AKIA...` for IAM, `ASIA...` for STS). */
export const AWS_ACCESS_KEY: Recognizer = {
  id: 'cloud:aws:access-key',
  pattern: /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
};

/** AWS secret access key — 40 base64-ish chars after a known prefix is hard
 * to bound, so this matches contextual hints: `aws_secret_access_key=...`. */
export const AWS_SECRET_KEY_HINTED: Recognizer = {
  id: 'cloud:aws:secret-key-hinted',
  pattern: /aws_secret_access_key\s*[:=]\s*([A-Za-z0-9/+=]{40})/g,
  label: 'secret',
  confidence: 0.95,
};

/** Google Cloud service-account key id (`AIza...`). */
export const GCP_API_KEY: Recognizer = {
  id: 'cloud:gcp:api-key',
  pattern: /\bAIza[0-9A-Za-z\-_]{35}\b/g,
  label: 'secret',
  confidence: 0.99,
};

/** Azure subscription / connection-string-style fragments. */
export const AZURE_CONNECTION_STRING: Recognizer = {
  id: 'cloud:azure:connection-string',
  pattern: /AccountKey=[A-Za-z0-9+/=]{40,}/g,
  label: 'secret',
  confidence: 0.99,
};

/** GitHub personal access token (`ghp_...`). */
export const GITHUB_PAT: Recognizer = {
  id: 'cloud:github:pat',
  pattern: /\bghp_[A-Za-z0-9]{36}\b/g,
  label: 'secret',
  confidence: 0.99,
};

/** Slack bot / app token. */
export const SLACK_TOKEN: Recognizer = {
  id: 'cloud:slack:token',
  pattern: /\bxox[abrsp]-[A-Za-z0-9-]{10,}\b/g,
  label: 'secret',
  confidence: 0.97,
};

/** Stripe live key (`sk_live_...`). */
export const STRIPE_LIVE_KEY: Recognizer = {
  id: 'cloud:stripe:live-key',
  pattern: /\bsk_live_[A-Za-z0-9]{24,}\b/g,
  label: 'secret',
  confidence: 0.99,
};

/** All-cloud-keys recognizer pack — drop-in. */
export const CLOUD_KEYS: readonly Recognizer[] = [
  AWS_ACCESS_KEY,
  AWS_SECRET_KEY_HINTED,
  GCP_API_KEY,
  AZURE_CONNECTION_STRING,
  GITHUB_PAT,
  SLACK_TOKEN,
  STRIPE_LIVE_KEY,
];
