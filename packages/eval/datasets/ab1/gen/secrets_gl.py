# SPDX-License-Identifier: Apache-2.0
"""Secret values drawn from the gitleaks rule list (lists/gitleaks/gitleaks.toml, pinned tag).

For each rule we generate a random string from the rule's own regex (the secret group, or the whole
match when the rule has no group), then verify that the full rule regex matches the value in a
canonical context line and that the matched secret equals the value, that the value meets the
rule's entropy threshold and is not caught by the rule's or the global allowlist.
Some rules get a structure-aware generator (published formats with checksums or fixed layouts).
"""
from __future__ import annotations

import base64
import json
import math
import random
import re
import re._constants as C
import re._parser as P
import string
import tomllib
import zlib
from collections import Counter
from dataclasses import dataclass

from common import LISTS

GITLEAKS_TOML = LISTS / "gitleaks" / "gitleaks.toml"
ALNUM = string.ascii_letters + string.digits
B62 = string.digits + string.ascii_uppercase + string.ascii_lowercase
SAFE_PUNCT_WEIGHT = 0.12

# Environment-variable style names for rules whose id is not what people call the variable.
VAR_NAMES = {
    "aws-access-token": "AWS_ACCESS_KEY_ID",
    "github-pat": "GITHUB_TOKEN",
    "github-fine-grained-pat": "GH_TOKEN",
    "github-oauth": "GITHUB_OAUTH_TOKEN",
    "github-app-token": "GITHUB_APP_TOKEN",
    "github-refresh-token": "GITHUB_REFRESH_TOKEN",
    "gcp-api-key": "GOOGLE_API_KEY",
    "openai-api-key": "OPENAI_API_KEY",
    "anthropic-api-key": "ANTHROPIC_API_KEY",
    "anthropic-admin-api-key": "ANTHROPIC_ADMIN_KEY",
    "stripe-access-token": "STRIPE_SECRET_KEY",
    "slack-bot-token": "SLACK_BOT_TOKEN",
    "slack-user-token": "SLACK_USER_TOKEN",
    "slack-app-token": "SLACK_APP_TOKEN",
    "slack-webhook-url": "SLACK_WEBHOOK_URL",
    "npm-access-token": "NPM_TOKEN",
    "pypi-upload-token": "TWINE_PASSWORD",
    "huggingface-access-token": "HF_TOKEN",
    "huggingface-organization-api-token": "HF_ORG_TOKEN",
    "sendgrid-api-token": "SENDGRID_API_KEY",
    "twilio-api-key": "TWILIO_API_KEY",
    "gitlab-pat": "GITLAB_TOKEN",
    "jwt": "AUTH_JWT",
    "jwt-base64": "AUTH_JWT_B64",
    "generic-api-key": "API_KEY",
    "databricks-api-token": "DATABRICKS_TOKEN",
    "digitalocean-pat": "DIGITALOCEAN_TOKEN",
    "heroku-api-key": "HEROKU_API_KEY",
    "heroku-api-key-v2": "HEROKU_API_KEY",
    "microsoft-teams-webhook": "TEAMS_WEBHOOK_URL",
    "vault-service-token": "VAULT_TOKEN",
    "vault-batch-token": "VAULT_TOKEN",
    "hashicorp-tf-api-token": "TFE_TOKEN",
    "doppler-api-token": "DOPPLER_TOKEN",
    "shopify-access-token": "SHOPIFY_ACCESS_TOKEN",
    "mailchimp-api-key": "MAILCHIMP_API_KEY",
    "mailgun-private-api-token": "MAILGUN_API_KEY",
    "sentry-user-token": "SENTRY_AUTH_TOKEN",
    "sentry-org-token": "SENTRY_AUTH_TOKEN",
    "sentry-access-token": "SENTRY_TOKEN",
    "age-secret-key": "SOPS_AGE_KEY",
    "1password-service-account-token": "OP_SERVICE_ACCOUNT_TOKEN",
    "1password-secret-key": "OP_SECRET_KEY",
    "linear-api-key": "LINEAR_API_KEY",
    "notion-api-token": "NOTION_TOKEN",
    "postman-api-token": "POSTMAN_API_KEY",
    "pulumi-api-token": "PULUMI_ACCESS_TOKEN",
    "telegram-bot-api-token": "TELEGRAM_BOT_TOKEN",
    "cloudflare-api-key": "CLOUDFLARE_API_TOKEN",
    "cloudflare-global-api-key": "CLOUDFLARE_API_KEY",
    "cloudflare-origin-ca-key": "CLOUDFLARE_ORIGIN_CA_KEY",
    "perplexity-api-key": "PERPLEXITY_API_KEY",
    "cohere-api-token": "COHERE_API_KEY",
    "flyio-access-token": "FLY_API_TOKEN",
    "snyk-api-token": "SNYK_TOKEN",
    "sonar-api-token": "SONAR_TOKEN",
    "datadog-access-token": "DATADOG_API_KEY",
    "new-relic-user-api-key": "NEW_RELIC_API_KEY",
    "netlify-access-token": "NETLIFY_AUTH_TOKEN",
    "grafana-service-account-token": "GRAFANA_TOKEN",
    "grafana-cloud-api-token": "GRAFANA_CLOUD_API_KEY",
    "grafana-api-key": "GRAFANA_API_KEY",
    "okta-access-token": "OKTA_API_TOKEN",
    "planetscale-password": "PLANETSCALE_PASSWORD",
    "planetscale-api-token": "PLANETSCALE_SERVICE_TOKEN",
    "rubygems-api-token": "GEM_HOST_API_KEY",
    "clojars-api-token": "CLOJARS_PASSWORD",
    "codecov-access-token": "CODECOV_TOKEN",
    "infracost-api-token": "INFRACOST_API_KEY",
    "prefect-api-token": "PREFECT_API_KEY",
    "readme-api-token": "README_API_KEY",
    "scalingo-api-token": "SCALINGO_API_TOKEN",
    "settlemint-personal-access-token": "SETTLEMINT_ACCESS_TOKEN",
    "settlemint-application-access-token": "SETTLEMINT_ACCESS_TOKEN",
    "settlemint-service-access-token": "SETTLEMINT_ACCESS_TOKEN",
    "aws-amazon-bedrock-api-key-long-lived": "AWS_BEARER_TOKEN_BEDROCK",
    "aws-amazon-bedrock-api-key-short-lived": "AWS_BEARER_TOKEN_BEDROCK",
    "gitlab-runner-authentication-token": "CI_RUNNER_TOKEN",
    "gitlab-runner-authentication-token-routable": "CI_RUNNER_TOKEN",
    "gitlab-deploy-token": "GITLAB_DEPLOY_TOKEN",
    "gitlab-pat-routable": "GITLAB_TOKEN",
    "harness-api-key": "HARNESS_API_KEY",
    "artifactory-api-key": "ARTIFACTORY_API_KEY",
    "artifactory-reference-token": "ARTIFACTORY_ACCESS_TOKEN",
    "easypost-api-token": "EASYPOST_API_KEY",
    "easypost-test-api-token": "EASYPOST_TEST_API_KEY",
    "duffel-api-token": "DUFFEL_ACCESS_TOKEN",
    "dynatrace-api-token": "DT_API_TOKEN",
    "frameio-api-token": "FRAMEIO_TOKEN",
    "flutterwave-secret-key": "FLW_SECRET_KEY",
    "flutterwave-public-key": "FLW_PUBLIC_KEY",
    "flutterwave-encryption-key": "FLW_ENCRYPTION_KEY",
    "shopify-custom-access-token": "SHOPIFY_ACCESS_TOKEN",
    "shopify-private-app-access-token": "SHOPIFY_APP_PASSWORD",
    "shopify-shared-secret": "SHOPIFY_API_SECRET",
    "gitlab-session-cookie": "GITLAB_SESSION",
    "openshift-user-token": "OPENSHIFT_TOKEN",
    "slack-legacy-token": "SLACK_TOKEN",
    "slack-legacy-bot-token": "SLACK_BOT_TOKEN",
    "slack-legacy-workspace-token": "SLACK_TOKEN",
    "slack-config-access-token": "SLACK_CONFIG_TOKEN",
    "slack-config-refresh-token": "SLACK_CONFIG_REFRESH_TOKEN",
    "sidekiq-secret": "BUNDLE_ENTERPRISE__CONTRIBSYS__COM",
    "sidekiq-sensitive-url": "SIDEKIQ_GEMS_URL",
    "kubernetes-secret-yaml": "K8S_SECRET",
    "private-key": "PRIVATE_KEY",
    "curl-auth-header": "AUTH_HEADER",
    "curl-auth-user": "CURL_USER",
    "nuget-config-password": "NUGET_PASSWORD",
    "hashicorp-tf-password": "TF_VAR_admin_password",
    "freemius-secret-key": "FS_SECRET_KEY",
    "authress-service-client-access-key": "AUTHRESS_KEY",
    "adobe-client-secret": "ADOBE_CLIENT_SECRET",
    "alibaba-access-key-id": "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "gocardless-api-token": "GOCARDLESS_ACCESS_TOKEN",
    "intra42-client-secret": "INTRA42_CLIENT_SECRET",
    "sendinblue-api-token": "SENDINBLUE_API_KEY",
    "defined-networking-api-token": "DNKEY",
    "dropbox-long-lived-api-token": "DROPBOX_TOKEN",
    "dropbox-short-lived-api-token": "DROPBOX_TOKEN",
    "dropbox-api-token": "DROPBOX_TOKEN",
}
# Rules whose regex matches only a fixed prefix of the real token.
PREFIX_ONLY = {"aws-amazon-bedrock-api-key-short-lived"}
# Rules whose secret is the whole match although the regex has (repeated or named) groups.
WHOLE_MATCH = {"jwt-base64", "microsoft-teams-webhook"}

# Rules whose value only makes sense in a dedicated context (handled by the renderers).
SPECIAL_CONTEXT = {"curl-auth-header", "curl-auth-user", "kubernetes-secret-yaml", "private-key",
                   "nuget-config-password", "hashicorp-tf-password", "gitlab-session-cookie",
                   "sidekiq-sensitive-url", "slack-webhook-url", "microsoft-teams-webhook", "freemius-secret-key"}
EXCLUDED = {"pkcs12-file": "path-only rule (no content regex)"}


def go_to_py(rx: str) -> str:
    """Translate the RE2 constructs gitleaks uses that Python's re does not accept.

    RE2 lets an inline flag group such as (?i) appear mid-pattern; it applies to the rest of the
    enclosing group, across later alternatives. Python only allows scoped (?i:...) there.
    """
    rx = rx.replace(r"\z", r"\Z").replace("[:alnum:]", "a-zA-Z0-9").replace("[:alpha:]", "a-zA-Z")
    rx = rx.replace("[:digit:]", "0-9")
    out = []
    stack: list[list[str]] = []  # per open group: inline flags opened inside it (owed ')')
    top: list[str] = []
    i = 0
    in_class = False
    while i < len(rx):
        ch = rx[i]
        if ch == "\\":
            out.append(rx[i:i + 2])
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
            out.append(ch)
            i += 1
            continue
        if ch == "[":
            in_class = True
            out.append(ch)
            i += 1
            if i < len(rx) and rx[i] == "^":
                out.append("^")
                i += 1
            if i < len(rx) and rx[i] == "]":
                out.append("]")
                i += 1
            continue
        m = re.match(r"\(\?([a-z]+)\)", rx[i:])
        if m and i > 0:
            out.append(f"(?{m.group(1)}:")
            (stack[-1] if stack else top).append(m.group(1))
            i += m.end()
            continue
        if ch == "(":
            stack.append([])
            out.append(ch)
            i += 1
            continue
        if ch == ")":
            owed = stack.pop()
            out.append(")" * len(owed) + ")")
            i += 1
            continue
        if ch == "|":
            owed = stack[-1] if stack else top
            out.append(")" * len(owed) + "|" + "".join(f"(?{f}:" for f in owed))
            i += 1
            continue
        out.append(ch)
        i += 1
    out.append(")" * len(top))
    return "".join(out)


def shannon(s: str) -> float:
    if not s:
        return 0.0
    c = Counter(s)
    n = len(s)
    return -sum(v / n * math.log2(v / n) for v in c.values())


# ------------------------------------------------------------------ regex walker

def _charset(items, rng_case: bool) -> list[str]:
    chars: set[str] = set()
    negate = False
    for op, av in items:
        if op is C.NEGATE:
            negate = True
        elif op is C.LITERAL:
            chars.add(chr(av))
        elif op is C.RANGE:
            lo, hi = av
            for c in range(lo, hi + 1):
                if 0x21 <= c <= 0x7E:
                    chars.add(chr(c))
        elif op is C.CATEGORY:
            if av is C.CATEGORY_DIGIT:
                chars.update(string.digits)
            elif av is C.CATEGORY_WORD:
                chars.update(ALNUM + "_")
            elif av is C.CATEGORY_SPACE:
                chars.add(" ")
            elif av is C.CATEGORY_NOT_SPACE:
                chars.update(ALNUM)
            elif av is C.CATEGORY_NOT_DIGIT:
                chars.update(string.ascii_letters)
            elif av is C.CATEGORY_NOT_WORD:
                chars.add("-")
    if negate:
        chars = set(ALNUM) - chars
    chars.discard("\\")
    return sorted(chars)


def _pick(chars: list[str], rng: random.Random) -> str:
    if not chars:
        return ""  # delimiter classes outside the printable set (only in context parts)
    weights = [1.0 if c in ALNUM else SAFE_PUNCT_WEIGHT for c in chars]
    return rng.choices(chars, weights)[0]


def _count(lo: int, hi: int, rng: random.Random) -> int:
    if hi == C.MAXREPEAT:
        if lo == 0:
            return rng.randint(0, 6)
        if lo == 1:
            return rng.randint(16, 32)
        return lo + rng.randint(0, max(3, lo // 6))
    return rng.randint(lo, hi)


def walk(pattern, rng: random.Random, groups: dict[int, str]) -> str:
    out = []
    for op, av in pattern:
        if op is C.LITERAL:
            out.append(chr(av))
        elif op is C.NOT_LITERAL:
            out.append(_pick([c for c in ALNUM if c != chr(av)], rng))
        elif op is C.ANY:
            out.append(_pick(list(ALNUM), rng))
        elif op is C.IN:
            out.append(_pick(_charset(av, False), rng))
        elif op is C.BRANCH:
            _, alts = av
            out.append(walk(rng.choice(alts), rng, groups))
        elif op is C.SUBPATTERN:
            gid, _add, _del, sub = av
            s = walk(sub, rng, groups)
            if gid is not None:
                groups[gid] = s
            out.append(s)
        elif op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT):
            lo, hi, sub = av
            n = _count(lo, hi, rng)
            out.extend(walk(sub, rng, groups) for _ in range(n))
        elif op in (C.AT, C.ASSERT, C.ASSERT_NOT):
            continue
        elif op is C.CATEGORY:
            out.append(_pick(_charset([(op, av)], False), rng))
        elif op is C.GROUPREF:
            out.append(groups.get(av, ""))
        else:
            raise ValueError(f"unsupported regex op {op}")
    return "".join(out)


def find_group(pattern, gid: int):
    for op, av in pattern:
        if op is C.SUBPATTERN:
            if av[0] == gid:
                return av[3]
            r = find_group(av[3], gid)
            if r is not None:
                return r
        elif op is C.BRANCH:
            for alt in av[1]:
                r = find_group(alt, gid)
                if r is not None:
                    return r
        elif op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT):
            r = find_group(av[2], gid)
            if r is not None:
                return r
    return None


# ------------------------------------------------------------------ structured formats

def b62(n: int, width: int = 6) -> str:
    s = ""
    while n:
        n, r = divmod(n, 62)
        s = B62[r] + s
    return s.rjust(width, "0")


def github_like(prefix: str, rng: random.Random) -> str:
    body = "".join(rng.choice(ALNUM) for _ in range(30))
    return prefix + body + b62(zlib.crc32(body.encode()) & 0xFFFFFFFF)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def make_jwt(rng: random.Random) -> str:
    header = {"alg": rng.choice(["HS256", "RS256", "ES256"]), "typ": "JWT"}
    now = rng.randint(1_690_000_000, 1_790_000_000)
    payload = {"sub": str(rng.randint(10_000, 9_999_999)), "iat": now, "exp": now + rng.choice([900, 3600, 86400]),
               "scope": rng.choice(["read", "read write", "admin", "api"]),
               "jti": "".join(rng.choice(ALNUM) for _ in range(16))}
    sig_len = {"HS256": 32, "RS256": 256, "ES256": 64}[header["alg"]]
    sig = bytes(rng.getrandbits(8) for _ in range(sig_len))
    return ".".join([b64url(json.dumps(header, separators=(",", ":")).encode()),
                     b64url(json.dumps(payload, separators=(",", ":")).encode()), b64url(sig)])


PEM_KINDS = [("RSA PRIVATE KEY", 1190), ("PRIVATE KEY", 1216), ("EC PRIVATE KEY", 121), ("OPENSSH PRIVATE KEY", 399)]


def make_pem_body(rng: random.Random) -> tuple[str, str]:
    label, nbytes = rng.choice(PEM_KINDS)
    raw = bytes(rng.getrandbits(8) for _ in range(nbytes))
    if label == "OPENSSH PRIVATE KEY":
        raw = b"openssh-key-v1\x00" + raw
    elif label in ("RSA PRIVATE KEY", "PRIVATE KEY"):
        raw = b"\x30\x82" + raw  # DER SEQUENCE header, rest random
    else:
        raw = b"\x30\x77\x02\x01\x01\x04\x20" + raw
    b = base64.b64encode(raw).decode()
    width = 70 if label == "OPENSSH PRIVATE KEY" else 64
    body = "\n".join(b[i:i + width] for i in range(0, len(b), width))
    return label, body


# ------------------------------------------------------------------ rules

@dataclass
class Rule:
    id: str
    regex: str
    py: re.Pattern
    secret_group: int
    entropy: float
    keywords: list[str]
    allow_regexes: list[re.Pattern]
    stopwords: list[str]
    var: str


def load_rules() -> tuple[list[Rule], dict[str, str], list[re.Pattern], list[str]]:
    conf = tomllib.loads(GITLEAKS_TOML.read_text(encoding="utf-8"))
    g_allow = [re.compile(go_to_py(r)) for r in conf["allowlist"].get("regexes", [])]
    g_stop = conf["allowlist"].get("stopwords", [])
    rules = []
    excluded = dict(EXCLUDED)
    for r in conf["rules"]:
        if r["id"] in excluded:
            continue
        if "regex" not in r:
            excluded[r["id"]] = "no regex"
            continue
        py = re.compile(go_to_py(r["regex"]))
        sg = r.get("secretGroup", 1 if py.groups >= 1 else 0)
        if r["id"] in WHOLE_MATCH:
            sg = 0
        allow, stop = [], []
        for al in r.get("allowlists", []):
            if al.get("paths") and not al.get("regexes") and not al.get("stopwords"):
                continue
            if al.get("condition") == "AND":
                continue
            allow += [re.compile(go_to_py(x)) for x in al.get("regexes", [])]
            stop += al.get("stopwords", [])
        var = VAR_NAMES.get(r["id"], r["id"].upper().replace("-", "_"))
        rules.append(Rule(r["id"], r["regex"], py, sg, float(r.get("entropy", 0)), r.get("keywords", []),
                          allow, stop, var))
    return rules, excluded, g_allow, g_stop


def canonical_line(rule: Rule, value: str) -> str:
    rid = rule.id
    if rid == "curl-auth-header":
        return f'curl -s -H "Authorization: Bearer {value}" https://api.example.com/v1/me'
    if rid == "curl-auth-user":
        return f"curl -s -u deploy:{value} https://ci.example.com/api/json"
    if rid == "nuget-config-password":
        return f'<add key="ClearTextPassword" value="{value}" />'
    if rid == "hashicorp-tf-password":
        return f'  administrator_login_password = "{value}"'
    if rid == "kubernetes-secret-yaml":
        return f"apiVersion: v1\nkind: Secret\nmetadata:\n  name: app\ndata:\n  token: {value}\n"
    if rid == "private-key":
        return value
    if rid in ("gitlab-session-cookie",):
        return f"Cookie: _gitlab_session={value}"
    if rid == "sidekiq-sensitive-url":
        return f"source \"https://{value}@gems.contribsys.com/\""
    if rid in ("slack-webhook-url", "microsoft-teams-webhook"):
        return f"{rule.var}={value}"
    if rid == "freemius-secret-key":
        return f"    'secret_key' => \"{value}\","
    return f"{rule.var}={value}"


class SecretFactory:
    def __init__(self) -> None:
        self.rules, self.excluded, self.g_allow, self.g_stop = load_rules()
        self.by_id = {r.id: r for r in self.rules}
        self._parsed = {r.id: P.parse(r.py.pattern, r.py.flags) for r in self.rules}
        self.failed: dict[str, str] = {}
        self._probe()

    def _probe(self) -> None:
        """Drop rules for which we cannot produce a verified value (recorded in README)."""
        keep = []
        for r in self.rules:
            rng = random.Random(f"probe:{r.id}")
            try:
                self.generate(r.id, rng)
                keep.append(r)
            except ValueError as exc:
                self.failed[r.id] = str(exc)
        self.rules = keep

    # value only (structured where the provider publishes a layout)
    def _raw(self, r: Rule, rng: random.Random) -> str:
        rid = r.id
        if rid in ("github-pat", "github-oauth", "github-refresh-token"):
            return github_like({"github-pat": "ghp_", "github-oauth": "gho_", "github-refresh-token": "ghr_"}[rid], rng)
        if rid == "github-app-token":
            return github_like(rng.choice(["ghu_", "ghs_"]), rng)
        if rid == "npm-access-token":
            return github_like("npm_", rng)
        if rid == "github-fine-grained-pat":
            return ("github_pat_" + "".join(rng.choice(ALNUM) for _ in range(22)) + "_"
                    + "".join(rng.choice(ALNUM) for _ in range(59)))
        if rid == "aws-access-token":
            return rng.choices(["AKIA", "ASIA"], [7, 3])[0] + "".join(
                rng.choice(string.ascii_uppercase + "234567") for _ in range(16))
        if rid == "gcp-api-key":
            return "AIzaSy" + "".join(rng.choice(ALNUM + "_-") for _ in range(33))
        if rid == "slack-webhook-url":
            up = string.ascii_uppercase + string.digits
            return ("https://hooks.slack.com/services/T" + "".join(rng.choice(up) for _ in range(rng.choice([8, 10])))
                    + "/B" + "".join(rng.choice(up) for _ in range(rng.choice([8, 10]))) + "/"
                    + "".join(rng.choice(ALNUM) for _ in range(24)))
        if rid == "slack-config-access-token":
            return "xoxe.xoxp-1-" + "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(rng.randint(163, 166)))
        if rid == "stripe-access-token":
            return rng.choices(["sk_live_", "sk_test_", "rk_live_"], [5, 3, 2])[0] + "".join(
                rng.choice(ALNUM) for _ in range(rng.choice([24, 99])))
        if rid == "aws-amazon-bedrock-api-key-short-lived":
            # base64 of a presigned bedrock.amazonaws.com URL (the rule matches the fixed prefix only)
            akid = "ASIA" + "".join(rng.choice(string.ascii_uppercase + "234567") for _ in range(16))
            day = f"2025{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
            url = (f"bedrock.amazonaws.com/?Action=CallWithBearerToken&X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential={akid}%2F{day}"
                   f"%2Fus-east-1%2Fbedrock%2Faws4_request&X-Amz-Date={day}T{rng.randint(0, 23):02d}0000Z&X-Amz-Expires=43200"
                   f"&X-Amz-Signature={''.join(rng.choice('0123456789abcdef') for _ in range(64))}&Version=1")
            return "bedrock-api-key-" + base64.b64encode(url.encode()).decode()
        if rid == "jwt":
            return make_jwt(rng)
        if rid == "jwt-base64":
            return base64.b64encode(make_jwt(rng).encode()).decode()
        if rid == "private-key":
            label, body = make_pem_body(rng)
            return f"-----BEGIN {label}-----\n{body}\n-----END {label}-----"
        if rid == "slack-bot-token":
            return (f"xoxb-{rng.randint(10**10, 10**12 - 1)}-{rng.randint(10**12, 10**13 - 1)}-"
                    + "".join(rng.choice(ALNUM) for _ in range(24)))
        if rid == "slack-user-token":
            return (f"xoxp-{rng.randint(10**10, 10**12 - 1)}-{rng.randint(10**10, 10**12 - 1)}-"
                    f"{rng.randint(10**12, 10**13 - 1)}-" + "".join(rng.choice("0123456789abcdef") for _ in range(32)))
        if rid == "kubernetes-secret-yaml":
            inner = "".join(rng.choice(ALNUM) for _ in range(rng.randint(20, 36)))
            return base64.b64encode(inner.encode()).decode()
        if rid == "curl-auth-user":
            return "".join(rng.choice(ALNUM) for _ in range(rng.randint(14, 24)))
        if rid == "curl-auth-header":
            return "".join(rng.choice(ALNUM) for _ in range(rng.randint(32, 48)))
        if rid == "hashicorp-tf-password":
            return "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(rng.randint(12, 20)))
        if rid == "nuget-config-password":
            return "".join(rng.choice(ALNUM + "!#%") for _ in range(rng.randint(14, 22)))
        if rid == "generic-api-key":
            return "".join(rng.choice(ALNUM) for _ in range(rng.choice([32, 40, 48])))
        if rid == "sidekiq-sensitive-url":
            h = "0123456789abcdef"
            return "".join(rng.choice(h) for _ in range(8)) + ":" + "".join(rng.choice(h) for _ in range(8))
        if rid == "sourcegraph-access-token":
            return "sgp_" + "".join(rng.choice("0123456789abcdef") for _ in range(16)) + "_" + "".join(
                rng.choice("0123456789abcdef") for _ in range(40))
        groups: dict[int, str] = {}
        parsed = self._parsed[rid]
        if r.secret_group == 0:
            return walk(parsed, rng, groups)
        sub = find_group(parsed, r.secret_group)
        if sub is None:
            raise ValueError("secret group not found")
        return walk(sub, rng, groups)

    def _verify(self, r: Rule, value: str) -> str | None:
        line = canonical_line(r, value)
        found = None
        for m in r.py.finditer(line):
            got = m.group(r.secret_group) if r.secret_group else m.group(0)
            if got is None and r.id == "curl-auth-header":
                got = next((g for g in m.groups() if g), None)
            if got is None and r.id == "curl-auth-user":
                got = next((g for g in m.groups() if g), None)
            if got is None:
                continue
            got = got.strip("\"'")
            found = got
            break
        if found is None:
            return "regex does not match canonical line"
        expect = value
        if r.id == "kubernetes-secret-yaml":
            found = found.split(":", 1)[1].strip() if ":" in found else found
        if r.id == "curl-auth-user":
            expect = "deploy:" + value
        if r.id == "sidekiq-sensitive-url":
            expect = value
        if r.id in PREFIX_ONLY and expect.startswith(found):
            found = expect
        if found != expect:
            return f"secret group mismatch ({found[:12]}... vs {expect[:12]}...)"
        target = value
        if r.entropy and shannon(found) < r.entropy:
            return "entropy below rule threshold"
        if any(a.search(found) for a in r.allow_regexes) or any(a.search(found) for a in self.g_allow):
            return "allowlisted"
        low = target.lower()
        if any(s.lower() in low for s in r.stopwords) or any(s.lower() in low for s in self.g_stop):
            return "stopword"
        return None

    def generate(self, rule_id: str, rng: random.Random) -> str:
        r = self.by_id[rule_id]
        last = ""
        for _ in range(60):
            v = self._raw(r, rng)
            if "\n" in v and r.id != "private-key":
                continue
            err = self._verify(r, v)
            if err is None:
                return v
            last = err
        raise ValueError(f"{rule_id}: {last}")

    def draw(self, rng: random.Random) -> tuple[Rule, str]:
        r = rng.choice(self.rules)
        return r, self.generate(r.id, rng)


if __name__ == "__main__":
    f = SecretFactory()
    print("usable rules", len(f.rules), "failed", f.failed, "excluded", f.excluded)
    rng = random.Random(1)
    for r in f.rules:
        v = f.generate(r.id, rng)
        print(f"{r.id:45s} {r.var:32s} {v[:90]!r}")
