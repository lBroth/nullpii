# SPDX-License-Identifier: Apache-2.0
"""Templates centred on reading configuration and project files."""

from __future__ import annotations

from ..core import F, T, lines, table
from ..phrases import say
from . import template


@template("env_db_connect", "cc", "file", "shell")
def env_db_connect(d):
    g, x, r = d.g, d.x, d.rng
    owner = d.me
    db_ip = g.ip("private")
    pw = g.password()
    svc = r.choice(["orders_app", "api", "app_rw", "svc_backend", "core"])
    dbname = r.choice(["orders", "app", "core", "billing", "main"])
    d.user(d.L(
        en="The API on staging can't reach Postgres since this morning. Can you check the config? Probably something in .env",
        it="Da stamattina l'API di staging non riesce a collegarsi a Postgres. Puoi controllare la config? Probabilmente qualcosa nel .env",
        de="Seit heute Morgen kommt die Staging-API nicht mehr an Postgres ran. Kannst du die Konfiguration prüfen? Vermutlich irgendwas in der .env",
        fr="Depuis ce matin l'API de staging n'arrive plus à joindre Postgres. Tu peux vérifier la config ? Sûrement un truc dans le .env",
        es="Desde esta mañana la API de staging no conecta con Postgres. ¿Puedes revisar la config? Seguramente algo del .env"))
    d.agent(say(d, "look_first", x=".env"))
    smtp_user = g.email(d.person(), "work")
    env_rows = [
        T("# staging — last edited by ⟦who⟧", who=g.name(owner)),
        "NODE_ENV=staging",
        T("PORT=⟦p⟧", p=x.port(r.choice([3000, 8080, 4000]))),
        T("DATABASE_URL=postgres://⟦u⟧:⟦pw⟧@⟦ip⟧:⟦port⟧/⟦db⟧", u=svc, pw=pw, ip=db_ip, port=x.port(5432), db=dbname),
        T("REDIS_URL=redis://⟦ip⟧:⟦port⟧/0", ip=g.ip("private"), port=x.port(6379)),
    ]
    if r.random() < 0.7:
        env_rows.append(T("STRIPE_SECRET_KEY=⟦k⟧", k=g.secret("stripe_live")))
    if r.random() < 0.6:
        env_rows.append(T("SENTRY_DSN=⟦k⟧", k=g.secret("sentry_dsn")))
    env_rows += [
        T("SMTP_HOST=smtp.⟦dom⟧", dom=d.domain),
        T("SMTP_USER=⟦u⟧", u=smtp_user),
        T("SMTP_PASS=⟦p⟧", p=g.password()),
        T("ADMIN_NOTIFY=⟦e⟧", e=g.email(owner, "work")),
        T("JWT_SECRET=⟦s⟧", s=g.secret("hex32")),
        "LOG_LEVEL=" + r.choice(["debug", "info"]),
    ]
    if r.random() < 0.5:
        env_rows.append(T("# docs: ⟦u⟧", u=x.url("docs", "https://www.postgresql.org/docs/current/libpq-connect.html")))
    tail = env_rows[5:]
    r.shuffle(tail)
    env_rows[5:] = tail
    d.tool("read", ".env", lines(*env_rows))
    d.agent(say(d, "check_next", x="docker compose"))
    ps_rows = [["NAME", "IMAGE", "STATUS", "PORTS"]]
    for name, img, port in [("api", f"{d.project}:staging", 8080), ("worker", f"{d.project}:staging", None),
                            ("pgbouncer", "edoburu/pgbouncer:1.22", 6432)]:
        status = r.choice(["Up 3 hours", "Up 41 minutes", "Restarting (1) 8 seconds ago", "Up 2 days"])
        ports = T("⟦ip⟧:⟦p⟧->⟦p2⟧/tcp", ip=x.rip(False), p=x.port(port), p2=x.port(port)) if port else ""
        ps_rows.append([f"{d.project}-{name}-1", img, status, ports])
    d.tool("sh", "docker compose ps", table(ps_rows, gap=3))
    if r.random() < 0.55:
        n = r.choice([6, 12, 25, 40, 70, 110])
        d.tool("sh", f"docker compose logs --no-color --tail {n} api", _api_log(d, n))
    d.tool("sh", 'docker compose exec api sh -c \'psql "$DATABASE_URL" -c "select 1"\'',
           T('psql: error: connection to server at "⟦ip⟧", port ⟦port⟧ failed: FATAL:  password authentication failed for user "⟦u⟧"\n',
             ip=db_ip, port=x.port(5432), u=svc))
    cause = "special" if pw.label and any(c in pw.text for c in "@:/#?%") else "rotated"
    if cause == "rotated":
        d.agent(say(d, "explain"), "\n\n",
                d.L(en="The password in DATABASE_URL no longer matches the role. The infra changelog says the staging DB credentials were rotated yesterday; the .env still has the old value.",
                    it="La password in DATABASE_URL non corrisponde più al ruolo. Dal changelog infra risulta che ieri le credenziali del DB di staging sono state ruotate; il .env ha ancora il vecchio valore.",
                    de="Das Passwort in DATABASE_URL passt nicht mehr zur Rolle. Laut Infra-Changelog wurden die Staging-DB-Zugangsdaten gestern rotiert; die .env enthält noch den alten Wert.",
                    fr="Le mot de passe de DATABASE_URL ne correspond plus au rôle. D'après le changelog infra, les identifiants de la base de staging ont été renouvelés hier ; le .env contient encore l'ancienne valeur.",
                    es="La contraseña de DATABASE_URL ya no coincide con el rol. Según el changelog de infra, ayer se rotaron las credenciales de la BD de staging; el .env sigue con el valor antiguo."))
        new_pw = g.password()
        d.user(d.L(en="New one is in the vault: ", it="Quella nuova è nel vault: ", de="Das neue steht im Vault: ",
                   fr="Le nouveau est dans le vault : ", es="La nueva está en el vault: "), new_pw)
        d.tool("edit", ".env", T("-DATABASE_URL=postgres://⟦u⟧:⟦a⟧@⟦ip⟧:⟦p⟧/⟦db⟧\n+DATABASE_URL=postgres://⟦u⟧:⟦b⟧@⟦ip⟧:⟦p⟧/⟦db⟧\n",
                                     u=svc, a=pw, b=new_pw, ip=db_ip, p=x.port(5432), db=dbname))
    else:
        d.agent(say(d, "explain"), "\n\n",
                d.L(en="The password contains characters that must be percent-encoded inside a connection URI, so libpq receives a truncated password. Encoding it fixes the parse.",
                    it="La password contiene caratteri che vanno codificati (percent-encoding) dentro un URI di connessione, quindi libpq riceve una password troncata.",
                    de="Das Passwort enthält Zeichen, die in einer Verbindungs-URI prozentkodiert werden müssen; libpq bekommt dadurch ein abgeschnittenes Passwort.",
                    fr="Le mot de passe contient des caractères qui doivent être encodés (percent-encoding) dans une URI de connexion ; libpq reçoit donc un mot de passe tronqué.",
                    es="La contraseña tiene caracteres que hay que codificar (percent-encoding) en una URI de conexión, así que libpq recibe una contraseña truncada."),
                "\n\n", x.url("docs", "https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING-URIS"))
        d.user(say(d, "go_ahead"))
        d.tool("sh", "docker compose restart api && docker compose logs --since 1m api | tail -n 4",
               lines(T("api-1  | ⟦t⟧ info: connected to postgres (pool size ⟦n⟧)", t=x.ts("iso_z", tick=(20, 40)), n=x.num(r.choice([10, 20]))),
                     T("api-1  | ⟦t⟧ info: listening on :⟦p⟧", t=x.ts("iso_z", tick=(0, 1)), p=x.port(8080))))
    if d.secret_ok and r.random() < 0.6:
        d.agent(say(d, "secret_warning", x=".env"))
    d.agent(say(d, "done"), "\n- ", d.L(en="DATABASE_URL updated in .env (not committed — .env is gitignored)",
                                         it="DATABASE_URL aggiornato nel .env (non committato: .env è in .gitignore)",
                                         de="DATABASE_URL in der .env aktualisiert (nicht committet — .env steht in .gitignore)",
                                         fr="DATABASE_URL mis à jour dans le .env (pas committé — .env est dans le .gitignore)",
                                         es="DATABASE_URL actualizado en el .env (sin commit: .env está en .gitignore)"))


_ROUTES = [("GET", "/api/v1/orders"), ("POST", "/api/v1/orders"), ("GET", "/api/v1/customers/⟦id⟧"),
           ("PATCH", "/api/v1/customers/⟦id⟧"), ("GET", "/healthz"), ("POST", "/api/v1/auth/login"),
           ("GET", "/api/v1/invoices?page=⟦id⟧"), ("DELETE", "/api/v1/sessions/current")]


def _api_log(d, n):
    """Request log lines of a Node API that cannot reach its database."""
    g, x, r = d.g, d.x, d.rng
    clients = [g.ip(r.choice(["public", "public", "private", "v6"])) for _ in range(r.randint(2, 6))]
    users = d.people(r.randint(1, 4))
    out = []
    for _ in range(n):
        t = x.ts("iso_z", tick=(0.05, 20))
        if r.random() < 0.12:
            out.append(T("api-1  | ⟦t⟧ error: ECONNREFUSED / password authentication failed (pool attempt ⟦k⟧)",
                         t=t, k=x.num(lo=1, hi=5)))
            continue
        method, path = r.choice(_ROUTES)
        path_f = T(path, id=x.num(lo=1, hi=99999)) if "⟦id⟧" in path else F(path)
        status = r.choice([200, 200, 201, 500, 500, 503, 401])
        extra = T(" user=⟦e⟧", e=g.email(r.choice(users), r.choice(["work", "personal"]))) if "auth" in path or r.random() < 0.3 else ""
        out.append(T("api-1  | ⟦t⟧ http ⟦m⟧ ⟦p⟧ ⟦s⟧ ⟦ms⟧ms ip=⟦ip⟧⟦u⟧ rid=⟦rid⟧", t=t, m=method, p=path_f, s=str(status),
                     ms=str(r.randint(2, 3000)), ip=r.choice(clients), u=extra, rid=x.rid()))
    return lines(*out)
