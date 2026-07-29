// SPDX-License-Identifier: Apache-2.0

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
  latLonPairInRange,
  luhnValid,
  macAddressNonReserved,
  vinValid,
} from './validators.js';

/** Backend chosen when the user passes nothing (or `'auto'`). The
 * ONNX model runtime today always resolves to `'cpu'` execution
 * providers + an optional accelerator fallback (`cuda` / `coreml`),
 * mapped at session construction in `nullpii.ts`. */
export const DEFAULT_BACKEND: BackendName = 'auto';

/** Model variant chosen when the user passes nothing (or `'auto'`).
 * Only `fp32` is shipped today; `int8` / `int4` are reserved (see
 * `PLAN.md §4`). */
export const DEFAULT_VARIANT: ModelVariant = 'auto';

/** Tokenizer file name within a model directory. */
export const TOKENIZER_FILE = 'tokenizer.json';

/** SHA256 sidecar suffix used by `hf-hub.ts`. */
export const CHECKSUM_SUFFIX = '.sha256';

/** XDG-style cache layout. Default: `$XDG_CACHE_HOME/nullpii/` if set,
 * else `~/.cache/nullpii/`. Shared across projects on the same host. */
export const CACHE_DIR_NAME = 'nullpii';
export const CACHE_MODELS_SUBDIR = 'models';

/** Pinned default HF model repo. Hardcoded — GLiNER ONNX
 * (`model.onnx` + tokenizer + config, ~1.16 GB FP32). See
 * `model-manager.ts` for the file manifest. */
export const DEFAULT_MODEL_REPO = 'lBroth/nullpii';
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
  // The public-host allowlist (`PUBLIC_URL_HOSTS` in `src/url-filter.ts`)
  // runs as a post-filter and is on by default; opt out via
  // `NullPiiConfig.urlAllowlist: 'none'`.
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
  // AWS Bedrock long-lived API key (`ABSK` prefix + 109-269 base64 chars).
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
  // Full block, header through trailer. Backref `\1` ensures the
  // algorithm token in `BEGIN` matches `END`, so an unterminated header
  // does not eat an unrelated `END` farther down the document. If the
  // matching trailer is absent (truncated paste), no match — better to
  // miss than to over-redact.
  {
    id: 'core:pem-private-key',
    pattern:
      /-----BEGIN (RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----[\s\S]*?-----END \1 PRIVATE KEY-----/g,
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
  // IBAN — `\s?` (any whitespace) between every group so PDF / human-typed
  // forms with spaces between country-check and bank-code (e.g. `GB29 NWBK
  // …`, `DE89 3704 …`) match alongside compact forms (`IT60X05428…`).
  // PDF NBSP / U+202F separators count as `\s`. Validated via mod-97
  // checksum to drop coincidental country-prefix shapes.
  {
    id: 'core:iban',
    pattern: /\b[A-Z]{2}\d{2}\s?[A-Z0-9]{1,4}(?:\s?\d{4}){2,5}(?:\s?\d{1,4})?\b/g,
    label: 'account_number',
    confidence: 0.95,
    validate: iban97Valid,
  },
  // Credit card (13-19 digits, optional `-`/`.`/space). Validated via Luhn.
  // 13 is the smallest issued card today (old Visa); 12-digit Luhn-passing
  // sequences are typically long phone numbers / IDs and tagging them as
  // `account_number` is a measurable FP source on bench corpora.
  {
    id: 'core:credit-card',
    pattern: /\b(?:\d[ \-.]?){13,19}\b/g,
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
  // MAC — lookbehind/lookahead bound to single-octet boundary. Labelled
  // `private_mac` (separate from `private_ip`) so consumers that group
  // spans by label keep hardware identifiers distinct from IPv4/IPv6.
  {
    id: 'core:mac',
    pattern: /(?<![:0-9A-Fa-f])[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![:0-9A-Fa-f])/g,
    label: 'private_mac',
    confidence: 0.85,
    validate: macAddressNonReserved,
  },
  // IPv4 — octet-bounded to reject version strings.
  {
    id: 'core:ipv4',
    pattern: /\b(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b/g,
    label: 'private_ip',
    confidence: 0.85,
  },
  {
    id: 'core:ipv6-full',
    pattern: /\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b/g,
    label: 'private_ip',
    confidence: 0.85,
  },
  {
    id: 'core:ipv6-compressed',
    pattern:
      /\b(?:[0-9a-fA-F]{1,4}:){1,7}:|:(?::[0-9a-fA-F]{1,4}){1,7}|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b/g,
    label: 'private_ip',
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

  // ─── Cloud / payment provider secrets (more than the AKIA + ghp_ already above) ──
  // AWS secret access key — only fired when the canonical hint
  // `aws_secret_access_key=...` precedes the 40-char base64-ish token.
  // Free-form 40-char base64 strings are too common to flag without an
  // anchor.
  {
    id: 'core:aws-secret-key-hinted',
    pattern: /aws_secret_access_key\s*[:=]\s*([A-Za-z0-9/+=]{40})/gi,
    label: 'secret',
    confidence: 0.95,
  },
  // Azure storage / event-hub connection string fragment.
  {
    id: 'core:azure-connection-string',
    pattern: /AccountKey=[A-Za-z0-9+/=]{40,}/g,
    label: 'secret',
    confidence: 0.99,
  },
  // Stripe live secret key (`sk_live_...`). Test keys (`sk_test_...`)
  // are public-by-design — not flagged.
  {
    id: 'core:stripe-live-key',
    pattern: /\bsk_live_[A-Za-z0-9]{24,}\b/g,
    label: 'secret',
    confidence: 0.99,
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

  // ─── Passport numbers (context-anchored where ambiguous) ──────────
  // Pattern strategy: prefer context-anchored ("passport", "passeport",
  // "passaporto", "passnummer", "P/N") to keep precision high. Add
  // syntax-only patterns ONLY where the format is unique enough that
  // standalone matching is acceptable (US: letter + 8 digits; UK: 9
  // digits → REQUIRES context due to FP rate). The international
  // ICAO 9303 MRZ format is too dataset-specific to ship by default.
  {
    // US passport book/card: 1 letter + 8 digits (I/O/Q excluded to
    // avoid digit confusion). Context REQUIRED — the uncontexted shape
    // collides with `id_card:` / `License:` / generic ID-number
    // formats (measured precision ~14% on nullpii-bench standalone).
    id: 'core:passport-us-context',
    pattern: /(?<=\bpassport(?:\s*(?:no|number|nbr|#))?[\s:.]+)[A-HJ-NPR-Z]\d{8}\b/gi,
    label: 'private_passport',
    confidence: 0.97,
  },
  {
    // Italian passport context: 2 letters + 7 digits (post-2006).
    // Uncontexted variant dropped — `[A-Z]{2}\d{7}` collides with SKUs,
    // model numbers, ISBNs on free text. Generic context fallback
    // (`core:passport-generic-context`) covers prose with the keyword.
    id: 'core:passport-it-context',
    pattern: /(?<=\b(?:passaporto|passport)[\s:.n°]+)[A-Z]{2}\d{7}\b/gi,
    label: 'private_passport',
    confidence: 0.97,
  },
  {
    // UK passport: 9 digits. Pure digits — context REQUIRED.
    id: 'core:passport-uk-context',
    pattern: /(?<=\bpassport(?:\s*(?:no|number))?[\s:.#]+)\d{9}\b/gi,
    label: 'private_passport',
    confidence: 0.95,
  },
  {
    // German passport context: typically C/F/G + 9 alphanumeric.
    // Uncontexted variant dropped — `[CFGRPT][0-9A-Z]{9}` collides
    // with serial numbers and product codes on free text.
    id: 'core:passport-de-context',
    pattern: /(?<=\b(?:passnummer|reisepass|passport)[\s:.#]+)[CFGRPT][0-9A-Z]{9}\b/gi,
    label: 'private_passport',
    confidence: 0.95,
  },
  {
    // French passport: 9 alphanumeric chars, typically 2 digit + 2 letter + 5 digit.
    id: 'core:passport-fr-context',
    pattern: /(?<=\b(?:passeport|passport)[\s:.n°]+)[0-9]{2}[A-Z]{2}[0-9]{5}\b/gi,
    label: 'private_passport',
    confidence: 0.95,
  },
  {
    // Spanish passport context: 3 letters + 6 digits.
    // Uncontexted variant dropped — overlaps with airline locators,
    // booking refs, ISBN-like sequences. Keep context-anchored only.
    id: 'core:passport-es-context',
    pattern: /(?<=\b(?:pasaporte|passport)[\s:.n°#]+)[A-Z]{3}\d{6}\b/gi,
    label: 'private_passport',
    confidence: 0.95,
  },
  {
    // Generic context-anchored passport (fallback for jurisdictions we
    // don't ship explicit patterns for). Matches 6-12 alphanumeric
    // after a passport keyword; required context keeps FP low.
    id: 'core:passport-generic-context',
    pattern:
      /(?<=\b(?:passport|passeport|passaporto|passnummer|reisepass|pasaporte|paszport|paspoort)[\s:.n°#-]+)[A-Z0-9]{6,12}\b/gi,
    label: 'private_passport',
    confidence: 0.9,
  },

  // ─── Driver licence numbers (context REQUIRED — formats too varied) ─
  // Driver licence formats are jurisdiction-specific and frequently
  // collide with phone numbers, account IDs, or SSN-shape strings.
  // Context anchor is mandatory; high-confidence cells stay.
  {
    id: 'core:driver-license-generic-context',
    pattern:
      /(?<=\b(?:driver(?:'s|s)?\s*(?:lic(?:ence|ense)|dl)|dln|dl#|patente|permis(?:\s*de\s*conduire)?|f[üu]hrerschein|carnet\s*de\s*conducir|rijbewijs|cnh|c[aá]rt[ae]\s*de\s*condu[çc][ãa]o)[\s:.#]+)[A-Z0-9][A-Z0-9\-]{4,18}[A-Z0-9]\b/gi,
    label: 'private_driver_license',
    confidence: 0.95,
  },
  {
    // California: letter + 7 digits.
    id: 'core:driver-license-ca-context',
    pattern: /(?<=\b(?:DL|driver\s*license)[\s:.#]+)[A-Z]\d{7}\b/gi,
    label: 'private_driver_license',
    confidence: 0.95,
  },
  {
    // New York: 9 digits OR 1 letter + 18 digits.
    id: 'core:driver-license-ny-context',
    pattern: /(?<=\b(?:NY\s*DL|driver\s*license)[\s:.#]+)(?:\d{9}|[A-Z]\d{18})\b/gi,
    label: 'private_driver_license',
    confidence: 0.95,
  },
  {
    // Italian patente: 1 letter + 1 alpha + 7 digits + 1 letter (10 chars).
    id: 'core:driver-license-it-context',
    pattern: /(?<=\b(?:patente(?:\s*di\s*guida)?|n\.?\s*patente)[\s:.#]+)[A-Z]{1,2}\d{7}[A-Z]\b/gi,
    label: 'private_driver_license',
    confidence: 0.95,
  },

  // ─── Vehicle identifiers ──────────────────────────────────────────
  // VIN: 17-char alphanumeric with mod-11 weighted check digit at pos 9.
  // Validator drops shape matches that don't satisfy ISO 3779.
  {
    id: 'core:vin',
    pattern: /\b[A-HJ-NPR-Z0-9]{17}\b/g,
    label: 'private_vehicle_id',
    confidence: 0.9,
    validate: vinValid,
  },
  // License plates (per-country canonical formats — keep tight).
  {
    // Italian plates (post-1994): 2 letters + 3 digits + 2 letters.
    id: 'core:plate-it',
    pattern: /\b[A-Z]{2}\s?\d{3}\s?[A-Z]{2}\b/g,
    label: 'private_vehicle_id',
    confidence: 0.85,
  },
  {
    // French plates (post-2009): 2 letters - 3 digits - 2 letters.
    id: 'core:plate-fr',
    pattern: /\b[A-Z]{2}-\d{3}-[A-Z]{2}\b/g,
    label: 'private_vehicle_id',
    confidence: 0.9,
  },
  {
    // German plates: 1-3 letters + dash + 1-2 letters + 1-4 digits.
    id: 'core:plate-de',
    pattern: /\b[A-Z]{1,3}-[A-Z]{1,2}\s?\d{1,4}\b/g,
    label: 'private_vehicle_id',
    confidence: 0.85,
  },
  {
    // UK plates (post-2001): 2 letters + 2 digits + space + 3 letters.
    id: 'core:plate-uk',
    pattern: /\b[A-Z]{2}\d{2}\s?[A-Z]{3}\b/g,
    label: 'private_vehicle_id',
    confidence: 0.85,
  },
  {
    // Spanish plates (post-2000): 4 digits + 3 letters (no vowels).
    id: 'core:plate-es',
    pattern: /\b\d{4}\s?[BCDFGHJKLMNPRSTVWXYZ]{3}\b/g,
    label: 'private_vehicle_id',
    confidence: 0.85,
  },
  {
    // US plates — too varied per state; context-anchored only.
    id: 'core:plate-us-context',
    pattern: /(?<=\b(?:license\s*plate|plate(?:\s*number)?|tag)[\s:.#]+)[A-Z0-9\-]{3,8}\b/gi,
    label: 'private_vehicle_id',
    confidence: 0.9,
  },

  // ─── Geolocation (lat/lon decimal pairs + DMS notation) ───────────
  // Decimal degree pairs: requires BOTH lat and lon separated by `,`
  // (with optional whitespace). Range-validated — pure decimals in
  // `[-180, 180]` are too common in arbitrary text to flag standalone.
  {
    id: 'core:geo-latlon-decimal',
    pattern: /-?\d{1,3}\.\d{2,8}\s*,\s*-?\d{1,3}\.\d{2,8}/g,
    label: 'private_geolocation',
    confidence: 0.9,
    validate: latLonPairInRange,
  },
  {
    // DMS (Degrees Minutes Seconds) with hemisphere letter — high
    // precision, low FP because the °'" sequence is distinctive.
    id: 'core:geo-dms',
    pattern: /\d{1,3}°\s?\d{1,2}['′]\s?\d{1,2}(?:\.\d+)?["″]?\s?[NSEW]/g,
    label: 'private_geolocation',
    confidence: 0.95,
  },
  {
    // Context-anchored decimal lat OR lon (drops the strict pairing
    // requirement when the user explicitly says "latitude: X").
    id: 'core:geo-context',
    pattern:
      /(?<=\b(?:lat(?:itude)?|lon(?:gitude)?|lng|gps|coord(?:inate)?s?)[\s:=]+)-?\d{1,3}\.\d{2,8}\b/gi,
    label: 'private_geolocation',
    confidence: 0.9,
  },

  // ─── HIPAA-coverage extensions to account_number ──────────────────
  // Medicare Beneficiary Identifier (MBI): 11 chars, structured
  // (digit/letter pattern excludes S, L, O, I, B, Z; explicit ordering).
  {
    id: 'core:mbi-us',
    pattern: /\b[1-9][AC-HJ-NP-Z]\d[AC-HJ-NP-Z0-9]\d[AC-HJ-NP-Z]\d[AC-HJ-NP-Z]{2}\d{2}\b/g,
    label: 'account_number',
    confidence: 0.95,
  },
  {
    // Medicare HIC (legacy, pre-MBI): SSN + 1-2 letter suffix.
    id: 'core:medicare-hic-legacy',
    pattern: /\b\d{3}-?\d{2}-?\d{4}[A-Z]{1,2}\b/g,
    label: 'account_number',
    confidence: 0.9,
  },
  {
    // NPI (National Provider Identifier): 10 digits. Context-anchored
    // on `NPI` / `provider id|number|#` — bare `\b\d{10}\b` collides
    // with NA phones (no country code), order IDs, timestamps, and the
    // generic `luhnValid` validator rejects sub-13-digit inputs by
    // design, so the structural gate must be the context anchor.
    // (CMS-spec NPI Luhn requires prefixing `80840` for the full
    // 15-digit check — not implemented here; context anchor is enough.)
    id: 'core:npi-us-context',
    pattern: /(?<=\b(?:npi|provider(?:\s*(?:id|number|#))?)[\s:.#]+)\d{10}\b/gi,
    label: 'account_number',
    confidence: 0.9,
  },
  {
    // Insurance policy / member number (context-anchored).
    id: 'core:insurance-policy-context',
    pattern:
      /(?<=\b(?:policy(?:\s*(?:no|number|#))?|member(?:\s*id)?|subscriber(?:\s*id)?|group(?:\s*(?:no|#))?)[\s:.#]+)[A-Z0-9][A-Z0-9\-]{5,18}[A-Z0-9]\b/gi,
    label: 'account_number',
    confidence: 0.9,
  },
  {
    // Professional / certificate licence (context-anchored).
    id: 'core:certificate-context',
    pattern:
      /(?<=\b(?:cert(?:ificate)?(?:\s*(?:no|number|#))?|licen[cs]e(?:\s*(?:no|number|#))?(?!\s*plate)|registration(?:\s*(?:no|#))?)[\s:.#]+)[A-Z0-9][A-Z0-9\-]{4,18}[A-Z0-9]\b/gi,
    label: 'account_number',
    confidence: 0.85,
  },
  {
    // Device serial (context-anchored — generic device IDs).
    id: 'core:device-serial-context',
    pattern:
      /(?<=\b(?:s\/?n|serial(?:\s*(?:no|number|#))?|imei|udid|device\s*id)[\s:.#]+)[A-Z0-9][A-Z0-9\-]{6,30}[A-Z0-9]\b/gi,
    label: 'account_number',
    confidence: 0.85,
  },
  {
    // IMEI context-anchored: 15 digits, Luhn-validated. Bare 15-digit
    // Luhn sequences appear occasionally in transaction IDs and barcodes;
    // anchor on an explicit IMEI / device keyword to avoid asymmetric
    // FPs vs competitors that don't ship a standalone IMEI rule.
    id: 'core:imei-context',
    pattern: /(?<=\b(?:imei|device(?:\s*(?:id|imei|#))?)[\s:.#]+)\d{15}\b/gi,
    label: 'account_number',
    confidence: 0.95,
    validate: luhnValid,
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

/** Default GLiNER decode threshold. Spans with sigmoid score below this
 * are dropped during the model decode pass (`decodeGlinerLogits`).
 * Tuned for the model ONNX — lower bloats output with low-confidence
 * noise, higher loses recall. */
export const DEFAULT_DECODE_THRESHOLD = 0.5;

/** Default secondary threshold applied AFTER ML + recognizer merge.
 * `0` means "do not drop anything beyond what decode + per-label
 * thresholds already filtered" — high-confidence recognizers should
 * always pass and ML spans already cleared `DEFAULT_DECODE_THRESHOLD`.
 * Override via `NullPiiConfig.threshold` / `categoryThresholds`. */
export const DEFAULT_POST_FILTER_THRESHOLD = 0;

/** IoU threshold used by `dedupeOverlappingSpans` when reconciling
 * ML + recognizer spans. Two spans with IoU at or above this are
 * treated as duplicates; higher-scoring one wins. */
export const DEFAULT_DEDUPE_IOU = 0.5;

/** Hard byte cap for `normalizeForDetection` and `runRecognizers`.
 * Inputs above this fall back to passthrough (normalize) or refuse
 * to scan (recognizers) so adversarial 1 MB+ payloads with quadratic
 * regex behaviour are not a DoS vector. */
export const MAX_INPUT_BYTES = 1_000_000;
