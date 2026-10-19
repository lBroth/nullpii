# SPDX-License-Identifier: Apache-2.0
"""Document builder: templates call d.user / d.agent / d.tool and place
values through the gold provider (d.g) and distractor provider (d.x)."""

from __future__ import annotations

import datetime as dt
import random

from . import distract as X
from . import values as V
from .core import F, Seg, T, merge_plain
from .lists import (COMPANIES, COUNTRY_OF, HOSTS, LOCALES, PLACEHOLDER_PEOPLE, PROJECTS, PUBLIC_ENTITIES,
                    PUBLIC_FIGURES, PUBLIC_URLS)
from .styles import STYLES

LANG_LOCALES = {"en": ["en_US", "en_GB"], "it": ["it_IT"], "de": ["de_DE"], "fr": ["fr_FR"], "es": ["es_ES"]}


class Mode:
    FULL = "full"            # gold of every category allowed
    NO_SECRET = "no_secret"  # gold allowed except secrets
    CLEAN = "clean"          # no gold at all


class Gold:
    """Gold value provider. Every method returns a tagged Seg (or fragment).
    In a clean document (or for secrets in a no-secret document) it returns
    the matching non-personal stand-in, tagged as a distractor."""

    def __init__(self, d: "Doc"):
        self.d = d
        self.rng = d.rng

    # -- plumbing
    def _v(self, label: str, value: str, ph_kind: str | None = None, *, fallback: Seg | None = None) -> Seg:
        allowed = self.d.gold_ok if label != "secret" else self.d.secret_ok
        if allowed:
            return Seg(value, label=label)
        if fallback is not None:
            return fallback
        return Seg(X.placeholder(self.rng, ph_kind or "generic"), cls="placeholder")

    def raw(self, label: str, value: str, ph_kind: str = "generic", fallback: Seg | None = None) -> Seg:
        """Gold value whose text the template computed itself; `fallback` is the
        stand-in used when this gold category is not allowed in the document."""
        return self._v(label, value, ph_kind, fallback=fallback)

    # -- people
    def name(self, p: V.Persona, form: str = "full") -> Seg:
        if form == "full":
            v = p.full
        elif form == "given":
            v = p.given
        elif form == "family":
            v = p.family
        elif form == "initial":
            v = f"{p.given[0]}. {p.family}"
        elif form == "family_given":
            v = f"{p.family}, {p.given}"
        elif form == "upper":
            v = f"{p.family.upper()} {p.given}"
        else:
            raise ValueError(form)
        if p.placeholder or not self.d.gold_ok:
            return Seg(v if p.placeholder else X.placeholder(self.rng, "name"), cls="placeholder")
        return Seg(v, label="private_person")

    def user(self, p: V.Persona, style: int | None = None) -> Seg:
        if p.placeholder or not self.d.gold_ok:
            return Seg(X.placeholder(self.rng, "user"), cls="placeholder")
        return Seg(p.username(style), label="private_person")

    def handle(self, p: V.Persona, style: int | None = None) -> Seg:
        if p.placeholder or not self.d.gold_ok:
            return Seg(self.rng.choice(["@username", "@your-handle", "@<user>", "@octocat"]), cls="placeholder")
        return Seg("@" + p.username(style), label="private_person")

    def email(self, p: V.Persona, kind: str = "work", domain: str | None = None, style: int | None = None) -> Seg:
        if p.placeholder or not self.d.gold_ok:
            return Seg(X.placeholder(self.rng, "email"), cls="placeholder")
        if kind == "work":
            v = V.email_work(p, domain or self.d.domain, style)
        else:
            if "personal_email" not in p.extra:
                p.extra["personal_email"] = V.email_personal(p, self.rng)
            v = p.extra["personal_email"]
        return Seg(v, label="private_email")

    def phone(self, p: V.Persona, intl: bool | None = None) -> Seg:
        if p.placeholder or not self.d.gold_ok:
            return Seg(X.placeholder(self.rng, "phone"), cls="placeholder")
        return Seg(V.phone_format(p, self.rng, intl), label="private_phone")

    def addr(self, p: V.Persona, form: str = "oneline") -> Seg:
        if p.placeholder or not self.d.gold_ok:
            kind = {"street": "street", "street_full": "street", "postcode": "postcode", "city": "city"}.get(form, "address")
            return Seg(X.placeholder(self.rng, kind), cls="placeholder")
        a = p.address
        v = {"oneline": a.oneline, "street": lambda: a.street, "city_line": a.city_line,
             "city": lambda: a.city, "postcode": lambda: a.postcode,
             "street_full": lambda: a.street + (f", {a.extra}" if a.extra else "")}[form]()
        return Seg(v, label="private_address")

    def date(self, d: dt.date, fmt: str | None = None, p: V.Persona | None = None) -> Seg:
        if not self.d.gold_ok or (p is not None and p.placeholder):
            return Seg(X.placeholder(self.rng, "date"), cls="placeholder")
        loc = p.locale if p is not None else self.d.locale
        fmt = fmt or V.date_fmt_for(loc, self.rng)
        lang = V.LANG_OF_LOCALE.get(loc, "en")
        return Seg(V.date_format(d, fmt, lang), label="private_date")

    def birth(self, p: V.Persona, fmt: str | None = None) -> Seg:
        return self.date(p.birth, fmt, p)

    # -- network
    def ip(self, kind: str = "any") -> Seg:
        if kind == "any":
            kind = self.rng.choice(["private", "private", "public", "public", "v6"])
        v = {"private": V.ipv4_private, "public": V.ipv4_public, "v6": V.ipv6_addr}[kind](self.rng)
        return self._v("private_ip", v, fallback=Seg(X.reserved_ip(self.rng, kind == "v6"), cls="reserved_ip"))

    def mac(self, style: int | None = None) -> Seg:
        return self._v("private_mac", V.mac_addr(self.rng, style), "mac")

    def url(self, kind: str = "internal", p: V.Persona | None = None, path: str | None = None) -> Seg:
        rng = self.rng
        d = self.d
        user = p.username() if p is not None and not p.placeholder else rng.choice(["mrossi", "jlee"])
        if kind == "internal":
            host = rng.choice(["git", "jenkins", "grafana", "kibana", "wiki", "nexus", "argocd", "vault", "admin",
                               "intranet", "sonar", "jira"])
            v = f"https://{host}.{d.int_domain}{path or rng.choice(['/', '/dashboard/7', '/job/deploy-prod/', '/d/api-latency', '/browse/OPS-' + str(rng.randint(100, 9999)), '/repo/' + d.project])}"
        elif kind == "repo":
            v = rng.choice([f"https://github.com/{user}/{d.project}", f"https://gitlab.com/{user}/{d.project}-private",
                            f"git@github.com:{d.slug}/{d.project}.git", f"https://git.{d.int_domain}/{d.slug}/{d.project}.git",
                            f"https://bitbucket.org/{d.slug}/{d.project}"])
        elif kind == "profile":
            v = rng.choice([f"https://github.com/{user}", f"https://www.linkedin.com/in/{user}-{rng.randint(10, 999)}",
                            f"https://{user}.dev", f"https://gitlab.com/{user}", f"https://{d.domain}/team/{user}"])
        elif kind == "token":
            v = rng.choice([
                f"https://{d.domain}/reset-password?token={V.rand_str(rng, V.ALNUM, 32)}",
                f"https://files.{d.int_domain}/share/{V.rand_str(rng, V.HEX, 24)}?sig={V.rand_str(rng, V.B64URL, 22)}",
                f"https://{d.slug}-uploads.s3.eu-central-1.amazonaws.com/invoices/{rng.randint(10000, 99999)}.pdf?X-Amz-Signature={V.rand_str(rng, V.HEX, 64)}",
                f"https://app.{d.domain}/invite/{V.rand_str(rng, V.ALNUM, 20)}",
                f"https://{d.domain}/unsubscribe?u={rng.randint(100000, 9999999)}&h={V.rand_str(rng, V.HEX, 16)}",
            ])
        elif kind == "user_resource":
            v = rng.choice([
                f"https://app.{d.domain}/customers/{rng.randint(10000, 999999)}",
                f"https://admin.{d.int_domain}/users/{rng.randint(1000, 99999)}/edit",
                f"https://{d.domain}/account/{user}/orders",
                f"https://crm.{d.int_domain}/contact/{V.rand_str(rng, V.HEX, 12)}",
                f"https://docs.google.com/spreadsheets/d/{V.rand_str(rng, V.B64URL, 44)}/edit",
            ])
        else:
            raise ValueError(kind)
        return self._v("private_url", v, fallback=Seg(X.placeholder(rng, "url"), cls="placeholder"))

    # -- accounts
    def iban(self, country: str | None = None, printed: bool | None = None, p: V.Persona | None = None) -> Seg:
        if country is None:
            country = V.IBAN_COUNTRY_OF[p.country] if p is not None else V.IBAN_COUNTRY_OF[COUNTRY_OF[self.d.locale]]
        v = V.iban(self.rng, country)
        if printed if printed is not None else self.rng.random() < 0.5:
            v = V.iban_print(v)
        return self._v("account_number", v, "iban")

    def card(self, brand: str | None = None, formatted: bool = True) -> Seg:
        num, _ = V.card_number(self.rng, brand)
        return self._v("account_number", V.card_format(num, self.rng) if formatted else num, "card")

    def natid(self, p: V.Persona) -> tuple[str, Seg]:
        kind, v = V.national_id(p, self.rng)
        if kind == "nir" and self.rng.random() < 0.5:
            v = V.fr_nir_print(v)
        if kind == "nino" and self.rng.random() < 0.5:
            v = V.uk_nino_print(v)
        if p.placeholder:
            return kind, Seg(X.placeholder(self.rng, "id"), cls="placeholder")
        return kind, self._v("account_number", v, "id")

    def taxid(self, p: V.Persona) -> Seg:
        return self.natid(p)[1]

    def cust(self) -> Seg:
        """Customer number; one numbering scheme per document."""
        if "cust_style" not in self.d.state:
            self.d.state["cust_style"] = self.rng.randrange(V.CUSTOMER_STYLES)
        v = V.customer_no(self.rng, self.d.state["cust_style"])
        return self._v("account_number", v, fallback=Seg(self.rng.choice(["CUST-0000000", "C000000", "<customer-id>", "12345678"]),
                                                          cls="placeholder"))

    def emp(self) -> Seg:
        """Employee number; one numbering scheme per document."""
        if "emp_style" not in self.d.state:
            self.d.state["emp_style"] = self.rng.randrange(V.EMPLOYEE_STYLES)
        v = V.employee_no(self.rng, self.d.state["emp_style"])
        return self._v("account_number", v, fallback=Seg(self.rng.choice(["EMP00000", "E-00000", "<employee-id>", "000000"]),
                                                          cls="placeholder"))

    # -- documents and vehicles
    def passport(self, p: V.Persona) -> Seg:
        return self._v("private_passport", V.passport(self.rng, p.country), "passport")

    def dl(self, p: V.Persona) -> Seg:
        return self._v("private_driver_license", V.driver_license(p, self.rng), "generic")

    def plate(self, p: V.Persona | None = None, country: str | None = None) -> Seg:
        c = country or (p.country if p else COUNTRY_OF[self.d.locale])
        rec = p.city_rec if p is not None and p.country in ("DE", "PL") else None
        return self._v("private_vehicle_id", V.number_plate(self.rng, c, rec), "plate")

    def vin(self) -> Seg:
        return self._v("private_vehicle_id", V.vin(self.rng), "vin")

    def geo(self, p: V.Persona | None = None, sep: str = ", ") -> Seg:
        la, lo = self._coords(p)
        return self._v("private_geolocation", f"{la}{sep}{lo}", "geo")

    def geo_parts(self, p: V.Persona | None = None) -> tuple[Seg, Seg]:
        la, lo = self._coords(p)
        if not self.d.gold_ok:
            return Seg("0.0", cls="placeholder"), Seg("0.0", cls="placeholder")
        return Seg(la, label="private_geolocation"), Seg(lo, label="private_geolocation")

    def _coords(self, p: V.Persona | None) -> tuple[str, str]:
        if p is None or p.placeholder:
            p = self.d.any_persona()
        lat, lon = V.city_latlon(p.locale, p.city_rec)
        return V.geo_pair(self.rng, lat, lon)

    # -- secrets
    def secret(self, kind: str | None = None) -> Seg:
        kind = kind or self.rng.choice(V.SECRET_KINDS)
        if kind in ("session", "session_signed", "rails_session", "bearer_opaque", "vault_token", "telegram", "discord"):
            ph = "token"
        elif kind in ("slack_webhook", "sentry_dsn"):
            ph = "url"
        else:
            ph = "api_key"
        return self._v("secret", V.secret_token(self.rng, kind), ph)

    def password(self) -> Seg:
        return self._v("secret", V.password(self.rng), "password")

    def jwt(self, claims: dict | None = None, alg: str = "HS256") -> Seg:
        return self._v("secret", V.jwt(self.rng, claims, alg), "token")

    def pem(self, kind: str = "rsa") -> Seg:
        if not self.d.secret_ok:
            return Seg(self.rng.choice(["-----BEGIN PRIVATE KEY-----\n<redacted>\n-----END PRIVATE KEY-----",
                                        "<private key omitted>", "${SSH_PRIVATE_KEY}", "[REDACTED PRIVATE KEY]"]),
                       cls="placeholder")
        return Seg(V.pem_private_key(self.rng, kind), label="secret")


class Distract:
    """Distractor provider: every method returns a Seg tagged with a class."""

    def __init__(self, d: "Doc"):
        self.d = d
        self.rng = d.rng

    def ts(self, style: str = "iso_z", tick: tuple | None = None, t: dt.datetime | None = None,
           local: bool = False) -> Seg:
        if tick is not None:
            self.d.clock.tick(*tick)
        tt = t or self.d.clock.t
        if local:
            tt = self.d.clock.local(tt)
        return Seg(X.fmt_ts(tt, style), cls="machine_timestamp")

    def sha(self) -> Seg:
        return Seg(X.sha1(self.rng), cls="identifier")

    def short(self, n: int | None = None) -> Seg:
        return Seg(X.short_sha(self.rng, n), cls="identifier")

    def sha256(self) -> Seg:
        return Seg(X.sha256(self.rng), cls="identifier")

    def uuid(self) -> Seg:
        return Seg(X.uuid4(self.rng), cls="identifier")

    def rid(self) -> Seg:
        return Seg(X.request_id(self.rng), cls="identifier")

    def ver(self, v: str | None = None) -> Seg:
        return Seg(v or X.version(self.rng), cls="identifier")

    def port(self, p: int | None = None) -> Seg:
        return Seg(str(p or self.rng.choice([3000, 5432, 6379, 8080, 8443, 9090, 5000, 8000, 27017, 3306, 9200])),
                   cls="identifier")

    def num(self, n: int | str | None = None, lo: int = 1, hi: int = 999) -> Seg:
        return Seg(str(n if n is not None else self.rng.randint(lo, hi)), cls="identifier")

    def id(self, text: str) -> Seg:
        return Seg(text, cls="identifier")

    def rip(self, v6: bool | None = None, text: str | None = None) -> Seg:
        return Seg(text or X.reserved_ip(self.rng, v6), cls="reserved_ip")

    def ph(self, kind: str = "generic", text: str | None = None) -> Seg:
        return Seg(text or X.placeholder(self.rng, kind), cls="placeholder")

    def url(self, kind: str | None = None, text: str | None = None) -> Seg:
        if text is None:
            kind = kind or self.rng.choice(list(PUBLIC_URLS))
            text = self.rng.choice(PUBLIC_URLS[kind])
        return Seg(text, cls="public_url")

    def ent(self, name: str | None = None, cat: str | None = None) -> Seg:
        if name is None:
            cat = cat or self.rng.choice(list(PUBLIC_ENTITIES))
            name = self.rng.choice(PUBLIC_ENTITIES[cat])
        return Seg(name, cls="public_entity")

    def fig(self) -> Seg:
        return Seg(self.rng.choice(PUBLIC_FIGURES), cls="public_entity")


class Doc:
    def __init__(self, doc_id: str, template_id: str, style: str, rng: random.Random, mode: str, lang: str):
        self.doc_id = doc_id
        self.template_id = template_id
        self.style = STYLES[style]
        self.rng = rng
        self.mode = mode
        self.lang = lang
        self.locale = rng.choice(LANG_LOCALES[lang]) if rng.random() < 0.75 else rng.choice(LOCALES)
        self.parts: list[Seg] = []
        self.state: dict = {}
        self.locales_used: set[str] = set()
        self.text_langs: set[str] = {lang}
        self.clock = X.Clock(rng)
        self.g = Gold(self)
        self.x = Distract(self)
        comp = [c for c in COMPANIES if c[2] == self.locale] or COMPANIES
        self.company, self.domain, _ = rng.choice(comp if rng.random() < 0.7 else COMPANIES)
        self.slug = V.slug(self.company.split()[0])
        self.int_domain = rng.choice([f"{self.slug}.internal", f"corp.{self.domain}", f"int.{self.domain}",
                                      f"{self.slug}.lan", f"svc.{self.domain}"])
        self.project = rng.choice(PROJECTS)
        self.host = rng.choice(HOSTS)
        self.me = self.person(self.locale)
        self.os = rng.choice(["mac", "mac", "linux", "linux", "wsl"])

    # -- modes
    @property
    def clean(self) -> bool:
        return self.mode == Mode.CLEAN

    @property
    def gold_ok(self) -> bool:
        return self.mode != Mode.CLEAN

    @property
    def secret_ok(self) -> bool:
        return self.mode == Mode.FULL

    # -- people
    def person(self, locale: str | None = None, **kw) -> V.Persona:
        if locale is None:
            locale = self.locale if self.rng.random() < 0.6 else self.rng.choice(LOCALES)
        p = V.make_persona(self.rng, locale, **kw)
        if self.clean:
            g, f = self.rng.choice(PLACEHOLDER_PEOPLE)
            p.given, p.family, p.placeholder = g, f, True
        else:
            self.locales_used.add(locale)
        return p

    def people(self, n: int, locale: str | None = None) -> list[V.Persona]:
        return [self.person(locale) for _ in range(n)]

    def any_persona(self) -> V.Persona:
        return self.me

    # -- language
    def L(self, **variants: str) -> str:
        """Text in the conversation language (English when no variant exists)."""
        if self.lang in variants:
            return variants[self.lang]
        self.text_langs.add("en")
        return variants["en"]

    def Lp(self, lang: str, **variants: str) -> str:
        """Text in a given language (e.g. the language of a ticket's author)."""
        if lang in variants:
            self.text_langs.add(lang)
            return variants[lang]
        self.text_langs.add("en")
        return variants["en"]

    @staticmethod
    def lang_of(p: V.Persona) -> str:
        return V.LANG_OF_LOCALE[p.locale]

    # -- environment fragments
    def dev_user(self) -> Seg:
        """The developer's login name, identical everywhere in the document."""
        if "home_user" not in self.state:
            self.state["home_user"] = self.g.user(self.me, style=self.rng.choice([0, 1, 2, 9]))
        return self.state["home_user"]

    def home(self) -> list:
        if self.clean:
            if "clean_home" not in self.state:
                self.state["clean_home"] = self.rng.choice(["/workspace", "/home/runner/work", "/srv", "/opt"])
            return F(self.state["clean_home"])
        u = self.dev_user()
        base = "/Users/" if self.os == "mac" else "/home/"
        return F(base, u)

    def cwd(self) -> list:
        if "cwd_sub" not in self.state:
            self.state["cwd_sub"] = self.rng.choice(["code", "src", "dev", "work", "projects", "git"])
        sub = self.state["cwd_sub"]
        if self.clean:
            return F(self.home(), "/", self.project)
        return F(self.home(), "/", sub, "/", self.project)

    def prompt(self) -> list:
        """Shell prompt as it appears in a pasted terminal."""
        if self.clean:
            return F("$ ")
        u = self.dev_user()
        if "laptop" not in self.state:
            self.state["laptop"] = self.rng.choice(["mbp", "laptop", "dev", "ws", "thinkpad", "xps"])
        host = self.state["laptop"]
        return F(u, "@", host, " ", self.project, " % " if self.os == "mac" else "$ ")

    # -- emission
    def emit(self, *parts) -> None:
        self.parts.extend(F(*parts))

    def user(self, *parts) -> None:
        self.emit(self.style.user(self, F(*parts)))

    def agent(self, *parts) -> None:
        self.emit(self.style.agent(self, F(*parts)))

    def call(self, tool: str, arg) -> None:
        self.emit(self.style.call(self, tool, F(arg)))

    def result(self, tool: str, *body) -> None:
        self.emit(self.style.result(self, tool, F(*body)))

    def tool(self, tool: str, arg, *body) -> None:
        self.call(tool, arg)
        self.result(tool, *body)

    def begin(self) -> None:
        self.emit(self.style.header(self))

    def end(self) -> None:
        self.emit(self.style.footer(self))

    def frag(self) -> list:
        return merge_plain(self.parts)
