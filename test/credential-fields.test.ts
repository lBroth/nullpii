// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { isCredentialLiteral } from '../src/credential-fields.js';
import { CREDENTIAL_KEY_BEFORE, credentialKeyValue } from '../src/credential-keys.js';
import { DEFAULT_RECOGNIZERS } from '../src/defaults.js';
import { runRecognizers } from '../src/recognizers.js';

// Fake values, built from parts so the source holds no credential for the
// secret scanner to flag.
const password = ['hunter', '2-', 'Fake9'].join('');
const token = ['fakeTok', '0123456789', 'abcdefXYZ'].join('');

const fields = DEFAULT_RECOGNIZERS.filter(
  (r) => r.id === 'core:password-field' || r.id === 'core:token-field',
);

/** The texts the field recognizers mask in `text`. */
function masked(text: string): string[] {
  return runRecognizers(text, fields, []).map((s) => s.text);
}

describe('credentialKeyValue', () => {
  it('reads a key by its last words, whatever the case and separators', () => {
    for (const key of ['password', 'DB_PASSWORD', 'dbPassword', 'spring.datasource.password']) {
      expect(credentialKeyValue(key), key).toBe('password');
    }
    for (const key of ['passwd', 'smtp_pass', 'pwd', 'gpg-passphrase']) {
      expect(credentialKeyValue(key), key).toBe('password');
    }
    for (const key of ['api_key', 'x-api-key', 'apiKey', 'APIKEY', 'jwt_secret', 'user_token']) {
      expect(credentialKeyValue(key), key).toBe('token');
    }
    for (const key of ['auth', 'session_id', 'sessionId', 'aws_secret_key', 'credentials']) {
      expect(credentialKeyValue(key), key).toBe('token');
    }
  });

  it('leaves keys that only name a credential elsewhere, or not at all', () => {
    for (const key of ['pass', 'PASS', 'PWD', 'OLDPWD', 'bypass', 'compass', 'password_hash']) {
      expect(credentialKeyValue(key), key).toBeNull();
    }
    for (const key of ['primary_key', 'key', 'token_type', 'author', 'authorization', 'user_id']) {
      expect(credentialKeyValue(key), key).toBeNull();
    }
    for (const key of ['label_new_password', 'title_change_password', 'error_wrong_password']) {
      expect(credentialKeyValue(key), key).toBeNull();
    }
    for (const key of [
      'sid',
      'account_sid',
      'next_page_token',
      'pageToken',
      'continuation_token',
    ]) {
      expect(credentialKeyValue(key), key).toBeNull();
    }
    expect(credentialKeyValue('cursor_token')).toBeNull();
  });
});

describe('CREDENTIAL_KEY_BEFORE (the UUID filter)', () => {
  it('matches the vocabulary the UUID filter has always used', () => {
    for (const before of [
      'HEROKU_API_KEY=',
      '  "client_secret": "',
      'Authorization: Bearer ',
      'X-Auth-Token: ',
      "password => '",
      'monkey=',
      'credentials: ',
    ]) {
      expect(CREDENTIAL_KEY_BEFORE.test(before), before).toBe(true);
    }
  });

  it('takes no session words: a UUID after them is a session id', () => {
    for (const before of ['session_id: ', 'sessionid=', 'sid=', 'gpg_passphrase=', 'request id ']) {
      expect(CREDENTIAL_KEY_BEFORE.test(before), before).toBe(false);
    }
  });
});

describe('isCredentialLiteral', () => {
  it('takes literals', () => {
    for (const v of [password, token, 's3cr3tPass', '/Ab3dE9fG7hJ2kL5mN8pQ', 'Pa55:word']) {
      expect(isCredentialLiteral(v), v).toBe(true);
    }
  });

  it('refuses references, calls, placeholders, types, paths, URLs and UUIDs', () => {
    for (const v of [
      '${DB_PASSWORD}',
      '$PGPASSWORD',
      '%(password)s',
      '{{ secrets.TOKEN }}',
      '<password>',
      '[[SECRET_1]]',
      '⟦pw⟧',
      '****',
      '@Value',
      '!vault',
      'getpass()',
      'config.db.password',
      'process.env.API_TOKEN',
      'os.environ[',
      'request.form[',
      'DB_PASSWORD',
      'hashedPassword',
      'new_password',
      'xxxxxx',
      'your_password_here',
      'changeme',
      'String',
      'null',
      'Optional?',
      './secrets/db.txt',
      '~/.aws/credentials',
      'C:\\secrets\\db.txt',
      '/run/secrets/db_password',
      '/Library/Keychains/App.db',
      'https://vault.example/v1/db',
      '42721e36-cd98-43e0-945c-b0e97f58532e',
    ]) {
      expect(isCredentialLiteral(v), v).toBe(false);
    }
  });
});

describe('core:password-field and core:token-field', () => {
  it('mask a password after a password-named key, the value only', () => {
    for (const text of [
      `db_password=${password}`,
      `DB_PASSWORD="${password}"`,
      `  "passwd": "${password}",`,
      `# passwd = ${password}`,
      `spring.datasource.password: ${password}`,
      `mysql --password ${password} -u root`,
      `mysql --password=${password}`,
      `$config['smtp_pass'] = '${password}';`,
    ]) {
      expect(masked(text), text).toEqual([password]);
    }
  });

  it('mask a token after a token-named key', () => {
    for (const text of [
      `apikey: ${token}`,
      `jwt_secret=${token}`,
      `"user_token"=>"${token}"`,
      `access_token='${token}'`,
      `X-Api-Key: ${token}`,
      `const clientSecret = "${token}";`,
      `session_id=${token}`,
    ]) {
      expect(masked(text), text).toEqual([token]);
    }
  });

  it('leave references, placeholders, types and short values readable', () => {
    for (const text of [
      'export DB_PASSWORD=${DB_PASSWORD}',
      'password: string',
      'password = os.environ["DB_PASSWORD"]',
      'password = getpass.getpass()',
      'password: hashedPassword,',
      'password: <password>',
      'password: ****',
      'password: changeme',
      'password: abc12',
      'password_file: /run/secrets/db',
      'token: ${{ secrets.GITHUB_TOKEN }}',
      'api_key: abcdefghijklmnopqrstu',
      'session_id: 42721e36-cd98-43e0-945c-b0e97f58532e',
      'auth: https://auth.example/oauth2/token',
      `label_new_password = "${password}"`,
      'DB_PASSWORD=⟦pw⟧',
      `sid: S-1-5-21-3623811015-3361044348-${'30300820'}-1013`,
      `next_page_token: ${token}`,
      `"nextPageToken": "${token}"`,
      `continuation_token=${token}`,
    ]) {
      expect(masked(text), text).toEqual([]);
    }
  });

  it('leave keys that are not a credential, and values on the next line, readable', () => {
    for (const text of [
      `pass: ${password}`,
      `PASS=${password}`,
      'PWD=/home/alice/project',
      'OLDPWD=/home/alice',
      `bypass: ${password}`,
      `password_hash: ${password}`,
      `token_type: ${token}`,
      `primary_key: ${token}`,
      `password:\n  vault_path: ${password}`,
      `mysql -password ${password}`,
      `the password ${password}`,
    ]) {
      expect(masked(text), text).toEqual([]);
    }
  });
});

// Low-entropy fakes of a key's sizes: base64 of 16, 24, 32 and 64 bytes.
const key16 = `${'Ab1'.repeat(7)}A==`;
const key24 = `${'Ab1'.repeat(10)}Ab`;
const key32 = `${'Ab1'.repeat(14)}A=`;
const key64 = `${'Ab1'.repeat(28)}Ab==`;
/** URL-safe base64 of 32 bytes, padded, as a Fernet key is written. */
const fernet = `${'Ab_1'.repeat(10)}Ab1=`;

const symmetric = DEFAULT_RECOGNIZERS.filter((r) => r.id === 'core:symmetric-key-field');

describe('core:symmetric-key-field', () => {
  /** The texts `core:symmetric-key-field` masks in `text`. */
  function keys(text: string): string[] {
    return runRecognizers(text, symmetric, []).map((s) => s.text);
  }

  it('masks base64 of a key size after a key whose last word is key, the value only', () => {
    const cases: [string, string][] = [
      [`openssl-tool --key=${key32}`, key32],
      [`age-tool --key ${key16} -o out`, key16],
      [`APP_KEY=base64:${key32}`, key32],
      [`encryption_key: "${key32}"`, key32],
      [`const cipherKey = '${key16}';`, key16],
      [`hmac_key=${key64}`, key64],
      [`KEY=${key24}`, key24],
      [`"data.key": "${key32}"`, key32],
      [`APP_KEY="base64:${key32}"`, key32],
      [`"primaryKey": "${key32}"`, key32],
      [`PresharedKey = ${key32}`, key32],
      [`AESKey = "${key32}"`, key32],
      [`fernet_key = ${fernet}`, fernet],
      [`API key: ${key32}`, key32],
    ];
    for (const [text, key] of cases) {
      expect(keys(text), text).toEqual([key]);
    }
  });

  it('leaves public, database, cache and host keys, other words and other sizes readable', () => {
    for (const text of [
      `public_key: ${key32}`,
      `PublicKey = ${key32}`,
      `cache_key: ${key32}`,
      `ssh_host_key=${key32}`,
      `monkey = ${key32}`,
      `turkey: ${key32}`,
      'key: d41d8cd98f00b204e9800998ecf8427e',
      `key: ${'Ab1'.repeat(10)}`,
      `key: ${'ab1'.repeat(14)}a=`,
      `key = ${key32.slice(0, -1)}==`,
      `key:\n  ${key32}`,
      `the key ${key32}`,
      `-key ${key32}`,
      `  public key: ${key32}`,
      `Public Key: ${key32}`,
      `foreign_key: ${key32}`,
      `sort_key: ${key32}`,
      `partition-key: ${key32}`,
      `idempotency_key: ${key32}`,
      `gpg_key: ${key32}`,
      `pgp.key: ${key32}`,
      `Sec-WebSocket-Key: ${key16}`,
      `next_page_key: ${key32}`,
      `"nextPageKey": "${key32}"`,
      `label_api_key: ${key32}`,
      'curl --key /etc/Certs2024/serverKeys/client.key https://example.com',
      'debug1: Offering public key: /opt/Build2024/.ssh/id_ed25519',
      'Key: "uploads/2024/Invoices/Q3/Report1"',
      `fernet_key = ${fernet.slice(0, -1)}A`,
      `key = ${'Ab_1'.repeat(10)}A+1=`,
    ]) {
      expect(keys(text), text).toEqual([]);
    }
  });

  it('leaves a credential core:token-field takes to it', () => {
    for (const text of [`api_key: ${key32}`, `secret_key=${key32}`, `private_key: ${key32}`]) {
      expect(keys(text), text).toEqual([]);
      expect(masked(text), text).toEqual([key32]);
    }
  });
});
