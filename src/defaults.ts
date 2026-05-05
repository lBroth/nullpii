//
// Single source of truth for every user-facing default in nullpii.
// Adding a new default? Put it here. Reading a default elsewhere? Import
// from here. No `?? 'auto'` / `?? MAGIC_NUMBER` scattered across modules.
//
// Strict TS index-access fallbacks (e.g. `arr[i] ?? 0` under
// `noUncheckedIndexedAccess`) are NOT user-facing defaults and stay inline.

import type { BackendName, ModelVariant } from './types/index.js';
import type { Recognizer } from './types/recognizer.js';
import {
  base58CheckValid,
  codiceFiscaleValid,
  cpfValid,
  iban97Valid,
  luhnValid,
} from './validators.js';

/** Backend chosen when the user passes nothing (or `'auto'`) — the router
 * then walks `BACKEND_AUTO_PRIORITY`. */
export const DEFAULT_BACKEND: BackendName = 'auto';

/** Model variant chosen when the user passes nothing (or `'auto'`).
 * Each backend resolves `'auto'` via its own `BackendConfig.autoVariant`. */
export const DEFAULT_VARIANT: ModelVariant = 'auto';

/** Backend lookup order under `DEFAULT_BACKEND === 'auto'`. */
export const BACKEND_AUTO_PRIORITY: readonly Exclude<BackendName, 'auto'>[] = [
  'cuda',
  'mps',
  'cpu',
];

/** ONNX subdirectory used by legacy single-shard backends (`OrtBackend`).
 * The shipping `MultiOrtBackend` resolves shards via `v10-onnx-merged/`. */
export const ONNX_SUBDIR = 'onnx';

/** Tokenizer file name within a model directory. */
export const TOKENIZER_FILE = 'tokenizer.json';

/** SHA256 sidecar suffix used by `hf-hub.ts`. */
export const CHECKSUM_SUFFIX = '.sha256';

/** XDG-style cache layout. Default: `$XDG_CACHE_HOME/nullpii/` if set,
 * else `~/.cache/nullpii/`. Shared across projects on the same host. */
export const CACHE_DIR_NAME = 'nullpii';
export const CACHE_MODELS_SUBDIR = 'models';

/** Pinned default HF model repo. Hardcoded — full router stack
 * (5 merged-LoRA ONNX shards + distiluse encoder + prototypes). See
 * `model-manager.ts` for the file manifest. */
export const DEFAULT_MODEL_REPO = 'lBroth/nullpii-v10-router-embedding';
export const DEFAULT_MODEL_REVISION = 'main';

/** Built-in recognizers auto-registered on every `NullPii` instance
 * unless the user passes `recognizers: 'none'` or supplies their own
 * array via config.
 *
 * These are the regex patterns proved necessary in the iter-N eval loop
 * (high precision, low FP rate). The ML model alone misses ~66% of URLs
 * and most secrets even when they are surrounded by clear context.
 *
 * Order is irrelevant — the runtime dedupes overlapping spans by
 * confidence (ML wins, then highest-confidence recognizer). */
export const DEFAULT_RECOGNIZERS: readonly Recognizer[] = [
  // ─── URL / Email ──────────────────────────────────────────────
  // URL: only http(s) + www. — bare-domain.tld dropped (FP-prone).
  // The optional URL whitelist filter (PUBLIC_URL_HOSTS) lives in
  // `src/url-filter.ts` and is opt-in.
  {
    id: 'core:url',
    pattern: /\b(?:https?:\/\/|www\.)[^\s<>"]+/g,
    label: 'private_url',
    confidence: 0.95,
  },
  {
    id: 'core:email',
    pattern: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g,
    label: 'private_email',
    confidence: 0.95,
  },

  // ─── AWS ──────────────────────────────────────────────────────
  // All access-token prefixes (A3T*, AKIA, ASIA, ABIA, ACCA).
  {
    id: 'core:aws-access-key',
    pattern: /\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  // AWS Bedrock long-lived. bounded.
  {
    id: 'core:aws-bedrock',
    pattern: /\bABSK[A-Za-z0-9+/]{109,269}={0,2}/g,
    label: 'secret',
    confidence: 0.99,
  },

  // ─── GitHub ───────────────────────────────────────────────────
  {
    id: 'core:github-pat-classic',
    pattern: /\bghp_[A-Za-z0-9]{36,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:github-server-token',
    pattern: /\bghs_[A-Za-z0-9]{36,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:github-oauth',
    pattern: /\bgho_[A-Za-z0-9]{36,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:github-user-token',
    pattern: /\bghu_[A-Za-z0-9]{36,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:github-refresh',
    pattern: /\bghr_[A-Za-z0-9]{36,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:github-pat-fine-grained',
    pattern: /\bgithub_pat_[A-Za-z0-9_]{82,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },

  // ─── OpenAI / Anthropic ───────────────────────────────────────
  {
    id: 'core:openai-key',
    pattern: /\bsk-[A-Za-z0-9]{32,255}\b/g,
    label: 'secret',
    confidence: 0.95,
  },
  {
    id: 'core:anthropic-key',
    pattern: /\bsk-ant-[A-Za-z0-9_-]{50,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:anthropic-admin',
    pattern: /\bsk-ant-admin01-[A-Za-z0-9_\-]{93}AA\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:anthropic-api03',
    pattern: /\bsk-ant-api03-[A-Za-z0-9_\-]{93}AA\b/g,
    label: 'secret',
    confidence: 0.99,
  },

  // ─── Stripe ───────────────────────────────────────────────────
  {
    id: 'core:stripe-key',
    pattern: /\bsk_(?:live|test)_[A-Za-z0-9]{24,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },

  // ─── 1Password / Adobe / Age / Airtable / Alibaba ─────────────
  {
    id: 'core:adobe-pwd',
    pattern:
      /\bA3-[A-Z0-9]{6}-(?:[A-Z0-9]{11}|[A-Z0-9]{6}-[A-Z0-9]{5})-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:1password-vault',
    pattern: /\bops_eyJ[a-zA-Z0-9+/]{250,2048}={0,3}/g,
    label: 'secret',
    confidence: 0.99,
  },
  { id: 'core:airtable', pattern: /\bp8e-[a-zA-Z0-9]{32}\b/g, label: 'secret', confidence: 0.99 },
  {
    id: 'core:age-key',
    pattern: /AGE-SECRET-KEY-1[QPZRY9X8GF2TVDW0S3JN54KHCE6MUA7L]{58}/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:airtable-pat',
    pattern: /\bpat[a-zA-Z0-9]{14}\.[a-f0-9]{64}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  { id: 'core:alibaba', pattern: /\bLTAI[a-zA-Z0-9]{20}\b/g, label: 'secret', confidence: 0.99 },

  // ─── Artifactory / Atlassian ──────────────────────────────────
  {
    id: 'core:artifactory-api',
    pattern: /\bAKCp[A-Za-z0-9]{69}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:artifactory-ref',
    pattern: /\bcmVmd[A-Za-z0-9]{59}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:atlassian-pat',
    pattern: /\bATATT3[A-Za-z0-9_\-=]{186}\b/g,
    label: 'secret',
    confidence: 0.99,
  },

  // ─── Misc cloud / SaaS ────────────────────────────────────────
  { id: 'core:beamer', pattern: /\b4b1d[A-Za-z0-9]{38}\b/g, label: 'secret', confidence: 0.95 },
  { id: 'core:clojars', pattern: /\bCLOJARS_[a-z0-9]{60}\b/gi, label: 'secret', confidence: 0.99 },
  {
    id: 'core:codeship',
    pattern: /\bv1\.0-[a-f0-9]{24}-[a-f0-9]{146}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:databricks',
    pattern: /\bdapi[a-f0-9]{32}(?:-\d)?\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:digitalocean-personal',
    pattern: /\bdoo_v1_[a-f0-9]{64}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:digitalocean-oauth',
    pattern: /\bdop_v1_[a-f0-9]{64}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:digitalocean-refresh',
    pattern: /\bdor_v1_[a-f0-9]{64}\b/g,
    label: 'secret',
    confidence: 0.99,
  },

  // ─── Slack ────────────────────────────────────────────────────
  {
    id: 'core:slack-token',
    pattern: /\bxox[baprs]-[A-Za-z0-9-]{10,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:slack-user-refresh',
    pattern: /\bxoxe\.xoxp-[0-9]+-[A-Za-z0-9]+\b/g,
    label: 'secret',
    confidence: 0.99,
  },

  // ─── GitLab / SendGrid / Twilio / NPM / PyPI / HF / Mailchimp / Notion / Linear ──
  {
    id: 'core:gitlab-pat',
    pattern: /\bglpat-[A-Za-z0-9_\-]{20,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:sendgrid',
    pattern: /\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  { id: 'core:twilio-account', pattern: /\bAC[a-f0-9]{32}\b/g, label: 'secret', confidence: 0.95 },
  { id: 'core:twilio-secret', pattern: /\bSK[a-f0-9]{32}\b/g, label: 'secret', confidence: 0.95 },
  {
    id: 'core:npm-token',
    pattern: /\bnpm_[A-Za-z0-9]{36,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:pypi-token',
    pattern: /\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:huggingface',
    pattern: /\bhf_[A-Za-z0-9]{34,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:mailchimp',
    pattern: /\b[a-f0-9]{32}-us[0-9]{1,2}\b/g,
    label: 'secret',
    confidence: 0.95,
  },
  { id: 'core:notion', pattern: /\bsecret_[A-Za-z0-9]{43}\b/g, label: 'secret', confidence: 0.95 },
  {
    id: 'core:linear',
    pattern: /\blin_api_[A-Za-z0-9]{40,255}\b/g,
    label: 'secret',
    confidence: 0.99,
  },

  // ─── PEM / JWT ────────────────────────────────────────────────
  {
    id: 'core:pem-private-key',
    pattern: /-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:jwt',
    pattern: /\beyJ[A-Za-z0-9_\-]{8,2048}\.[A-Za-z0-9_\-]{8,2048}\.[A-Za-z0-9_\-]{8,2048}\b/g,
    label: 'secret',
    confidence: 0.95,
  },

  // ─── Google / Discord / Telegram / Mailgun / Mapbox / Square / PayPal / Heroku ──
  {
    id: 'core:google-api',
    pattern: /\bAIza[0-9A-Za-z_\-]{35}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:discord-webhook',
    pattern: /https:\/\/discord(?:app)?\.com\/api\/webhooks\/\d+\/[A-Za-z0-9_\-]+/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:discord-bot',
    pattern: /\b[MN][A-Za-z\d]{23}\.[\w-]{6}\.[\w-]{27,255}\b/g,
    label: 'secret',
    confidence: 0.95,
  },
  {
    id: 'core:telegram-bot',
    pattern: /\b\d{8,10}:[A-Za-z0-9_\-]{35}\b/g,
    label: 'secret',
    confidence: 0.95,
  },
  { id: 'core:mailgun', pattern: /\bkey-[a-f0-9]{32}\b/g, label: 'secret', confidence: 0.95 },
  {
    id: 'core:mapbox',
    pattern: /\bpk\.eyJ1Ijoi[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:square-access',
    pattern: /\bEAA[A-Za-z0-9_\-]{200,400}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:paypal-braintree',
    pattern: /\baccess_token\$production\$[a-z0-9]{16}\$[a-f0-9]{32}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:heroku-api',
    pattern: /\bheroku_api_key=[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/g,
    label: 'secret',
    confidence: 0.95,
  },

  // ─── Account-number patterns ──────────────────────────────────
  // IBAN — `\s?` (any whitespace) so PDF NBSP/U+202F separators
  // match. Validated via mod-97 checksum to drop coincidental country-prefix
  // shapes.
  {
    id: 'core:iban',
    pattern: /\b[A-Z]{2}\d{2}[A-Z0-9]{1,4}(?:\s?\d{4}){2,5}(?:\s?\d{1,4})?\b/g,
    label: 'account_number',
    confidence: 0.95,
    validate: iban97Valid,
  },
  // Credit card (12-19 digits, optional `-`/`.`/space). Validated via Luhn.
  {
    id: 'core:credit-card',
    pattern: /\b(?:\d[ \-.]?){12,19}\b/g,
    label: 'account_number',
    confidence: 0.95,
    validate: luhnValid,
  },
  { id: 'core:ssn', pattern: /\b\d{3}-\d{2}-\d{4}\b/g, label: 'account_number', confidence: 0.9 },
  // BTC Legacy/P2SH addresses validated via base58check
  // checksum. Drops prose-token false positives that share the
  // base58 shape (e.g. `Order ID: 1A2B3C4D5E6F...`).
  {
    id: 'core:btc-legacy-1',
    pattern: /\b1[A-HJ-NP-Za-km-z1-9]{25,34}\b/g,
    label: 'account_number',
    confidence: 0.95,
    validate: base58CheckValid,
  },
  {
    id: 'core:btc-p2sh',
    pattern: /\b3[A-HJ-NP-Za-km-z1-9]{25,34}\b/g,
    label: 'account_number',
    confidence: 0.95,
    validate: base58CheckValid,
  },
  {
    id: 'core:btc-bech32',
    pattern: /\bbc1[a-z0-9]{39,59}\b/g,
    label: 'account_number',
    confidence: 0.95,
  },
  {
    id: 'core:eth-address',
    pattern: /\b0x[a-fA-F0-9]{40}\b/g,
    label: 'account_number',
    confidence: 0.95,
  },
  {
    id: 'core:uuid-v4',
    pattern:
      /\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b/g,
    label: 'account_number',
    confidence: 0.85,
  },
  // MAC — lookbehind/lookahead bound to single-octet boundary.
  {
    id: 'core:mac',
    pattern: /(?<![:0-9A-Fa-f])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![:0-9A-Fa-f])/g,
    label: 'account_number',
    confidence: 0.85,
  },
  // IPv4 — octet-bounded to reject version strings.
  {
    id: 'core:ipv4',
    pattern: /\b(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b/g,
    label: 'account_number',
    confidence: 0.85,
  },
  {
    id: 'core:ipv6-full',
    pattern: /\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b/g,
    label: 'account_number',
    confidence: 0.85,
  },
  {
    id: 'core:ipv6-compressed',
    pattern:
      /\b(?:[0-9a-fA-F]{1,4}:){1,7}:|:(?::[0-9a-fA-F]{1,4}){1,7}|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b/g,
    label: 'account_number',
    confidence: 0.85,
  },

  // ─── National IDs ─────────────────────────────────────────────
  {
    id: 'core:dni-spain',
    pattern: /\b\d{8}[A-HJ-NP-TV-Z]\b/g,
    label: 'account_number',
    confidence: 0.9,
  },
  {
    id: 'core:cpf-brazil',
    pattern: /\b\d{3}\.\d{3}\.\d{3}-\d{2}\b/g,
    label: 'account_number',
    confidence: 0.99,
    validate: cpfValid,
  },
  {
    id: 'core:passport-us',
    pattern: /\b[A-CEFGHJ-NPR-Z]\d{8}\b/g,
    label: 'account_number',
    confidence: 0.85,
  },
  { id: 'core:ein-us', pattern: /\b\d{2}-\d{7}\b/g, label: 'account_number', confidence: 0.85 },
  // Italian Codice Fiscale — Validated via per-character
  // odd/even position weights + final-letter check (drops shape
  // matches that don't satisfy the official checksum).
  {
    id: 'core:cf-italy',
    pattern: /\b[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]\b/g,
    label: 'account_number',
    confidence: 0.99,
    validate: codiceFiscaleValid,
  },

  // ─── Phone — anchored on `+` for international, context-anchored for domestic ──
  {
    id: 'core:phone-international',
    pattern: /\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{3,8}/g,
    label: 'private_phone',
    confidence: 0.85,
  },
  // Domestic IT (Tel: 02 3456789). REQUIRED leading context.
  {
    id: 'core:phone-it-domestic',
    pattern: /\b(?:tel|telefono|phone|cell|cellulare|mobile)[\s:.]+(0\d{1,2}[\s\-.]?\d{6,9})\b/gi,
    label: 'private_phone',
    confidence: 0.85,
  },
  // Domestic FR.
  {
    id: 'core:phone-fr-domestic',
    pattern: /\b(?:tel|t[eé]l[eé]phone|portable|mobile|gsm)[\s:.]+(0[1-9](?:[\s\-.]?\d{2}){4})\b/gi,
    label: 'private_phone',
    confidence: 0.85,
  },
  // Domestic ES.
  {
    id: 'core:phone-es-domestic',
    pattern:
      /\b(?:tel|tel[eé]fono|m[oó]vil|cell|cellular|phone)[\s:.]+([6-9]\d{2}[\s\-.]?\d{3}[\s\-.]?\d{2}[\s\-.]?\d{2})\b/gi,
    label: 'private_phone',
    confidence: 0.85,
  },
];

/** Whether `DEFAULT_RECOGNIZERS` are auto-registered on every
 * `NullPii` instance. Override with `new NullPii({ recognizers: 'none' })`
 * or supply a custom list via `recognizers: [...]`. */
export const DEFAULT_RECOGNIZERS_ENABLED = true;

/** Whether to trim leading/trailing whitespace + common punctuation
 * from span edges as a final post-pass. Helps partial-match scoring
 * (IoU >= 0.5) where the model includes trailing dots / brackets that
 * ground-truth annotations exclude. */
export const DEFAULT_BOUNDARY_REFINE = true;

/** Characters trimmed from span edges when boundary-refine is on. */
export const BOUNDARY_REFINE_TRIM_CHARS = ' \t\n\r,.;:!?"\'()[]{}<>';
