# SPDX-License-Identifier: Apache-2.0
"""Templates centred on HTTP traffic: verbose API calls, webhooks, cookies,
GraphQL, OAuth, KYC/CRM integrations, SOAP and httpie sessions."""

from __future__ import annotations

import datetime as dt
import json

from .. import values as V
from ..core import F, J, T, Seg, esc_json, grid, lines, numbered, table
from ..phrases import say
from . import template

# ---------------------------------------------------------------- private helpers


class _Raw:
    """A fragment placed into JSON unquoted (numbers, nested literals)."""

    __slots__ = ("f",)

    def __init__(self, *parts):
        self.f = F(*parts)


class _Q:
    """A composite fragment placed into JSON as one quoted string."""

    __slots__ = ("f",)

    def __init__(self, *parts):
        self.f = F(*parts)


def _js(o, indent: int | None = 2, lvl: int = 0, sep: tuple = (", ", ": ")) -> list:
    """Render a JSON value whose leaves may be Segs (quoted, escaped)."""
    if isinstance(o, _Raw):
        return o.f
    if isinstance(o, _Q):
        return F('"', esc_json(o.f), '"')
    if isinstance(o, Seg):
        return F('"', esc_json([o]), '"')
    if o is None:
        return F("null")
    if isinstance(o, bool):
        return F("true" if o else "false")
    if isinstance(o, (int, float)):
        return F(json.dumps(o))
    if isinstance(o, str):
        return F(json.dumps(o, ensure_ascii=False))
    if isinstance(o, dict):
        if not o:
            return F("{}")
        kv = sep[1] if indent is None else ": "
        items = [F(json.dumps(k, ensure_ascii=False), kv, _js(v, indent, lvl + 1, sep)) for k, v in o.items()]
        if indent is None:
            return F("{", J(sep[0], items), "}")
        pad, end = " " * (indent * (lvl + 1)), " " * (indent * lvl)
        return F("{\n", J(",\n", [F(pad, it) for it in items]), "\n", end, "}")
    if isinstance(o, list):
        if not o:
            return F("[]")
        items = [_js(v, indent, lvl + 1, sep) for v in o]
        if indent is None:
            return F("[", J(sep[0], items), "]")
        pad, end = " " * (indent * (lvl + 1)), " " * (indent * lvl)
        return F("[\n", J(",\n", [F(pad, it) for it in items]), "\n", end, "]")
    raise TypeError(type(o).__name__)


def _jl(o) -> list:
    """Compact one-line JSON (log lines)."""
    return _js(o, None, 0, (",", ":"))


def _enc_email(d, p) -> Seg:
    """The persona's work e-mail percent-encoded as it appears in a query string."""
    return d.g.raw("private_email", V.email_work(p, d.domain).replace("@", "%40"), "email")


def _host(d, sub: str) -> str:
    """Internal host name; a documentation domain in clean documents."""
    return f"{sub}.{d.int_domain}" if d.gold_ok else f"{sub}.example.com"


def _purl(d, text: str) -> Seg:
    """A private URL the template built itself (placeholder-tagged when clean)."""
    if d.gold_ok:
        return d.g.raw("private_url", text, "url")
    return d.x.ph("url", text)


def _acct(d, value: str) -> Seg:
    """A customer/user number in a record about a person; a test-fixture id when clean."""
    return d.g.raw("account_number", value) if d.gold_ok else d.x.id(value)


_SECRET_STANDINS = {
    "session": ["<session-id>", "REDACTED", "***", "s%3A<redacted>"],
    "token": ["<token>", "REDACTED", "$ACCESS_TOKEN", "eyJhbGciOi...<redacted>"],
    "key": ["<api-key>", "YOUR_API_KEY", "${CRM_API_KEY}", "********"],
}


def _sec(d, kind: str, standin: str = "token") -> Seg:
    """Gold secret, or a fitting stand-in when secrets are not allowed."""
    if d.secret_ok:
        return d.g.secret(kind)
    return d.x.ph("token", d.rng.choice(_SECRET_STANDINS[standin]))


class _Past:
    """A time cursor that starts in the past, for log lines read during the session."""

    def __init__(self, d, lo_h: float = 1, hi_h: float = 48):
        self.r = d.rng
        self.t = d.clock.t - dt.timedelta(seconds=d.rng.uniform(lo_h * 3600, hi_h * 3600))

    def tick(self, lo: float, hi: float) -> dt.datetime:
        self.t += dt.timedelta(seconds=self.r.uniform(lo, hi))
        return self.t


_E164_CC = {"it_IT": "39", "de_DE": "49", "fr_FR": "33", "es_ES": "34", "nl_NL": "31", "pt_PT": "351",
            "pl_PL": "48", "en_US": "1", "en_GB": "44"}


def _e164(d, p) -> Seg:
    return d.g.raw("private_phone", "+" + _E164_CC[p.locale] + p.phone_digits, "phone")


def _brand(card_text: str) -> str:
    first = next((c for c in card_text if c.isdigit()), "4")
    return {"4": "visa", "5": "mastercard", "2": "mastercard", "3": "amex", "6": "discover"}.get(first, "visa")


def _uid(d) -> str:
    return str(d.rng.randint(10_000, 9_999_999))


def _ua(d) -> str:
    return d.rng.choice([
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    ])


# ---------------------------------------------------------------- 1. curl -v against a profile endpoint


@template("curl_verbose_profile", "cc", "http", "shell")
def curl_verbose_profile(d):
    g, x, r = d.g, d.x, d.rng
    cust = d.person()
    uid = _uid(d)
    host = _host(d, "api")
    url = _purl(d, f"https://{host}/v2/users/{uid}/profile")
    email_raw = V.email_work(cust, d.domain) if r.random() < 0.4 else V.email_personal(cust, r)
    cust.extra["personal_email"] = email_raw
    token = g.jwt({"email": email_raw, "name": cust.full, "scope": "openid orders:read", "aud": "web-app"})
    branch = r.choice(["forbidden", "serialize"])
    short = r.random() < 0.35
    api_ip = g.ip("private")
    if branch == "forbidden":
        d.user(T(d.L(
            en="GET /v2/users/:id/profile answers 403 with a token that should be valid (user ⟦u⟧). Token is in $TOKEN, can you look?",
            it="GET /v2/users/:id/profile risponde 403 con un token che dovrebbe essere valido (utente ⟦u⟧). Il token è in $TOKEN, puoi guardare?",
            de="GET /v2/users/:id/profile liefert 403 mit einem Token, das eigentlich gültig sein sollte (User ⟦u⟧). Token liegt in $TOKEN, kannst du schauen?",
            fr="GET /v2/users/:id/profile répond 403 avec un token qui devrait être valide (utilisateur ⟦u⟧). Le token est dans $TOKEN, tu peux regarder ?",
            es="GET /v2/users/:id/profile responde 403 con un token que debería ser válido (usuario ⟦u⟧). El token está en $TOKEN, ¿puedes mirarlo?"),
            u=_acct(d, uid)))
    else:
        d.user(T(d.L(
            en="The mobile team says the profile endpoint returns birth dates one day off for some users. Example: user ⟦u⟧. Token in $TOKEN.",
            it="Il team mobile dice che l'endpoint del profilo restituisce date di nascita sballate di un giorno per alcuni utenti. Esempio: utente ⟦u⟧. Token in $TOKEN.",
            de="Das Mobile-Team meldet, dass der Profil-Endpunkt bei manchen Usern das Geburtsdatum um einen Tag verschoben liefert. Beispiel: User ⟦u⟧. Token in $TOKEN.",
            fr="L'équipe mobile signale que l'endpoint profil renvoie des dates de naissance décalées d'un jour pour certains utilisateurs. Exemple : utilisateur ⟦u⟧. Token dans $TOKEN.",
            es="El equipo de móvil dice que el endpoint de perfil devuelve fechas de nacimiento con un día de desfase para algunos usuarios. Ejemplo: usuario ⟦u⟧. Token en $TOKEN."),
            u=_acct(d, uid)))
    d.agent(say(d, "look_first", x=d.L(en="the raw exchange with curl -v", it="lo scambio grezzo con curl -v",
                                       de="den rohen Austausch mit curl -v", fr="l'échange brut avec curl -v",
                                       es="el intercambio en crudo con curl -v")))
    cmd = F('curl -v -H "Authorization: Bearer $TOKEN" ', url)
    tls_detail = [] if short else [
        "* ALPN: curl offers h2,http/1.1",
        "* SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384 / X25519 / RSASSA-PSS",
        "* Server certificate:",
        T("*  subject: CN=*.⟦h⟧", h=host.split(".", 1)[1]),
        T("*  start date: ⟦a⟧", a=x.ts("http", t=d.clock.t - dt.timedelta(days=r.randint(20, 80)))),
        T("*  expire date: ⟦a⟧", a=x.ts("http", t=d.clock.t + dt.timedelta(days=r.randint(10, 300)))),
        T("*  issuer: C=US; O=Let's Encrypt; CN=R11"),
        "*  SSL certificate verify ok.",
    ]
    tls = lines(
        T("*   Trying ⟦ip⟧:443...", ip=api_ip),
        T("* Connected to ⟦h⟧ (⟦ip⟧) port 443", h=host, ip=api_ip),
        *tls_detail,
        T("> GET /v2/users/⟦u⟧/profile HTTP/2", u=_acct(d, uid)),
        T("> Host: ⟦h⟧", h=host),
        T("> User-Agent: curl/⟦v⟧", v=x.ver(r.choice(["8.4.0", "8.7.1", "7.88.1"]))),
        "> Accept: */*",
        T("> Authorization: Bearer ⟦t⟧", t=token),
        ">",
    )
    birth = cust.birth
    shifted = birth - dt.timedelta(days=1)
    tz_h = r.choice([22, 23])

    def profile(bdate_seg) -> list:
        a = cust.address
        body = {
            "id": _acct(d, uid),
            "name": g.name(cust),
            "email": g.email(cust, "personal"),
            "phone": g.phone(cust, intl=True),
            "birth_date": bdate_seg,
            "address": {"street": g.addr(cust, "street_full"), "postcode": g.addr(cust, "postcode"),
                        "city": g.addr(cust, "city"), "country": a.country},
            "marketing_opt_in": r.random() < 0.4,
            "created_at": x.ts("iso_z", t=d.clock.t - dt.timedelta(days=r.randint(30, 900))),
        }
        return _js(body)

    if branch == "forbidden":
        resp_body = _jl({"error": "insufficient_scope", "required": "profile:read",
                         "request_id": x.rid()})
        status = "403"
    else:
        resp_body = profile(g.raw("private_date", f"{shifted.isoformat()}T{tz_h}:00:00.000Z", "date"))
        status = "200"
    resp = lines(
        T("< HTTP/2 ⟦s⟧", s=status),
        T("< date: ⟦t⟧", t=x.ts("http", tick=(1, 3))),
        "< content-type: application/json; charset=utf-8",
        T("< set-cookie: sid=⟦s⟧; Path=/; HttpOnly; Secure; SameSite=Lax", s=_sec(d, "session", "session")),
        T("< x-request-id: ⟦r⟧", r=x.rid()),
        "< vary: Origin",
        "<",
    )
    d.tool("sh", cmd, tls, resp, resp_body, "\n", T("* Connection #0 to host ⟦h⟧ left intact", h=host))
    if branch == "forbidden":
        d.agent(d.L(en="The API wants the `profile:read` scope. Let me decode the token payload to see what it actually carries.",
                    it="L'API richiede lo scope `profile:read`. Decodifico il payload del token per vedere cosa contiene davvero.",
                    de="Die API verlangt den Scope `profile:read`. Ich dekodiere den Token-Payload, um zu sehen, was wirklich drinsteht.",
                    fr="L'API exige le scope `profile:read`. Je décode le payload du token pour voir ce qu'il contient vraiment.",
                    es="La API pide el scope `profile:read`. Decodifico el payload del token para ver qué lleva realmente."))
        iat = d.clock.t - dt.timedelta(minutes=r.randint(2, 50))
        payload = {
            "iss": _purl(d, f"https://{_host(d, 'auth')}/"),
            "sub": _acct(d, uid),
            "email": g.email(cust, "personal"),
            "name": g.name(cust),
            "scope": "openid orders:read",
            "aud": "web-app",
            "iat": _Raw(x.ts("epoch", t=iat)),
            "exp": _Raw(x.ts("epoch", t=iat + dt.timedelta(hours=1))),
        }
        d.tool("sh", "echo \"$TOKEN\" | cut -d. -f2 | base64 -d 2>/dev/null | jq .", _js(payload))
        if not short:
            d.tool("grep", "\"profile:read\" src/", lines(
                T("src/routes/profile.ts:⟦n⟧:  router.get(\"/users/:id/profile\", requireScope(\"profile:read\"), getProfile);", n=x.num(lo=8, hi=40)),
                T("src/auth/scopes.ts:⟦n⟧:  \"profile:read\": [\"web-app\", \"mobile-app\"],", n=x.num(lo=5, hi=30)),
                T("docs/auth.md:⟦n⟧:The web client must request `profile:read` explicitly.", n=x.num(lo=10, hi=90))))
        d.agent(say(d, "explain"), "\n\n",
                d.L(en="The token was issued to the web client with only `openid orders:read`. The web login flow never asks for `profile:read`, so the API is right to refuse. The fix belongs in the client's authorize request, not in the API.",
                    it="Il token è stato emesso al client web con solo `openid orders:read`. Il flusso di login web non chiede mai `profile:read`, quindi l'API fa bene a rifiutare. La correzione va nella richiesta di authorize del client, non nell'API.",
                    de="Das Token wurde für den Web-Client nur mit `openid orders:read` ausgestellt. Der Web-Login fordert `profile:read` nie an, die API lehnt also zu Recht ab. Der Fix gehört in den Authorize-Request des Clients, nicht in die API.",
                    fr="Le token a été émis pour le client web avec seulement `openid orders:read`. Le flux de connexion web ne demande jamais `profile:read`, l'API a donc raison de refuser. La correction se fait dans la requête authorize du client, pas dans l'API.",
                    es="El token se emitió para el cliente web solo con `openid orders:read`. El login web nunca pide `profile:read`, así que la API rechaza con razón. La corrección va en la petición authorize del cliente, no en la API."))
        d.tool("edit", "web/src/auth/config.ts", lines(
            "@@ -11,7 +11,7 @@ export const authConfig = {",
            "   clientId: \"web-app\",",
            T("   issuer: \"https://⟦h⟧/\",", h=_host(d, "auth")),
            "-  scope: \"openid orders:read\",",
            "+  scope: \"openid orders:read profile:read\",",
            "   redirectUri: `${window.location.origin}/auth/callback`,"))
        if r.random() < 0.6:
            d.user(d.L(en="ok, I logged in again and exported the new token. Try it", it="ok, ho rifatto il login ed esportato il nuovo token. Riprova",
                       de="ok, neu eingeloggt und das neue Token exportiert. Probier nochmal", fr="ok, je me suis reconnecté et j'ai exporté le nouveau token. Réessaie",
                       es="vale, he vuelto a iniciar sesión y exportado el token nuevo. Prueba"))
            d.tool("sh", F("curl -s -H \"Authorization: Bearer $TOKEN\" ", url, " | jq ."),
                   profile(g.birth(cust, "iso")))
    else:
        d.agent(say(d, "explain"), "\n\n",
                d.L(en=f"`birth_date` comes back as a timestamp at {tz_h}:00 UTC of the previous day. The value is loaded as a local-midnight Date and serialised with toISOString(), so every user in a timezone east of UTC loses a day.",
                    it=f"`birth_date` torna come timestamp alle {tz_h}:00 UTC del giorno prima. Il valore viene caricato come Date a mezzanotte locale e serializzato con toISOString(), quindi chi è in un fuso a est di UTC perde un giorno.",
                    de=f"`birth_date` kommt als Zeitstempel um {tz_h}:00 UTC des Vortags zurück. Der Wert wird als Date um lokale Mitternacht geladen und mit toISOString() serialisiert – östlich von UTC fehlt dadurch ein Tag.",
                    fr=f"`birth_date` revient comme un horodatage à {tz_h}:00 UTC la veille. La valeur est chargée comme une Date à minuit local puis sérialisée avec toISOString(), donc tout utilisateur à l'est d'UTC perd un jour.",
                    es=f"`birth_date` vuelve como marca de tiempo a las {tz_h}:00 UTC del día anterior. El valor se carga como Date a medianoche local y se serializa con toISOString(), así que quien está al este de UTC pierde un día."))
        src = lines(
            "import { Profile } from \"../models/profile\";",
            "",
            "export function serializeProfile(p: Profile) {",
            "  return {",
            "    id: p.id,",
            "    name: `${p.givenName} ${p.familyName}`,",
            "    email: p.email,",
            "    phone: p.phoneE164,",
            "    birth_date: p.birthDate,          // Date from the pg driver",
            "    address: serializeAddress(p.address),",
            "    marketing_opt_in: p.marketingOptIn,",
            "    created_at: p.createdAt.toISOString(),",
            "  };",
            "}",
        )
        if not short:
            d.tool("read", "src/serializers/profile.ts", numbered(src))
            d.agent(say(d, "applying"))
        d.tool("edit", "src/serializers/profile.ts", lines(
            "-    birth_date: p.birthDate,          // Date from the pg driver",
            "+    // DATE column: format as calendar date, never through a timezone",
            "+    birth_date: formatISODate(p.birthDate),"))
        d.tool("sh", F("curl -s -H \"Authorization: Bearer $TOKEN\" ", url, " | jq .birth_date"),
               T("\"⟦b⟧\"\n", b=g.birth(cust, "iso")))
    if r.random() < 0.5:
        d.agent(say(d, "pii_warning"))
    d.agent(say(d, "not_committed"))


# ---------------------------------------------------------------- 2. Stripe webhook signature failures


@template("stripe_webhook_debug", "xml", "http", "file")
def stripe_webhook_debug(d):
    g, x, r = d.g, d.x, d.rng
    cust = d.person()
    port = r.choice([3000, 4242, 8080])
    d.user(d.L(
        en="Stripe webhooks fail on staging with 400 \"No signatures found matching the expected signature for payload\". It started after the Express upgrade.",
        it="I webhook di Stripe falliscono in staging con 400 \"No signatures found matching the expected signature for payload\". È iniziato dopo l'aggiornamento di Express.",
        de="Die Stripe-Webhooks schlagen auf Staging mit 400 \"No signatures found matching the expected signature for payload\" fehl. Seit dem Express-Upgrade.",
        fr="Les webhooks Stripe échouent en staging avec un 400 \"No signatures found matching the expected signature for payload\". Ça a commencé après la mise à jour d'Express.",
        es="Los webhooks de Stripe fallan en staging con 400 \"No signatures found matching the expected signature for payload\". Empezó tras actualizar Express."))
    d.agent(say(d, "look_first", x="src/routes/webhooks.ts"))
    code = lines(
        "import express from \"express\";",
        "import Stripe from \"stripe\";",
        "import { config } from \"../config\";",
        "import { logger } from \"../logger\";",
        "import { handleEvent } from \"../billing/events\";",
        "",
        "const stripe = new Stripe(config.stripe.secretKey, { apiVersion: \"2024-06-20\" });",
        "export const router = express.Router();",
        "",
        "router.use(express.json({ limit: \"1mb\" }));",
        "",
        "router.post(\"/webhooks/stripe\", async (req, res) => {",
        "  const sig = req.headers[\"stripe-signature\"] as string;",
        "  let event: Stripe.Event;",
        "  try {",
        "    event = stripe.webhooks.constructEvent(req.body, sig, config.stripe.webhookSecret);",
        "  } catch (err) {",
        "    logger.warn({ err, sig }, \"stripe signature verification failed\");",
        "    return res.status(400).send(`Webhook Error: ${(err as Error).message}`);",
        "  }",
        "  await handleEvent(event);",
        "  res.json({ received: true });",
        "});",
    )
    d.tool("read", "src/routes/webhooks.ts", code)
    whsec = g.secret("stripe_whsec")
    env_rows = [
        "# staging",
        T("STRIPE_SECRET_KEY=⟦k⟧", k=g.secret("stripe_live")),
        T("STRIPE_PUBLISHABLE_KEY=⟦k⟧", k=x.id("pk_live_" + V.rand_str(r, V.ALNUM, 24))),
        T("STRIPE_WEBHOOK_SECRET=⟦k⟧", k=whsec),
        T("BILLING_ALERTS_TO=⟦e⟧", e=g.email(d.me, "work")),
    ]
    if r.random() < 0.5:
        env_rows.append(T("DATABASE_URL=postgres://billing:⟦p⟧@⟦ip⟧:5432/billing", p=g.password(), ip=g.ip("private")))
    d.tool("read", ".env.staging", lines(*env_rows))
    if d.secret_ok and r.random() < 0.6:
        d.agent(say(d, "secret_warning", x=".env.staging"))
    d.agent(d.L(en="Let me forward live events locally and watch the responses.",
                it="Inoltro gli eventi in locale e guardo le risposte.",
                de="Ich leite die Events lokal weiter und beobachte die Antworten.",
                fr="Je redirige les événements en local et je regarde les réponses.",
                es="Reenvío los eventos en local y miro las respuestas."))
    evts = []
    rows = [T("> Ready! You are using Stripe API Version [2024-06-20]. Your webhook signing secret is ⟦w⟧ (^C to quit)", w=whsec)]
    kinds = r.sample(["customer.updated", "payment_method.attached", "invoice.paid", "customer.created",
                      "charge.succeeded", "checkout.session.completed"], r.randint(2, 4))
    for k in kinds:
        eid = "evt_" + V.rand_str(r, V.ALNUM, 24)
        evts.append((k, eid))
        rows.append(T("⟦t⟧   --> ⟦k⟧ [⟦e⟧]", t=x.ts("space", tick=(2, 40)), k=k, e=x.id(eid)))
        rows.append(T("⟦t⟧  <--  [400] POST http://localhost:⟦p⟧/webhooks/stripe [⟦e⟧]", t=x.ts("space", tick=(0, 1)),
                      p=x.port(port), e=x.id(eid)))
    d.tool("sh", F("stripe listen --forward-to localhost:", x.port(port), "/webhooks/stripe"), lines(*rows))
    kind, eid = evts[0]
    a = cust.address
    created = x.ts("epoch", tick=(0, 0))
    if kind.startswith("payment_method"):
        obj = {
            "id": x.id("pm_" + V.rand_str(r, V.ALNUM, 24)),
            "object": "payment_method",
            "billing_details": {
                "address": {"city": g.addr(cust, "city"), "country": a.country, "line1": g.addr(cust, "street"),
                            "line2": None, "postal_code": g.addr(cust, "postcode"), "state": a.region or None},
                "email": g.email(cust, "personal"),
                "name": g.name(cust),
                "phone": g.phone(cust, intl=True),
            },
            "card": {"brand": r.choice(["visa", "mastercard", "amex"]), "country": a.country,
                     "exp_month": r.randint(1, 12), "exp_year": r.randint(2026, 2031),
                     "fingerprint": x.id(V.rand_str(r, V.ALNUM, 16)), "funding": "credit",
                     "last4": x.ph("card", f"{r.randint(0, 9999):04d}")},
            "customer": x.id("cus_" + V.rand_str(r, V.ALNUM, 14)),
            "type": "card",
        }
    else:
        obj = {
            "id": x.id("cus_" + V.rand_str(r, V.ALNUM, 14)),
            "object": "customer",
            "address": {"city": g.addr(cust, "city"), "country": a.country, "line1": g.addr(cust, "street"),
                        "line2": g.raw("private_address", a.extra, "address") if a.extra else None,
                        "postal_code": g.addr(cust, "postcode"), "state": a.region or None},
            "balance": 0,
            "currency": r.choice(["eur", "gbp", "usd"]),
            "email": g.email(cust, "personal"),
            "invoice_prefix": V.rand_str(r, V.UPPER + "0123456789", 8),
            "metadata": {"account_id": g.cust()},
            "name": g.name(cust),
            "phone": g.phone(cust, intl=True),
        }
    event = {"id": x.id(eid), "object": "event", "api_version": x.ver("2024-06-20"), "created": _Raw(created),
             "data": {"object": obj}, "livemode": True, "pending_webhooks": 1,
             "request": {"id": x.id("req_" + V.rand_str(r, V.ALNUM, 14)), "idempotency_key": x.uuid()},
             "type": kind}
    d.tool("sh", F("stripe events retrieve ", x.id(eid)), _js(event))
    sig_rows = []
    pc = _Past(d, 0.2, 6)
    for _ in range(r.randint(2, 4)):
        t = pc.tick(5, 600)
        sig_rows.append(_jl({"level": 40, "time": _Raw(x.ts("epoch_ms", t=t)), "pid": r.randint(20, 900),
                             "hostname": f"api-{V.rand_str(r, V.HEX, 9)}-{V.rand_str(r, 'abcdefghijklmnopqrstuvwxyz0123456789', 5)}",
                             "sig": _Q("t=", x.ts("epoch", t=t), ",v1=", x.id(V.rand_str(r, V.HEX, 64))),
                             "msg": "stripe signature verification failed"}))
    d.tool("sh", "grep 'signature verification failed' logs/api.log | tail -n 3", lines(*sig_rows))
    d.agent(say(d, "explain"), "\n\n",
            d.L(en="`router.use(express.json())` runs before the webhook route, so `req.body` is already a parsed object. `constructEvent` must receive the exact raw bytes Stripe signed; re-serialised JSON never matches the signature.",
                it="`router.use(express.json())` viene eseguito prima della route del webhook, quindi `req.body` è già un oggetto. `constructEvent` deve ricevere i byte grezzi firmati da Stripe; il JSON riserializzato non combacia mai con la firma.",
                de="`router.use(express.json())` läuft vor der Webhook-Route, `req.body` ist also schon ein geparstes Objekt. `constructEvent` braucht exakt die rohen Bytes, die Stripe signiert hat; neu serialisiertes JSON passt nie zur Signatur.",
                fr="`router.use(express.json())` s'exécute avant la route du webhook, donc `req.body` est déjà un objet. `constructEvent` doit recevoir les octets bruts signés par Stripe ; un JSON resérialisé ne correspond jamais à la signature.",
                es="`router.use(express.json())` se ejecuta antes de la ruta del webhook, así que `req.body` ya es un objeto. `constructEvent` necesita los bytes en crudo que firmó Stripe; el JSON reserializado nunca coincide con la firma."),
            "\n", x.url("docs", "https://docs.stripe.com/webhooks/signature"))
    d.tool("edit", "src/routes/webhooks.ts", lines(
        "@@ -9,9 +9,11 @@ export const router = express.Router();",
        "-router.use(express.json({ limit: \"1mb\" }));",
        "-",
        "-router.post(\"/webhooks/stripe\", async (req, res) => {",
        "+router.post(\"/webhooks/stripe\", express.raw({ type: \"application/json\" }), async (req, res) => {",
        "   const sig = req.headers[\"stripe-signature\"] as string;",
        "@@ -24,3 +26,5 @@",
        "   res.json({ received: true });",
        " });",
        "+",
        "+router.use(express.json({ limit: \"1mb\" }));"))
    d.tool("sh", F("stripe events resend ", x.id(eid)), lines(
        T("⟦t⟧   --> ⟦k⟧ [⟦e⟧]", t=x.ts("space", tick=(20, 90)), k=kind, e=x.id(eid)),
        T("⟦t⟧  <--  [200] POST http://localhost:⟦p⟧/webhooks/stripe [⟦e⟧]", t=x.ts("space", tick=(0, 1)),
          p=x.port(port), e=x.id(eid))))
    d.agent(say(d, "done"), "\n- ",
            d.L(en="raw body for the Stripe route, JSON parser mounted after it",
                it="body grezzo per la route Stripe, parser JSON montato dopo",
                de="Raw-Body für die Stripe-Route, JSON-Parser danach eingehängt",
                fr="corps brut pour la route Stripe, parseur JSON monté après",
                es="body en crudo para la ruta de Stripe, parser JSON montado después"),
            "\n- ", d.L(en="verified with a resent event (200)", it="verificato con un evento reinviato (200)",
                        de="mit einem erneut gesendeten Event verifiziert (200)", fr="vérifié avec un événement renvoyé (200)",
                        es="verificado con un evento reenviado (200)"))


# ---------------------------------------------------------------- 3. HAR file: lost session cookie


@template("har_cookie_analysis", "md", "http", "file")
def har_cookie_analysis(d):
    g, x, r = d.g, d.x, d.rng
    cust = d.person()
    shop = f"shop.{d.domain}"
    pay_host = r.choice(["checkout.adyen.com", "pay.paypal.com", "hooks.stripe.com", "secure.mollie.com"])
    browser = r.choice(["Chrome", "Firefox", "Safari", "Edge"])
    d.user(d.L(
        en=f"After paying, customers come back to /checkout/complete logged out. I exported a HAR from {browser} into debug/logout.har, can you see why?",
        it=f"Dopo il pagamento i clienti tornano su /checkout/complete sloggati. Ho esportato un HAR da {browser} in debug/logout.har, riesci a capire perché?",
        de=f"Nach dem Bezahlen landen Kunden ausgeloggt auf /checkout/complete. Ich habe ein HAR aus {browser} nach debug/logout.har exportiert, siehst du warum?",
        fr=f"Après le paiement, les clients reviennent sur /checkout/complete déconnectés. J'ai exporté un HAR depuis {browser} dans debug/logout.har, tu vois pourquoi ?",
        es=f"Después de pagar, los clientes vuelven a /checkout/complete sin sesión. Exporté un HAR de {browser} en debug/logout.har, ¿ves por qué?"))
    d.agent(say(d, "look_first", x=d.L(en="the request timeline in the HAR", it="la sequenza delle richieste nel HAR",
                                       de="die Request-Abfolge im HAR", fr="la chronologie des requêtes du HAR",
                                       es="la secuencia de peticiones del HAR")))
    sess_id = "cs_live_" + V.rand_str(r, V.ALNUM, 40)
    if d.gold_ok:
        complete_url = g.raw("private_url", f"https://{shop}/checkout/complete?session_id={sess_id}", "url")
    else:
        complete_url = x.ph("url", f"https://{shop}/checkout/complete?session_id={{CHECKOUT_SESSION_ID}}")
    rows = []
    timeline = [
        ("GET", 200, F("https://", shop, "/cart")),
        ("GET", 200, x.url("cdn")),
        ("POST", 303, F("https://", shop, "/checkout")),
        ("GET", 200, F("https://", pay_host, "/session/", x.id(V.rand_str(r, V.ALNUM, 18)))),
        ("POST", 302, complete_url),
        ("GET", 302, F("https://", shop, "/account?email=", _enc_email(d, cust))),
        ("GET", 200, F("https://", shop, "/login?next=%2Fcheckout%2Fcomplete")),
    ]
    if r.random() < 0.5:
        timeline.insert(2, ("GET", 200, x.url("cdn")))
    post_t = None
    pc = _Past(d, 0.3, 5)
    for method, status, url in timeline:
        rows.append(F(x.ts("iso_z", t=pc.tick(0.2, 6)), "\t", method, "\t", str(status), "\t", url))
        if url is complete_url:
            post_t = pc.t
    d.tool("sh", "jq -r '.log.entries[] | [.startedDateTime, .request.method, .response.status, .request.url] | @tsv' debug/logout.har",
           lines(*rows))
    idx = 4 + (1 if len(timeline) == 8 else 0)
    old_sid, new_sid = _sec(d, "session_signed", "session"), _sec(d, "session_signed", "session")
    entry = {
        "startedDateTime": x.ts("iso_z", t=post_t),
        "time": round(r.uniform(80, 900), 3),
        "request": {
            "method": "POST",
            "url": complete_url,
            "httpVersion": "h2",
            "cookies": [
                {"name": "cart_id", "value": x.uuid()},
                {"name": "_ga", "value": x.id(f"GA1.1.{r.randint(10**8, 10**10)}.{int(d.clock.t.timestamp()) - r.randint(10**5, 10**7)}")},
                {"name": "consent", "value": "analytics:0,marketing:0"},
            ],
            "headers": [
                {"name": "origin", "value": "https://" + pay_host},
                {"name": "content-type", "value": "application/x-www-form-urlencoded"},
                {"name": "user-agent", "value": _ua(d)},
            ],
            "queryString": [{"name": "session_id", "value": x.id(sess_id)}],
            "postData": {"mimeType": "application/x-www-form-urlencoded",
                         "text": _Q("payment_status=paid&customer_email=", _enc_email(d, cust))},
        },
        "response": {
            "status": 302,
            "statusText": "",
            "headers": [
                {"name": "date", "value": x.ts("http", t=post_t)},
                {"name": "location", "value": "/login?next=%2Fcheckout%2Fcomplete"},
                {"name": "set-cookie", "value": _Q("connect.sid=", new_sid, "; Path=/; Expires=",
                                                   x.ts("http", t=post_t + dt.timedelta(days=14)), "; HttpOnly")},
                {"name": "x-request-id", "value": x.rid()},
            ],
            "cookies": [{"name": "connect.sid", "value": new_sid, "path": "/", "httpOnly": True, "secure": False}],
        },
        "serverIPAddress": g.ip("public"),
        "connection": "443",
    }
    d.agent(d.L(en=f"Entry {idx} is the POST back from the payment page. Full entry:",
                it=f"La voce {idx} è il POST di ritorno dalla pagina di pagamento. Dettaglio:",
                de=f"Eintrag {idx} ist der POST zurück von der Bezahlseite. Vollständig:",
                fr=f"L'entrée {idx} est le POST de retour depuis la page de paiement. En entier :",
                es=f"La entrada {idx} es el POST de vuelta desde la página de pago. Completa:"))
    d.tool("sh", f"jq '.log.entries[{idx}]' debug/logout.har", _js(entry))
    prev = {"name": "connect.sid", "value": old_sid}
    d.tool("sh", f"jq '.log.entries[0].request.cookies[] | select(.name==\"connect.sid\")' debug/logout.har", _js(prev))
    d.agent(say(d, "explain"), "\n\n",
            d.L(en="The session cookie is present on the first-party requests but missing on the cross-site POST coming back from the payment page. With no SameSite attribute the browser treats it as `Lax`, and Lax cookies are not sent on cross-site POST navigations. The server sees no session, issues a fresh `connect.sid` and redirects to /login.",
                it="Il cookie di sessione c'è nelle richieste first-party ma manca nel POST cross-site che torna dalla pagina di pagamento. Senza attributo SameSite il browser lo tratta come `Lax`, e i cookie Lax non vengono inviati nelle navigazioni POST cross-site. Il server non vede sessione, ne crea una nuova e redirige su /login.",
                de="Das Session-Cookie ist bei den First-Party-Requests da, fehlt aber beim Cross-Site-POST von der Bezahlseite. Ohne SameSite-Attribut behandelt der Browser es als `Lax`, und Lax-Cookies werden bei Cross-Site-POST-Navigationen nicht mitgeschickt. Der Server sieht keine Session, vergibt eine neue `connect.sid` und leitet auf /login um.",
                fr="Le cookie de session est présent sur les requêtes first-party mais absent du POST cross-site qui revient de la page de paiement. Sans attribut SameSite le navigateur le traite comme `Lax`, et les cookies Lax ne sont pas envoyés sur une navigation POST cross-site. Le serveur ne voit pas de session, en crée une nouvelle et redirige vers /login.",
                es="La cookie de sesión está en las peticiones first-party pero falta en el POST cross-site que vuelve de la página de pago. Sin atributo SameSite el navegador la trata como `Lax`, y las cookies Lax no se envían en navegaciones POST cross-site. El servidor no ve sesión, crea un `connect.sid` nuevo y redirige a /login."),
            "\n\n", x.url("docs", "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie#samesitesamesite-value"))
    d.tool("grep", "-n \"cookie\" src/app.js src/session.js", lines(
        T("src/app.js:⟦n⟧:app.use(session(sessionConfig));", n=x.num(lo=20, hi=60)),
        T("src/session.js:⟦n⟧:  cookie: {", n=x.num(lo=8, hi=20)),
        T("src/session.js:⟦n⟧:    httpOnly: true,", n=x.num(lo=9, hi=21)),
        T("src/session.js:⟦n⟧:    maxAge: 14 * 24 * 3600 * 1000,", n=x.num(lo=10, hi=22))))
    fix = r.choice(["samesite", "get"])
    if fix == "samesite":
        d.tool("edit", "src/session.js", lines(
            "   cookie: {",
            "     httpOnly: true,",
            "+    secure: true,",
            "+    sameSite: \"none\", // payment provider returns with a cross-site POST",
            "     maxAge: 14 * 24 * 3600 * 1000,",
            "   },",
            "+  proxy: true, // TLS terminates at the load balancer"))
    else:
        d.agent(d.L(en="Rather than relaxing the session cookie, I'll make the return URL a GET: the provider supports `return_method=GET`, and the order is confirmed by the webhook anyway.",
                    it="Invece di allentare il cookie di sessione, rendo l'URL di ritorno una GET: il provider supporta `return_method=GET` e l'ordine viene comunque confermato dal webhook.",
                    de="Statt das Session-Cookie aufzuweichen, mache ich die Rücksprung-URL zu einem GET: der Anbieter unterstützt `return_method=GET`, und die Bestellung bestätigt ohnehin der Webhook.",
                    fr="Plutôt que d'assouplir le cookie de session, je passe l'URL de retour en GET : le prestataire supporte `return_method=GET`, et la commande est de toute façon confirmée par le webhook.",
                    es="En lugar de relajar la cookie de sesión, hago que la URL de retorno sea GET: el proveedor admite `return_method=GET` y el pedido lo confirma el webhook de todas formas."))
        d.tool("edit", "src/checkout/createSession.js", lines(
            "   success_url: `${BASE_URL}/checkout/complete?session_id={CHECKOUT_SESSION_ID}`,",
            "-  return_method: \"POST\",",
            "+  return_method: \"GET\",",))
    d.agent(say(d, "pii_warning"), " ",
            d.L(en="The HAR also holds live session cookies — please don't commit debug/logout.har.",
                it="Il HAR contiene anche cookie di sessione validi: per favore non committare debug/logout.har.",
                de="Das HAR enthält außerdem gültige Session-Cookies – bitte debug/logout.har nicht committen.",
                fr="Le HAR contient aussi des cookies de session valides — ne committe pas debug/logout.har.",
                es="El HAR también tiene cookies de sesión válidas; no hagas commit de debug/logout.har."))
    if r.random() < 0.6:
        d.user(say(d, "thanks"))


# ---------------------------------------------------------------- 4. GraphQL customer query


@template("graphql_customer_query", "colon", "http")
def graphql_customer_query(d):
    g, x, r = d.g, d.x, d.rng
    cust = d.person()
    cno = V.customer_no(r)
    cno_seg = _acct(d, cno)
    d.user(T(d.L(
        en="Support says customer ⟦c⟧ sees their current address on old orders, which is wrong. This is the query the account page runs, can you check the API?",
        it="Il supporto dice che il cliente ⟦c⟧ vede l'indirizzo attuale anche sugli ordini vecchi, ed è sbagliato. Questa è la query della pagina account, puoi controllare l'API?",
        de="Der Support sagt, Kunde ⟦c⟧ sieht bei alten Bestellungen seine aktuelle Adresse, das ist falsch. Das ist die Query der Kontoseite, kannst du die API prüfen?",
        fr="Le support signale que le client ⟦c⟧ voit son adresse actuelle sur ses anciennes commandes, ce qui est faux. Voici la requête de la page compte, tu peux vérifier l'API ?",
        es="Soporte dice que el cliente ⟦c⟧ ve su dirección actual en pedidos antiguos, y no es correcto. Esta es la query de la página de cuenta, ¿puedes revisar la API?"),
        c=cno_seg), "\n\n",
        lines("query AccountOrders($id: ID!) {", "  customer(id: $id) {", "    id fullName email phone",
              "    defaultAddress { line1 line2 postcode city country }",
              "    orders(first: 10) { edges { node { number placedAt total",
              "      recipientName shippingAddress { line1 line2 postcode city country } } } }",
              "  }", "}"))
    token = g.secret("bearer_opaque")
    d.call("sh", F("curl -s https://api.", d.domain, "/graphql -H 'Authorization: Bearer ", token,
                   "' -H 'Content-Type: application/json' --data @/tmp/account-orders.json | jq"))
    others = [d.person(cust.locale) for _ in range(r.randint(0, 2))]
    n_orders = r.choice([2, 3, 4, 5, 6, 8, 10, 14, 18])
    a = cust.address
    edges = []
    t = d.clock.t
    null_idx = r.randint(1, n_orders - 1)
    for i in range(n_orders):
        t = t - dt.timedelta(days=r.randint(15, 200))
        gift = others and r.random() < 0.35
        rp = r.choice(others) if gift else cust
        node = {
            "number": x.id(f"{r.choice(['SO', 'ORD', 'WEB'])}-{r.randint(100000, 999999)}"),
            "placedAt": x.ts("iso_s", t=t),
            "total": f"{r.uniform(9, 480):.2f}",
            "recipientName": g.name(rp),
            "shippingAddress": None if i == null_idx else {
                "line1": g.addr(cust, "street"), "line2": None, "postcode": g.addr(cust, "postcode"),
                "city": g.addr(cust, "city"), "country": a.country},
        }
        edges.append({"node": node})
    resp = {
        "errors": [{"message": "Cannot return null for non-nullable field Address.line2.",
                    "locations": [{"line": _Raw(x.num(6)), "column": _Raw(x.num(r.choice([42, 48, 51])))}],
                    "path": ["customer", "orders", "edges", null_idx, "node", "shippingAddress", "line2"],
                    "extensions": {"code": "INTERNAL_SERVER_ERROR", "requestId": x.rid()}}],
        "data": {"customer": {
            "id": cno_seg, "fullName": g.name(cust), "email": g.email(cust, r.choice(["work", "personal"])),
            "phone": g.phone(cust),
            "defaultAddress": {"line1": g.addr(cust, "street"), "line2": None, "postcode": g.addr(cust, "postcode"),
                               "city": g.addr(cust, "city"), "country": a.country},
            "orders": {"edges": edges}}},
    }
    d.result("sh", _js(resp))
    d.agent(say(d, "explain"), "\n",
            d.L(en=f"1. Every order's shippingAddress equals the customer's current defaultAddress — even orders from years ago.\n2. Order #{null_idx} has no stored shipping address at all, and the fallback object breaks the non-null `line2` field.",
                it=f"1. La shippingAddress di ogni ordine coincide con il defaultAddress attuale del cliente, anche per ordini di anni fa.\n2. L'ordine #{null_idx} non ha proprio un indirizzo di spedizione salvato e l'oggetto di fallback rompe il campo non-null `line2`.",
                de=f"1. Die shippingAddress jeder Bestellung entspricht der aktuellen defaultAddress – auch bei Jahre alten Bestellungen.\n2. Bestellung #{null_idx} hat gar keine gespeicherte Lieferadresse, und das Fallback-Objekt bricht das Non-Null-Feld `line2`.",
                fr=f"1. La shippingAddress de chaque commande est égale à la defaultAddress actuelle du client, même pour des commandes anciennes.\n2. La commande #{null_idx} n'a aucune adresse de livraison enregistrée, et l'objet de repli casse le champ non-null `line2`.",
                es=f"1. La shippingAddress de cada pedido es igual a la defaultAddress actual del cliente, incluso en pedidos de hace años.\n2. El pedido #{null_idx} no tiene dirección de envío guardada y el objeto de respaldo rompe el campo no nulo `line2`."))
    resolver = lines(
        "import { Resolvers } from \"../generated/types\";",
        "",
        "export const Order: Resolvers[\"Order\"] = {",
        "  recipientName: (o) => o.recipientName ?? o.customerName,",
        "  shippingAddress: async (o, _args, ctx) => {",
        "    const customer = await ctx.loaders.customer.load(o.customerId);",
        "    return customer.defaultAddress;",
        "  },",
        "  total: (o) => o.totalCents / 100,",
        "};",
    )
    d.tool("read", "src/graphql/resolvers/Order.ts", numbered(resolver))
    d.tool("grep", "-n \"line2\" src/graphql/schema.graphql", lines(
        T("⟦n⟧:  line2: String!", n=x.num(lo=40, hi=140))))
    d.agent(say(d, "applying"))
    d.tool("edit", "src/graphql/resolvers/Order.ts", lines(
        "-  shippingAddress: async (o, _args, ctx) => {",
        "-    const customer = await ctx.loaders.customer.load(o.customerId);",
        "-    return customer.defaultAddress;",
        "-  },",
        "+  // the address snapshot stored at checkout; null for legacy orders",
        "+  shippingAddress: (o) => o.shippingAddressSnapshot ?? null,"))
    d.tool("edit", "src/graphql/schema.graphql", lines("-  line2: String!", "+  line2: String"))
    if r.random() < 0.7:
        d.tool("sh", "npm run codegen && npm test -- graphql/order", lines(
            "> codegen", T("✔ Parse Configuration  ✔ Generate outputs (⟦n⟧ files)", n=x.num(lo=3, hi=9)),
            "", T(" PASS  src/graphql/__tests__/order.test.ts (⟦s⟧ s)", s=f"{r.uniform(1, 6):.3f}"),
            T("Tests:       ⟦a⟧ passed, ⟦a⟧ total", a=x.num(lo=4, hi=18))))
    d.agent(say(d, "done"), "\n",
            d.L(en="- shippingAddress now comes from the per-order snapshot (null for legacy orders)\n- `line2` is nullable in the schema",
                it="- shippingAddress ora viene dallo snapshot dell'ordine (null per gli ordini legacy)\n- `line2` è nullable nello schema",
                de="- shippingAddress kommt jetzt aus dem Snapshot der Bestellung (null bei Altbestellungen)\n- `line2` ist im Schema nullable",
                fr="- shippingAddress provient maintenant de l'instantané de la commande (null pour les anciennes)\n- `line2` est nullable dans le schéma",
                es="- shippingAddress sale ahora de la instantánea del pedido (null en pedidos antiguos)\n- `line2` es nullable en el esquema"))


# ---------------------------------------------------------------- 5. OAuth callback failures


@template("oauth_callback_debug", "jsonl", "http", "log")
def oauth_callback_debug(d):
    g, x, r = d.g, d.x, d.rng
    users = [d.person() for _ in range(r.choice([2, 3, 3, 4, 5, 6, 8, 10]))]
    login = _host(d, "login")
    app = f"app.{d.domain}"
    cause = r.choice(["double", "expired"])
    d.user(d.L(
        en="Some users can't log in with SSO, the callback fails with invalid_grant. Not everyone, maybe one in twenty. Logs are in logs/auth-callback.log",
        it="Alcuni utenti non riescono a fare login con SSO, la callback fallisce con invalid_grant. Non tutti, forse uno su venti. I log sono in logs/auth-callback.log",
        de="Manche User können sich nicht per SSO anmelden, der Callback scheitert mit invalid_grant. Nicht alle, vielleicht einer von zwanzig. Logs liegen in logs/auth-callback.log",
        fr="Certains utilisateurs n'arrivent pas à se connecter en SSO, le callback échoue avec invalid_grant. Pas tout le monde, peut-être un sur vingt. Les logs sont dans logs/auth-callback.log",
        es="Algunos usuarios no pueden entrar con SSO, el callback falla con invalid_grant. No todos, quizá uno de cada veinte. Los logs están en logs/auth-callback.log"))
    d.agent(say(d, "logs_window"))
    rows = []
    failing = r.sample(range(len(users)), 1)
    pc = _Past(d, 0.5, 30)
    for i, u in enumerate(users):
        ip = g.ip(r.choice(["public", "public", "v6"]))
        state = V.rand_str(r, V.B64URL, 22)
        email_q = V.email_work(u, d.domain).replace("@", "%40")
        auth_url = _purl(d, f"https://{login}/oauth2/authorize?response_type=code&client_id=web-portal"
                            f"&redirect_uri=https%3A%2F%2F{app}%2Fauth%2Fcallback&scope=openid%20email%20profile"
                            f"&state={state}&login_hint={email_q}")
        code = _sec(d, "bearer_opaque", "token")
        rows.append(_jl({"ts": x.ts("iso_z", t=pc.tick(3, 90)), "level": "info", "event": "authorize_redirect",
                         "session": x.uuid(), "url": auth_url}))
        cb = {"ts": x.ts("iso_z", t=pc.tick(8, 40)), "level": "info", "event": "callback",
              "path": _Q("/auth/callback?code=", code, "&state=", x.id(state)), "ip": ip, "ua": _ua(d)}
        rows.append(_jl(cb))
        if i in failing and cause == "double":
            rows.append(_jl({"ts": x.ts("iso_z", t=pc.tick(0.1, 0.6)), "level": "info", "event": "callback",
                             "path": _Q("/auth/callback?code=", code, "&state=", x.id(state)), "ip": ip,
                             "ua": _ua(d), "purpose": "prefetch"}))
            rows.append(_jl({"ts": x.ts("iso_z", t=pc.tick(0.2, 0.9)), "level": "info", "event": "session_created",
                             "user_id": _acct(d, _uid(d)), "email": g.email(u, "work")}))
            rows.append(_jl({"ts": x.ts("iso_z", t=pc.tick(0.1, 0.4)), "level": "error", "event": "token_exchange_failed",
                             "status": 400, "error": "invalid_grant",
                             "error_description": "Authorization code already redeemed", "login_hint": g.email(u, "work"),
                             "ip": ip}))
        elif i in failing:
            rows.append(_jl({"ts": x.ts("iso_z", t=pc.tick(10, 10.5)), "level": "warn", "event": "token_exchange_timeout",
                             "attempt": 1, "timeout_ms": 10000, "login_hint": g.email(u, "work")}))
            rows.append(_jl({"ts": x.ts("iso_z", t=pc.tick(20, 25)), "level": "error", "event": "token_exchange_failed",
                             "attempt": 2, "status": 400, "error": "invalid_grant",
                             "error_description": "Authorization code expired", "login_hint": g.email(u, "work"),
                             "ip": ip}))
        else:
            rows.append(_jl({"ts": x.ts("iso_z", t=pc.tick(0.2, 0.9)), "level": "info", "event": "session_created",
                             "user_id": _acct(d, _uid(d)), "email": g.email(u, "work")}))
    d.tool("sh", "tail -n 40 logs/auth-callback.log", lines(*rows))
    if cause == "double":
        d.agent(say(d, "explain"), "\n",
                d.L(en="For the failing login the callback is hit twice within a second with the same code — the second request carries `Sec-Purpose: prefetch`. The browser prefetches the redirect target; the first exchange wins and the real navigation then gets invalid_grant because codes are single-use.",
                    it="Per il login che fallisce la callback viene chiamata due volte in meno di un secondo con lo stesso code — la seconda richiesta ha `Sec-Purpose: prefetch`. Il browser fa prefetch della destinazione del redirect; il primo scambio vince e la navigazione vera riceve invalid_grant perché i code sono monouso.",
                    de="Beim fehlschlagenden Login wird der Callback innerhalb einer Sekunde zweimal mit demselben Code aufgerufen — der zweite Request trägt `Sec-Purpose: prefetch`. Der Browser lädt das Redirect-Ziel vorab; der erste Austausch gewinnt, und die echte Navigation bekommt invalid_grant, weil Codes nur einmal gültig sind.",
                    fr="Pour la connexion en échec, le callback est appelé deux fois en moins d'une seconde avec le même code — la seconde requête porte `Sec-Purpose: prefetch`. Le navigateur précharge la cible de la redirection ; le premier échange gagne et la vraie navigation reçoit invalid_grant car les codes sont à usage unique.",
                    es="En el login que falla, el callback se llama dos veces en menos de un segundo con el mismo code; la segunda petición lleva `Sec-Purpose: prefetch`. El navegador precarga el destino de la redirección; el primer intercambio gana y la navegación real recibe invalid_grant porque los codes son de un solo uso."))
    else:
        d.agent(say(d, "explain"), "\n",
                d.L(en="The failing login timed out on the first token request (10 s) and the client retried with the same code ~20 s later. The IdP's codes live 30 s, so the retry is rejected as expired. Retrying an authorization-code exchange can never succeed anyway.",
                    it="Il login fallito è andato in timeout sulla prima richiesta di token (10 s) e il client ha ritentato con lo stesso code dopo ~20 s. I code dell'IdP durano 30 s, quindi il retry viene rifiutato come scaduto. Ritentare uno scambio di authorization code non può comunque funzionare.",
                    de="Der fehlgeschlagene Login lief beim ersten Token-Request in einen Timeout (10 s), und der Client hat ~20 s später mit demselben Code erneut versucht. Die Codes des IdP leben 30 s, also wird der Retry als abgelaufen abgelehnt. Ein Code-Austausch lässt sich ohnehin nicht wiederholen.",
                    fr="La connexion en échec a expiré sur la première requête de token (10 s) et le client a réessayé avec le même code ~20 s plus tard. Les codes de l'IdP vivent 30 s, donc la nouvelle tentative est refusée comme expirée. Rejouer un échange de code ne peut de toute façon pas marcher.",
                    es="El login fallido agotó el tiempo en la primera petición de token (10 s) y el cliente reintentó con el mismo code ~20 s después. Los codes del IdP duran 30 s, así que el reintento se rechaza como caducado. Reintentar un intercambio de code nunca puede funcionar."))
    fresh = _sec(d, "bearer_opaque", "token")
    d.user(T(d.L(en="To compare with a good exchange, here's a fresh code from my own login (valid ~30s): ⟦c⟧",
                 it="Per confrontare con uno scambio buono, ecco un code fresco dal mio login (vale ~30s): ⟦c⟧",
                 de="Zum Vergleich mit einem funktionierenden Austausch: frischer Code aus meinem Login (gilt ~30s): ⟦c⟧",
                 fr="Pour comparer avec un échange qui marche, voici un code tout frais de ma connexion (valable ~30 s) : ⟦c⟧",
                 es="Para comparar con un intercambio correcto, aquí tienes un code recién sacado de mi login (vale ~30 s): ⟦c⟧"),
               c=fresh))
    me = d.me
    secret = _sec(d, "bearer_opaque", "key")
    d.call("sh", F("curl -s -X POST https://", login, "/oauth2/token -d grant_type=authorization_code -d code=", fresh,
                   " -d redirect_uri=https://", app, "/auth/callback -d client_id=web-portal -d client_secret=", secret,
                   " | jq ."))
    tok = {
        "access_token": g.jwt({"email": V.email_work(me, d.domain), "scope": "openid email profile"}, "RS256"),
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": _sec(d, "bearer_opaque", "token"),
        "id_token": g.jwt({"email": V.email_work(me, d.domain), "name": me.full, "email_verified": True}, "RS256"),
        "scope": "openid email profile",
    }
    d.result("sh", _js(tok))
    src = lines(
        "export async function oauthCallback(req: Request, res: Response) {",
        "  const { code, state } = req.query as Record<string, string>;",
        "  if (!state || state !== req.session.oauthState) return res.status(400).send(\"bad state\");",
        "  const tokens = await withRetry(() => idp.exchangeCode(code), { attempts: 3, timeoutMs: 10_000 });",
        "  const claims = verifyIdToken(tokens.id_token);",
        "  await createSession(req, claims);",
        "  res.redirect(req.session.returnTo ?? \"/\");",
        "}",
    )
    d.tool("read", "src/auth/callback.ts", numbered(src, start=r.randint(12, 40)))
    if cause == "double":
        d.tool("edit", "src/auth/callback.ts", lines(
            "+  if (req.get(\"Sec-Purpose\")?.includes(\"prefetch\")) return res.status(204).end();",
            "   const { code, state } = req.query as Record<string, string>;",
            "   if (!state || state !== req.session.oauthState) return res.status(400).send(\"bad state\");",
            "+  delete req.session.oauthState; // a state is consumed once"))
    else:
        d.tool("edit", "src/auth/callback.ts", lines(
            "-  const tokens = await withRetry(() => idp.exchangeCode(code), { attempts: 3, timeoutMs: 10_000 });",
            "+  // an authorization code is single-use: never retry the exchange, restart the flow instead",
            "+  const tokens = await idp.exchangeCode(code, { timeoutMs: 25_000 });"))
    if cause == "double":
        summary = d.L(en="- prefetch requests to the callback are answered with 204 and never touch the code\n- the OAuth state is consumed once",
                      it="- le richieste di prefetch alla callback ricevono 204 e non toccano il code\n- lo state OAuth viene consumato una sola volta",
                      de="- Prefetch-Requests auf den Callback bekommen 204 und fassen den Code nicht an\n- der OAuth-State wird nur einmal verbraucht",
                      fr="- les requêtes de préchargement du callback reçoivent un 204 et ne touchent pas au code\n- le state OAuth n'est consommé qu'une fois",
                      es="- las peticiones de prefetch al callback reciben 204 y no tocan el code\n- el state de OAuth se consume una sola vez")
    else:
        summary = d.L(en="- the code exchange is no longer retried\n- the exchange timeout is raised to 25 s; a failure restarts the login",
                      it="- lo scambio del code non viene più ritentato\n- il timeout sale a 25 s; in caso di errore si riparte dal login",
                      de="- der Code-Austausch wird nicht mehr wiederholt\n- Timeout auf 25 s erhöht; bei Fehlern startet der Login neu",
                      fr="- l'échange du code n'est plus rejoué\n- le délai passe à 25 s ; en cas d'échec on relance la connexion",
                      es="- el intercambio del code ya no se reintenta\n- el timeout sube a 25 s; si falla, se reinicia el login")
    d.agent(say(d, "done"), "\n", summary)
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x=d.L(en="this conversation (client_secret)", it="questa conversazione (client_secret)",
                                                de="dieser Verlauf (client_secret)", fr="cette conversation (client_secret)",
                                                es="esta conversación (client_secret)")))


# ---------------------------------------------------------------- 6. KYC provider integration


@template("kyc_api_integration", "tslog", "http", "file")
def kyc_api_integration(d):
    g, x, r = d.g, d.x, d.rng
    provider = r.choice(["Onfido", "Veriff", "Sumsub", "Jumio"])
    d.user(T(d.L(
        en="⟦p⟧ rejects about half of our identity checks with invalid date_of_birth since we switched to the new client. The client is src/kyc/client.py",
        it="⟦p⟧ rifiuta circa metà delle verifiche d'identità con invalid date_of_birth da quando usiamo il nuovo client. Il client è src/kyc/client.py",
        de="⟦p⟧ lehnt seit dem neuen Client etwa die Hälfte unserer Identitätsprüfungen mit invalid date_of_birth ab. Der Client ist src/kyc/client.py",
        fr="⟦p⟧ rejette environ la moitié de nos vérifications d'identité avec invalid date_of_birth depuis le nouveau client. Le client est src/kyc/client.py",
        es="⟦p⟧ rechaza más o menos la mitad de las verificaciones de identidad con invalid date_of_birth desde el cliente nuevo. El cliente está en src/kyc/client.py"),
        p=x.ent(provider)))
    d.agent(say(d, "look_first", x="src/kyc/client.py"))
    code = lines(
        "import requests",
        "",
        "from .config import settings",
        "",
        "TIMEOUT = 15",
        "",
        "",
        "def build_payload(customer, document) -> dict:",
        "    return {",
        "        \"reference\": customer.customer_no,",
        "        \"first_name\": customer.given_name,",
        "        \"last_name\": customer.family_name,",
        "        \"date_of_birth\": customer.birth_date.strftime(\"%d/%m/%Y\"),",
        "        \"nationality\": customer.nationality,",
        "        \"national_id\": customer.national_id,",
        "        \"address\": {",
        "            \"line1\": customer.street,",
        "            \"postcode\": customer.postcode,",
        "            \"city\": customer.city,",
        "            \"country\": customer.country,",
        "        },",
        "        \"document\": {",
        "            \"type\": document.kind,",
        "            \"number\": document.number,",
        "            \"issuing_country\": document.country,",
        "            \"expiry_date\": document.expiry.isoformat(),",
        "        },",
        "        \"images\": {\"front\": document.front_url, \"selfie\": document.selfie_url},",
        "    }",
        "",
        "",
        "def submit(customer, document):",
        "    resp = requests.post(",
        "        f\"{settings.KYC_BASE_URL}/checks\",",
        "        json=build_payload(customer, document),",
        "        headers={\"Authorization\": f\"Token token={settings.KYC_API_TOKEN}\"},",
        "        timeout=TIMEOUT,",
        "    )",
        "    resp.raise_for_status()",
        "    return resp.json()",
    )
    d.tool("read", "src/kyc/client.py", code)
    d.agent(d.L(en="The date is sent as DD/MM/YYYY. Let me look at what the provider answered for a few recent checks.",
                it="La data viene inviata come GG/MM/AAAA. Guardo cosa ha risposto il provider per qualche verifica recente.",
                de="Das Datum geht als TT/MM/JJJJ raus. Ich schaue mir die Antworten des Anbieters zu ein paar aktuellen Prüfungen an.",
                fr="La date part au format JJ/MM/AAAA. Je regarde ce que le prestataire a répondu pour quelques vérifications récentes.",
                es="La fecha se envía como DD/MM/AAAA. Miro qué respondió el proveedor en algunas verificaciones recientes."))
    recs = []
    n = r.choice([1, 2, 2, 3, 3, 4, 5, 7, 9])
    pc = _Past(d, 2, 70)
    swapped_case = r.randint(0, n - 1)
    for i in range(n):
        p = d.person()
        if i == swapped_case:
            p.birth = p.birth.replace(day=r.randint(1, 12))
            if p.birth.month == p.birth.day:
                p.birth = p.birth.replace(month=(p.birth.month % 12) + 1)
        else:
            p.birth = p.birth.replace(day=r.randint(13, 28))
        cno = V.customer_no(r)
        kind, nid = g.natid(p)
        expiry = d.clock.t.date() + dt.timedelta(days=r.randint(200, 3000))
        bucket = f"{d.slug}-kyc-uploads"
        imgs = {}
        for side in ("front", "selfie"):
            imgs[side] = _purl(d, f"https://{bucket}.s3.eu-central-1.amazonaws.com/{cno}/{side}_{V.rand_str(r, V.HEX, 8)}.jpg"
                                  f"?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=900&X-Amz-Signature={V.rand_str(r, V.HEX, 64)}")
        req = {
            "reference": _acct(d, cno),
            "first_name": g.name(p, "given"),
            "last_name": g.name(p, "family"),
            "date_of_birth": g.birth(p, "eu"),
            "nationality": p.country,
            "national_id": nid,
            "address": {"line1": g.addr(p, "street_full"), "postcode": g.addr(p, "postcode"),
                        "city": g.addr(p, "city"), "country": p.country},
            "document": {"type": "passport", "number": g.passport(p), "issuing_country": p.country,
                         "expiry_date": g.date(expiry, "iso", p)},
            "images": imgs,
        }
        if i == swapped_case:
            wrong = dt.date(p.birth.year, p.birth.day, p.birth.month)
            resp = {"status": "consider", "check_id": x.uuid(),
                    "reasons": [{"field": "date_of_birth", "code": "mismatch_with_document",
                                 "detail": _Q("parsed ", g.date(wrong, "iso", p), ", document MRZ says ", g.birth(p, "iso"))}]}
        else:
            resp = {"status": "rejected", "check_id": x.uuid(),
                    "reasons": [{"field": "date_of_birth", "code": "invalid_format",
                                 "detail": "expected YYYY-MM-DD or MM/DD/YYYY"}]}
        recs.append(_jl({"ts": x.ts("iso_z", t=pc.tick(60, 4000)), "request": req, "response": resp,
                         "http_status": 200 if i == swapped_case else 422, "duration_ms": r.randint(300, 2400)}))
    d.tool("sh", "grep -E '\"status\":\"(rejected|consider)\"' logs/kyc-checks.jsonl | tail -n " + str(n), lines(*recs))
    d.agent(say(d, "explain"), "\n",
            d.L(en="The provider accepts ISO dates and, as a fallback, US-style MM/DD/YYYY. Every birthday after the 12th of the month is an impossible month → rejected. Birthdays on or before the 12th are silently parsed with day and month swapped and then fail the document cross-check (`consider`). Sending ISO 8601 fixes both.",
                it="Il provider accetta date ISO e, come ripiego, il formato USA MM/GG/AAAA. Ogni compleanno dopo il 12 del mese diventa un mese impossibile → rifiutato. Quelli fino al 12 vengono letti in silenzio con giorno e mese invertiti e poi falliscono il controllo con il documento (`consider`). Inviare ISO 8601 risolve entrambi i casi.",
                de="Der Anbieter akzeptiert ISO-Daten und ersatzweise US-Format MM/TT/JJJJ. Jeder Geburtstag nach dem 12. ergibt einen unmöglichen Monat → abgelehnt. Geburtstage bis zum 12. werden still mit vertauschtem Tag und Monat gelesen und scheitern dann am Dokumentabgleich (`consider`). ISO 8601 löst beides.",
                fr="Le prestataire accepte les dates ISO et, à défaut, le format américain MM/JJ/AAAA. Tout anniversaire après le 12 du mois donne un mois impossible → rejeté. Ceux jusqu'au 12 sont lus silencieusement avec jour et mois inversés, puis échouent au contrôle du document (`consider`). Envoyer de l'ISO 8601 règle les deux cas.",
                es="El proveedor acepta fechas ISO y, como alternativa, el formato estadounidense MM/DD/AAAA. Cualquier cumpleaños después del día 12 da un mes imposible → rechazado. Los del 1 al 12 se leen en silencio con día y mes cambiados y luego fallan el cotejo con el documento (`consider`). Enviar ISO 8601 arregla ambos casos."))
    d.tool("edit", "src/kyc/client.py", lines(
        "-        \"date_of_birth\": customer.birth_date.strftime(\"%d/%m/%Y\"),",
        "+        \"date_of_birth\": customer.birth_date.isoformat(),  # provider expects YYYY-MM-DD"))
    if r.random() < 0.7:
        d.tool("write", "tests/kyc/test_payload.py", lines(
            "import datetime as dt",
            "",
            "from kyc.client import build_payload",
            "",
            "",
            "def test_birth_date_is_iso(customer_factory, passport_factory):",
            "    c = customer_factory(birth_date=dt.date(1990, 3, 25))",
            "    assert build_payload(c, passport_factory())[\"date_of_birth\"] == \"1990-03-25\""))
    d.tool("sh", "pytest tests/kyc -q", lines(
        T("⟦n⟧ passed in ⟦s⟧s", n=x.num(lo=6, hi=24), s=f"{r.uniform(0.4, 3.5):.2f}")))
    if r.random() < 0.6:
        d.user(d.L(en="how many checks do we need to resubmit?", it="quante verifiche dobbiamo reinviare?",
                   de="wie viele Prüfungen müssen wir neu einreichen?", fr="combien de vérifications faut-il renvoyer ?",
                   es="¿cuántas verificaciones hay que reenviar?"))
        d.tool("sh", "psql \"$REPLICA_URL\" -Atc \"select status, count(*) from kyc_checks where created_at > '2025-01-01' and client_version = '2' group by 1\"",
               lines(F("rejected|", x.num(lo=300, hi=900)), F("consider|", x.num(lo=150, hi=420)),
                     F("approved|", x.num(lo=8, hi=60))))
        d.agent(d.L(en="Both the `rejected` and the `consider` rows from the new client need resubmitting; the approved ones had the same day and month, so they are fine.",
                    it="Vanno reinviate sia le righe `rejected` sia `consider` del nuovo client; le approvate avevano giorno e mese coincidenti, quindi sono a posto.",
                    de="Sowohl `rejected` als auch `consider` aus dem neuen Client sollten neu eingereicht werden; die genehmigten hatten identischen Tag und Monat und sind in Ordnung.",
                    fr="Il faut renvoyer les lignes `rejected` et `consider` du nouveau client ; les approuvées avaient jour et mois identiques, elles sont correctes.",
                    es="Hay que reenviar las filas `rejected` y `consider` del cliente nuevo; las aprobadas tenían día y mes iguales, así que están bien."))
    d.agent(say(d, "pii_warning"))


# ---------------------------------------------------------------- 7. CRM sync with cursor pagination


@template("rest_client_pagination", "box", "http", "shell")
def rest_client_pagination(d):
    g, x, r = d.g, d.x, d.rng
    crm = _host(d, "crm")
    base = f"https://{crm}/api/v3"
    total = r.randint(140, 620)
    page = 100
    hardcoded = r.random() < 0.45
    d.user(T(d.L(
        en="scripts/sync_contacts.py only ever imports the first 100 contacts from the CRM. We have ⟦n⟧ or so. Can you fix the pagination?",
        it="scripts/sync_contacts.py importa sempre solo i primi 100 contatti dal CRM. Ne abbiamo circa ⟦n⟧. Puoi sistemare la paginazione?",
        de="scripts/sync_contacts.py importiert immer nur die ersten 100 Kontakte aus dem CRM. Wir haben ungefähr ⟦n⟧. Kannst du die Paginierung reparieren?",
        fr="scripts/sync_contacts.py n'importe toujours que les 100 premiers contacts du CRM. On en a environ ⟦n⟧. Tu peux corriger la pagination ?",
        es="scripts/sync_contacts.py solo importa los primeros 100 contactos del CRM. Tenemos unos ⟦n⟧. ¿Puedes arreglar la paginación?"),
        n=str(round(total, -1))))
    key_line = (T("API_KEY = \"⟦k⟧\"  # TODO move to env", k=_sec(d, "bearer_opaque", "key")) if hardcoded
                else F("API_KEY = os.environ[\"CRM_API_KEY\"]"))
    code = lines(
        "import os",
        "import sys",
        "",
        "import requests",
        "",
        "from app.db import upsert_contact",
        "",
        T("API = \"⟦u⟧\"", u=_purl(d, base)),
        key_line,
        "HEADERS = {\"X-Api-Key\": API_KEY, \"Accept\": \"application/json\"}",
        "",
        "",
        "def fetch_contacts():",
        "    resp = requests.get(f\"{API}/contacts\", params={\"limit\": 100}, headers=HEADERS, timeout=30)",
        "    resp.raise_for_status()",
        "    return resp.json()[\"results\"]",
        "",
        "",
        "def main(dry_run=False, verbose=False):",
        "    contacts = fetch_contacts()",
        "    for c in contacts:",
        "        if verbose:",
        "            print(f\"  - {c['name']} <{c['email']}> {c.get('phone') or ''}\")",
        "        if not dry_run:",
        "            upsert_contact(c)",
        "    print(f\"done: {'would import' if dry_run else 'imported'} {len(contacts)} contacts\")",
        "",
        "",
        "if __name__ == \"__main__\":",
        "    main(dry_run=\"--dry-run\" in sys.argv, verbose=\"--verbose\" in sys.argv)",
    )
    d.tool("read", "scripts/sync_contacts.py", code)
    if hardcoded and d.secret_ok:
        d.agent(say(d, "secret_warning", x="scripts/sync_contacts.py"))

    def contact_line(p) -> list:
        return F("  - ", g.name(p), " <", g.email(p, r.choice(["work", "personal"]), domain=r.choice(
            ["acme-retail.de", "bottega-verdi.it", "maison-carre.fr", "northfield-ltd.co.uk", "tallerluna.es"])),
            "> ", g.phone(p) if r.random() < 0.8 else "")

    shown = [contact_line(d.person()) for _ in range(r.randint(3, 10))]
    d.tool("sh", "python scripts/sync_contacts.py --dry-run --verbose | tail -n " + str(len(shown) + 1),
           lines(*shown, "done: would import 100 contacts"))
    d.agent(d.L(en="Exactly one page. Let me see how the API signals the next one.",
                it="Esattamente una pagina. Vediamo come l'API segnala la successiva.",
                de="Genau eine Seite. Mal sehen, wie die API die nächste ankündigt.",
                fr="Exactement une page. Voyons comment l'API signale la suivante.",
                es="Exactamente una página. Veamos cómo indica la API la siguiente."))
    cursor = V.b64url(json.dumps({"after": r.randint(10**5, 10**7), "ts": int(d.clock.t.timestamp())}).encode())
    next_url = _purl(d, f"{base}/contacts?limit=100&cursor={cursor}")
    reset = d.clock.t + dt.timedelta(seconds=r.randint(20, 60))
    hdr = lines(
        "HTTP/2 200",
        T("date: ⟦t⟧", t=x.ts("http", tick=(30, 200))),
        "content-type: application/json",
        T("x-total-count: ⟦n⟧", n=str(total)),
        T("x-ratelimit-limit: ⟦n⟧", n=x.num(r.choice([60, 120, 600]))),
        T("x-ratelimit-remaining: ⟦n⟧", n=x.num(lo=1, hi=58)),
        T("x-ratelimit-reset: ⟦t⟧", t=x.ts("epoch", t=reset)),
        T("link: <⟦u⟧>; rel=\"next\"", u=next_url),
        T("x-request-id: ⟦i⟧", i=x.rid()),
    )
    d.tool("sh", F("curl -s -D - -o /dev/null -H \"X-Api-Key: $CRM_API_KEY\" '", _purl(d, f"{base}/contacts?limit=100"), "'"),
           hdr)
    d.agent(say(d, "explain"), "\n",
            d.L(en="The API uses cursor pagination through the `Link` header (rel=\"next\"); the script never follows it. The rate limit is low, so the loop should also back off when `x-ratelimit-remaining` hits zero.",
                it="L'API usa una paginazione a cursore tramite l'header `Link` (rel=\"next\"); lo script non lo segue mai. Il rate limit è basso, quindi il ciclo deve anche fermarsi quando `x-ratelimit-remaining` arriva a zero.",
                de="Die API paginiert per Cursor über den `Link`-Header (rel=\"next\"); das Skript folgt ihm nie. Das Rate-Limit ist niedrig, also sollte die Schleife auch pausieren, wenn `x-ratelimit-remaining` auf null fällt.",
                fr="L'API pagine par curseur via l'en-tête `Link` (rel=\"next\") ; le script ne le suit jamais. La limite de débit est basse, la boucle doit donc aussi patienter quand `x-ratelimit-remaining` tombe à zéro.",
                es="La API pagina con cursor mediante la cabecera `Link` (rel=\"next\"); el script nunca la sigue. El rate limit es bajo, así que el bucle también debe esperar cuando `x-ratelimit-remaining` llegue a cero."),
            "\n", x.url("docs", "https://requests.readthedocs.io/en/latest/user/advanced/#link-headers"))
    edit = lines(
        "-def fetch_contacts():",
        "-    resp = requests.get(f\"{API}/contacts\", params={\"limit\": 100}, headers=HEADERS, timeout=30)",
        "-    resp.raise_for_status()",
        "-    return resp.json()[\"results\"]",
        "+def fetch_contacts(verbose=False):",
        "+    url, params = f\"{API}/contacts\", {\"limit\": 100}",
        "+    page = 0",
        "+    while url:",
        "+        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)",
        "+        resp.raise_for_status()",
        "+        page += 1",
        "+        results = resp.json()[\"results\"]",
        "+        if verbose:",
        "+            print(f\"page {page}: {len(results)} contacts\", file=sys.stderr)",
        "+        yield from results",
        "+        if int(resp.headers.get(\"x-ratelimit-remaining\", 1)) == 0:",
        "+            time.sleep(max(0, int(resp.headers[\"x-ratelimit-reset\"]) - time.time()) + 1)",
        "+        url, params = resp.links.get(\"next\", {}).get(\"url\"), None",
    )
    d.agent(say(d, "applying"))
    d.tool("edit", "scripts/sync_contacts.py", edit)
    pages = -(-total // page)
    out = []
    shown_per_page = r.randint(1, 8)
    for i in range(pages):
        n = page if i < pages - 1 else total - page * (pages - 1)
        out.append(F(f"page {i + 1}: {n} contacts"))
        if i < 3:
            out += [contact_line(d.person()) for _ in range(shown_per_page)]
    out.append(F(f"done: would import {total} contacts"))
    d.tool("sh", "python scripts/sync_contacts.py --dry-run --verbose 2>&1 | grep -v '^  - ' | head; "
                 "python scripts/sync_contacts.py --dry-run --verbose 2>&1 | grep '^  - ' | shuf -n 5",
           lines(*out))
    d.agent(say(d, "done"), "\n",
            d.L(en=f"- follows `Link: rel=\"next\"` until the last page ({pages} pages, {total} contacts in the dry run)\n- waits for the rate-limit reset when the quota is exhausted",
                it=f"- segue `Link: rel=\"next\"` fino all'ultima pagina ({pages} pagine, {total} contatti nel dry run)\n- aspetta il reset del rate limit quando la quota è esaurita",
                de=f"- folgt `Link: rel=\"next\"` bis zur letzten Seite ({pages} Seiten, {total} Kontakte im Dry-Run)\n- wartet auf den Rate-Limit-Reset, wenn das Kontingent aufgebraucht ist",
                fr=f"- suit `Link: rel=\"next\"` jusqu'à la dernière page ({pages} pages, {total} contacts en dry run)\n- attend la réinitialisation de la limite quand le quota est épuisé",
                es=f"- sigue `Link: rel=\"next\"` hasta la última página ({pages} páginas, {total} contactos en el dry run)\n- espera al reinicio del rate limit cuando se agota la cuota"))
    if hardcoded:
        d.user(say(d, "rotate_later"))


# ---------------------------------------------------------------- 8. Slack events signature verification


@template("webhook_signature_slack", "hai", "http", "file")
def webhook_signature_slack(d):
    g, x, r = d.g, d.x, d.rng
    d.user(d.L(
        en="Our Slack bot stopped answering mentions after the refactor of the events endpoint. The app dashboard shows lots of failed requests. Can you check bot/slack_events.py?",
        it="Il nostro bot Slack non risponde più alle menzioni dopo il refactoring dell'endpoint degli eventi. La dashboard dell'app mostra tante richieste fallite. Puoi guardare bot/slack_events.py?",
        de="Unser Slack-Bot reagiert seit dem Refactoring des Events-Endpunkts nicht mehr auf Erwähnungen. Das App-Dashboard zeigt viele fehlgeschlagene Requests. Kannst du dir bot/slack_events.py ansehen?",
        fr="Notre bot Slack ne répond plus aux mentions depuis le refactoring de l'endpoint des événements. Le tableau de bord de l'app montre plein de requêtes en échec. Tu peux regarder bot/slack_events.py ?",
        es="Nuestro bot de Slack dejó de responder a las menciones tras refactorizar el endpoint de eventos. El panel de la app muestra muchas peticiones fallidas. ¿Puedes mirar bot/slack_events.py?"))
    code = lines(
        "import hashlib",
        "import hmac",
        "import json",
        "import os",
        "import time",
        "",
        "from flask import Flask, abort, request",
        "",
        "from .handlers import dispatch",
        "",
        "app = Flask(__name__)",
        "SIGNING_SECRET = os.environ[\"SLACK_SIGNING_SECRET\"].encode()",
        "",
        "",
        "def verify(req):",
        "    ts = req.headers.get(\"X-Slack-Request-Timestamp\", \"0\")",
        "    if abs(time.time() - int(ts)) > 60 * 5:",
        "        abort(401)",
        "    body = json.dumps(req.get_json(), separators=(\",\", \":\"))",
        "    base = f\"v0:{ts}:{body}\".encode()",
        "    expected = \"v0=\" + hmac.new(SIGNING_SECRET, base, hashlib.sha256).hexdigest()",
        "    if not hmac.compare_digest(expected, req.headers.get(\"X-Slack-Signature\", \"\")):",
        "        app.logger.warning(\"signature mismatch ts=%s sig=%s\", ts, req.headers.get(\"X-Slack-Signature\"))",
        "        abort(401)",
        "",
        "",
        "@app.post(\"/slack/events\")",
        "def events():",
        "    verify(request)",
        "    payload = request.get_json()",
        "    if payload.get(\"type\") == \"url_verification\":",
        "        return {\"challenge\": payload[\"challenge\"]}",
        "    dispatch(payload[\"event\"])",
        "    return \"\", 200",
    )
    short = r.random() < 0.35
    if short:
        d.tool("grep", "-n -A4 'def verify' bot/slack_events.py", lines(
            F(x.num(15), ":def verify(req):"),
            F(x.num(16), "-    ts = req.headers.get(\"X-Slack-Request-Timestamp\", \"0\")"),
            F(x.num(17), "-    if abs(time.time() - int(ts)) > 60 * 5:"),
            F(x.num(18), "-        abort(401)"),
            F(x.num(19), "-    body = json.dumps(req.get_json(), separators=(\",\", \":\"))")))
    else:
        d.tool("read", "bot/slack_events.py", numbered(code))
    if not short and r.random() < 0.7:
        d.tool("read", ".env", lines(
            T("SLACK_SIGNING_SECRET=⟦s⟧", s=g.raw("secret", V.rand_str(r, V.HEX, 32), "api_key")),
            T("SLACK_BOT_TOKEN=⟦s⟧", s=g.secret("slack_bot")),
            T("BOT_OWNER=⟦h⟧", h=g.handle(d.me)),
            "FLASK_ENV=production"))
    bot_uid = "U0" + V.rand_str(r, V.UPPER + "0123456789", 9)
    asker = d.person()
    subject = d.person()
    log = []
    team = "T0" + V.rand_str(r, V.UPPER + "0123456789", 9)
    app_id = "A0" + V.rand_str(r, V.UPPER + "0123456789", 9)
    uid = ""
    pc = _Past(d, 0.5, 12)
    for _ in range(1 if short else r.randint(2, 5)):
        t = pc.tick(20, 900)
        evt_ts = f"{int(t.timestamp())}.{r.randint(100000, 999999)}"
        uid = "U0" + V.rand_str(r, V.UPPER + "0123456789", 9)
        mention = F("<@", x.id(bot_uid), "> ")
        text = r.choice([
            F(mention, "can you pull the last invoice for ", g.name(subject), "?"),
            F(mention, "status of ticket ", x.id(f"SUP-{r.randint(1000, 9999)}"), " please"),
            F(mention, "who is on call this week?"),
            F(mention, "add ", g.email(subject, "personal"), " to the beta list"),
        ])
        payload = {"token": g.raw("secret", V.rand_str(r, V.ALNUM, 24), "api_key"),
                   "team_id": x.id(team), "api_app_id": x.id(app_id),
                   "event": {"type": "app_mention", "user": x.id(uid), "text": _Q(text),
                             "ts": Seg(evt_ts, cls="machine_timestamp"),
                             "channel": x.id("C0" + V.rand_str(r, V.UPPER + "0123456789", 9))},
                   "type": "event_callback", "event_id": x.id("Ev0" + V.rand_str(r, V.UPPER + "0123456789", 9)),
                   "event_time": _Raw(x.ts("epoch", t=t))}
        log.append(F(x.ts("space_ms", t=t), " DEBUG bot.slack_events: payload=", _jl(payload)))
        log.append(F(x.ts("space_ms", t=pc.tick(0, 0.01)), " WARNING bot.slack_events: signature mismatch ts=",
                     x.ts("epoch", t=t), " sig=v0=", x.id(V.rand_str(r, V.HEX, 64))))
        log.append(F(x.ts("space_ms", t=pc.tick(0, 0.01)), " INFO werkzeug: ", g.ip("private"), " - - [",
                     x.ts("clf", t=t), "] \"POST /slack/events HTTP/1.1\" 401 -"))
    d.tool("sh", "tail -n " + str(len(log)) + " logs/bot.log", lines(*log))
    d.agent(say(d, "explain"), "\n",
            d.L(en="Slack signs the raw request body. `verify()` re-serialises the parsed JSON, which changes the bytes: different spacing, key order, and `json.dumps` escapes every non-ASCII character (names with accents, emoji) as \\uXXXX. The HMAC can never match. It must hash `request.get_data()` exactly as received.",
                it="Slack firma il body grezzo della richiesta. `verify()` riserializza il JSON già parsato, cambiando i byte: spaziatura, ordine delle chiavi, e `json.dumps` trasforma ogni carattere non ASCII (nomi accentati, emoji) in \\uXXXX. L'HMAC non può mai combaciare. Bisogna firmare `request.get_data()` così come arriva.",
                de="Slack signiert den rohen Request-Body. `verify()` serialisiert das geparste JSON neu und verändert damit die Bytes: Abstände, Schlüsselreihenfolge, und `json.dumps` maskiert jedes Nicht-ASCII-Zeichen (Namen mit Umlauten, Emoji) als \\uXXXX. Der HMAC kann nie passen. Es muss `request.get_data()` genau wie empfangen gehasht werden.",
                fr="Slack signe le corps brut de la requête. `verify()` resérialise le JSON parsé, ce qui change les octets : espaces, ordre des clés, et `json.dumps` échappe chaque caractère non ASCII (noms accentués, emoji) en \\uXXXX. Le HMAC ne peut jamais correspondre. Il faut hacher `request.get_data()` tel que reçu.",
                es="Slack firma el body en crudo. `verify()` vuelve a serializar el JSON ya parseado y cambia los bytes: espacios, orden de claves, y `json.dumps` escapa cada carácter no ASCII (nombres con tildes, emoji) como \\uXXXX. El HMAC nunca coincide. Hay que firmar `request.get_data()` tal cual llega."),
            "\n", x.url("docs", "https://api.slack.com/authentication/verifying-requests-from-slack"))
    d.tool("edit", "bot/slack_events.py", lines(
        "-    body = json.dumps(req.get_json(), separators=(\",\", \":\"))",
        "+    body = req.get_data(as_text=True)  # the exact bytes Slack signed"))
    if not short:
        d.tool("sh", "pytest tests/test_verify.py -q", lines(
            T("⟦n⟧ passed in ⟦s⟧s", n=x.num(lo=3, hi=9), s=f"{r.uniform(0.1, 0.9):.2f}")))
    if not short and r.random() < 0.6:
        d.user(d.L(en="while you're there: the 'invoice for <name>' command can't find people with accents. Check what users.info returns for the asker",
                   it="già che ci sei: il comando 'fattura per <nome>' non trova le persone con gli accenti. Guarda cosa restituisce users.info per chi ha chiesto",
                   de="wo du gerade dabei bist: der Befehl 'Rechnung für <Name>' findet keine Leute mit Umlauten. Schau, was users.info für den Fragenden liefert",
                   fr="tant que tu y es : la commande 'facture pour <nom>' ne trouve pas les personnes avec des accents. Regarde ce que renvoie users.info pour l'auteur",
                   es="ya que estás: el comando 'factura de <nombre>' no encuentra a gente con tildes. Mira qué devuelve users.info para quien preguntó"))
        info = {"ok": True, "user": {
            "id": x.id(uid), "team_id": x.id(team),
            "name": g.user(asker), "real_name": g.name(asker),
            "tz": r.choice(["Europe/Rome", "Europe/Berlin", "Europe/Paris", "Europe/Madrid", "Europe/London"]),
            "profile": {"title": r.choice(["Account Manager", "Support Lead", "Backoffice", "Finance"]),
                        "phone": g.phone(asker), "real_name": g.name(asker), "display_name": g.name(asker, "given"),
                        "email": g.email(asker, "work")},
            "is_admin": False, "updated": _Raw(x.ts("epoch", tick=(0, 0)))}}
        d.tool("sh", F("curl -s -H \"Authorization: Bearer $SLACK_BOT_TOKEN\" \"", x.url(text="https://slack.com/api/users.info"),
                       "?user=", x.id(uid), "\" | jq ."), _js(info))
        d.agent(d.L(en="users.info returns the name in Unicode as expected; the lookup in handlers/invoice.py compares against an ASCII-folded column. I'll normalise both sides with NFKD before comparing.",
                    it="users.info restituisce il nome in Unicode come previsto; la ricerca in handlers/invoice.py confronta con una colonna senza accenti. Normalizzo entrambi i lati con NFKD prima del confronto.",
                    de="users.info liefert den Namen wie erwartet in Unicode; die Suche in handlers/invoice.py vergleicht mit einer ASCII-gefalteten Spalte. Ich normalisiere beide Seiten vor dem Vergleich mit NFKD.",
                    fr="users.info renvoie bien le nom en Unicode ; la recherche dans handlers/invoice.py compare avec une colonne sans accents. Je normalise les deux côtés en NFKD avant la comparaison.",
                    es="users.info devuelve el nombre en Unicode como se espera; la búsqueda en handlers/invoice.py compara con una columna sin tildes. Normalizo ambos lados con NFKD antes de comparar."))
    d.agent(say(d, "not_committed"))


# ---------------------------------------------------------------- 9. Postman environment + newman in CI


@template("postman_collection_env", "irc", "http", "file")
def postman_collection_env(d):
    g, x, r = d.g, d.x, d.rng
    cause = r.choice(["disabled", "slash"])
    api = _host(d, "partner-api")
    base = f"https://{api}" + ("/" if cause == "slash" else "")
    cust = d.person()
    cid = V.customer_no(r)
    d.user(d.L(
        en="newman run of the partner API collection fails in CI, but the same collection works in Postman desktop. Env file is postman/staging.postman_environment.json",
        it="newman sulla collection della partner API fallisce in CI, ma la stessa collection funziona in Postman desktop. Il file d'ambiente è postman/staging.postman_environment.json",
        de="newman mit der Partner-API-Collection schlägt im CI fehl, in Postman Desktop läuft dieselbe Collection. Environment-Datei: postman/staging.postman_environment.json",
        fr="newman sur la collection de l'API partenaire échoue en CI, alors que la même collection marche dans Postman desktop. Le fichier d'environnement est postman/staging.postman_environment.json",
        es="newman con la colección de la API de partners falla en CI, pero la misma colección funciona en Postman escritorio. El entorno está en postman/staging.postman_environment.json"))
    env = {
        "id": x.uuid(),
        "name": "staging",
        "values": [
            {"key": "baseUrl", "value": _purl(d, base), "type": "default", "enabled": True},
            {"key": "apiKey", "value": _sec(d, "bearer_opaque", "key"), "type": "secret", "enabled": cause != "disabled"},
            {"key": "clientId", "value": "partner-portal", "type": "default", "enabled": True},
            {"key": "adminUser", "value": g.email(d.me, "work"), "type": "default", "enabled": True},
            {"key": "adminPassword", "value": g.password(), "type": "secret", "enabled": True},
            {"key": "customerId", "value": _acct(d, cid), "type": "default", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_at": x.ts("iso_z", t=d.clock.t - dt.timedelta(days=r.randint(1, 60))),
        "_postman_exported_using": _Q("Postman/", x.ver(r.choice(["10.24.3", "11.2.1", "10.18.6"]))),
    }
    d.tool("read", "postman/staging.postman_environment.json", _js(env, indent=r.choice([2, 4])))
    d.agent(say(d, "check_next", x="newman --verbose"))
    prefix = base.rstrip("/") + ("//" if cause == "slash" else "/")
    tok_url = _purl(d, prefix + "oauth/token")
    cust_path = _purl(d, f"{prefix}v1/customers/{cid}")
    out = [F("newman"), F(""), F("Partner API"), F(""), F("→ Auth / get token")]
    if cause == "disabled":
        out += [F("  POST ", tok_url, " [401 Unauthorized, 212B, ", str(r.randint(30, 120)), "ms]"),
                F("  ┌"), F("  │ ", _jl({"error": "invalid_client", "error_description": "missing X-Api-Key"})),
                F("  └"), F("  1. status is 200")]
    else:
        out += [F("  POST ", tok_url, " [404 Not Found, 153B, ", str(r.randint(30, 120)), "ms]"),
                F("  ┌"), F("  │ ", _jl({"timestamp": x.ts("iso_z", tick=(1, 2)), "status": 404, "error": "Not Found",
                                         "path": "//oauth/token"})),
                F("  └"), F("  1. status is 200")]
    out += [F(""), F("→ Customers / get customer"),
            F("  GET ", cust_path, " [401 Unauthorized, 98B, ", str(r.randint(20, 90)), "ms]"),
            F("  2. status is 200"), F("  3. body has email")]
    out += [F(""), F("┌─────────────────────────┬───────────────────┬──────────────────┐"),
            F("│                         │          executed │           failed │"),
            F("├─────────────────────────┼───────────────────┼──────────────────┤"),
            F("│              iterations │                 1 │                0 │"),
            F("│                requests │                 2 │                0 │"),
            F("│            test-scripts │                 2 │                0 │"),
            F("│              assertions │                 3 │                3 │"),
            F("└─────────────────────────┴───────────────────┴──────────────────┘")]
    d.tool("sh", "npx newman run postman/partner-api.postman_collection.json -e postman/staging.postman_environment.json --verbose",
           lines(*out))
    if cause == "disabled":
        d.agent(say(d, "explain"), " ",
                d.L(en="`apiKey` is exported with `\"enabled\": false`. Postman desktop still resolves it from your local session value, newman doesn't, so the token request goes out without X-Api-Key.",
                    it="`apiKey` è esportata con `\"enabled\": false`. Postman desktop la risolve comunque dal valore locale della tua sessione, newman no, quindi la richiesta del token parte senza X-Api-Key.",
                    de="`apiKey` ist mit `\"enabled\": false` exportiert. Postman Desktop nimmt trotzdem deinen lokalen Session-Wert, newman nicht – der Token-Request geht also ohne X-Api-Key raus.",
                    fr="`apiKey` est exportée avec `\"enabled\": false`. Postman desktop la résout quand même depuis ta valeur de session locale, newman non, donc la requête de token part sans X-Api-Key.",
                    es="`apiKey` se exportó con `\"enabled\": false`. Postman escritorio la resuelve igualmente con tu valor local, newman no, así que la petición del token sale sin X-Api-Key."))
        d.tool("edit", "postman/staging.postman_environment.json", lines(
            "       \"key\": \"apiKey\",", "@@", "-      \"enabled\": false", "+      \"enabled\": true"))
    else:
        d.agent(say(d, "explain"), " ",
                d.L(en="`baseUrl` ends with a slash and the requests are written as `{{baseUrl}}/oauth/token`, so newman sends `//oauth/token`. The desktop app normalises the double slash, the gateway doesn't.",
                    it="`baseUrl` finisce con uno slash e le richieste sono scritte come `{{baseUrl}}/oauth/token`, quindi newman invia `//oauth/token`. L'app desktop normalizza il doppio slash, il gateway no.",
                    de="`baseUrl` endet mit einem Slash, die Requests lauten `{{baseUrl}}/oauth/token` – newman schickt also `//oauth/token`. Die Desktop-App normalisiert den doppelten Slash, das Gateway nicht.",
                    fr="`baseUrl` se termine par un slash et les requêtes s'écrivent `{{baseUrl}}/oauth/token`, donc newman envoie `//oauth/token`. L'application desktop normalise le double slash, la passerelle non.",
                    es="`baseUrl` termina en barra y las peticiones son `{{baseUrl}}/oauth/token`, así que newman envía `//oauth/token`. La app de escritorio normaliza la doble barra, el gateway no."))
        d.tool("edit", "postman/staging.postman_environment.json", lines(
            T("-      \"value\": \"⟦u⟧\",", u=_purl(d, base)), T("+      \"value\": \"⟦u⟧\",", u=_purl(d, base.rstrip("/")))))
    d.user(say(d, "go_ahead"))
    order_n = r.randint(1, 4)
    body = {"id": _acct(d, cid), "name": g.name(cust), "email": g.email(cust, "personal"), "phone": g.phone(cust),
            "billing": {"street": g.addr(cust, "street_full"), "postcode": g.addr(cust, "postcode"),
                        "city": g.addr(cust, "city"), "country": cust.country},
            "openOrders": order_n, "updatedAt": x.ts("iso_z", t=d.clock.t - dt.timedelta(hours=r.randint(1, 300)))}
    ok = [F("newman"), F(""), F("Partner API"), F(""), F("→ Auth / get token"),
          F("  POST ", _purl(d, base.rstrip("/") + "/oauth/token"), " [200 OK, 1.1kB, ", str(r.randint(80, 400)), "ms]"),
          F("  ✓  status is 200"), F(""), F("→ Customers / get customer"),
          F("  GET ", _purl(d, f"{base.rstrip('/')}/v1/customers/{cid}"), " [200 OK, 734B, ", str(r.randint(20, 200)), "ms]"),
          F("  ┌"), F("  │ ", _jl(body)), F("  └"), F("  ✓  status is 200"), F("  ✓  body has email"), F(""),
          F("┌─────────────────────────┬───────────────────┬──────────────────┐"),
          F("│              assertions │                 3 │                0 │"),
          F("└─────────────────────────┴───────────────────┴──────────────────┘")]
    d.tool("sh", "npx newman run postman/partner-api.postman_collection.json -e postman/staging.postman_environment.json --verbose",
           lines(*ok))
    d.agent(say(d, "tests_pass"), " ",
            d.L(en="Note that the environment file stores the admin password and the API key in clear text; in CI they should come from `--env-var` with masked secrets instead.",
                it="Nota che il file d'ambiente contiene password admin e API key in chiaro; in CI dovrebbero arrivare da `--env-var` con segreti mascherati.",
                de="Beachte, dass die Environment-Datei Admin-Passwort und API-Key im Klartext enthält; im CI sollten sie per `--env-var` aus maskierten Secrets kommen.",
                fr="Note que le fichier d'environnement contient le mot de passe admin et la clé d'API en clair ; en CI ils devraient venir de `--env-var` avec des secrets masqués.",
                es="Ojo: el fichero de entorno guarda la contraseña de admin y la API key en claro; en CI deberían venir de `--env-var` con secretos enmascarados."))


# ---------------------------------------------------------------- 10. SOAP policy lookup (insurance)

_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
_WSU_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"


@template("soap_xml_insurance", "react", "http", "file")
def soap_xml_insurance(d):
    g, x, r = d.g, d.x, d.rng
    holder = d.person()
    second = d.person(holder.locale) if r.random() < 0.5 else None
    insurer = r.choice(["Allianz", "Generali", "AXA", "Zurich", "Mapfre", "HDI", "Unipol"])
    ns = f"urn:{d.slug}:insurer-gw:policy"
    endpoint = _purl(d, f"https://{_host(d, 'b2b')}/insurer-gw/PolicyService/v3")
    policy_no = f"{r.choice(['POL', 'AUT', 'RCA', 'KFZ'])}-{r.randint(10**7, 10**8 - 1)}"
    _, nid = g.natid(holder)
    make, model = r.choice([("Fiat", "Panda"), ("Volkswagen", "Golf"), ("Renault", "Clio"), ("Toyota", "Yaris"),
                            ("Tesla", "Model 3")])
    d.user(T(d.L(
        en="Policy lookups against the ⟦i⟧ SOAP service fail with a SOAP fault since they published the v3 WSDL. A captured request is in integration/samples/get_policy.xml",
        it="Le ricerche polizza sul servizio SOAP di ⟦i⟧ falliscono con un SOAP fault da quando hanno pubblicato il WSDL v3. Una richiesta catturata è in integration/samples/get_policy.xml",
        de="Policenabfragen gegen den SOAP-Service von ⟦i⟧ scheitern mit einem SOAP-Fault, seit dort das v3-WSDL veröffentlicht wurde. Ein mitgeschnittener Request liegt in integration/samples/get_policy.xml",
        fr="Les recherches de contrat sur le service SOAP de ⟦i⟧ échouent avec un SOAP fault depuis la publication du WSDL v3. Une requête capturée est dans integration/samples/get_policy.xml",
        es="Las consultas de póliza al servicio SOAP de ⟦i⟧ fallan con un SOAP fault desde que publicaron el WSDL v3. Hay una petición capturada en integration/samples/get_policy.xml"),
        i=x.ent(insurer)))
    d.agent(say(d, "look_first", x="integration/samples/get_policy.xml"))
    created = x.ts("iso_z", tick=(0, 0))
    nonce = x.id(V.b64url(bytes(r.randint(0, 255) for _ in range(16))) + "==")

    def holder_block(tag_tax: str, tag_birth: str) -> list:
        return lines(
            "      <pol:Holder>",
            T("        <pol:FamilyName>⟦f⟧</pol:FamilyName>", f=g.name(holder, "family")),
            T("        <pol:GivenName>⟦n⟧</pol:GivenName>", n=g.name(holder, "given")),
            T(f"        <pol:{tag_tax}>⟦t⟧</pol:{tag_tax}>", t=nid),
            T(f"        <pol:{tag_birth}>⟦b⟧</pol:{tag_birth}>", b=g.birth(holder, "iso")),
            "        <pol:Address>",
            T("          <pol:Street>⟦s⟧</pol:Street>", s=g.addr(holder, "street")),
            T("          <pol:PostalCode>⟦p⟧</pol:PostalCode>", p=g.addr(holder, "postcode")),
            T("          <pol:City>⟦c⟧</pol:City>", c=g.addr(holder, "city")),
            f"          <pol:Country>{holder.country}</pol:Country>",
            "        </pol:Address>",
            "      </pol:Holder>",
        )

    def envelope(version: str, tag_tax: str, tag_birth: str) -> list:
        return F(lines(
            T("<soapenv:Envelope xmlns:soapenv=\"⟦a⟧\" xmlns:pol=\"⟦n⟧\">", a=x.url(text=_SOAP_NS), n=f"{ns}:{version}"),
            "  <soapenv:Header>",
            T("    <wsse:Security xmlns:wsse=\"⟦w⟧\" xmlns:wsu=\"⟦u⟧\">", w=x.url(text=_WSSE_NS), u=x.url(text=_WSU_NS)),
            "      <wsse:UsernameToken>",
            f"        <wsse:Username>svc_{d.slug}_b2b</wsse:Username>",
            T("        <wsse:Password Type=\"#PasswordText\">⟦p⟧</wsse:Password>", p=pw),
            T("        <wsse:Nonce>⟦n⟧</wsse:Nonce>", n=nonce),
            T("        <wsu:Created>⟦c⟧</wsu:Created>", c=created),
            "      </wsse:UsernameToken>",
            "    </wsse:Security>",
            "  </soapenv:Header>",
            "  <soapenv:Body>",
            "    <pol:GetPolicyRequest>",
            T("      <pol:PolicyNumber>⟦p⟧</pol:PolicyNumber>", p=_acct(d, policy_no))),
            holder_block(tag_tax, tag_birth),
            lines("    </pol:GetPolicyRequest>", "  </soapenv:Body>", "</soapenv:Envelope>"))

    pw = g.password()
    d.tool("read", "integration/samples/get_policy.xml", envelope("v2", "TaxCode", "BirthDate"))
    d.agent(d.L(en="Replaying it against the gateway to get the exact fault.",
                it="La rimando al gateway per vedere il fault esatto.",
                de="Ich schicke ihn erneut ans Gateway, um den genauen Fault zu sehen.",
                fr="Je la rejoue contre la passerelle pour obtenir le fault exact.",
                es="La reenvío al gateway para ver el fault exacto."))
    d.call("sh", F("curl -s -X POST ", endpoint, " -H 'Content-Type: text/xml; charset=utf-8' -H 'SOAPAction: \"GetPolicy\"' "
                   "--data @integration/samples/get_policy.xml | xmllint --format -"))
    d.result("sh", lines(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        T("<soap:Envelope xmlns:soap=\"⟦a⟧\">", a=x.url(text=_SOAP_NS)),
        "  <soap:Body>",
        "    <soap:Fault>",
        "      <faultcode>soap:Client</faultcode>",
        f"      <faultstring>Unmarshalling Error: cvc-complex-type.2.4.a: Invalid content was found starting with element 'pol:TaxCode'. One of '{{\"{ns}:v3\":FiscalCode}}' is expected.</faultstring>",
        "      <detail>",
        f"        <ns2:ErrorInfo xmlns:ns2=\"{ns}:v3\">",
        T("          <ns2:TraceId>⟦t⟧</ns2:TraceId>", t=x.uuid()),
        T("          <ns2:Timestamp>⟦t⟧</ns2:Timestamp>", t=x.ts("iso_off", tick=(0.3, 2))),
        "        </ns2:ErrorInfo>",
        "      </detail>",
        "    </soap:Fault>",
        "  </soap:Body>",
        "</soap:Envelope>"))
    d.agent(d.L(en="v3 renamed elements. Let me list what changed in the holder type.",
                it="La v3 ha rinominato degli elementi. Vediamo cosa cambia nel tipo Holder.",
                de="v3 hat Elemente umbenannt. Ich schaue, was sich im Holder-Typ geändert hat.",
                fr="La v3 a renommé des éléments. Voyons ce qui change dans le type Holder.",
                es="La v3 renombró elementos. Veamos qué cambia en el tipo Holder."))
    wsdl_lines = [
        ("<xs:complexType name=\"HolderType\">", 0),
        ("  <xs:element name=\"FamilyName\" type=\"xs:string\"/>", 1),
        ("  <xs:element name=\"GivenName\" type=\"xs:string\"/>", 1),
        ("  <xs:element name=\"FiscalCode\" type=\"tns:FiscalCodeType\"/>", 1),
        ("  <xs:element name=\"DateOfBirth\" type=\"xs:date\"/>", 1),
        ("  <xs:element name=\"Address\" type=\"tns:AddressType\"/>", 1),
    ]
    start = r.randint(80, 240)
    d.tool("grep", "-n -A6 'complexType name=\"HolderType\"' wsdl/PolicyService_v3.wsdl",
           lines(*[F(x.num(start + i), ":" if i == 0 else "-", ln) for i, (ln, _) in enumerate(wsdl_lines)]))
    client = lines(
        "from zeep import Client, Settings",
        "from zeep.wsse.username import UsernameToken",
        "",
        "from .config import settings",
        "",
        "WSDL = settings.INSURER_WSDL  # PolicyService_v2.wsdl",
        "",
        "",
        "def get_policy(policy_no, holder):",
        "    client = Client(WSDL, wsse=UsernameToken(settings.B2B_USER, settings.B2B_PASSWORD),",
        "                    settings=Settings(strict=True))",
        "    return client.service.GetPolicy(",
        "        PolicyNumber=policy_no,",
        "        Holder={",
        "            \"FamilyName\": holder.family_name,",
        "            \"GivenName\": holder.given_name,",
        "            \"TaxCode\": holder.tax_id,",
        "            \"BirthDate\": holder.birth_date,",
        "            \"Address\": holder.address_dict(),",
        "        },",
        "    )",
    )
    d.tool("read", "integration/policy_client.py", numbered(client))
    d.tool("edit", "integration/policy_client.py", lines(
        "-WSDL = settings.INSURER_WSDL  # PolicyService_v2.wsdl",
        "+WSDL = settings.INSURER_WSDL_V3",
        "@@",
        "-            \"TaxCode\": holder.tax_id,",
        "-            \"BirthDate\": holder.birth_date,",
        "+            \"FiscalCode\": holder.tax_id,",
        "+            \"DateOfBirth\": holder.birth_date,"))
    d.tool("edit", "integration/samples/get_policy.xml", lines(
        f"-<soapenv:Envelope xmlns:soapenv=\"{_SOAP_NS}\" xmlns:pol=\"{ns}:v2\">",
        f"+<soapenv:Envelope xmlns:soapenv=\"{_SOAP_NS}\" xmlns:pol=\"{ns}:v3\">",
        "@@",
        T("-        <pol:TaxCode>⟦t⟧</pol:TaxCode>", t=nid),
        T("-        <pol:BirthDate>⟦b⟧</pol:BirthDate>", b=g.birth(holder, "iso")),
        T("+        <pol:FiscalCode>⟦t⟧</pol:FiscalCode>", t=nid),
        T("+        <pol:DateOfBirth>⟦b⟧</pol:DateOfBirth>", b=g.birth(holder, "iso"))))
    valid_from = d.clock.t.date() - dt.timedelta(days=r.randint(10, 300))
    drivers = [holder] + ([second] if second else [])
    drv = []
    for p in drivers:
        drv += [
            "        <pol:Driver>",
            T("          <pol:Name>⟦n⟧</pol:Name>", n=g.name(p)),
            T("          <pol:DateOfBirth>⟦b⟧</pol:DateOfBirth>", b=g.birth(p, "iso")),
            T("          <pol:LicenceNumber>⟦l⟧</pol:LicenceNumber>", l=g.dl(p)),
            T("          <pol:LicenceIssued>⟦i⟧</pol:LicenceIssued>",
              i=g.date(dt.date(min(p.birth.year + r.randint(18, 30), 2025), r.randint(1, 12), r.randint(1, 28)), "iso", p)),
            "        </pol:Driver>",
        ]
    d.tool("sh", F("curl -s -X POST ", endpoint, " -H 'Content-Type: text/xml; charset=utf-8' -H 'SOAPAction: \"GetPolicy\"' "
                   "--data @integration/samples/get_policy.xml | xmllint --format -"),
           lines(
               "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
               T("<soap:Envelope xmlns:soap=\"⟦a⟧\">", a=x.url(text=_SOAP_NS)),
               "  <soap:Body>",
               f"    <ns2:GetPolicyResponse xmlns:ns2=\"{ns}:v3\">",
               "      <ns2:Policy>",
               T("        <ns2:PolicyNumber>⟦p⟧</ns2:PolicyNumber>", p=_acct(d, policy_no)),
               "        <ns2:Status>ACTIVE</ns2:Status>",
               T("        <ns2:ValidFrom>⟦a⟧</ns2:ValidFrom>", a=g.date(valid_from, "iso", holder)),
               T("        <ns2:ValidTo>⟦a⟧</ns2:ValidTo>", a=g.date(valid_from + dt.timedelta(days=365), "iso", holder)),
               T("        <ns2:HolderName>⟦n⟧</ns2:HolderName>", n=g.name(holder, "upper")),
               T("        <ns2:HolderAddress>⟦a⟧</ns2:HolderAddress>", a=g.addr(holder)),
               "        <ns2:Vehicle>",
               T("          <ns2:Make>⟦m⟧</ns2:Make>", m=x.ent(make)),
               f"          <ns2:Model>{model}</ns2:Model>",
               T("          <ns2:Plate>⟦p⟧</ns2:Plate>", p=g.plate(holder)),
               T("          <ns2:VIN>⟦v⟧</ns2:VIN>", v=g.vin()),
               "        </ns2:Vehicle>",
               *drv,
               f"        <ns2:AnnualPremium currency=\"EUR\">{r.uniform(280, 1900):.2f}</ns2:AnnualPremium>",
               "      </ns2:Policy>",
               "    </ns2:GetPolicyResponse>",
               "  </soap:Body>",
               "</soap:Envelope>"))
    d.agent(say(d, "done"), "\n",
            d.L(en="- client and sample request moved to the v3 namespace\n- TaxCode → FiscalCode, BirthDate → DateOfBirth",
                it="- client e richiesta di esempio spostati sul namespace v3\n- TaxCode → FiscalCode, BirthDate → DateOfBirth",
                de="- Client und Beispiel-Request auf den v3-Namespace umgestellt\n- TaxCode → FiscalCode, BirthDate → DateOfBirth",
                fr="- client et requête d'exemple passés sur le namespace v3\n- TaxCode → FiscalCode, BirthDate → DateOfBirth",
                es="- cliente y petición de ejemplo pasados al namespace v3\n- TaxCode → FiscalCode, BirthDate → DateOfBirth"),
            "\n", say(d, "pii_warning"))


# ---------------------------------------------------------------- 11. httpie against a booking API


@template("httpie_booking_api", "steps", "http")
def httpie_booking_api(d):
    g, x, r = d.g, d.x, d.rng
    guest = d.person()
    companion = d.person(guest.locale) if r.random() < 0.4 else None
    branch = r.choice(["phone", "passport", "arrival"])
    short = r.random() < 0.35
    bid = f"BK-{r.randint(100000, 999999)}"
    fno = str(r.randint(1000, 9999))
    if branch == "passport" and guest.country in ("IT", "PL"):
        branch = "phone"
    d.user(T(d.L(
        en="The mobile app gets a 422 on POST /api/v1/bookings for some guests. Support forwarded the payload of a failing one in tmp/booking-⟦b⟧.json. Can you reproduce it with httpie against the local server?",
        it="L'app mobile riceve 422 su POST /api/v1/bookings per alcuni ospiti. Il supporto ha girato il payload di uno che fallisce in tmp/booking-⟦b⟧.json. Riesci a riprodurlo con httpie sul server locale?",
        de="Die Mobile-App bekommt bei manchen Gästen ein 422 auf POST /api/v1/bookings. Der Support hat das Payload eines fehlschlagenden Falls in tmp/booking-⟦b⟧.json weitergeleitet. Kannst du das mit httpie gegen den lokalen Server nachstellen?",
        fr="L'app mobile reçoit un 422 sur POST /api/v1/bookings pour certains clients. Le support a transmis le payload d'un cas en échec dans tmp/booking-⟦b⟧.json. Tu peux reproduire avec httpie sur le serveur local ?",
        es="La app móvil recibe un 422 en POST /api/v1/bookings con algunos huéspedes. Soporte reenvió el payload de uno que falla en tmp/booking-⟦b⟧.json. ¿Puedes reproducirlo con httpie contra el servidor local?"),
        b=fno))
    arrival = d.clock.t.date() + dt.timedelta(days=0 if branch == "arrival" else r.randint(3, 120))
    departure = arrival + dt.timedelta(days=r.randint(1, 9))
    card = g.card()
    phone = g.phone(guest, intl=False) if branch == "phone" else _e164(d, guest)
    note_lang = d.lang_of(guest)
    note = d.Lp(note_lang,
                en="We will arrive late, around 11pm. Quiet room if possible.",
                it="Arriveremo tardi, verso le 23. Se possibile una camera silenziosa.",
                de="Wir kommen spät an, gegen 23 Uhr. Wenn möglich ein ruhiges Zimmer.",
                fr="Nous arriverons tard, vers 23h. Une chambre calme si possible.",
                es="Llegaremos tarde, sobre las 23:00. Habitación tranquila si es posible.")
    payload = {
        "guest": {
            "first_name": g.name(guest, "given"),
            "last_name": g.name(guest, "family"),
            "email": g.email(guest, "personal"),
            "phone": phone,
            "nationality": guest.country,
            "date_of_birth": g.birth(guest, "iso"),
            "document": {"type": "passport", "number": g.passport(guest)},
        },
        "stay": {"hotel_id": r.randint(10, 400), "arrival": g.date(arrival, "iso", guest),
                 "departure": g.date(departure, "iso", guest), "room_type": r.choice(["DBL", "TWN", "SGL", "FAM"]),
                 "adults": 2 if companion else 1},
        "payment": {"card_number": card, "expiry": f"{r.randint(1, 12):02d}/{r.randint(26, 31)}",
                    "holder": g.name(guest, "upper")},
        "notes": note,
    }
    if companion:
        payload["companions"] = [{"name": g.name(companion), "date_of_birth": g.birth(companion, "iso")}]
    d.tool("read", f"tmp/booking-{fno}.json", _js(payload))
    if not short:
        d.agent(say(d, "pii_warning"))
    d.call("sh", f"http --print=hb POST :8000/api/v1/bookings < tmp/booking-{fno}.json")
    if branch == "phone":
        detail = {"type": "value_error", "loc": ["body", "guest", "phone"],
                  "msg": "Value error, phone must be in E.164 format", "input": phone}
    elif branch == "passport":
        detail = {"type": "string_pattern_mismatch", "loc": ["body", "guest", "document", "number"],
                  "msg": "String should match pattern '^[A-Z]{2}[0-9]{7}$'", "input": payload["guest"]["document"]["number"],
                  "ctx": {"pattern": "^[A-Z]{2}[0-9]{7}$"}}
    else:
        detail = {"type": "value_error", "loc": ["body", "stay", "arrival"],
                  "msg": "Value error, arrival must not be in the past", "input": payload["stay"]["arrival"]}
    d.result("sh", lines(
        "HTTP/1.1 422 Unprocessable Entity",
        T("content-length: ⟦n⟧", n=str(r.randint(180, 420))),
        "content-type: application/json",
        T("date: ⟦t⟧", t=x.ts("http", tick=(20, 90))),
        "server: uvicorn",
        T("x-request-id: ⟦i⟧", i=x.rid()),
        "",
        _js({"detail": [detail]})))
    schema = lines(
        "from datetime import date",
        "",
        "from pydantic import BaseModel, Field, field_validator",
        "",
        "E164 = r\"^\\+[1-9]\\d{6,14}$\"",
        "",
        "",
        "class Document(BaseModel):",
        "    type: str",
        "    number: str = Field(pattern=r\"^[A-Z]{2}[0-9]{7}$\")",
        "",
        "",
        "class Guest(BaseModel):",
        "    first_name: str",
        "    last_name: str",
        "    email: str",
        "    phone: str",
        "    nationality: str = Field(min_length=2, max_length=2)",
        "    date_of_birth: date",
        "    document: Document",
        "",
        "    @field_validator(\"phone\")",
        "    @classmethod",
        "    def e164(cls, v: str) -> str:",
        "        if not re.fullmatch(E164, v):",
        "            raise ValueError(\"phone must be in E.164 format\")",
        "        return v",
        "",
        "",
        "class Stay(BaseModel):",
        "    hotel_id: int",
        "    arrival: date",
        "    departure: date",
        "",
        "    @field_validator(\"arrival\")",
        "    @classmethod",
        "    def not_past(cls, v: date) -> date:",
        "        if v < date.today():",
        "            raise ValueError(\"arrival must not be in the past\")",
        "        return v",
    )
    if short:
        needle, lineno, text = {
            "phone": ("E164", 5, "E164 = r\"^\\+[1-9]\\d{6,14}$\""),
            "passport": ("pattern=", 10, "    number: str = Field(pattern=r\"^[A-Z]{2}[0-9]{7}$\")"),
            "arrival": ("date.today", 38, "        if v < date.today():"),
        }[branch]
        d.tool("grep", f"-n '{needle}' app/schemas/booking.py", lines(F(x.num(lineno), ":", text)))
    else:
        d.tool("read", "app/schemas/booking.py", schema)
    if branch == "phone":
        expl = d.L(en="The app sends the number as the guest typed it (national format, spaces). The validator only accepts strict E.164. Normalising with `phonenumbers` using the guest's nationality as default region is safer than rejecting.",
                   it="L'app invia il numero come l'ha digitato l'ospite (formato nazionale, spazi). Il validatore accetta solo E.164 stretto. Normalizzare con `phonenumbers` usando la nazionalità come regione di default è meglio che rifiutare.",
                   de="Die App schickt die Nummer so, wie der Gast sie eingetippt hat (nationales Format, Leerzeichen). Der Validator akzeptiert nur striktes E.164. Mit `phonenumbers` und der Nationalität als Default-Region zu normalisieren ist besser als abzulehnen.",
                   fr="L'app envoie le numéro tel que saisi par le client (format national, espaces). Le validateur n'accepte que du E.164 strict. Normaliser avec `phonenumbers` en prenant la nationalité comme région par défaut vaut mieux que rejeter.",
                   es="La app envía el número tal como lo escribió el huésped (formato nacional, espacios). El validador solo acepta E.164 estricto. Normalizar con `phonenumbers` usando la nacionalidad como región por defecto es mejor que rechazar.")
        diff = lines("-        if not re.fullmatch(E164, v):",
                     "-            raise ValueError(\"phone must be in E.164 format\")",
                     "-        return v",
                     "+        try:",
                     "+            n = phonenumbers.parse(v, info.data.get(\"nationality\"))",
                     "+        except phonenumbers.NumberParseException as e:",
                     "+            raise ValueError(\"invalid phone number\") from e",
                     "+        return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)")
    elif branch == "passport":
        expl = d.L(en="The passport pattern is the Italian one (two letters + seven digits). Passport numbers vary by issuing country; the API should only check length and charset and leave real validation to the KYC step.",
                   it="Il pattern del passaporto è quello italiano (due lettere + sette cifre). I numeri di passaporto cambiano per paese emittente; l'API dovrebbe controllare solo lunghezza e caratteri e lasciare la validazione vera al KYC.",
                   de="Das Passmuster ist das italienische (zwei Buchstaben + sieben Ziffern). Passnummern unterscheiden sich je nach ausstellendem Land; die API sollte nur Länge und Zeichensatz prüfen und die echte Validierung dem KYC überlassen.",
                   fr="Le motif du passeport est celui de l'Italie (deux lettres + sept chiffres). Les numéros varient selon le pays émetteur ; l'API devrait seulement vérifier longueur et caractères et laisser la vraie validation au KYC.",
                   es="El patrón del pasaporte es el italiano (dos letras + siete cifras). Los números cambian según el país emisor; la API solo debería comprobar longitud y caracteres y dejar la validación real al KYC.")
        diff = lines("-    number: str = Field(pattern=r\"^[A-Z]{2}[0-9]{7}$\")",
                     "+    number: str = Field(pattern=r\"^[A-Z0-9]{6,9}$\")  # format differs per issuing country")
    else:
        expl = d.L(en="`date.today()` runs in UTC on the server. A guest checking in today from a timezone ahead of UTC is rejected before midnight UTC. Compare against the hotel's local date instead.",
                   it="`date.today()` sul server gira in UTC. Un ospite che arriva oggi da un fuso avanti rispetto a UTC viene rifiutato prima della mezzanotte UTC. Bisogna confrontare con la data locale dell'hotel.",
                   de="`date.today()` läuft auf dem Server in UTC. Ein Gast, der heute aus einer Zeitzone östlich von UTC anreist, wird bis Mitternacht UTC abgelehnt. Es muss mit dem lokalen Datum des Hotels verglichen werden.",
                   fr="`date.today()` tourne en UTC sur le serveur. Un client qui arrive aujourd'hui depuis un fuseau en avance sur UTC est refusé avant minuit UTC. Il faut comparer avec la date locale de l'hôtel.",
                   es="`date.today()` en el servidor va en UTC. Un huésped que llega hoy desde una zona por delante de UTC se rechaza hasta la medianoche UTC. Hay que comparar con la fecha local del hotel.")
        diff = lines("-        if v < date.today():",
                     "+        if v < hotel_today(info.data[\"hotel_id\"]):  # hotel-local date, not server UTC")
    d.agent(say(d, "explain"), " ", expl)
    d.tool("edit", "app/schemas/booking.py", diff)
    d.tool("sh", f"http --print=hb POST :8000/api/v1/bookings < tmp/booking-{fno}.json", lines(
        "HTTP/1.1 201 Created",
        "content-type: application/json",
        T("date: ⟦t⟧", t=x.ts("http", tick=(30, 120))),
        T("location: /api/v1/bookings/⟦b⟧", b=x.id(bid)),
        "server: uvicorn",
        "",
        _js({"id": x.id(bid), "status": "confirmed",
             "guest": {"name": g.name(guest), "email": g.email(guest, "personal")},
             "stay": {"arrival": g.date(arrival, "iso", guest), "nights": (departure - arrival).days},
             "payment": {"brand": _brand(card.text),
                         "card": x.ph("card", "**** **** **** " + "".join(c for c in card.text if c.isdigit())[-4:])},
             "created_at": x.ts("iso_z")})))
    if not short:
        d.tool("sh", "pytest tests/api/test_bookings.py -q", lines(
            T("⟦n⟧ passed, 1 warning in ⟦s⟧s", n=x.num(lo=8, hi=40), s=f"{r.uniform(0.8, 6):.2f}")))
    d.agent(say(d, "not_committed"), " ",
            d.L(en="I'd also delete the forwarded payload from tmp/ — it contains the guest's passport and card numbers.",
                it="Cancellerei anche il payload inoltrato da tmp/: contiene passaporto e numero di carta dell'ospite.",
                de="Ich würde außerdem das weitergeleitete Payload aus tmp/ löschen – es enthält Pass- und Kartennummer des Gastes.",
                fr="Je supprimerais aussi le payload transmis dans tmp/ : il contient le passeport et le numéro de carte du client.",
                es="También borraría el payload reenviado de tmp/: contiene el pasaporte y la tarjeta del huésped."))
