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
    for (const key of ['auth', 'session_id', 'sessionId', 'sid', 'aws_secret_key', 'credentials']) {
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
