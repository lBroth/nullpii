# SPDX-License-Identifier: Apache-2.0
"""Slot values for templates and injections.

Ctx hands out annotated values. In a clean document (no MUST_MASK allowed) every MUST_MASK slot
returns a MUST_KEEP or AMBIGUOUS substitute of the kind that really appears in clean traffic
(placeholders, env references, example.com addresses, documentation IPs, dummy credentials).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import keepvals as K
import values as VV
from doc import AM, KP, MM, P, V, Doc, json_escape

GENERIC_USERS = ["runner", "ubuntu", "app", "node", "deploy", "ci", "www-data", "ec2-user", "vscode", "root"]


@dataclass
class Secret:
    rule: str
    var: str
    value: str          # full value (for private keys: the whole PEM)
    clean: bool = False
    clean_kind: str = ""

    @property
    def is_pem(self) -> bool:
        return self.rule == "private-key" and not self.clean


class Ctx:
    def __init__(self, rng: random.Random, lang: str, clean: bool, factory, country: str | None = None) -> None:
        self.rng = rng
        self.lang = lang
        self.clean = clean
        self.factory = factory
        self.country = country or rng.choice(VV.COUNTRY_OF_LANG[lang])
        self._people: list[VV.Person] = []
        self.encode = False          # set by the build for documents selected for an encoded copy
        self.enc_rng: random.Random | None = None
        self.encoded_label: str | None = None
        self.hookable = False
        self.kind = "file"
        self.file_style = "sh"
        self.ps1_done = False

    def finish(self, doc: Doc) -> Doc:
        """Apply the encoded-copy hook (if this document was selected) using the separate RNG.

        Context-specific hooks registered by the template are preferred; otherwise a generic hook
        appends the encoded copy as a new last line. Nothing here touches self.rng, so the base
        document is identical whether or not it gets an encoded copy.
        """
        from encode import generic_hooks
        from inject import effective_end, insert_lines
        from tplutil import apply_hook
        if not doc.hooks:
            doc.hooks = generic_hooks(doc, self.kind, self.lang, self.file_style)
        self.hookable = self.hookable or bool(doc.hooks)
        if self.encode and self.encoded_label is None and doc.hooks:
            self.encoded_label = apply_hook(doc, self.enc_rng, lambda d, f: insert_lines(d, effective_end(d), [f]))
        return doc

    # ------------------------------------------------------------- people
    def person(self, lang: str | None = None) -> VV.Person:
        p = VV.person(self.rng, lang or self.lang, self.country if (lang or self.lang) == self.lang else None)
        self._people.append(p)
        return p

    def name(self, p: VV.Person, kind: str = "full_name") -> V:
        if self.clean:
            role = {"en": "the maintainer", "it": "il responsabile", "de": "die Teamleitung", "fr": "le responsable", "es": "el responsable"}[self.lang]
            return AM(K.public_figure(self.rng), "public_figure") if self.rng.random() < 0.5 else P(role)
        if kind == "given_name":
            return MM(p.given, "person", "given_name")
        if kind == "family_name":
            return MM(p.family, "person", "family_name")
        return MM(p.full, "person", kind)

    def given(self, p: VV.Person) -> V:
        if self.clean:
            return P({"en": self.rng.choice(["the team", "QA", "the on-call", "ops"]), "it": "il team", "de": "das Team", "fr": "l'équipe",
                      "es": "el equipo"}[self.lang])
        return MM(p.given, "person", "given_name")

    def user(self, p: VV.Person) -> V:
        if self.clean:
            return P(self.rng.choice(GENERIC_USERS))
        return MM(VV.username(self.rng, p), "person", "os_username")

    def handle(self, p: VV.Person) -> V:
        if self.clean:
            return P(self.rng.choice(["dependabot[bot]", "github-actions[bot]", "renovate[bot]", "ci-bot"]))
        return MM(VV.handle(self.rng, p), "person", "username")

    def email(self, p: VV.Person | None = None, work: bool | None = None) -> V:
        if self.clean or p is None:
            if self.rng.random() < 0.6:
                return KP(K.example_email(self.rng), "reserved_address")
            return AM(K.role_email(self.rng), "role_address")
        return MM(VV.email(self.rng, p, work), "email", "email")

    def phone(self, country: str | None = None) -> V:
        if self.clean:
            return KP(self.rng.choice(["<phone>", "+XX XXX XXX XXXX", "{{customer.phone}}", "[REDACTED]", "<telefono>"]), "placeholder")
        return MM(VV.phone(self.rng, country or self.country), "phone", "phone")

    def address(self, country: str | None = None) -> V:
        if self.clean:
            return KP(self.rng.choice(["<address>", "{{customer.address}}", "[REDACTED]", "<indirizzo>"]), "placeholder")
        a = VV.address(self.rng, country or self.country)
        return MM(a.line, "address", "postal_address")

    # ------------------------------------------------------------- ids
    def iban(self, country: str | None = None) -> V:
        if self.clean:
            return KP(self.rng.choice(["<IBAN>", "IBAN_PLACEHOLDER", "{{iban}}", "XXXX XXXX XXXX XXXX"]), "placeholder")
        return MM(VV.iban(self.rng, country or self.country), "iban", "iban")

    def card(self) -> V:
        if self.clean:
            return AM(self.rng.choice(["4242 4242 4242 4242", "4111111111111111", "5555555555554444"]), "dummy_credential")
        _brand, num = VV.card(self.rng)
        return MM(num, "card", "card_number")

    def national_id(self, p: VV.Person) -> V:
        if self.clean:
            return KP(self.rng.choice(["<tax-id>", "{{codice_fiscale}}", "XXXXXXXXXXXXXXXX", "[REDACTED]"]), "placeholder")
        kind, v = VV.national_id(self.rng, p, VV.birth_date(self.rng))
        return MM(v, "national_id", kind)

    def passport(self, country: str | None = None) -> V:
        if self.clean:
            return KP("<passport-number>", "placeholder")
        return MM(VV.passport(self.rng, country or self.country), "passport", "passport_number")

    def driver_license(self, p: VV.Person) -> V:
        if self.clean:
            return KP("<licence-number>", "placeholder")
        return MM(VV.driver_license(self.rng, p, VV.birth_date(self.rng)), "driver_license", "driver_license_number")

    def account(self) -> V:
        if self.clean:
            return KP(self.rng.choice(["<customer-id>", "{{customer_id}}", "CUST-XXXXXXX"]), "placeholder")
        kind, v = VV.account_number(self.rng, self.lang)
        return MM(v, "account", kind)

    # ------------------------------------------------------------- network
    def ip(self, v6_share: float = 0.15) -> V:
        if self.clean:
            return KP(VV.doc_ip(self.rng), "reserved_address")
        return MM(VV.public_ip(self.rng, v6_share), "ip", "ip_address")

    def private_ip(self) -> V:
        return AM(VV.private_ipv4(self.rng), "rfc1918_ip")

    def mac(self) -> V:
        if self.clean:
            return KP(self.rng.choice(["xx:xx:xx:xx:xx:xx", "<mac-address>", "XX:XX:XX:XX:XX:XX"]), "placeholder")
        return MM(VV.mac(self.rng), "mac", "mac_address")

    def purl(self, p: VV.Person) -> V:
        if self.clean:
            return KP(K.public_url(self.rng), "public_url")
        return MM(VV.personal_url(self.rng, p), "url", "personal_url")

    # ------------------------------------------------------------- secrets
    def password(self, p: VV.Person | None = None) -> V:
        if self.clean:
            r = self.rng.random()
            if r < 0.4:
                return AM(K.dummy_cred(self.rng), "dummy_credential")
            if r < 0.7:
                return KP(K.env_ref(self.rng, self.rng.choice(["DB_PASSWORD", "PGPASSWORD", "SMTP_PASSWORD", "ADMIN_PASSWORD"])), "env_ref")
            return KP(K.placeholder(self.rng, "password"), "placeholder")
        return MM(VV.password(self.rng, p), "secret", "password")

    def secret(self) -> Secret:
        rule, value = self.factory.draw(self.rng)
        if self.clean:
            r = self.rng.random()
            if r < 0.45:
                return Secret(rule.id, rule.var, K.env_ref(self.rng, rule.var), True, "env_ref")
            if r < 0.85:
                return Secret(rule.id, rule.var, K.placeholder(self.rng, rule.var.lower()), True, "placeholder")
            return Secret(rule.id, rule.var, K.dummy_cred(self.rng), True, "dummy_credential")
        return Secret(rule.id, rule.var, value)

    def secret_value(self, s: Secret) -> V:
        """The annotated value of a single-line secret."""
        if s.clean:
            if s.clean_kind == "dummy_credential":
                return AM(s.value, "dummy_credential")
            return KP(s.value, s.clean_kind)
        if s.rule == "gitlab-session-cookie":
            return MM(s.value.split("=", 1)[1], "secret", "gitleaks:" + s.rule, var=s.var)
        return MM(s.value, "secret", "gitleaks:" + s.rule, var=s.var)

    def pem_doc(self, s: Secret, indent: str = "") -> Doc:
        """PEM block; the body (between the BEGIN and END lines) is one item."""
        lines = s.value.split("\n")
        d = Doc()
        d.add(indent + lines[0] + "\n" + indent)
        d.add(MM(("\n" + indent).join(lines[1:-1]), "secret", "gitleaks:private-key"))
        d.add("\n" + indent + lines[-1])
        return d

    def secret_line(self, s: Secret, style: str, var: str | None = None) -> Doc:
        """Render one secret as a config line in the given style (no trailing newline)."""
        var = var or s.var
        lower = var.lower()
        d = Doc()
        if s.is_pem:
            if style in ("env", "export", "docker_env", "compose_env"):
                pre = {"env": "", "export": "export ", "docker_env": "ENV ", "compose_env": "      - "}[style]
                d.add(f'{pre}{var}="')
                d.extend(json_escape(self.pem_doc(s)))
                d.add('"')
                return d
            if style == "json":
                d.add(f'"{lower}": "')
                d.extend(json_escape(self.pem_doc(s)))
                d.add('"')
                return d
            if style in ("yaml", "compose_yaml"):
                ind = "  " if style == "yaml" else "        "
                d.add(f"{lower}: |\n")
                d.extend(self.pem_doc(s, ind))
                return d
            if style in ("py", "toml", "ini", "js"):
                q = '"""' if style == "py" else ('`' if style == "js" else "'''")
                pre = {"py": f"{var} = ", "toml": f"{lower} = ", "ini": f"{lower} = ", "js": f"const {var} = "}[style]
                d.add(pre + q)
                d.extend(self.pem_doc(s))
                d.add(q + (";" if style == "js" else ""))
                return d
            d.add(f"{var}=")
            d.extend(json_escape(self.pem_doc(s)))
            return d
        v = self.secret_value(s)
        q = self.rng.choice(['"', "", "'"]) if style in ("env", "export", "compose_env") else '"'
        if style == "env":
            d.fmt(f"{var}={q}«v»{q}", v=v)
        elif style == "export":
            d.fmt(f"export {var}={q}«v»{q}", v=v)
        elif style == "docker_env":
            d.fmt(f"ENV {var}=«v»", v=v)
        elif style == "compose_env":
            d.fmt(f"      - {var}=«v»", v=v)
        elif style == "compose_yaml":
            d.fmt(f"      {var}: «v»", v=v)
        elif style == "yaml":
            d.fmt(f"{lower}: «v»" if self.rng.random() < 0.6 else f'{lower}: "«v»"', v=v)
        elif style == "json":
            d.fmt(f'"{lower}": "«v»"', v=v)
        elif style == "py":
            d.fmt(f'{var} = "«v»"', v=v)
        elif style == "js":
            d.fmt(f"const {var} = '«v»';", v=v)
        elif style == "toml":
            d.fmt(f'{lower} = "«v»"', v=v)
        elif style == "ini":
            d.fmt(f"{lower} = «v»", v=v)
        elif style == "cli":
            d.fmt(f"--{lower.replace('_', '-')}=«v»", v=v)
        else:
            raise ValueError(style)
        return d

    # ------------------------------------------------------------- keep / ambiguous helpers
    def kp(self, kind: str, **kw) -> V:
        r = self.rng
        gen = {
            "date": lambda: K.human_date(r, kw.get("lang", self.lang)),
            "iso_date": lambda: K.iso_date(r),
            "ts": lambda: K.iso_ts(r),
            "log_ts": lambda: K.log_ts(r),
            "version": lambda: K.version(r),
            "sha": lambda: K.sha40(r),
            "short_sha": lambda: K.short_sha(r),
            "uuid": lambda: K.uuid4(r),
            "hash": lambda: K.sha256hex(r),
            "public_url": lambda: K.public_url(r),
            "ticket_number": lambda: K.ticket_ref(r),
            "port": lambda: str(r.choice([80, 443, 3000, 5000, 5432, 6379, 8000, 8080, 8443, 9000, 9200, 27017, 3306, 5672, 15672])),
            "pid": lambda: str(r.randint(200, 65000)),
            "http_status": lambda: str(r.choice([200, 201, 204, 301, 400, 401, 403, 404, 409, 422, 429, 500, 502, 503])),
            "env_ref": lambda: K.env_ref(r),
            "placeholder": lambda: K.placeholder(r),
            "org": lambda: K.org(r),
            "job_title": lambda: K.job_title(r, kw.get("lang", self.lang)),
            "code_identifier": lambda: K.namelike_identifier(r, kw.get("lang", self.lang)),
            "reserved_address": lambda: K.reserved_host(r),
            "line_number": lambda: str(r.randint(3, 900)),
        }[kind]
        out_kind = {"iso_date": "date", "ts": "date", "log_ts": "date", "short_sha": "sha"}.get(kind, kind)
        return KP(kw.get("value") or gen(), out_kind)

    def company(self, lang: str | None = None) -> V:
        return KP(VV.company_name(self.rng, lang or self.lang), "org")

    def honorific(self, gender: str, lang: str | None = None) -> V:
        return KP(K.honorific(self.rng, lang or self.lang, gender), "honorific")

    def amb(self, kind: str) -> V:
        r = self.rng
        gen = {
            "internal_host": lambda: K.internal_host(r),
            "rfc1918_ip": lambda: VV.private_ipv4(r),
            "order_number": lambda: K.order_number(r),
            "dummy_credential": lambda: K.dummy_cred(r),
            "role_address": lambda: K.role_email(r),
            "public_figure": lambda: K.public_figure(r),
        }[kind]
        return AM(gen(), kind)
