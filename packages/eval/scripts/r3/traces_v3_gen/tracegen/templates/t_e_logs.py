# SPDX-License-Identifier: Apache-2.0
"""Templates centred on application, system and network logs."""

from __future__ import annotations

import base64 as _b64
import datetime as _dt

from .. import values as V
from ..core import F, J, T, Seg, esc_json, grid, lines, numbered, table
from ..phrases import say
from . import template

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "okhttp/4.12.0", "Dalvik/2.1.0 (Linux; U; Android 13; SM-A536B Build/TP1A.220624.014)",
]
_BOT_UAS = ["python-requests/2.31.0", "curl/8.5.0", "Go-http-client/1.1", "Mozilla/5.0 zgrab/0.x",
            "Mozilla/5.0 (compatible; Nmap Scripting Engine)", "masscan/1.3", "Hello, world"]


def _LOOPBACK() -> Seg:
    return Seg("127.0.0.1", cls="reserved_ip")


def _mts(text: str) -> Seg:
    """Machine timestamp in a format the shared formatter does not cover."""
    return Seg(text, cls="machine_timestamp")


def _last_fmt(d, t=None) -> Seg:
    t = d.clock.local(t)
    return _mts(f"{_DOW[t.weekday()]} {_MON[t.month - 1]} {t.day:2d} {t:%H:%M}")


def _wg_key(d) -> str:
    """Base64 of 32 random bytes, as WireGuard prints keys."""
    return _b64.b64encode(bytes(d.rng.randint(0, 255) for _ in range(32))).decode()


def _one_of(d, *opts):
    return d.rng.choice(opts)


# ---------------------------------------------------------------------------------------------------------------
# 1. nginx access log: top talkers and a fail2ban ban


def _personal_path(d) -> Seg | str:
    r = d.rng
    if not d.gold_ok:
        return r.choice(["/api/v1/products?page=2", "/api/v1/cart", "/account", "/api/v1/stores/12/hours"])
    kind = r.random()
    if kind < 0.4:
        return d.g.raw("private_url", f"/api/v1/customers/{r.randint(10000, 999999)}/{r.choice(['orders', 'invoices', 'addresses'])}", "url")
    if kind < 0.7:
        return d.g.raw("private_url", f"/account/reset-password?token={V.rand_str(r, V.ALNUM, 32)}", "url")
    return d.g.raw("private_url", f"/u/{d.person().username()}/profile", "url")


def _plain_path(d) -> list:
    r = d.rng
    choice = r.randint(0, 6)
    if choice == 0:
        return F("/static/js/app.", d.x.short(8), ".js")
    if choice == 1:
        return F("/static/css/main.", d.x.short(8), ".css")
    return F(r.choice(["/", "/login", "/favicon.ico", "/api/v1/products?page=3", "/api/v1/cart", "/robots.txt",
                       "/api/v1/search?q=boots"]))


def _access(d, ip, method, path, status, size, ua, user="-", ref="-") -> list:
    return T('⟦ip⟧ - ⟦u⟧ [⟦t⟧] "⟦m⟧ ⟦p⟧ HTTP/1.1" ⟦s⟧ ⟦b⟧ "⟦ref⟧" "⟦ua⟧"', ip=ip, u=user,
             t=d.x.ts("clf", tick=(0.02, 2.5), local=True), m=method, p=path, s=str(status), b=str(size), ref=ref,
             ua=ua)


@template("nginx_access_top_ips", "colon", "log", "shell")
def nginx_access_top_ips(d):
    g, x, r = d.g, d.x, d.rng
    endpoint = r.choice(["/login", "/api/v1/auth/token", "/wp-login.php", "/api/v1/password/forgot"])
    d.user(d.L(
        en=f"Something is hammering {endpoint} on the public web box, CPU is pegged. Can you check the nginx access log and tell me who it is?",
        it=f"Qualcuno sta martellando {endpoint} sul web server pubblico, la CPU è al 100%. Puoi guardare l'access log di nginx e dirmi chi è?",
        de=f"Irgendwer hämmert auf {endpoint} auf dem öffentlichen Webserver, die CPU ist am Anschlag. Kannst du ins nginx-Access-Log schauen, wer das ist?",
        fr=f"Quelqu'un martèle {endpoint} sur le serveur web public, le CPU est à fond. Tu peux regarder l'access log nginx et me dire qui c'est ?",
        es=f"Alguien está machacando {endpoint} en el servidor web público y la CPU está al máximo. ¿Puedes mirar el access log de nginx y decirme quién es?"))
    d.agent(say(d, "look_first", x="/var/log/nginx/access.log"))
    attackers = [g.ip("public") for _ in range(r.randint(1, 3))]
    clients = [g.ip(r.choice(["public", "public", "v6"])) for _ in range(r.randint(3, 7))]
    office = g.ip("public")
    rows = []
    n = r.randint(6, 60)
    for _ in range(n):
        k = r.random()
        if k < 0.5:
            ip = r.choice(attackers)
            path = endpoint if r.random() < 0.8 else r.choice(["/.env", "/admin", "/wp-login.php", "/.git/config"])
            st = r.choice([401, 401, 401, 429]) if path == endpoint else r.choice([404, 403, 404])
            rows.append(_access(d, ip, "POST" if path == endpoint else "GET", path, st, r.randint(150, 600),
                                r.choice(_BOT_UAS)))
        elif k < 0.62:
            rows.append(_access(d, _LOOPBACK(), "GET", "/healthz", 200, 2, r.choice(["kube-probe/1.29", "Consul Health Check"])))
        elif k < 0.75 and d.gold_ok:
            ip = r.choice(clients)
            rows.append(_access(d, ip, "GET", _personal_path(d), r.choice([200, 200, 304, 302]), r.randint(300, 9000),
                                r.choice(_UAS), ref=F("https://www.", d.domain, "/")))
        elif k < 0.8:
            staff = d.person()
            rows.append(_access(d, office, "GET", "/admin/reports/daily", 200, r.randint(2000, 40000), r.choice(_UAS),
                                user=g.user(staff)))
        else:
            rows.append(_access(d, r.choice(clients), "GET", _plain_path(d), r.choice([200, 200, 304]),
                                r.randint(100, 250000), r.choice(_UAS)))
    d.tool("sh", f"tail -n {n} /var/log/nginx/access.log", lines(*rows))
    d.agent(d.L(en="Mostly repeated POSTs to the same endpoint from a handful of addresses. Counting requests per client IP:",
                it="Sono soprattutto POST ripetuti sullo stesso endpoint da pochi indirizzi. Conto le richieste per IP:",
                de="Hauptsächlich wiederholte POSTs auf denselben Endpunkt von ein paar Adressen. Ich zähle die Requests pro IP:",
                fr="Surtout des POST répétés sur le même endpoint depuis quelques adresses. Je compte les requêtes par IP :",
                es="Sobre todo POST repetidos al mismo endpoint desde unas pocas direcciones. Cuento las peticiones por IP:"))
    counts = sorted([r.randint(2000, 48000) for _ in attackers], reverse=True)
    top = [T("⟦c⟧ ⟦ip⟧", c=f"{c:>7}", ip=ip) for c, ip in zip(counts, attackers)]
    for ip in clients[: r.randint(2, 4)]:
        top.append(T("⟦c⟧ ⟦ip⟧", c=f"{r.randint(40, 900):>7}", ip=ip))
    top.append(T("⟦c⟧ ⟦ip⟧", c=f"{r.randint(500, 1500):>7}", ip=_LOOPBACK()))
    d.tool("sh", "awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -n 8", lines(*top))
    if r.random() < 0.6:
        d.tool("sh", T("grep -c '⟦ip⟧ .*\"POST ⟦e⟧' /var/log/nginx/access.log; grep '⟦ip2⟧' /var/log/nginx/access.log | awk '{print $9}' | sort | uniq -c",
                       ip=attackers[0], e=endpoint, ip2=attackers[0]),
               lines(str(counts[0] - r.randint(0, 40)), f"  {r.randint(1500, counts[0])} 401", f"  {r.randint(10, 400)} 429",
                     f"   {r.randint(1, 30)} 404"))
    for ip in attackers:
        d.tool("sh", T("sudo fail2ban-client set nginx-login banip ⟦ip⟧", ip=ip), "1")
    if r.random() < 0.55:
        d.agent(d.L(en="Banned. I'd also make the jail permanent so this doesn't need manual work next time, and whitelist the office egress IP so admins don't lock themselves out:",
                    it="Bannati. Renderei anche permanente la jail, così la prossima volta non serve intervenire a mano, e metterei in whitelist l'IP di uscita dell'ufficio:",
                    de="Gebannt. Ich würde den Jail dauerhaft einrichten und die Büro-IP auf die Ignore-Liste setzen, damit sich Admins nicht aussperren:",
                    fr="Bannis. Je rendrais aussi la jail permanente et j'ajouterais l'IP de sortie du bureau en liste blanche pour que les admins ne se bloquent pas :",
                    es="Baneadas. También dejaría la jail permanente y añadiría la IP de salida de la oficina a la lista blanca para que los admins no se bloqueen:"))
        d.tool("write", "/etc/fail2ban/jail.d/nginx-login.conf", lines(
            "[nginx-login]", "enabled  = true", "port     = http,https", "filter   = nginx-login",
            "logpath  = /var/log/nginx/access.log", f"maxretry = {r.choice([5, 10, 20])}", "findtime = 600",
            f"bantime  = {r.choice([3600, 86400, '1w'])}",
            T("ignoreip = ⟦lo⟧/8 ⟦lo6⟧ ⟦office⟧", lo=_LOOPBACK(), lo6=Seg("::1", cls="reserved_ip"), office=office)))
        d.tool("sh", "sudo fail2ban-client reload && sudo fail2ban-client status nginx-login",
               lines("OK", "Status for the jail: nginx-login", "|- Filter",
                     f"|  |- Currently failed:\t{r.randint(0, 6)}", f"|  |- Total failed:\t{r.randint(500, 9000)}",
                     "|  `- File list:\t/var/log/nginx/access.log", "`- Actions",
                     f"   |- Currently banned:\t{len(attackers)}", f"   |- Total banned:\t{len(attackers) + r.randint(0, 9)}",
                     F("   `- Banned IP list:\t", J(" ", attackers))))
    d.agent(say(d, "done"), "\n- ",
            d.L(en=f"{len(attackers)} source address(es) banned in fail2ban; they made up most of the traffic to {endpoint}.",
                it=f"{len(attackers)} indirizzo/i bannato/i con fail2ban; erano la maggior parte del traffico su {endpoint}.",
                de=f"{len(attackers)} Quelladresse(n) per fail2ban gebannt; sie machten den Großteil des Traffics auf {endpoint} aus.",
                fr=f"{len(attackers)} adresse(s) source bannie(s) via fail2ban ; elles représentaient l'essentiel du trafic sur {endpoint}.",
                es=f"{len(attackers)} dirección(es) baneada(s) con fail2ban; eran casi todo el tráfico a {endpoint}."),
            "\n- ", d.L(en="Consider limit_req on that location as well: ", it="Valuta anche limit_req su quella location: ",
                        de="Zusätzlich limit_req für diese location erwägen: ", fr="Pense aussi à limit_req sur cette location : ",
                        es="Plantéate también limit_req en esa location: "),
            x.url(text="https://nginx.org/en/docs/http/ngx_http_limit_req_module.html"))


# ---------------------------------------------------------------------------------------------------------------
# 2. PostgreSQL slow query log


@template("postgres_slow_query_log", "jsonl", "log")
def postgres_slow_query_log(d):
    g, x, r = d.g, d.x, d.rng
    d.user(d.L(
        en="The customer lookup endpoint went from 50ms to multiple seconds after yesterday's import. Can you go through the postgres slow log on db-primary and find out why?",
        it="L'endpoint di ricerca clienti è passato da 50ms a diversi secondi dopo l'import di ieri. Puoi guardare lo slow log di postgres su db-primary e capire perché?",
        de="Der Kunden-Lookup-Endpunkt ist seit dem Import gestern von 50 ms auf mehrere Sekunden gestiegen. Kannst du das Postgres-Slow-Log auf db-primary durchgehen?",
        fr="L'endpoint de recherche client est passé de 50 ms à plusieurs secondes depuis l'import d'hier. Tu peux regarder le slow log postgres sur db-primary ?",
        es="El endpoint de búsqueda de clientes pasó de 50 ms a varios segundos tras la importación de ayer. ¿Puedes revisar el slow log de postgres en db-primary?"))
    d.agent(say(d, "logs_window"))
    app_ips = [g.ip("private") for _ in range(r.randint(2, 4))]
    analyst = d.person()
    analyst_ip = g.ip("private")
    people = d.people(r.randint(3, 8))
    target = people[0]
    target_mail = g.email(target, "personal")
    db = r.choice(["shop", "crm", "core", "orders"])

    def prefix(user, ip):
        return T("⟦t⟧ [⟦pid⟧] ⟦u⟧@⟦db⟧ ⟦ip⟧(⟦port⟧) ", t=x.ts("pg", tick=(0.5, 40)), pid=x.num(lo=1200, hi=65000),
                 u=user, db=db, ip=ip, port=str(r.randint(32768, 60999)))

    rows = []
    n = r.randint(8, 40)
    for i in range(n):
        k = r.random()
        ip = r.choice(app_ips)
        pre_f = prefix("app", ip)
        if i == 0 or k < 0.3:
            p = target if i == 0 else r.choice(people)
            mail = target_mail if p is target else g.email(p, "personal")
            ms = f"{r.uniform(1200, 4800):.3f}"
            rows.append(F(pre_f, "LOG:  duration: ", ms, " ms  statement: SELECT id, first_name, last_name, customer_no FROM customers WHERE lower(email) = lower('", mail, "')"))
        elif k < 0.45:
            p = r.choice(people)
            rows.append(F(pre_f, "LOG:  duration: ", f"{r.uniform(600, 3000):.3f}", " ms  execute <unnamed>: SELECT * FROM customers WHERE phone = $1",
                          "\n", pre_f, "DETAIL:  parameters: $1 = '", g.phone(p), "'"))
        elif k < 0.55:
            rows.append(F(pre_f, "LOG:  duration: ", f"{r.uniform(500, 1500):.3f}", " ms  statement: UPDATE customers SET last_seen_at = now() WHERE customer_no = '", g.cust(), "'"))
        elif k < 0.62:
            rows.append(F(prefix(g.user(analyst), analyst_ip), "LOG:  duration: ", f"{r.uniform(8000, 42000):.3f}",
                          " ms  statement: SELECT date_trunc('month', created_at), count(*) FROM orders GROUP BY 1 ORDER BY 1"))
        elif k < 0.75:
            rows.append(F(x.ts("pg", tick=(10, 120)), " [", x.num(lo=1200, hi=65000), "] LOG:  checkpoint complete: wrote ",
                          str(r.randint(200, 9000)), " buffers (", f"{r.uniform(0.5, 20):.1f}", "%); 0 WAL file(s) added, 0 removed, ",
                          str(r.randint(0, 4)), " recycled; write=", f"{r.uniform(10, 270):.3f}", " s"))
        elif k < 0.85:
            rows.append(F(x.ts("pg", tick=(5, 60)), " [", x.num(lo=1200, hi=65000), "] LOG:  automatic vacuum of table \"",
                          db, ".public.", r.choice(["events", "sessions", "orders", "audit_log"]), "\": index scans: 1"))
        else:
            rows.append(F(pre_f, "LOG:  connection authorized: user=app database=", db, " application_name=",
                          r.choice(["api", "worker", "psql", "pgbouncer"])))
    d.tool("sh", f"ssh db-primary \"sudo tail -n {n * 2} /var/log/postgresql/postgresql-16-main.log | grep -E 'duration|DETAIL|checkpoint|vacuum|authorized'\"",
           lines(*rows))
    d.agent(d.L(en="The e-mail lookup dominates. Checking the plan for one of those statements:",
                it="Domina la ricerca per e-mail. Controllo il piano di una di quelle query:",
                de="Die Suche per E-Mail dominiert. Ich prüfe den Plan für eine dieser Abfragen:",
                fr="La recherche par e-mail domine. Je regarde le plan d'une de ces requêtes :",
                es="Domina la búsqueda por e-mail. Reviso el plan de una de esas consultas:"))
    rows_total = r.randint(300_000, 2_400_000)
    seq_ms = r.uniform(1500, 4500)
    plan = lines(
        "                                                       QUERY PLAN",
        "---------------------------------------------------------------------------------------------------------------------",
        f" Seq Scan on customers  (cost=0.00..{rows_total * 0.06:.2f} rows={rows_total // 200} width=72) (actual time=0.041..{seq_ms:.3f} rows=1 loops=1)",
        T("   Filter: (lower((email)::text) = '⟦m⟧'::text)", m=target_mail),
        f"   Rows Removed by Filter: {rows_total - 1}",
        f"   Buffers: shared hit={r.randint(100, 4000)} read={r.randint(20000, 90000)}",
        f" Planning Time: {r.uniform(0.05, 0.4):.3f} ms",
        f" Execution Time: {seq_ms + 0.031:.3f} ms",
        "(6 rows)")
    d.tool("sh", T("psql -h db-primary -U app ⟦db⟧ -c \"EXPLAIN (ANALYZE, BUFFERS) SELECT id FROM customers WHERE lower(email) = lower('⟦m⟧')\"",
                   db=db, m=target_mail), plan)
    d.tool("sh", T("psql -h db-primary -U app ⟦db⟧ -c '\\d customers' | grep -i -A12 Indexes", db=db),
           lines("Indexes:", '    "customers_pkey" PRIMARY KEY, btree (id)',
                 '    "customers_customer_no_key" UNIQUE CONSTRAINT, btree (customer_no)',
                 '    "customers_email_idx" btree (email)' if r.random() < 0.7 else '    "customers_created_at_idx" btree (created_at)'))
    d.agent(say(d, "explain"), "\n",
            d.L(en="the query filters on lower(email), so a plain btree on email can't be used and every lookup scans the whole table. The import roughly doubled the row count, which is why it tipped over now. An expression index fixes it.",
                it="la query filtra su lower(email), quindi un btree semplice su email non viene usato e ogni ricerca scansiona tutta la tabella. L'import ha quasi raddoppiato le righe, ecco perché ora è peggiorato. Serve un indice su espressione.",
                de="die Abfrage filtert auf lower(email), deshalb kann ein normaler btree auf email nicht genutzt werden und jede Suche scannt die ganze Tabelle. Der Import hat die Zeilenzahl etwa verdoppelt. Ein Ausdrucksindex löst das.",
                fr="la requête filtre sur lower(email), donc un btree simple sur email n'est pas utilisable et chaque recherche parcourt toute la table. L'import a presque doublé le nombre de lignes. Un index sur expression règle ça.",
                es="la consulta filtra por lower(email), así que un btree normal sobre email no sirve y cada búsqueda recorre toda la tabla. La importación casi duplicó las filas. Un índice de expresión lo arregla."))
    mig = f"db/migrations/V{r.randint(20, 140)}__customers_lower_email_idx.sql"
    d.tool("write", mig, lines("-- lookups use lower(email); see slow log analysis",
                               "CREATE INDEX CONCURRENTLY IF NOT EXISTS customers_lower_email_idx",
                               "    ON customers (lower(email));"))
    if r.random() < 0.7:
        d.tool("sh", T("psql -h db-primary -U app ⟦db⟧ -f ⟦mig⟧ && psql -h db-primary -U app ⟦db⟧ -c \"EXPLAIN ANALYZE SELECT id FROM customers WHERE lower(email) = lower('⟦m⟧')\" | head -n 4",
                       db=db, mig=mig, m=target_mail),
               lines("CREATE INDEX", "                                   QUERY PLAN",
                     "-------------------------------------------------------------------------------",
                     f" Index Scan using customers_lower_email_idx on customers  (cost=0.43..8.45 rows=1 width=8) (actual time=0.031..0.033 rows=1 loops=1)"))
    d.agent(d.L(en="One more thing: the log is full of customer e-mails and phone numbers in plain text (statements and bind parameters). I'd turn that off on the server:",
                it="Un'altra cosa: il log è pieno di e-mail e numeri di telefono dei clienti in chiaro (statement e parametri). Lo disattiverei sul server:",
                de="Noch etwas: Das Log ist voller Kunden-E-Mails und Telefonnummern im Klartext (Statements und Bind-Parameter). Das würde ich serverseitig abstellen:",
                fr="Autre chose : le log est plein d'e-mails et de numéros de téléphone clients en clair (requêtes et paramètres). Je désactiverais ça côté serveur :",
                es="Otra cosa: el log está lleno de e-mails y teléfonos de clientes en claro (sentencias y parámetros). Lo desactivaría en el servidor:"),
            "\n\n    log_min_duration_statement = 500ms\n    log_parameter_max_length = 0\n    log_statement = 'none'\n\n",
            x.url(text="https://www.postgresql.org/docs/current/runtime-config-logging.html"))


# ---------------------------------------------------------------------------------------------------------------
# 3. sshd journal


_INVALID_USERS = ["admin", "oracle", "test", "ubuntu", "git", "postgres", "user", "pi", "ftpuser", "guest", "deploy",
                  "minecraft", "es", "hadoop", "support"]


@template("sshd_auth_journal", "tslog", "log", "shell")
def sshd_auth_journal(d):
    g, x, r = d.g, d.x, d.rng
    host = r.choice(["bastion", "bastion-01", "jump", d.host])
    d.user(d.L(
        en=f"We got an alert about SSH logins on {host}. Can you check the journal and tell me whether anyone actually got in?",
        it=f"Ci è arrivato un alert sui login SSH su {host}. Puoi controllare il journal e dirmi se qualcuno è entrato davvero?",
        de=f"Wir haben einen Alarm wegen SSH-Logins auf {host} bekommen. Kannst du im Journal nachsehen, ob tatsächlich jemand reingekommen ist?",
        fr=f"On a reçu une alerte sur des connexions SSH sur {host}. Tu peux regarder le journal et me dire si quelqu'un est vraiment entré ?",
        es=f"Nos ha saltado una alerta de logins SSH en {host}. ¿Puedes mirar el journal y decirme si alguien entró de verdad?"))
    admins = d.people(r.randint(1, 3))
    admin_ips = [g.ip("private") for _ in admins]
    attackers = [g.ip("public") for _ in range(r.randint(2, 6))]
    suspicious = r.random() < 0.4
    sus_user = r.choice(admins)
    sus_ip = g.ip("public")
    uid = {id(a): 1000 + i + 1 for i, a in enumerate(admins)}

    def pre():
        return F(x.ts("syslog", tick=(0.3, 25), local=True), " ", host, " sshd[", x.num(lo=1000, hi=99999), "]: ")

    rows = []
    n = r.randint(14, 70)
    accepted_at = r.sample(range(n), k=min(n, r.randint(1, 3)))
    sus_at = r.randrange(n) if suspicious else -1
    for i in range(n):
        if i == sus_at:
            rows.append(F(pre(), "Accepted password for ", g.user(sus_user), " from ", sus_ip, " port ",
                          x.port(r.randint(1025, 65000)), " ssh2"))
            rows.append(F(pre(), "pam_unix(sshd:session): session opened for user ", g.user(sus_user), "(uid=",
                          str(uid[id(sus_user)]), ") by (uid=0)"))
            continue
        if i in accepted_at:
            j = r.randrange(len(admins))
            rows.append(F(pre(), "Accepted publickey for ", g.user(admins[j]), " from ", admin_ips[j], " port ",
                          x.port(r.randint(1025, 65000)), " ssh2: ED25519 SHA256:", x.id(V.rand_str(r, V.ALNUM + "+/", 43))))
            rows.append(F(pre(), "pam_unix(sshd:session): session opened for user ", g.user(admins[j]), "(uid=",
                          str(uid[id(admins[j])]), ") by (uid=0)"))
            continue
        ip = r.choice(attackers)
        u = r.choice(_INVALID_USERS)
        port = x.port(r.randint(1025, 65000))
        kind = r.randint(0, 4)
        if kind == 0:
            rows.append(F(pre(), "Invalid user ", u, " from ", ip, " port ", port))
        elif kind == 1:
            rows.append(F(pre(), "Failed password for invalid user ", u, " from ", ip, " port ", port, " ssh2"))
        elif kind == 2:
            rows.append(F(pre(), "Failed password for root from ", ip, " port ", port, " ssh2"))
        elif kind == 3:
            rows.append(F(pre(), "Connection closed by authenticating user root ", ip, " port ", port, " [preauth]"))
        else:
            rows.append(F(pre(), "Received disconnect from ", ip, " port ", port, ":11: Bye Bye [preauth]"))
    d.tool("sh", f"journalctl -u ssh --since '3 hours ago' --no-pager | tail -n {len(rows)}", lines(*rows))
    d.agent(d.L(en="Lots of noise from scanners. Let me see who has sessions and recent logins:",
                it="Molto rumore da scanner. Vediamo chi ha sessioni e login recenti:",
                de="Viel Rauschen von Scannern. Mal sehen, wer Sessions und letzte Logins hat:",
                fr="Beaucoup de bruit venant de scanners. Voyons qui a des sessions et des connexions récentes :",
                es="Mucho ruido de escáneres. Veamos quién tiene sesiones y logins recientes:"))
    last_rows = []
    now = d.clock.t
    if suspicious:
        last_rows.append([g.user(sus_user), "pts/2", sus_ip, F(_last_fmt(d, now), "   still logged in")])
    back = 0
    for a, ip in zip(admins, admin_ips):
        back += r.randint(600, 9000)
        start = now - _dt.timedelta(seconds=back)
        if r.random() < 0.5:
            tail = "   still logged in"
        else:
            mins = r.randint(3, 59)
            end = d.clock.local(start + _dt.timedelta(minutes=mins))
            tail = f" - {end:%H:%M}  (00:{mins:02d})"
        last_rows.append([g.user(a), f"pts/{r.randint(0, 3)}", ip, F(_last_fmt(d, start), tail)])
    boot = now - _dt.timedelta(days=r.randint(2, 40), seconds=back)
    last_rows.append(["reboot", "system boot", Seg("0.0.0.0", cls="reserved_ip"), F(_last_fmt(d, boot), "   still running")])
    d.tool("sh", "last -i | head -n 10", F(table(last_rows, gap=3), "\nwtmp begins ", _mts(f"{_DOW[r.randint(0, 6)]} {_MON[r.randint(0, 11)]}  1 00:0{r.randint(0, 9)}:{r.randint(10, 59)} 2025"), "\n"))
    if suspicious:
        d.tool("sh", T("getent passwd ⟦u⟧; sudo grep -c 'Accepted password' /var/log/auth.log", u=g.user(sus_user)),
               lines(T("⟦u⟧:x:⟦uid⟧:⟦uid2⟧:⟦name⟧,,,:/home/⟦u2⟧:/bin/bash", u=g.user(sus_user), uid=str(uid[id(sus_user)]),
                       uid2=str(uid[id(sus_user)]), name=g.name(sus_user), u2=g.user(sus_user)), "1"))
        d.agent(d.L(en="This is the one that matters: a *password* login for a real account from an address outside the VPN range, and the session is still open. Everything else is failed brute force. I'd kill the session, lock the account and disable password auth.",
                    it="Questo è quello che conta: un login *con password* per un account reale da un indirizzo fuori dal range VPN, e la sessione è ancora aperta. Il resto è brute force fallito. Chiuderei la sessione, bloccherei l'account e disattiverei l'autenticazione via password.",
                    de="Das ist der relevante Eintrag: ein *Passwort*-Login für ein echtes Konto von einer Adresse außerhalb des VPN-Bereichs, und die Session ist noch offen. Der Rest ist gescheitertes Brute-Forcing. Ich würde die Session beenden, das Konto sperren und Passwort-Login abschalten.",
                    fr="C'est celui-ci qui compte : une connexion *par mot de passe* sur un vrai compte depuis une adresse hors de la plage VPN, et la session est toujours ouverte. Le reste, c'est du brute force raté. Je tuerais la session, verrouillerais le compte et désactiverais l'authentification par mot de passe.",
                    es="Este es el que importa: un login *con contraseña* de una cuenta real desde una IP fuera del rango de la VPN, y la sesión sigue abierta. Lo demás es fuerza bruta fallida. Cerraría la sesión, bloquearía la cuenta y desactivaría la autenticación por contraseña."))
        d.user(say(d, "go_ahead"))
        d.tool("sh", T("sudo pkill -KILL -u ⟦u⟧ && sudo usermod -L ⟦u2⟧ && sudo passwd -S ⟦u3⟧", u=g.user(sus_user),
                       u2=g.user(sus_user), u3=g.user(sus_user)),
               T("⟦u⟧ L ⟦day⟧ 0 99999 7 -1\n", u=g.user(sus_user), day=x.ts("date")))
    else:
        d.agent(d.L(en="Nobody got in: every successful login is a public-key login from the VPN range, by people who have keys on this box. The rest is failed brute force.",
                    it="Non è entrato nessuno: tutti i login riusciti sono con chiave pubblica dal range VPN, da persone che hanno le chiavi su questa macchina. Il resto è brute force fallito.",
                    de="Niemand ist reingekommen: Alle erfolgreichen Logins sind Public-Key-Logins aus dem VPN-Bereich von Leuten, die hier Schlüssel hinterlegt haben. Der Rest ist gescheitertes Brute-Forcing.",
                    fr="Personne n'est entré : toutes les connexions réussies sont par clé publique depuis la plage VPN, par des personnes qui ont leurs clés sur cette machine. Le reste est du brute force raté.",
                    es="No entró nadie: todos los logins correctos son con clave pública desde el rango de la VPN, de gente que tiene claves en esta máquina. Lo demás es fuerza bruta fallida."))
    if r.random() < 0.75:
        d.tool("sh", "sudo fail2ban-client status sshd",
               lines("Status for the jail: sshd", "|- Filter", f"|  |- Currently failed:\t{r.randint(0, 12)}",
                     f"|  |- Total failed:\t{r.randint(200, 6000)}", "|  `- Journal matches:\t_SYSTEMD_UNIT=sshd.service + _COMM=sshd",
                     "`- Actions", f"   |- Currently banned:\t{len(attackers)}", f"   |- Total banned:\t{len(attackers) + r.randint(5, 80)}",
                     F("   `- Banned IP list:\t", J(" ", attackers))))
    d.tool("edit", "/etc/ssh/sshd_config.d/50-hardening.conf",
           lines("+PasswordAuthentication no", "+KbdInteractiveAuthentication no", "+PermitRootLogin no",
                 f"+MaxAuthTries {r.choice([3, 4])}"))
    d.agent(say(d, "done"), "\n- ",
            d.L(en="password authentication disabled (sshd reload needed)", it="autenticazione via password disattivata (serve reload di sshd)",
                de="Passwort-Authentifizierung deaktiviert (sshd-Reload nötig)", fr="authentification par mot de passe désactivée (reload de sshd nécessaire)",
                es="autenticación por contraseña desactivada (hay que recargar sshd)"))


# ---------------------------------------------------------------------------------------------------------------
# 4. JSON application logs through jq


@template("json_logs_jq", "box", "log", "shell")
def json_logs_jq(d):
    g, x, r = d.g, d.x, d.rng
    cust = d.person()
    cust_mail = g.email(cust, "personal")
    d.user(d.L(
        en="Support ticket: customer ", it="Ticket dal supporto: il cliente ", de="Support-Ticket: Kunde ",
        fr="Ticket support : le client ", es="Ticket de soporte: el cliente "), cust_mail,
        d.L(en=" says checkout keeps failing since yesterday. Can you dig through the checkout logs?",
            it=" dice che il checkout fallisce da ieri. Puoi scavare nei log del checkout?",
            de=" sagt, der Checkout schlägt seit gestern fehl. Kannst du die Checkout-Logs durchsuchen?",
            fr=" dit que le paiement échoue depuis hier. Tu peux fouiller les logs du checkout ?",
            es=" dice que el checkout falla desde ayer. ¿Puedes revisar los logs del checkout?"))
    cause = r.choice(["postcode", "3ds"])
    others = d.people(r.randint(2, 6))
    ids = {}

    def uid(p):
        return ids.setdefault(id(p), g.cust())

    ips = {}

    def ip_of(p):
        return ips.setdefault(id(p), g.ip(r.choice(["public", "public", "v6"])))

    def entry(p, level, msg, extra=None):
        la, lo = g.geo_parts(p)
        parts = [T('{"ts":"⟦t⟧","level":"⟦lv⟧","msg":"⟦m⟧","req_id":"⟦rid⟧","user":{"id":"⟦id⟧","email":"⟦e⟧"},"ip":"⟦ip⟧","geo":{"lat":⟦la⟧,"lon":⟦lo⟧}',
                   t=x.ts("iso_z", tick=(1, 400)), lv=level, m=msg, rid=x.rid(), id=uid(p),
                   e=cust_mail if p is cust else g.email(p, "personal"), ip=ip_of(p), la=la, lo=lo)]
        if extra:
            parts.append(extra)
        parts.append(T(',"ua":"⟦ua⟧"}', ua=r.choice(_UAS)))
        return F(*parts)

    def err_entry(p):
        if cause == "postcode":
            return entry(p, "error", "address_validation_failed",
                         T(',"field":"shipping.postcode","value":"⟦pc⟧","country":"⟦c⟧"', pc=g.addr(p, "postcode"), c=p.country))
        return entry(p, "error", "payment_authorization_failed",
                     T(',"psp":"⟦psp⟧","reason":"3ds_challenge_timeout","elapsed_ms":⟦ms⟧', psp=x.ent(r.choice(["Stripe", "Adyen"])),
                       ms=str(r.randint(10001, 10400))))

    rows = []
    n = r.randint(4, 18)
    for i in range(n):
        p = cust if (i % r.randint(2, 4) == 0) else r.choice(others)
        k = r.random()
        if p is cust or k < 0.35:
            rows.append(err_entry(p))
        elif k < 0.7:
            rows.append(entry(p, "error", r.choice(["inventory_reservation_expired", "coupon_invalid", "cart_stale"])))
        else:
            rows.append(entry(p, "warn", r.choice(["slow_psp_response", "retrying_tax_lookup"])))
    d.tool("sh", "kubectl -n shop logs deploy/checkout --since=24h | jq -c 'select(.level==\"error\" or .level==\"warn\")' | tail -n 40",
           lines(*rows))
    d.agent(d.L(en="Filtering on that customer only:", it="Filtro solo quel cliente:", de="Ich filtere nur auf diesen Kunden:",
                fr="Je filtre sur ce client uniquement :", es="Filtro solo ese cliente:"))
    def proj(p):
        if cause == "postcode":
            return T('{"ts":"⟦t⟧","msg":"address_validation_failed","field":"shipping.postcode","value":"⟦pc⟧","reason":null,"ip":"⟦ip⟧"}',
                     t=x.ts("iso_z", tick=(30, 3000)), pc=g.addr(p, "postcode"), ip=ip_of(p))
        return T('{"ts":"⟦t⟧","msg":"payment_authorization_failed","field":null,"value":null,"reason":"3ds_challenge_timeout","ip":"⟦ip⟧"}',
                 t=x.ts("iso_z", tick=(30, 3000)), ip=ip_of(p))

    mine = [proj(cust) for _ in range(r.randint(2, 7))]
    d.tool("sh", T("kubectl -n shop logs deploy/checkout --since=48h | jq -c 'select(.user.email==\"⟦e⟧\") | {ts, msg, field, value, reason, ip}'",
                   e=cust_mail), lines(*mine))
    if cause == "postcode":
        d.tool("read", "src/validation/address.ts", numbered(lines(
            "export const POSTCODE = /^[0-9]{5}$/;",
            "",
            "export function validateShipping(addr: Address): ValidationError[] {",
            "  const errors: ValidationError[] = [];",
            "  if (!POSTCODE.test(addr.postcode.trim())) {",
            "    errors.push({ field: 'shipping.postcode', code: 'invalid' });",
            "  }",
            "  return errors;",
            "}"), start=1))
        d.agent(say(d, "explain"), "\n",
                d.L(en="the postcode check assumes five digits. Customers from countries with other formats (letters, dashes, spaces) can never complete checkout. I'll validate per country instead.",
                    it="il controllo sul CAP presume cinque cifre. I clienti di paesi con altri formati (lettere, trattini, spazi) non possono mai completare il checkout. Lo farò per paese.",
                    de="die PLZ-Prüfung geht von fünf Ziffern aus. Kunden aus Ländern mit anderen Formaten (Buchstaben, Bindestriche, Leerzeichen) kommen nie durch den Checkout. Ich validiere stattdessen pro Land.",
                    fr="la vérification du code postal suppose cinq chiffres. Les clients de pays avec d'autres formats (lettres, tirets, espaces) ne peuvent jamais finaliser. Je valide par pays à la place.",
                    es="la validación del código postal asume cinco dígitos. Los clientes de países con otros formatos (letras, guiones, espacios) nunca pueden terminar el checkout. Validaré por país."))
        d.tool("edit", "src/validation/address.ts", lines(
            "-export const POSTCODE = /^[0-9]{5}$/;",
            "+const POSTCODE: Record<string, RegExp> = {",
            "+  DE: /^\\d{5}$/, FR: /^\\d{5}$/, IT: /^\\d{5}$/, ES: /^\\d{5}$/,",
            "+  NL: /^\\d{4} ?[A-Z]{2}$/, PT: /^\\d{4}-\\d{3}$/, PL: /^\\d{2}-\\d{3}$/,",
            "+  GB: /^[A-Z]{1,2}\\d[A-Z\\d]? ?\\d[A-Z]{2}$/i, US: /^\\d{5}(-\\d{4})?$/,",
            "+};",
            "-  if (!POSTCODE.test(addr.postcode.trim())) {",
            "+  const re = POSTCODE[addr.country];",
            "+  if (re && !re.test(addr.postcode.trim())) {"))
    else:
        d.agent(say(d, "explain"), "\n",
                d.L(en="the PSP call is aborted after exactly 10 s, but the 3-D Secure challenge regularly takes longer for this card issuer. The timeout in config is too aggressive.",
                    it="la chiamata al PSP viene interrotta dopo 10 s esatti, ma la challenge 3-D Secure con questo emittente dura spesso di più. Il timeout in config è troppo aggressivo.",
                    de="der PSP-Aufruf wird nach genau 10 s abgebrochen, aber die 3-D-Secure-Challenge dauert bei diesem Kartenaussteller oft länger. Der Timeout ist zu knapp.",
                    fr="l'appel au PSP est interrompu après 10 s pile, mais le challenge 3-D Secure de cet émetteur dure souvent plus. Le timeout est trop agressif.",
                    es="la llamada al PSP se corta a los 10 s exactos, pero el reto 3-D Secure de este emisor suele tardar más. El timeout es demasiado agresivo."))
        d.tool("edit", "config/payments.yaml", lines("-  authorization_timeout_ms: 10000", "+  authorization_timeout_ms: 45000",
                                                     "+  # 3DS challenges can take >30s on mobile banking apps"))
    d.user(d.L(en="Also: why are we logging full emails and coordinates at all? Write a redaction rule for the log shipper.",
               it="Poi: perché logghiamo email complete e coordinate? Scrivi una regola di redaction per il log shipper.",
               de="Außerdem: Warum loggen wir überhaupt komplette E-Mails und Koordinaten? Schreib eine Redaction-Regel für den Log-Shipper.",
               fr="Et pourquoi on logue des e-mails complets et des coordonnées ? Écris une règle de masquage pour le log shipper.",
               es="Además: ¿por qué logueamos emails completos y coordenadas? Escribe una regla de redacción para el log shipper."))
    d.tool("write", "deploy/vector/redact.toml", lines(
        "[transforms.redact_pii]", 'type = "remap"', 'inputs = ["checkout_logs"]', 'source = \'\'\'',
        "  if exists(.user.email) { .user.email = redact(.user.email, filters: [r'^[^@]+'], redactor: \"full\") }",
        "  del(.geo)",
        "  if exists(.value) && .field == \"shipping.postcode\" { .value = \"[redacted]\" }",
        "  .ip = ip_subnet!(.ip, \"/24\")", "\'\'\'"))
    d.agent(say(d, "done"), "\n- ",
            d.L(en="fix for the checkout failure (see diff above)", it="correzione per l'errore di checkout (vedi diff sopra)",
                de="Fix für den Checkout-Fehler (siehe Diff oben)", fr="correctif pour l'échec du paiement (voir diff ci-dessus)",
                es="corrección del fallo del checkout (ver diff arriba)"),
            "\n- ", d.L(en="Vector transform that drops geo, masks e-mail local parts and truncates IPs to /24",
                        it="transform di Vector che rimuove geo, maschera la parte locale delle e-mail e tronca gli IP a /24",
                        de="Vector-Transform, der geo entfernt, E-Mail-Localparts maskiert und IPs auf /24 kürzt",
                        fr="transform Vector qui supprime geo, masque la partie locale des e-mails et tronque les IP en /24",
                        es="transform de Vector que elimina geo, enmascara la parte local de los emails y trunca las IP a /24"),
            "\n\n", say(d, "not_committed"))


# ---------------------------------------------------------------------------------------------------------------
# 5. DHCP leases and MAC reservations


_DEV_HOSTNAMES = ["printer-2f", "meeting-room-tv", "NPI3A41F2", "android-7f3c2a9e1b", "iPhone", "DESKTOP-4KQ2M1T",
                  "raspberrypi", "ESP_3A41F2", "ap-floor1", "voip-phone-12", "LAPTOP-8HD20QX", "Galaxy-S23",
                  "sonos-kitchen", "nas-01", "badge-reader-lobby"]


@template("dhcp_leases_mac", "hai", "log", "file")
def dhcp_leases_mac(d):
    g, x, r = d.g, d.x, d.rng
    net = r.choice(["192.168.10", "192.168.1", "10.20.0"]) if d.gold_ok else "192.0.2"

    def hip(n: int) -> Seg:
        if d.gold_ok:
            return g.raw("private_ip", f"{net}.{n}", "generic")
        return Seg(f"{net}.{n}", cls="reserved_ip")
    d.user(d.L(
        en="One of the laptops in the office keeps getting a different IP than its reservation, so the VPN split-tunnel rules don't match. Can you check the DHCP server?",
        it="Uno dei portatili in ufficio continua a prendere un IP diverso dalla sua prenotazione, quindi le regole split-tunnel della VPN non corrispondono. Puoi controllare il server DHCP?",
        de="Einer der Laptops im Büro bekommt ständig eine andere IP als seine Reservierung, deshalb greifen die Split-Tunnel-Regeln nicht. Kannst du den DHCP-Server prüfen?",
        fr="Un des portables du bureau obtient sans arrêt une IP différente de sa réservation, du coup les règles de split-tunnel VPN ne collent pas. Tu peux regarder le serveur DHCP ?",
        es="Uno de los portátiles de la oficina sigue cogiendo una IP distinta a su reserva, así que las reglas de split-tunnel de la VPN no casan. ¿Puedes revisar el servidor DHCP?"))
    owners = d.people(r.randint(2, 5))
    reserved = []
    for i, o in enumerate(owners):
        mac_raw = V.mac_addr(r, 0)
        reserved.append({"p": o, "mac_raw": mac_raw, "ip": hip(20 + i),
                         "host": f"lab-laptop-{r.randint(1, 40):02d}"})
    victim = reserved[0]
    new_mac = V.mac_addr(r, 0)

    def mac_seg(raw):
        return g.raw("private_mac", raw, "mac")

    def lease_block(ip, mac, hostname):
        st = d.clock.tick(60, 9000)
        dow = (st.weekday() + 1) % 7
        starts = x.ts("slash")
        ends_t = st + _dt.timedelta(hours=12)
        return lines(
            F("lease ", ip, " {"),
            F("  starts ", str(dow), " ", starts, ";"),
            F("  ends ", str(dow), " ", x.ts("slash", t=ends_t), ";"),
            F("  cltt ", str(dow), " ", x.ts("slash", t=st), ";"),
            "  binding state active;", "  next binding state free;", "  rewind binding state free;",
            F("  hardware ethernet ", mac, ";"),
            F('  client-hostname "', hostname, '";'),
            "}")

    blocks = [F("# The format of this file is documented in the dhcpd.leases(5) manual page.\n",
                "# This lease file was written by isc-dhcp-", x.ver(r.choice(["4.4.3", "4.4.1"])), "\n\n",
                'server-duid "\\000\\001\\000\\001', V.rand_str(r, "0123456789", 4), '";\n\n')]
    dyn_ip = hip(r.randint(100, 199))
    n_other = r.randint(2, 9)
    pos = r.randrange(n_other + 1)
    for i in range(n_other + 1):
        if i == pos:
            blocks.append(lease_block(dyn_ip, mac_seg(new_mac), victim["host"]))
        else:
            ipx = hip(r.randint(100, 250))
            blocks.append(lease_block(ipx, g.mac(r.choice([0, 0, 1])), r.choice(_DEV_HOSTNAMES)))
        blocks.append(F("\n"))
    d.tool("read", "/var/lib/dhcp/dhcpd.leases", F(*blocks))
    iface = r.choice(["eth1", "br0", "vlan20"])
    dpid = x.num(lo=300, hi=3000)
    sys_rows = []
    for _ in range(r.randint(1, 3)):
        d.clock.tick(600, 20000)
        for kind in ("DISCOVER", "OFFER", "REQUEST", "ACK"):
            pre = F(x.ts("syslog", tick=(0, 1), local=True), " gw dhcpd[", dpid, "]: ")
            if kind == "DISCOVER":
                sys_rows.append(F(pre, "DHCPDISCOVER from ", mac_seg(new_mac), " (", victim["host"], ") via ", iface))
            elif kind == "OFFER":
                sys_rows.append(F(pre, "DHCPOFFER on ", dyn_ip, " to ", mac_seg(new_mac), " (", victim["host"], ") via ", iface))
            elif kind == "REQUEST":
                sys_rows.append(F(pre, "DHCPREQUEST for ", dyn_ip, " (", hip(1), ") from ", mac_seg(new_mac), " (", victim["host"], ") via ", iface))
            else:
                sys_rows.append(F(pre, "DHCPACK on ", dyn_ip, " to ", mac_seg(new_mac), " (", victim["host"], ") via ", iface))
    d.tool("sh", T("grep -E 'DHCP(ACK|OFFER|REQUEST|DISCOVER)' /var/log/syslog | grep -i ⟦h⟧ | tail -n ⟦n⟧", h=victim["host"], n=str(len(sys_rows))),
           lines(*sys_rows))
    conf = [F("# /etc/dhcp/dhcpd.conf — static reservations\n", "option domain-name \"", d.int_domain, "\";\n",
              "default-lease-time 43200;\nmax-lease-time 86400;\n\n",
              "subnet ", hip(0), " netmask 255.255.255.0 {\n  range ", hip(100), " ", hip(250), ";\n  option routers ",
              hip(1), ";\n}\n\n")]
    for res in reserved:
        conf.append(T("host ⟦h⟧ {  # ⟦n⟧ (⟦e⟧)\n  hardware ethernet ⟦m⟧;\n  fixed-address ⟦ip⟧;\n}\n",
                      h=res["host"], n=g.name(res["p"]), e=g.email(res["p"]), m=mac_seg(res["mac_raw"]), ip=res["ip"]))
    d.tool("read", "/etc/dhcp/dhcpd.conf", F(*conf))
    d.agent(say(d, "explain"), "\n",
            d.L(en=f"the reservation for {victim['host']} is bound to the old hardware address, but the machine now presents a different MAC — most likely the dock/USB-C adapter changed or the OS uses a randomized address on that network. dhcpd doesn't match it to the host block, so it hands out a dynamic lease.",
                it=f"la prenotazione per {victim['host']} è legata al vecchio indirizzo hardware, ma ora la macchina presenta un MAC diverso: probabilmente è cambiato il dock/adattatore USB-C o il sistema usa un indirizzo casuale su quella rete. dhcpd non lo associa al blocco host e assegna un lease dinamico.",
                de=f"die Reservierung für {victim['host']} hängt an der alten Hardwareadresse, das Gerät meldet aber inzwischen eine andere MAC — vermutlich anderes Dock/USB-C-Adapter oder eine zufällige MAC im WLAN. dhcpd ordnet es dem host-Block nicht zu und vergibt eine dynamische Lease.",
                fr=f"la réservation de {victim['host']} est liée à l'ancienne adresse matérielle, mais la machine présente maintenant une autre MAC — sans doute un nouveau dock/adaptateur USB-C ou une adresse aléatoire sur ce réseau. dhcpd ne la rattache pas au bloc host et attribue un bail dynamique.",
                es=f"la reserva de {victim['host']} está ligada a la dirección hardware antigua, pero el equipo presenta ahora otra MAC: seguramente cambió el dock/adaptador USB-C o el sistema usa una dirección aleatoria en esa red. dhcpd no la asocia al bloque host y da un lease dinámico."))
    d.user(d.L(en="Yes, new dock. Update it.", it="Sì, dock nuovo. Aggiornalo.", de="Ja, neues Dock. Aktualisier das.",
               fr="Oui, nouveau dock. Mets à jour.", es="Sí, dock nuevo. Actualízalo."))
    d.tool("edit", "/etc/dhcp/dhcpd.conf", T("-  hardware ethernet ⟦a⟧;\n+  hardware ethernet ⟦b⟧;\n", a=mac_seg(victim["mac_raw"]), b=mac_seg(new_mac)))
    d.tool("sh", "sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf && sudo systemctl restart isc-dhcp-server && systemctl is-active isc-dhcp-server",
           lines(F("Internet Systems Consortium DHCP Server ", x.ver(r.choice(["4.4.3-P1", "4.4.1"]))),
                 "Copyright 2004-2022 Internet Systems Consortium.", "All rights reserved.",
                 F("For info, please visit ", x.url(text="https://www.isc.org/software/dhcp/")),
                 "Config file: /etc/dhcp/dhcpd.conf", "Database file: /var/lib/dhcp/dhcpd.leases",
                 "PID file: /var/run/dhcpd.pid", "active"))
    d.agent(d.L(en="Config validated and server restarted. The laptop will get its reserved address at the next renewal (or after `sudo ipconfig set en0 DHCP` / reconnecting).",
                it="Configurazione validata e server riavviato. Il portatile prenderà l'indirizzo prenotato al prossimo rinnovo (o riconnettendosi).",
                de="Konfiguration validiert und Server neu gestartet. Der Laptop bekommt seine reservierte Adresse beim nächsten Renew (oder nach einem Reconnect).",
                fr="Config validée et serveur redémarré. Le portable récupérera son adresse réservée au prochain renouvellement (ou après reconnexion).",
                es="Configuración validada y servidor reiniciado. El portátil cogerá su IP reservada en la próxima renovación (o al reconectar)."))


# ---------------------------------------------------------------------------------------------------------------
# 6. Fleet telematics


@template("fleet_telematics", "irc", "log", "file")
def fleet_telematics(d):
    g, x, r = d.g, d.x, d.rng
    depot = r.choice(["north depot", "Hub-2", "depot-mi-01", "Lager Süd", "entrepôt Est", "Bilbao hub"])
    d.user(d.L(
        en=f"Geofence alerts for {depot} fire when trucks are nowhere near it. Ingest log and yesterday's trips export are in data/. Can you find the bug?",
        it=f"Gli alert di geofence per {depot} scattano quando i camion non sono nemmeno vicini. Log di ingest ed export viaggi di ieri sono in data/. Trovi il bug?",
        de=f"Die Geofence-Alarme für {depot} feuern, obwohl die LKW weit weg sind. Ingest-Log und der Trip-Export von gestern liegen in data/. Findest du den Bug?",
        fr=f"Les alertes de geofence pour {depot} se déclenchent alors que les camions en sont loin. Le log d'ingestion et l'export des trajets d'hier sont dans data/. Tu trouves le bug ?",
        es=f"Las alertas de geocerca de {depot} saltan cuando los camiones ni están cerca. El log de ingesta y el export de viajes de ayer están en data/. ¿Encuentras el bug?"))
    drivers = d.people(r.randint(2, 5))
    trucks = [{"drv": p, "vin": g.vin(), "plate": g.plate(p), "dl": g.dl(p), "ph": g.phone(p, True)} for p in drivers]
    rows = []
    n = r.randint(5, 24)
    for _ in range(n):
        t = r.choice(trucks)
        la, lo = g.geo_parts(t["drv"])
        ev = r.choice(["POS", "POS", "POS", "GEOFENCE_ENTER", "GEOFENCE_EXIT", "IGNITION_OFF"])
        rows.append(T('⟦ts⟧ INFO  ingest.telemetry ev=⟦ev⟧ vin=⟦vin⟧ plate="⟦pl⟧" driver="⟦drv⟧" lic=⟦dl⟧ lat=⟦la⟧ lon=⟦lo⟧ speed=⟦sp⟧ hdg=⟦h⟧ fence=⟦f⟧',
                      ts=x.ts("iso_z", tick=(3, 120)), ev=ev, vin=t["vin"], pl=t["plate"], drv=g.name(t["drv"]),
                      dl=t["dl"], la=la, lo=lo, sp=f"{r.uniform(0, 92):.1f}", h=str(r.randint(0, 359)),
                      f=("depot-01" if ev.startswith("GEOFENCE") else "-")))
        if r.random() < 0.08:
            rows.append(T("⟦ts⟧ WARN  ingest.telemetry gps fix degraded hdop=⟦h⟧ vin=⟦vin⟧", ts=x.ts("iso_z", tick=(0.1, 2)),
                          h=f"{r.uniform(2, 9):.1f}", vin=t["vin"]))
    d.tool("sh", f"grep -E 'ev=(POS|GEOFENCE|IGNITION)' data/ingest.log | tail -n {n}", lines(*rows))
    csv = ["trip_id,vin,plate,driver_name,driver_phone,start_ts,start_lat,start_lon,end_lat,end_lon,km"]
    trip_rows = [F(*csv, "\n")]
    for i in range(r.randint(2, 8)):
        t = r.choice(trucks)
        la1, lo1 = g.geo_parts(t["drv"])
        la2, lo2 = g.geo_parts(t["drv"])
        trip_rows.append(T("⟦id⟧,⟦vin⟧,⟦pl⟧,⟦n⟧,⟦ph⟧,⟦ts⟧,⟦a⟧,⟦b⟧,⟦c⟧,⟦e⟧,⟦km⟧\n", id=x.num(lo=100000, hi=999999),
                           vin=t["vin"], pl=t["plate"], n=g.name(t["drv"]), ph=t["ph"],
                           ts=x.ts("iso_s", tick=(600, 7200)), a=la1, b=lo1, c=la2, e=lo2, km=f"{r.uniform(3, 380):.1f}"))
    d.tool("read", "data/trips_export.csv", F(*trip_rows))
    bug = r.choice(["swap", "radians"])
    if bug == "swap":
        code = lines("def inside(fence: Polygon, lat: float, lon: float) -> bool:",
                     "    # ray casting over (x=lon, y=lat) vertices",
                     "    x, y = lat, lon",
                     "    hit = False",
                     "    for (x1, y1), (x2, y2) in zip(fence.vertices, fence.vertices[1:] + fence.vertices[:1]):",
                     "        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:",
                     "            hit = not hit",
                     "    return hit")
    else:
        code = lines("def distance_m(lat1, lon1, lat2, lon2):",
                     "    dlat = lat2 - lat1",
                     "    dlon = lon2 - lon1",
                     "    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2",
                     "    return 2 * EARTH_RADIUS_M * asin(sqrt(a))",
                     "",
                     "def inside(fence: Circle, lat: float, lon: float) -> bool:",
                     "    return distance_m(fence.lat, fence.lon, lat, lon) <= fence.radius_m")
    d.tool("read", "telemetry/geofence.py", numbered(code, start=r.randint(10, 60)))
    if bug == "swap":
        d.agent(d.L(en="Found it: the vertices are stored as (lon, lat) but the point is unpacked as (lat, lon). For any fence away from the equator the test runs against a mirrored point, so random positions fall 'inside'.",
                    it="Trovato: i vertici sono salvati come (lon, lat) ma il punto viene spacchettato come (lat, lon). Per qualsiasi recinto lontano dall'equatore il test usa un punto speculare, quindi posizioni a caso risultano 'dentro'.",
                    de="Gefunden: Die Eckpunkte sind als (lon, lat) gespeichert, der Punkt wird aber als (lat, lon) entpackt. Für jeden Zaun abseits des Äquators wird gegen einen gespiegelten Punkt getestet, daher landen zufällige Positionen 'innen'.",
                    fr="Trouvé : les sommets sont stockés en (lon, lat) mais le point est décomposé en (lat, lon). Pour toute zone loin de l'équateur, le test se fait sur un point inversé, d'où des positions aléatoires 'dedans'.",
                    es="Encontrado: los vértices se guardan como (lon, lat) pero el punto se desempaqueta como (lat, lon). Para cualquier geocerca lejos del ecuador se prueba un punto reflejado, así que posiciones aleatorias quedan 'dentro'."))
        d.tool("edit", "telemetry/geofence.py", lines("-    x, y = lat, lon", "+    x, y = lon, lat"))
    else:
        d.agent(d.L(en="Found it: the haversine formula is fed degrees instead of radians, so distances are wildly off and the radius check passes for points tens of km away.",
                    it="Trovato: alla formula dell'haversine passano gradi invece di radianti, quindi le distanze sono sballate e il controllo sul raggio passa per punti a decine di km.",
                    de="Gefunden: Die Haversine-Formel bekommt Grad statt Bogenmaß, die Distanzen sind dadurch völlig falsch und der Radius-Check greift für Punkte zig km entfernt.",
                    fr="Trouvé : la formule de haversine reçoit des degrés au lieu de radians, les distances sont fausses et le test de rayon passe pour des points à des dizaines de km.",
                    es="Encontrado: a la fórmula de haversine le llegan grados en vez de radianes, así que las distancias salen mal y el radio se cumple para puntos a decenas de km."))
        d.tool("edit", "telemetry/geofence.py", lines("-    dlat = lat2 - lat1", "-    dlon = lon2 - lon1",
                                                      "+    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))",
                                                      "+    dlat = lat2 - lat1", "+    dlon = lon2 - lon1"))
    npass = r.randint(4, 11)
    d.tool("sh", "pytest tests/test_geofence.py -q",
           F("." * npass, " " * (44 - npass), "[100%]\n", str(npass), " passed in ", f"{r.uniform(0.05, 0.9):.2f}", "s\n"))
    if d.gold_ok and r.random() < 0.6:
        d.agent(d.L(en="Side note: the ingest log writes driver names and licence numbers next to raw coordinates on every position update. That's a lot of personal location data in plain logs; consider logging only the VIN hash.",
                    it="Nota a margine: il log di ingest scrive nomi e numeri di patente degli autisti accanto alle coordinate a ogni aggiornamento. Sono molti dati di localizzazione personali nei log; valuta di loggare solo un hash del VIN.",
                    de="Randnotiz: Das Ingest-Log schreibt bei jedem Positionsupdate Fahrernamen und Führerscheinnummern neben die Koordinaten. Das sind viele personenbezogene Standortdaten im Klartext; besser nur einen VIN-Hash loggen.",
                    fr="Remarque : le log d'ingestion écrit le nom et le numéro de permis des chauffeurs à côté des coordonnées à chaque mise à jour. Ça fait beaucoup de données de localisation personnelles ; mieux vaut ne loguer qu'un hash du VIN.",
                    es="Nota: el log de ingesta escribe nombre y número de carné de los conductores junto a las coordenadas en cada actualización. Son muchos datos de localización personales en claro; mejor loguear solo un hash del VIN."))
    d.user(say(d, "thanks"))


# ---------------------------------------------------------------------------------------------------------------
# 7. Admin audit trail


@template("audit_log_admin_actions", "react", "log")
def audit_log_admin_actions(d):
    g, x, r = d.g, d.x, d.rng
    d.user(d.L(
        en="Compliance wants to know who changed customers' bank details over the last 7 days. Pull it from the audit log and write a short report in reports/.",
        it="La compliance vuole sapere chi ha modificato le coordinate bancarie dei clienti negli ultimi 7 giorni. Estrailo dall'audit log e scrivi un breve report in reports/.",
        de="Compliance will wissen, wer in den letzten 7 Tagen Bankdaten von Kunden geändert hat. Zieh das aus dem Audit-Log und schreib einen kurzen Bericht nach reports/.",
        fr="La conformité veut savoir qui a modifié les coordonnées bancaires des clients ces 7 derniers jours. Sors ça du journal d'audit et écris un court rapport dans reports/.",
        es="Cumplimiento quiere saber quién cambió los datos bancarios de clientes en los últimos 7 días. Sácalo del log de auditoría y escribe un informe corto en reports/."))
    agents = d.people(r.randint(2, 4))
    agent_ips = [g.ip("private") for _ in agents]
    agent_mail = [g.email(a) for a in agents]
    odd = r.randrange(len(agents))
    odd_ip = g.ip("public")
    source = r.choice(["db", "file"])
    entries = []
    act_pool = ["update_iban", "update_iban", "update_iban", "update_address"]
    if r.random() < 0.6:
        act_pool.append("update_id_document")
    acts_sql = ",".join(f"'{a}'" for a in dict.fromkeys(act_pool))
    acts_re = "|".join(dict.fromkeys(act_pool))
    n = r.randint(3, 18)
    d.clock.jump(1, 3)
    for i in range(n):
        a = r.randrange(len(agents))
        if a == odd and r.random() < 0.5:
            ip = odd_ip
        else:
            ip = agent_ips[a]
        c = d.person()
        act = r.choice(act_pool)
        if act == "update_iban":
            old, new = g.iban(p=c), g.iban(p=c)
        elif act == "update_id_document":
            old, new = g.passport(c), g.passport(c)
        else:
            old, new = g.addr(c), g.addr(d.person(c.locale))
        entries.append({"t": x.ts("space", tick=(600, 40000)), "actor": agents[a], "cust": g.cust(), "act": act,
                        "old": old, "new": new, "ip": ip, "a": a})
    if source == "db":
        d.agent(d.L(en="The audit trail lives in the audit_log table. Querying the last 7 days of bank/address changes.",
                    it="L'audit trail è nella tabella audit_log. Interrogo le modifiche a IBAN/indirizzi degli ultimi 7 giorni.",
                    de="Der Audit-Trail liegt in der Tabelle audit_log. Ich frage die Bank-/Adressänderungen der letzten 7 Tage ab.",
                    fr="La piste d'audit est dans la table audit_log. Je requête les changements bancaires/adresses des 7 derniers jours."))
        d.call("sh", "psql -h db-replica-1 -U readonly backoffice -c \"SELECT created_at, actor_email, customer_no, action, old_value, new_value, source_ip FROM audit_log WHERE action IN (" + acts_sql + ") AND created_at > now() - interval '7 days' ORDER BY created_at\"")
        d.result("sh", grid(["created_at", "actor_email", "customer_no", "action", "old_value", "new_value", "source_ip"],
                            [[e["t"], agent_mail[e["a"]], e["cust"], e["act"], e["old"], e["new"], e["ip"]] for e in entries]))
    else:
        d.agent(d.L(en="The backoffice writes its audit trail to a log file. Grepping the relevant actions.",
                    it="Il backoffice scrive l'audit trail su file. Filtro le azioni rilevanti.",
                    de="Das Backoffice schreibt den Audit-Trail in eine Logdatei. Ich filtere die relevanten Aktionen.",
                    fr="Le backoffice écrit la piste d'audit dans un fichier. Je filtre les actions concernées."))
        d.call("sh", "grep -E 'action=(" + acts_re + ")' /var/log/backoffice/audit.log | tail -n 200")
        d.result("sh", lines(*[T('ts=⟦t⟧ actor=⟦a⟧ action=⟦act⟧ target=⟦c⟧ old="⟦o⟧" new="⟦n⟧" ip=⟦ip⟧ session=⟦s⟧',
                                   t=e["t"], a=agent_mail[e["a"]], act=e["act"], c=e["cust"], o=e["old"], n=e["new"],
                                   ip=e["ip"], s=x.short(16)) for e in entries]))
    per = {}
    for e in entries:
        per[e["a"]] = per.get(e["a"], 0) + 1
    order = sorted(per, key=lambda k: (-per[k], k))
    d.agent(d.L(en="Counting changes per actor and source address:", it="Conto le modifiche per operatore e indirizzo di origine:",
                de="Ich zähle Änderungen pro Akteur und Quelladresse:", fr="Je compte les changements par acteur et adresse source :"))
    d.tool("sh", "psql ... -c \"SELECT actor_email, count(*), count(DISTINCT source_ip) FROM audit_log WHERE ... GROUP BY 1 ORDER BY 2 DESC\"",
           grid(["actor_email", "count", "ips"], [[agent_mail[k], str(per[k]), str(1 + (k == odd))] for k in order]))
    flag = any(e["a"] == odd and e["ip"] is odd_ip for e in entries)
    rep = [F("# Bank-detail changes — last 7 days\n\n", "Generated from `audit_log` on ", x.ts("date"), ".\n\n",
             "| Actor | Changes | Notes |\n|---|---|---|\n")]
    for k in order:
        note = F("changes from an address outside the office range (", odd_ip, ")") if (k == odd and flag) else "—"
        rep.append(F("| ", g.name(agents[k]), " | ", str(per[k]), " | ", note, " |\n"))
    rep.append(F("\nIBANs in this report are masked (e.g. ", x.ph(text=r.choice(["IT** **** **** 4821", "****1234", "DE** **** 0017"])),
                 "); full values are in the audit table.\n"))
    if flag:
        rep.append(F("\n## Follow-up\n\nConfirm with ", g.name(agents[odd]), " whether the changes from ", odd_ip,
                     " were made over the VPN; if not, freeze the affected payouts.\n"))
    d.tool("write", f"reports/bank-detail-changes-{r.choice(['w11', 'w37', 'week', 'last7d'])}.md", F(*rep))
    d.agent(say(d, "done"), "\n",
            d.L(en=f"{len(entries)} changes by {len(agents)} people. ", it=f"{len(entries)} modifiche da parte di {len(agents)} persone. ",
                de=f"{len(entries)} Änderungen von {len(agents)} Personen. ", fr=f"{len(entries)} changements par {len(agents)} personnes. ",
                es=f"{len(entries)} cambios de {len(agents)} personas. "),
            (d.L(en="One actor also worked from an unexpected public IP; flagged in the report.",
                 it="Un operatore ha lavorato anche da un IP pubblico inatteso; segnalato nel report.",
                 de="Ein Akteur hat auch von einer unerwarteten öffentlichen IP gearbeitet; im Bericht markiert.",
                 fr="Un acteur a aussi travaillé depuis une IP publique inattendue ; signalé dans le rapport.",
                 es="Una persona trabajó también desde una IP pública inesperada; marcado en el informe.") if flag else ""))


# ---------------------------------------------------------------------------------------------------------------
# 8. Postfix bounces


_MX_BY_DOMAIN = {
    "gmail.com": "gmail-smtp-in.l.google.com", "outlook.com": "outlook-com.olc.protection.outlook.com",
    "hotmail.co.uk": "eur.olc.protection.outlook.com", "hotmail.es": "eur.olc.protection.outlook.com",
    "hotmail.nl": "eur.olc.protection.outlook.com", "hotmail.com": "hotmail-com.olc.protection.outlook.com",
    "outlook.it": "eur.olc.protection.outlook.com", "outlook.fr": "eur.olc.protection.outlook.com",
    "outlook.es": "eur.olc.protection.outlook.com", "outlook.pt": "eur.olc.protection.outlook.com",
    "web.de": "mx-ha03.web.de", "gmx.de": "mx00.gmx.net", "t-online.de": "mx00.t-online.de",
    "posteo.de": "mx01.posteo.de", "libero.it": "smtp-in.libero.it", "virgilio.it": "mx.virgilio.it",
    "tiscali.it": "mx.tiscali.it", "orange.fr": "smtp-in.orange.fr", "free.fr": "mx1.free.fr",
    "laposte.net": "mx.laposte.net", "wp.pl": "mx.wp.pl", "onet.pl": "mx.poczta.onet.pl",
    "interia.pl": "mx.poczta.interia.pl", "o2.pl": "mx.o2.pl", "sapo.pt": "mx.sapo.pt", "clix.pt": "mx.clix.pt",
    "yahoo.com": "mta5.am0.yahoodns.net", "yahoo.es": "mta6.am0.yahoodns.net", "proton.me": "mail.protonmail.ch",
    "icloud.com": "mx01.mail.icloud.com", "btinternet.com": "mx.bt.lon5.cpcloud.co.uk", "ziggo.nl": "mx.ziggo.nl",
    "kpnmail.nl": "mx.kpnmail.nl", "telefonica.net": "mx.telefonica.net",
}
_MX_FALLBACK = ["gmail-smtp-in.l.google.com", "mx00.gmx.net", "smtp-in.orange.fr", "mx.wp.pl"]


@template("mail_server_bounce", "steps", "log")
def mail_server_bounce(d):
    g, x, r = d.g, d.x, d.rng
    d.user(d.L(
        en="Several customers say they never receive their invoice e-mails. Can you check mail-relay and figure out what's going on?",
        it="Diversi clienti dicono di non ricevere mai le e-mail con la fattura. Puoi controllare mail-relay e capire cosa succede?",
        de="Mehrere Kunden sagen, dass ihre Rechnungs-E-Mails nie ankommen. Kannst du auf mail-relay nachsehen, was los ist?",
        fr="Plusieurs clients disent ne jamais recevoir leurs factures par e-mail. Tu peux regarder mail-relay et voir ce qui se passe ?",
        es="Varios clientes dicen que nunca reciben los emails de factura. ¿Puedes mirar mail-relay y ver qué pasa?"))
    cause = r.choice(["spf", "spf", "typo", "full"])
    relay_ip = g.ip("public")
    custs = d.people(r.randint(3, 7))
    mails = [g.email(c, "personal") for c in custs]
    mx_ips: dict = {}

    def mx_of(mail_seg):
        dom = mail_seg.text.rsplit("@", 1)[-1] if mail_seg.label else ""
        host = _MX_BY_DOMAIN.get(dom) or (f"mx1.{dom}" if dom else r.choice(_MX_FALLBACK))
        if host not in mx_ips:
            mx_ips[host] = g.ip("public")
        return host, mx_ips[host]

    smtp_pid = x.num(lo=1000, hi=60000)
    recs = []
    n = r.randint(3, 26)
    typo_at = r.randrange(n) if cause == "typo" else -1
    for i in range(n):
        ts = x.ts("syslog", tick=(5, 600), local=True)
        qid = x.id(V.rand_str(r, "0123456789ABCDEF", r.choice([10, 11])))
        if i == typo_at:
            bad = custs[0]
            dom = r.choice(['gmial.com', 'gmail.con', 'hotmial.com', 'outlok.com', 'gmx.dee', 'libero.ti'])
            bad_mail = g.raw("private_email", f"{bad.email_local()}@{dom}", "email")
            shown_dom = dom if d.gold_ok else "example.invalid"
            line = F(ts, " mail-relay postfix/smtp[", smtp_pid, "]: ", qid, ": to=<", bad_mail,
                     ">, relay=none, delay=0.4, delays=0.02/0/0.38/0, dsn=5.4.4, status=bounced (Host or domain name not found. Name service error for name=",
                     shown_dom, " type=MX: Host not found)")
            recs.append({"qid": qid, "mail": bad_mail, "line": line, "dsn": "5.4.4", "t": d.clock.t})
            continue
        j = r.randrange(len(custs))
        mail = mails[j]
        mx, ip = mx_of(mail)
        k = r.random()
        relay = F(mx, "[", ip, "]:25")
        if cause == "spf" and k < 0.6:
            dsn = "5.7.26"
            status = F("status=bounced (host ", mx, "[", ip, "] said: 550 5.7.26 Unauthenticated email from ",
                       d.domain, " is not accepted due to domain's DMARC policy (in reply to end of DATA command))")
        elif cause == "full" and k < 0.4:
            dsn = "4.2.2"
            status = F("status=deferred (host ", mx, "[", ip, "] said: 452 4.2.2 The email account that you tried to reach is over quota (in reply to RCPT TO command))")
        elif k < 0.85:
            dsn = "2.0.0"
            if "google" in mx:
                status = F("status=sent (250 2.0.0 OK  ", x.num(lo=1700000000, hi=1799999999), " ", x.short(12), " - gsmtp)")
            else:
                status = F("status=sent (250 2.0.0 Ok: queued as ", x.id(V.rand_str(r, "0123456789ABCDEFGHJKLMNPQRSTVWXYZ", 12)), ")")
        else:
            dsn = "4.4.1"
            relay = F("none")
            status = F("status=deferred (connect to ", mx, "[", ip, "]:25: Connection timed out)")
        line = F(ts, " mail-relay postfix/smtp[", smtp_pid, "]: ", qid, ": to=<", mail, ">, relay=", relay, ", delay=",
                 f"{r.uniform(0.2, 9):.1f}", ", delays=", f"{r.uniform(0, 0.3):.2f}/0/{r.uniform(0, 2):.1f}/{r.uniform(0, 3):.1f}",
                 ", dsn=", dsn, ", ", status)
        recs.append({"qid": qid, "mail": mail, "line": line, "dsn": dsn, "t": d.clock.t})
    d.tool("sh", f"sudo grep -E 'postfix/smtp.*status=' /var/log/mail.log | tail -n {len(recs)}", lines(*[rc["line"] for rc in recs]))
    want = {"spf": "5.7.26", "typo": "5.4.4", "full": "4.2.2"}[cause]
    failing = ([rc for rc in recs if rc["dsn"] == want] or [rc for rc in recs if rc["dsn"] != "2.0.0"] or recs)
    pick = r.choice(failing)
    qid = pick["qid"]
    t0 = pick["t"] - _dt.timedelta(seconds=r.uniform(2, 8))
    d.tool("sh", F("sudo grep ", qid, " /var/log/mail.log"),
           lines(F(x.ts("syslog", t=t0, local=True), " mail-relay postfix/smtpd[", x.num(lo=1000, hi=60000), "]: ", qid,
                   ": client=", r.choice(["billing-worker", "app-blue", "worker-3", d.host]), "[", g.ip("private"), "]"),
                 F(x.ts("syslog", t=t0 + _dt.timedelta(seconds=0.4), local=True), " mail-relay postfix/cleanup[", x.num(lo=1000, hi=60000), "]: ", qid,
                   ": message-id=<", x.uuid(), "@", d.domain, ">"),
                 F(x.ts("syslog", t=t0 + _dt.timedelta(seconds=1.1), local=True), " mail-relay postfix/qmgr[", x.num(lo=1000, hi=60000), "]: ", qid,
                   ": from=<invoices@", d.domain, ">, size=", str(r.randint(20000, 400000)), ", nrcpt=1 (queue active)"),
                 pick["line"]))
    if cause == "spf":
        d.tool("sh", f"dig +short TXT {d.domain} | grep spf; dig +short TXT _dmarc.{d.domain}; curl -s ifconfig.me",
               lines(F('"v=spf1 include:_spf.google.com include:', x.ent("sendgrid.net"), ' -all"'),
                     F('"v=DMARC1; p=reject; rua=mailto:dmarc@', d.domain, '; adkim=s; aspf=s"'), relay_ip))
        d.agent(say(d, "explain"), "\n",
                d.L(en="the relay sends from an address that is not in the SPF record, DKIM signing isn't set up on this box, and DMARC is p=reject — so strict receivers bounce every invoice. Fix: add the relay's egress IP to SPF (or route invoices through the ESP that is already authorised).",
                    it="il relay invia da un indirizzo che non è nel record SPF, la firma DKIM non è configurata su questa macchina e DMARC è p=reject: i provider più rigidi rimbalzano ogni fattura. Soluzione: aggiungere l'IP di uscita del relay all'SPF (o passare dall'ESP già autorizzato).",
                    de="das Relay sendet von einer Adresse, die nicht im SPF-Record steht, DKIM ist auf dieser Maschine nicht eingerichtet und DMARC steht auf p=reject — strenge Empfänger bouncen jede Rechnung. Lösung: Egress-IP des Relays ins SPF aufnehmen (oder über den bereits autorisierten ESP senden).",
                    fr="le relais envoie depuis une adresse absente de l'enregistrement SPF, DKIM n'est pas configuré sur cette machine et DMARC est en p=reject : les destinataires stricts rejettent chaque facture. Correctif : ajouter l'IP de sortie du relais au SPF (ou passer par l'ESP déjà autorisé).",
                    es="el relay envía desde una IP que no está en el registro SPF, DKIM no está configurado en esta máquina y DMARC está en p=reject, así que los receptores estrictos rebotan cada factura. Solución: añadir la IP de salida del relay al SPF (o enviar por el ESP ya autorizado)."),
                "\n\n", T('    v=spf1 ip4:⟦ip⟧ include:_spf.google.com include:sendgrid.net -all', ip=relay_ip))
    elif cause == "typo":
        d.agent(say(d, "explain"), "\n",
                d.L(en="most mail is delivered; the bounce in question is a typo in the customer's stored address (misspelled mail domain). The CRM accepted it because it only checks the syntax. I'd add an MX check on save and ask support to confirm the address with the customer.",
                    it="la maggior parte delle mail viene consegnata; il rimbalzo è dovuto a un refuso nell'indirizzo salvato del cliente (dominio scritto male). Il CRM lo ha accettato perché controlla solo la sintassi. Aggiungerei una verifica MX al salvataggio.",
                    de="die meisten Mails werden zugestellt; der Bounce kommt von einem Tippfehler in der gespeicherten Adresse (falsch geschriebene Domain). Das CRM prüft nur die Syntax. Ich würde beim Speichern einen MX-Check ergänzen.",
                    fr="la plupart des mails sont livrés ; le rebond vient d'une faute de frappe dans l'adresse enregistrée (domaine mal orthographié). Le CRM ne vérifie que la syntaxe. J'ajouterais une vérification MX à l'enregistrement.",
                    es="la mayoría de correos se entregan; el rebote es una errata en la dirección guardada del cliente (dominio mal escrito). El CRM solo valida la sintaxis. Añadiría una comprobación MX al guardar."))
    else:
        d.agent(say(d, "explain"), "\n",
                d.L(en="nothing is wrong on our side for these: the receiving mailboxes are over quota (4.2.2) and Postfix keeps them deferred until the queue lifetime expires. I'd surface the deferral in the customer portal so support can tell the customer.",
                    it="per questi non c'è nulla di sbagliato da parte nostra: le caselle di destinazione sono piene (4.2.2) e Postfix le tiene in coda finché non scade il tempo massimo. Mostrerei il ritardo nel portale clienti.",
                    de="auf unserer Seite ist hier nichts falsch: Die Zielpostfächer sind voll (4.2.2) und Postfix hält die Mails zurück, bis die Queue-Lifetime abläuft. Ich würde das im Kundenportal anzeigen.",
                    fr="rien d'anormal de notre côté : les boîtes destinataires sont pleines (4.2.2) et Postfix diffère l'envoi jusqu'à expiration de la file. Je l'afficherais dans le portail client.",
                    es="no hay nada mal por nuestra parte: los buzones de destino están llenos (4.2.2) y Postfix los deja diferidos hasta que caduca la cola. Lo mostraría en el portal de clientes."))
        d.tool("sh", "postqueue -p | tail -n 3", lines(f"-- {r.randint(20, 900)} Kbytes in {r.randint(3, 40)} Requests."))
    d.user(say(d, "thanks"))


# ---------------------------------------------------------------------------------------------------------------
# 9. IoT device registry


@template("iot_device_registry", "aider", "file", "log")
def iot_device_registry(d):
    g, x, r = d.g, d.x, d.rng
    d.user(d.L(
        en="The nightly registry sync marks half the thermostats as offline even though they're publishing. Look at registry/devices.json and the broker log.",
        it="La sincronizzazione notturna del registro segna metà dei termostati come offline anche se stanno pubblicando. Guarda registry/devices.json e il log del broker.",
        de="Der nächtliche Registry-Sync markiert die Hälfte der Thermostate als offline, obwohl sie publizieren. Schau dir registry/devices.json und das Broker-Log an.",
        fr="La synchro nocturne du registre marque la moitié des thermostats hors ligne alors qu'ils publient. Regarde registry/devices.json et le log du broker.",
        es="La sincronización nocturna del registro marca la mitad de los termostatos como offline aunque están publicando. Mira registry/devices.json y el log del broker."))
    owners = d.people(r.randint(2, 6))
    devs = []
    for i, o in enumerate(owners):
        mac_raw = V.mac_addr(r, 0)
        if i == 0 or r.random() < 0.5:
            mac_raw = mac_raw.upper()
        devs.append({"p": o, "serial": f"TH2-{r.randint(1000000, 9999999)}", "mac_raw": mac_raw, "fw": x.ver(r.choice(["2.4.1", "2.4.0", "2.3.9", "2.5.0-rc.1"])),
                     "ip": g.ip("private")})
    body = [F("[\n")]
    for i, dv in enumerate(devs):
        p = dv["p"]
        la, lo = g.geo_parts(p)
        body.append(T('''  {
    "serial": "⟦s⟧",
    "mac": "⟦m⟧",
    "model": "⟦model⟧",
    "firmware": "⟦fw⟧",
    "owner": {
      "name": "⟦n⟧",
      "email": "⟦e⟧",
      "phone": "⟦ph⟧"
    },
    "install_address": {
      "street": "⟦st⟧",
      "postcode": "⟦pc⟧",
      "city": "⟦city⟧"
    },
    "location": {"lat": ⟦la⟧, "lon": ⟦lo⟧},
    "last_seen": "⟦t⟧"
  }⟦comma⟧
''', s=dv["serial"], m=g.raw("private_mac", dv["mac_raw"], "mac"), model=r.choice(["Thermo One", "Thermo One v2", "TH2-Mini"]),
            fw=dv["fw"], n=g.name(p), e=g.email(p, "personal"), ph=g.phone(p, True), st=g.addr(p, "street"),
            pc=g.addr(p, "postcode"), city=g.addr(p, "city"), la=la, lo=lo,
            t=x.ts("iso_s", t=d.clock.t - _dt.timedelta(seconds=r.randint(100, 80000))),
            comma="," if i < len(devs) - 1 else ""))
    body.append(F("]\n"))
    d.call("read", "registry/devices.json")
    d.result("read", F(*body))
    rows = []
    for _ in range(r.randint(6, 30)):
        dv = r.choice(devs)
        k = r.random()
        ts = x.ts("epoch", tick=(1, 300))
        if k < 0.35:
            rows.append(T("⟦t⟧: New client connected from ⟦ip⟧:⟦port⟧ as ⟦cid⟧ (p2, c1, k60, u'thermo').", t=ts, ip=dv["ip"],
                          port=x.port(r.randint(30000, 60000)), cid=dv["serial"].lower()))
        elif k < 0.6:
            rows.append(T("⟦t⟧: Received PUBLISH from ⟦cid⟧ (d0, q1, r0, m⟦m⟧, 'tele/⟦cid2⟧/state', ... (⟦n⟧ bytes))", t=ts,
                          cid=dv["serial"].lower(), m=str(r.randint(1, 60000)), cid2=dv["serial"].lower(), n=str(r.randint(40, 300))))
        elif k < 0.8:
            rows.append(T("⟦t⟧: Client ⟦cid⟧ closed its connection.", t=ts, cid=dv["serial"].lower()))
        else:
            rows.append(T("⟦t⟧: Socket error on client ⟦cid⟧, disconnecting.", t=ts, cid=dv["serial"].lower()))
    d.tool("sh", "tail -n 40 /var/log/mosquitto/mosquitto.log", lines(*rows))
    hello = [T("⟦t⟧ INFO registry_sync hello serial=⟦s⟧ mac=⟦m⟧ fw=⟦fw⟧ ip=⟦ip⟧", t=x.ts("space_ms", tick=(1, 30)), s=dv["serial"],
               m=g.raw("private_mac", dv["mac_raw"].lower(), "mac"), fw=dv["fw"], ip=dv["ip"]) for dv in devs]
    hello.append(T("⟦t⟧ WARN registry_sync no hello matched for ⟦n⟧ registered devices -> marking offline",
                   t=x.ts("space_ms", tick=(1, 4)), n=str(sum(1 for dv in devs if dv["mac_raw"] != dv["mac_raw"].lower()))))
    d.tool("sh", "grep registry_sync /var/log/iot/sync.log | tail -n 12", lines(*hello))
    d.agent(d.L(en="Some registry entries store the MAC in upper case (the ones added through the installer app), but the hello messages always report lower case, and the sync compares raw strings. Normalising both sides fixes the match:",
                it="Alcune voci del registro hanno il MAC in maiuscolo (quelle inserite dall'app dell'installatore), ma i messaggi hello lo riportano sempre in minuscolo e il sync confronta stringhe grezze. Normalizzando entrambi i lati il match funziona:",
                de="Einige Registry-Einträge speichern die MAC in Großbuchstaben (die über die Installer-App angelegten), die Hello-Nachrichten melden sie aber immer klein, und der Sync vergleicht die Strings roh. Normalisieren auf beiden Seiten behebt das:",
                fr="Certaines entrées du registre stockent la MAC en majuscules (celles créées via l'appli de l'installateur), mais les messages hello l'envoient toujours en minuscules et la synchro compare les chaînes brutes. Normaliser des deux côtés règle le problème :",
                es="Algunas entradas del registro guardan la MAC en mayúsculas (las creadas desde la app del instalador), pero los mensajes hello siempre la mandan en minúsculas y la sincronización compara las cadenas tal cual. Normalizar ambos lados lo arregla:"),
            "\n\nsync/registry_sync.py\n```python\n<<<<<<< SEARCH\n    known = {dev[\"mac\"]: dev for dev in registry}\n    for hello in hellos:\n        dev = known.get(hello.mac)\n=======\n    def norm(mac: str) -> str:\n        return mac.replace(\"-\", \":\").lower()\n\n    known = {norm(dev[\"mac\"]): dev for dev in registry}\n    for hello in hellos:\n        dev = known.get(norm(hello.mac))\n>>>>>>> REPLACE\n```")
    d.tool("sh", "python -m sync.registry_sync --dry-run",
           lines(T("⟦t⟧ INFO registry_sync loaded ⟦n⟧ devices from registry/devices.json", t=x.ts("space_ms", tick=(30, 90)), n=str(len(devs))),
                 T("⟦t⟧ INFO registry_sync dry-run: online=⟦a⟧ offline=0 changed=⟦b⟧", t=x.ts("space_ms", tick=(0.2, 2)),
                   a=str(len(devs)), b=str(sum(1 for dv in devs if dv["mac_raw"] != dv["mac_raw"].lower())))))
    if d.gold_ok and r.random() < 0.6:
        d.user(d.L(en="Why does the registry even have owners' home addresses and coordinates?",
                   it="Perché il registro contiene addirittura indirizzi di casa e coordinate dei proprietari?",
                   de="Warum stehen in der Registry überhaupt Wohnadressen und Koordinaten der Besitzer?",
                   fr="Pourquoi le registre contient-il les adresses et coordonnées des propriétaires ?",
                   es="¿Por qué el registro tiene direcciones y coordenadas de los propietarios?"))
        d.agent(d.L(en="The installer app writes them for the weather-compensation feature, which only needs a coarse region. Rounding to 2 decimals (~1 km) and moving the owner contact to the CRM would cut most of the personal data out of this file.",
                    it="Li scrive l'app dell'installatore per la compensazione meteo, che però richiede solo una zona approssimativa. Arrotondare a 2 decimali (~1 km) e spostare i contatti nel CRM toglierebbe gran parte dei dati personali da questo file.",
                    de="Die Installer-App schreibt sie für die Wetterkompensation, die aber nur eine grobe Region braucht. Auf 2 Nachkommastellen (~1 km) runden und Besitzerkontakt ins CRM verschieben würde den Großteil der personenbezogenen Daten entfernen.",
                    fr="L'appli de l'installateur les écrit pour la compensation météo, qui n'a besoin que d'une zone approximative. Arrondir à 2 décimales (~1 km) et déplacer le contact dans le CRM enlèverait l'essentiel des données personnelles de ce fichier.",
                    es="La app del instalador los guarda para la compensación meteorológica, que solo necesita una zona aproximada. Redondear a 2 decimales (~1 km) y mover el contacto al CRM quitaría casi todos los datos personales de este fichero."))


# ---------------------------------------------------------------------------------------------------------------
# 10. VPN access: OpenVPN status and WireGuard peers


@template("vpn_access_log", "plain", "log")
def vpn_access_log(d):
    g, x, r = d.g, d.x, d.rng
    d.user(d.L(
        en="Can you clean up stale VPN peers on vpn-gw? Anyone who hasn't connected in 30 days goes. We run OpenVPN for staff and WireGuard for contractors.",
        it="Puoi ripulire i peer VPN inattivi su vpn-gw? Chi non si collega da 30 giorni va rimosso. Usiamo OpenVPN per i dipendenti e WireGuard per i consulenti.",
        de="Kannst du auf vpn-gw die verwaisten VPN-Peers aufräumen? Wer sich seit 30 Tagen nicht verbunden hat, fliegt raus. OpenVPN für Mitarbeiter, WireGuard für Externe.",
        fr="Tu peux nettoyer les pairs VPN inactifs sur vpn-gw ? Tous ceux qui ne se sont pas connectés depuis 30 jours dégagent. OpenVPN pour les salariés, WireGuard pour les prestataires.",
        es="¿Puedes limpiar los peers VPN inactivos en vpn-gw? Quien no se haya conectado en 30 días, fuera. Usamos OpenVPN para plantilla y WireGuard para externos."))
    staff = d.people(r.randint(2, 5))
    st_rows = [F("OpenVPN CLIENT LIST\nUpdated,", x.ts("space"), "\nCommon Name,Real Address,Bytes Received,Bytes Sent,Connected Since\n")]
    routes = [F("ROUTING TABLE\nVirtual Address,Common Name,Real Address,Last Ref\n")]
    for i, p in enumerate(staff):
        real = g.ip("public")
        port = str(r.randint(1025, 65000))
        virt = g.raw("private_ip", f"10.8.0.{6 + 4 * i}", "generic") if d.gold_ok else x.rip(False)
        st_rows.append(F(g.user(p), ",", real, ":", port, ",", str(r.randint(10000, 90000000)), ",", str(r.randint(10000, 90000000)),
                         ",", x.ts("space", t=d.clock.t.replace(hour=r.randint(6, 10))), "\n"))
        routes.append(F(virt, ",", g.user(p), ",", real, ":", port, ",", x.ts("space", tick=(-300, -1)), "\n"))
    status = F(*st_rows, *routes, "GLOBAL STATS\nMax bcast/mcast queue length,", str(r.randint(0, 4)), "\nEND\n")
    d.tool("sh", "sudo cat /var/log/openvpn/status.log", status)
    contractors = d.people(r.randint(3, 7))
    peers = []
    for i, p in enumerate(contractors):
        days = r.choice([0, 0, 1, 3, 12, 34, 41, 58, 90, None])
        peers.append({"p": p, "pub": x.id(_wg_key(d)), "ep": g.ip(r.choice(["public", "public", "public", "v6"])),
                      "aip": g.raw("private_ip", f"10.9.0.{10 + i}", "generic") if d.gold_ok else x.rip(False),
                      "days": days})
    wg = [F("interface: wg0\n  public key: ", x.id(_wg_key(d)), "\n  private key: (hidden)\n  listening port: ", x.port(51820), "\n\n")]
    for pe in peers:
        wg.append(F("peer: ", pe["pub"], "\n"))
        if pe["days"] is not None:
            if ":" in pe["ep"].text:
                wg.append(F("  endpoint: [", pe["ep"], "]:", str(r.randint(1025, 65000)), "\n"))
            else:
                wg.append(F("  endpoint: ", pe["ep"], ":", str(r.randint(1025, 65000)), "\n"))
        wg.append(F("  allowed ips: ", pe["aip"], "/32\n"))
        if pe["days"] is None:
            wg.append(F("\n"))
            continue
        hrs = r.randint(1, 23)
        hs = (f"{pe['days']} day{'s' if pe['days'] != 1 else ''}, {hrs} hour{'s' if hrs != 1 else ''} ago"
              if pe["days"] else f"{r.randint(1, 59)} seconds ago")
        wg.append(F("  latest handshake: ", hs, "\n  transfer: ", f"{r.uniform(0.1, 900):.2f} MiB received, {r.uniform(0.1, 900):.2f} MiB sent", "\n\n"))
    d.tool("sh", "sudo wg show wg0", F(*wg))
    priv = g.raw("secret", _wg_key(d), "api_key") if d.secret_ok else x.ph(text=r.choice(["<redacted>", "${WG_PRIVATE_KEY}", "(see vault: vpn/wg0)"]))
    conf = [T("[Interface]\nAddress = ⟦a⟧/24\nListenPort = ⟦p⟧\nPrivateKey = ⟦k⟧\nPostUp = iptables -A FORWARD -i wg0 -j ACCEPT\n\n",
              a=g.raw("private_ip", "10.9.0.1", "generic") if d.gold_ok else x.rip(False), p=x.port(51820), k=priv)]
    for pe in peers:
        conf.append(T("# ⟦n⟧ — ⟦e⟧\n[Peer]\nPublicKey = ⟦pub⟧\nAllowedIPs = ⟦aip⟧/32\n\n", n=g.name(pe["p"]),
                      e=g.email(pe["p"], "personal" if r.random() < 0.5 else "work"), pub=pe["pub"], aip=pe["aip"]))
    d.tool("read", "/etc/wireguard/wg0.conf", F(*conf))
    stale = [pe for pe in peers if pe["days"] is None or pe["days"] > 30]
    if not stale:
        stale = [peers[-1]]
        stale[0]["days"] = None
    d.agent(d.L(en="OpenVPN staff sessions are all current. On WireGuard these peers have no handshake in 30+ days (or never):",
                it="Le sessioni OpenVPN dei dipendenti sono tutte attive. Su WireGuard questi peer non fanno handshake da oltre 30 giorni (o mai):",
                de="Die OpenVPN-Sessions der Mitarbeiter sind alle aktuell. Bei WireGuard haben diese Peers seit über 30 Tagen (oder nie) keinen Handshake:",
                fr="Les sessions OpenVPN des salariés sont toutes actives. Côté WireGuard, ces pairs n'ont pas fait de handshake depuis plus de 30 jours (ou jamais) :",
                es="Las sesiones OpenVPN de la plantilla están al día. En WireGuard estos peers no tienen handshake en más de 30 días (o nunca):"),
            "\n", J("\n", [F("- ", g.name(pe["p"]), " (", pe["aip"], ")") for pe in stale]),
            "\n\n", d.L(en="Removing them from the config and syncing the live interface.", it="Li rimuovo dalla configurazione e sincronizzo l'interfaccia.",
                        de="Ich entferne sie aus der Konfiguration und synchronisiere das Interface.",
                        fr="Je les retire de la config et je synchronise l'interface.", es="Los quito de la config y sincronizo la interfaz."))
    diff = []
    for pe in stale:
        diff.append(T("-# ⟦n⟧\n-[Peer]\n-PublicKey = ⟦pub⟧\n-AllowedIPs = ⟦aip⟧/32\n", n=g.name(pe["p"]), pub=pe["pub"], aip=pe["aip"]))
    d.tool("edit", "/etc/wireguard/wg0.conf", F(*diff))
    d.tool("sh", "sudo wg syncconf wg0 <(sudo wg-quick strip wg0) && sudo wg show wg0 peers | wc -l", str(len(peers) - len(stale)))
    d.agent(say(d, "done"), "\n- ", f"{len(stale)} WireGuard peer(s) removed; ", "\n- ",
            d.L(en="no OpenVPN changes needed (all staff connected within the window)",
                it="nessuna modifica a OpenVPN (tutti i dipendenti connessi nel periodo)",
                de="keine OpenVPN-Änderungen nötig (alle Mitarbeiter im Zeitraum verbunden)",
                fr="aucun changement OpenVPN (tous les salariés connectés dans la période)",
                es="sin cambios en OpenVPN (toda la plantilla conectada en el periodo)"))


# ---------------------------------------------------------------------------------------------------------------
# 11. Kubernetes ingress-nginx logs and cert-manager events


@template("k8s_events_ingress", "cc", "log")
def k8s_events_ingress(d):
    g, x, r = d.g, d.x, d.rng
    host = f"api.{d.domain}"
    d.user(d.L(
        en=f"Since the certificate renewal last night, {host} returns 404 for every /v2 route. /v1 is fine. Can you look at the ingress?",
        it=f"Dal rinnovo del certificato di stanotte, {host} restituisce 404 per tutte le route /v2. /v1 va. Puoi guardare l'ingress?",
        de=f"Seit der Zertifikatserneuerung heute Nacht liefert {host} für alle /v2-Routen 404. /v1 geht. Kannst du dir das Ingress anschauen?",
        fr=f"Depuis le renouvellement du certificat cette nuit, {host} renvoie 404 sur toutes les routes /v2. /v1 marche. Tu peux regarder l'ingress ?",
        es=f"Desde la renovación del certificado anoche, {host} devuelve 404 en todas las rutas /v2. /v1 va bien. ¿Puedes mirar el ingress?"))
    d.agent(say(d, "logs_window"))
    clients = [g.ip(r.choice(["public", "public", "public", "v6"])) for _ in range(r.randint(2, 6))]
    upstream = [g.ip("private") for _ in range(r.randint(1, 3))]
    rows = []
    n = r.randint(8, 50)
    for _ in range(n):
        v2 = r.random() < 0.6
        if v2:
            path = r.choice([F("/v2/orders/", x.num(lo=10000, hi=999999)), F("/v2/health"), F("/v2/me"),
                             (d.g.raw("private_url", f"/v2/customers/{r.randint(10000, 999999)}/addresses", "url") if d.gold_ok else "/v2/catalog")])
            status, up, svc = 404, F("-"), "[]"
        else:
            path = r.choice(["/v1/orders?page=2", "/v1/health", "/v1/catalog", "/v1/me"])
            status, up, svc = r.choice([200, 200, 200, 304]), F(r.choice(upstream), ":", x.port(8080)), f"[api-api-svc-8080]"
        rows.append(T('⟦ip⟧ - - [⟦t⟧] "GET ⟦p⟧ HTTP/2.0" ⟦s⟧ ⟦b⟧ "-" "⟦ua⟧" ⟦rl⟧ ⟦rt⟧ ⟦svc⟧ [] ⟦up⟧ ⟦ub⟧ ⟦urt⟧ ⟦us⟧ ⟦rid⟧',
                      ip=r.choice(clients), t=x.ts("clf", tick=(0.1, 20)), p=path, s=str(status),
                      b=str(r.randint(146, 548) if status == 404 else r.randint(100, 9000)),
                      ua=r.choice(_UAS), rl=str(r.randint(300, 900)), rt=f"{r.uniform(0.001, 0.4):.3f}", svc=svc, up=up,
                      ub=str(r.randint(0, 9000)) if status != 404 else "0", urt=f"{r.uniform(0.001, 0.4):.3f}" if status != 404 else "-",
                      us=str(status) if status != 404 else "-", rid=x.id(V.rand_str(r, V.HEX, 32))))
    d.tool("sh", f"kubectl -n ingress-nginx logs deploy/ingress-nginx-controller --since=1h | grep {host} | tail -n {n}", lines(*rows))
    d.agent(d.L(en="The /v2 requests never reach an upstream (empty service field). Checking what changed around the renewal:",
                it="Le richieste /v2 non arrivano mai a un upstream (campo service vuoto). Controllo cosa è cambiato con il rinnovo:",
                de="Die /v2-Requests erreichen nie einen Upstream (leeres Service-Feld). Ich prüfe, was sich bei der Erneuerung geändert hat:",
                fr="Les requêtes /v2 n'atteignent jamais d'upstream (champ service vide). Je regarde ce qui a changé au renouvellement :",
                es="Las peticiones /v2 nunca llegan a un upstream (campo service vacío). Miro qué cambió con la renovación:"))
    ev = [["LAST SEEN", "TYPE", "REASON", "OBJECT", "MESSAGE"]]
    for age, typ, reason, obj, msg in [(f"{r.randint(5, 9)}h", "Normal", "Issuing", "certificate/api-tls", "Renewing certificate as renewal was scheduled"),
                                       (f"{r.randint(5, 9)}h", "Normal", "Generated", "certificate/api-tls", "Stored new private key in temporary Secret resource"),
                                       (f"{r.randint(4, 8)}h", "Normal", "Sync", "ingress/api", "Scheduled for sync"),
                                       (f"{r.randint(4, 8)}h", "Normal", "Issuing", "certificate/api-tls", "The certificate has been successfully issued"),
                                       (f"{r.randint(2, 4)}h", "Normal", "UPDATE", "ingress/api", "Ingress api/api")]:
        ev.append([age, typ, reason, obj, msg])
    d.tool("sh", "kubectl -n api get events --sort-by=.lastTimestamp | tail -n 8", table(ev, gap=3))
    issuer_mail = g.email(d.me if r.random() < 0.5 else d.person())
    yaml_doc = T('''apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api
  namespace: api
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/use-regex: "true"
    nginx.ingress.kubernetes.io/rewrite-target: /$2
  resourceVersion: "⟦rv⟧"
  uid: ⟦uid⟧
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - ⟦host⟧
    secretName: api-tls
  rules:
  - host: ⟦host2⟧
    http:
      paths:
      - path: /v1(/|$)(.*)
        pathType: ImplementationSpecific
        backend:
          service:
            name: api-svc
            port:
              number: ⟦port⟧
      - path: /v2/(.*)
        pathType: Prefix
        backend:
          service:
            name: api-v2-svc
            port:
              number: ⟦port2⟧
''', rv=x.num(lo=1000000, hi=99999999), uid=x.uuid(), host=host, host2=host, port=x.port(8080), port2=x.port(8080))
    d.tool("sh", "kubectl -n api get ingress api -o yaml", yaml_doc)
    if r.random() < 0.6:
        d.tool("sh", "kubectl get clusterissuer letsencrypt-prod -o jsonpath='{.spec.acme.email}{\"\\n\"}{.spec.acme.server}'",
               F(issuer_mail, "\n", x.url(text="https://acme-v02.api.letsencrypt.org/directory"), "\n"))
    d.agent(say(d, "explain"), "\n",
            d.L(en="the renewal re-applied the ingress from the Helm chart, and the /v2 path came back with `pathType: Prefix`. With `use-regex` enabled, a Prefix path containing a regex never matches, so nginx falls through to the default backend (404). /v1 still uses ImplementationSpecific.",
                it="il rinnovo ha riapplicato l'ingress dal chart Helm e il path /v2 è tornato con `pathType: Prefix`. Con `use-regex` attivo, un path Prefix con una regex non fa mai match e nginx finisce sul default backend (404). /v1 usa ancora ImplementationSpecific.",
                de="bei der Erneuerung wurde das Ingress aus dem Helm-Chart neu angewendet, und der /v2-Pfad kam mit `pathType: Prefix` zurück. Mit `use-regex` matcht ein Prefix-Pfad mit Regex nie, daher landet nginx im Default-Backend (404). /v1 nutzt weiterhin ImplementationSpecific.",
                fr="le renouvellement a réappliqué l'ingress depuis le chart Helm et le chemin /v2 est revenu en `pathType: Prefix`. Avec `use-regex`, un chemin Prefix contenant une regex ne matche jamais, d'où le backend par défaut (404). /v1 est toujours en ImplementationSpecific.",
                es="la renovación volvió a aplicar el ingress desde el chart de Helm y la ruta /v2 quedó con `pathType: Prefix`. Con `use-regex`, una ruta Prefix con regex nunca coincide, así que nginx cae al backend por defecto (404). /v1 sigue con ImplementationSpecific."))
    d.tool("edit", "charts/api/templates/ingress.yaml",
           lines("-      - path: /v2/(.*)", "-        pathType: Prefix", "+      - path: /v2(/|$)(.*)", "+        pathType: ImplementationSpecific"))
    d.tool("sh", f"helm upgrade api charts/api -n api --reuse-values && curl -sI https://{host}/v2/health | head -n 3",
           lines("Release \"api\" has been upgraded. Happy Helming!", "NAME: api",
                 F("LAST DEPLOYED: ", x.ts("git", tick=(30, 90), local=True)), "HTTP/2 200",
                 F("date: ", x.ts("http", tick=(1, 3))), "content-type: application/json"))
    d.agent(say(d, "done"), "\n- ",
            d.L(en="/v2 path fixed in the chart (so the next renewal won't revert it)", it="path /v2 corretto nel chart (così il prossimo rinnovo non lo annulla)",
                de="/v2-Pfad im Chart korrigiert (damit die nächste Erneuerung ihn nicht zurücksetzt)", fr="chemin /v2 corrigé dans le chart (le prochain renouvellement ne l'écrasera pas)",
                es="ruta /v2 corregida en el chart (la próxima renovación no la revertirá)"),
            "\n- ", say(d, "not_committed"))
