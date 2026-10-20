# SPDX-License-Identifier: Apache-2.0
"""Templates centred on tickets, e-mail, chat threads and records about
people that arrive through support/HR/finance workflows."""

from __future__ import annotations

import datetime as dt

from .. import values as V
from ..core import F, J, T, Seg, esc_json, grid, lines, numbered, prefix_lines, table
from ..phrases import say
from . import template


# ---------------------------------------------------------------- private helpers


def _pl(d, p, **variants: str) -> str:
    """Prose in the persona's language (falls back to English)."""
    return d.Lp(d.lang_of(p), **variants)


def _hm(d, lo: float, hi: float, ampm: bool = True) -> Seg:
    """Chat-client clock time (machine timestamp)."""
    t = d.clock.local(d.clock.tick(lo, hi))
    if ampm:
        s = f"{(t.hour % 12) or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"
    else:
        s = f"{t.hour:02d}:{t.minute:02d}"
    return Seg(s, cls="machine_timestamp")


def _today(d) -> dt.date:
    return d.clock.local().date()


def _future(d, lo: int, hi: int) -> dt.date:
    return _today(d) + dt.timedelta(days=d.rng.randint(lo, hi))


def _amount(r, lo: float, hi: float) -> str:
    return f"{r.uniform(lo, hi):.2f}"


# ================================================================ 1. GitHub issue


_GH_BUGS = {
    "unicode": {
        "title": "Crash in `{t} export --format csv` when names contain accents",
        "exc": "UnicodeEncodeError: 'ascii' codec can't encode character '\\xe9' in position {pos}: ordinal not in range(128)",
        "frame": ("export.py", "write_rows", "writer.writerow(row)"),
        "env": "LC_ALL=C",
        "cmd": "export --format csv --out /tmp/out.csv",
        "fix_old": '    with open(out_path, "w", newline="") as fh:',
        "fix_new": '    with open(out_path, "w", newline="", encoding="utf-8") as fh:',
    },
    "tz": {
        "title": "`{t} sync` fails with naive/aware datetime comparison",
        "exc": "TypeError: can't compare offset-naive and offset-aware datetimes",
        "frame": ("sync.py", "needs_refresh", "return entry.updated_at < cutoff"),
        "env": "TZ=Europe/Rome",
        "cmd": "sync --once",
        "fix_old": "    cutoff = datetime.now() - timedelta(hours=ttl_hours)",
        "fix_new": "    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)",
    },
    "proxy": {
        "title": "`{t} login` ignores proxy credentials (407 behind corporate proxy)",
        "exc": "requests.exceptions.ProxyError: HTTPSConnectionPool(host='api.{dom}', port=443): Max retries exceeded with url: /v2/session (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 407 Proxy Authentication Required')))",
        "frame": ("http.py", "open_session", "resp = self._session.post(url, json=payload, timeout=10)"),
        "env": "HTTPS_PROXY=http://proxy.test:3128",
        "cmd": "login --non-interactive",
        "fix_old": "        self._session.trust_env = False",
        "fix_new": "        self._session.trust_env = True  # honour HTTPS_PROXY incl. user:pass",
    },
}


@template("github_issue_bug_report", "steps", "ticket", "trace")
def github_issue_bug_report(d):
    g, x, r = d.g, d.x, d.rng
    rep, maint = d.person(), d.person()
    tool = d.project.split("-")[0]
    num = r.randint(140, 4890)
    bug_key = r.choice(sorted(_GH_BUGS))
    bug = _GH_BUGS[bug_key]
    rep_lang = d.lang_of(rep) if r.random() < 0.45 else "en"
    login = g.user(rep)
    ver = x.ver()
    d.user(T(d.L(
        en="Can you look at issue #⟦n⟧? Someone reports a crash in ⟦t⟧. Reproduce it locally before changing anything.",
        it="Puoi guardare la issue #⟦n⟧? Un utente segnala un crash di ⟦t⟧. Riproducilo in locale prima di toccare il codice.",
        de="Kannst du dir Issue #⟦n⟧ ansehen? Jemand meldet einen Absturz in ⟦t⟧. Bitte erst lokal reproduzieren, bevor du etwas änderst.",
        fr="Tu peux regarder l'issue #⟦n⟧ ? Quelqu'un signale un crash de ⟦t⟧. Reproduis-le en local avant de modifier quoi que ce soit.",
        es="¿Puedes mirar la issue #⟦n⟧? Alguien reporta un fallo en ⟦t⟧. Reprodúcelo en local antes de cambiar nada."),
        n=x.num(num), t=tool))
    d.agent(say(d, "look_first", x=F("issue #", x.num(num))))

    win = r.random() < 0.3
    if win:
        home = F("C:\\Users\\", login)
        site = F(home, "\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\", tool)
        sep = "\\"
    else:
        home = F("/home/" if r.random() < 0.4 else "/Users/", login)
        site = F(home, "/.local/pipx/venvs/", tool, "/lib/python3.12/site-packages/", tool)
        sep = "/"
    proxy_ip = g.ip("private")
    fname, func, code = bug["frame"]
    trace = lines(
        "Traceback (most recent call last):",
        T('  File "⟦s⟧⟦sep⟧cli.py", line ⟦n⟧, in main', s=site, sep=sep, n=x.num(lo=40, hi=300)),
        "    return args.func(args)",
        T('  File "⟦s⟧⟦sep⟧⟦f⟧", line ⟦n⟧, in ⟦fn⟧', s=site, sep=sep, f=fname, n=x.num(lo=20, hi=400), fn=func),
        "    " + code,
        bug["exc"].format(pos=r.randint(3, 60), dom=d.domain),
    )
    title = bug["title"].format(t=tool)
    desc = d.Lp(rep_lang,
                en="Since upgrading to the latest release the command crashes immediately. It worked on the previous version.",
                it="Da quando ho aggiornato all'ultima release il comando va in crash subito. Con la versione precedente funzionava.",
                de="Seit dem Update auf das neueste Release stürzt der Befehl sofort ab. Mit der Vorversion lief es.",
                fr="Depuis la mise à jour vers la dernière version, la commande plante immédiatement. Ça marchait avec la version précédente.",
                es="Desde que actualicé a la última versión el comando falla nada más arrancar. Con la versión anterior funcionaba.",
                nl="Sinds de update naar de nieuwste release crasht het commando meteen. Met de vorige versie werkte het wel.",
                pt="Desde que atualizei para a última versão o comando falha logo ao arrancar. Na versão anterior funcionava.")
    body = F(
        "### Describe the bug\n", desc, "\n\n### Environment\n",
        "- ", tool, " version: ", ver, "\n",
        "- OS: ", r.choice(["Windows 11 23H2", "macOS 14.5", "Ubuntu 22.04", "Fedora 40"]) if not win else "Windows 11 23H2", "\n",
        "- install path: `", site, "`\n",
        T("- corporate proxy: `http://⟦ip⟧:⟦p⟧`\n", ip=proxy_ip, p=x.port(3128)) if bug_key == "proxy" or r.random() < 0.4 else "",
        "\n### Traceback\n```\n", trace, "```\n",
    )
    comments = []
    n_comments = r.randint(1, 3)
    maint_login = g.user(maint)
    comments.append((maint_login, "member", T(
        "Thanks @⟦u⟧ for the report! Could you run `⟦t⟧ doctor` and paste the output here? Please strip anything you consider private.",
        u=login, t=tool)))
    doctor_rows = [
        ["version", ver],
        ["python", F(home, "\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" if win else F("/.local/pipx/venvs/", tool, "/bin/python"),
                     " (3.12.", x.num(lo=1, hi=7), ")")],
        ["config", F(home, sep, ".config", sep, tool, sep, "config.toml")],
        ["git user", F(g.name(rep), " <", g.email(rep, "personal"), ">")],
        ["locale", "C / US-ASCII" if bug_key == "unicode" else r.choice(["it_IT.UTF-8", "de_DE.UTF-8", "en_GB.UTF-8"])],
        ["proxy", T("http://⟦u⟧:⟦pw⟧@⟦ip⟧:⟦p⟧", u=login, pw=g.password(), ip=proxy_ip, p=x.port(3128)) if bug_key == "proxy" else "(none)"],
        ["api", F("https://api.", d.domain, " (reachable: ", "no" if bug_key == "proxy" else "yes", ")")],
    ]
    comments.append((login, "none", F(
        d.Lp(rep_lang, en="Here you go:", it="Ecco qui:", de="Bitte sehr:", fr="Voilà :", es="Aquí está:", nl="Alsjeblieft:"),
        "\n\n```\n$ ", tool, " doctor\n", table([["  " + k, v] for k, v in doctor_rows], gap=4), "```")))
    if n_comments >= 3:
        other = d.person()
        comments.append((g.user(other), "none", F(
            d.Lp(d.lang_of(other), en="+1, same here. Workaround for now: pin the previous version.",
                 it="+1, anche a me. Per ora ho rimesso la versione precedente.",
                 de="+1, bei mir genauso. Workaround: vorherige Version pinnen.",
                 fr="+1, pareil chez moi. Contournement : rester sur la version précédente.",
                 es="+1, a mí también. De momento he vuelto a la versión anterior."),
            T(" (`pip install ⟦t⟧==⟦v⟧`)", t=tool, v=x.ver()))))
    gh = F(
        "title:\t", title, "\nstate:\tOPEN\nauthor:\t", login, "\nlabels:\tbug, needs-triage\ncomments:\t",
        str(len(comments)), "\nassignees:\t\nprojects:\t\nmilestone:\t\nnumber:\t", x.num(num), "\n--\n", body)
    for who, assoc, text in comments:
        gh += F("--\nauthor:\t", who, "\nassociation:\t", assoc, "\nedited:\tfalse\nstatus:\tnone\n--\n", text, "\n")
    d.tool("sh", F("gh issue view ", x.num(num), " --comments"), gh)
    if rep_lang != "en" and rep_lang != d.lang and r.random() < 0.5:
        d.agent(d.L(en="The reporter wrote part of it in their own language; the traceback is what matters.",
                    it="Il reporter ha scritto in parte nella sua lingua; quello che conta è il traceback.",
                    de="Der Reporter hat teils in seiner Sprache geschrieben; entscheidend ist der Traceback.",
                    fr="Le rapporteur a écrit en partie dans sa langue ; c'est la traceback qui compte.",
                    es="El autor escribió parte en su idioma; lo importante es el traceback."))
    d.agent(d.L(en="Reproducing with the same environment conditions.", it="Provo a riprodurre con le stesse condizioni d'ambiente.",
                de="Ich reproduziere mit denselben Umgebungsbedingungen.", fr="Je reproduis avec les mêmes conditions d'environnement.",
                es="Reproduzco con las mismas condiciones de entorno."))
    local_trace = lines(
        "Traceback (most recent call last):",
        T('  File "⟦c⟧/src/⟦t⟧/⟦f⟧", line ⟦n⟧, in ⟦fn⟧', c=d.cwd(), t=tool, f=fname, n=x.num(lo=20, hi=400), fn=func),
        "    " + code,
        bug["exc"].format(pos=r.randint(3, 60), dom=d.domain),
    )
    d.tool("sh", F(bug["env"], " python -m ", tool, " ", bug["cmd"]),
           local_trace)
    d.agent(say(d, "explain"), "\n", d.L(
        en="Reproduced. The code path relies on an implicit default (encoding / timezone / proxy handling) that differs on the reporter's machine.",
        it="Riprodotto. Il codice si basa su un default implicito (encoding / fuso orario / proxy) che sulla macchina del reporter è diverso.",
        de="Reproduziert. Der Codepfad verlässt sich auf einen impliziten Default (Encoding / Zeitzone / Proxy), der beim Reporter anders ist.",
        fr="Reproduit. Le code dépend d'une valeur implicite (encodage / fuseau / proxy) qui diffère sur la machine du rapporteur.",
        es="Reproducido. El código depende de un valor implícito (codificación / zona horaria / proxy) que es distinto en su máquina."))
    hunk = x.num(lo=10, hi=200)
    d.tool("edit", F("src/", tool, "/", fname), F("@@ -", hunk, ",7 +", hunk, ",7 @@\n-", bug["fix_old"], "\n+", bug["fix_new"], "\n"))
    d.tool("sh", "pytest -q tests/", lines(T("⟦a⟧ passed in ⟦s⟧s", a=x.num(lo=40, hi=380), s=f"{r.uniform(0.8, 9.5):.2f}")))
    d.agent(say(d, "done"), "\n", T(d.L(
        en="- fix in src/⟦t⟧/⟦f⟧ plus a regression test\n- suggested reply on the issue: \"Thanks @⟦u⟧, reproduced and fixed; it will ship in the next patch release.\"",
        it="- fix in src/⟦t⟧/⟦f⟧ più un test di regressione\n- risposta suggerita sulla issue: \"Thanks @⟦u⟧, reproduced and fixed; it will ship in the next patch release.\"",
        de="- Fix in src/⟦t⟧/⟦f⟧ plus Regressionstest\n- Vorschlag für die Antwort im Issue: \"Thanks @⟦u⟧, reproduced and fixed; it will ship in the next patch release.\"",
        fr="- correctif dans src/⟦t⟧/⟦f⟧ et test de non-régression\n- réponse proposée sur l'issue : \"Thanks @⟦u⟧, reproduced and fixed; it will ship in the next patch release.\"",
        es="- arreglo en src/⟦t⟧/⟦f⟧ y un test de regresión\n- respuesta sugerida en la issue: \"Thanks @⟦u⟧, reproduced and fixed; it will ship in the next patch release.\""),
        t=tool, f=fname, u=login))


# ================================================================ 2. Jira refund ticket


@template("jira_refund_ticket", "aider", "ticket", "file")
def jira_refund_ticket(d):
    g, x, r = d.g, d.x, d.rng
    cust, agent_p, dev = d.person(), d.person(d.locale), d.me
    key = f"{r.choice(['PAY', 'SUP', 'FIN', 'CS'])}-{r.randint(120, 9800)}"
    variant = r.choice(["spaces", "spaces", "lowercase"])
    order = f"{r.choice(['ORD', 'SO', 'A'])}-{r.randint(100000, 999999)}"
    amount = _amount(r, 19, 890)
    lang = d.lang_of(agent_p)
    iban_seg = g.iban(p=cust, printed=variant == "spaces")
    if variant == "lowercase" and iban_seg.label:
        iban_seg = g.raw("account_number", iban_seg.text.lower().replace(" ", ""), "iban")
    d.user(T(d.L(
        en="Support escalated ⟦k⟧: refunds are failing with \"invalid IBAN\". Please fix the validation in payments/refunds.py.",
        it="Il supporto ha scalato ⟦k⟧: i rimborsi falliscono con \"invalid IBAN\". Sistema la validazione in payments/refunds.py.",
        de="Der Support hat ⟦k⟧ eskaliert: Erstattungen scheitern mit \"invalid IBAN\". Bitte die Validierung in payments/refunds.py fixen.",
        fr="Le support a escaladé ⟦k⟧ : les remboursements échouent avec \"invalid IBAN\". Corrige la validation dans payments/refunds.py.",
        es="Soporte ha escalado ⟦k⟧: los reembolsos fallan con \"invalid IBAN\". Arregla la validación en payments/refunds.py."),
        k=x.id(key)))
    d.tool("sh", F("jira issue view ", x.id(key), " --plain"), F(
        "Bug · In Progress · High\n# ", d.Lp(lang, en="Refund rejected: invalid IBAN", it="Rimborso rifiutato: IBAN non valido",
                                            de="Erstattung abgelehnt: ungültige IBAN", fr="Remboursement refusé : IBAN invalide",
                                            es="Reembolso rechazado: IBAN no válido"),
        "\nReporter: ", g.name(agent_p), "   Assignee: ", g.name(dev), "\nCreated: ", x.ts("space", tick=(3600, 9000)), "\n\n",
        "------------------------ Description ------------------------\n",
        T(_pl(d, agent_p,
              en="Customer ⟦n⟧ (customer no. ⟦c⟧) asked for a refund of EUR ⟦a⟧ for order ⟦o⟧. The refund fails with \"invalid IBAN\" although the IBAN provided looks right:\n\n    ⟦i⟧\n\nThe customer has called three times already, callback number ⟦ph⟧. Can someone please look at this today?",
              it="Il cliente ⟦n⟧ (codice cliente ⟦c⟧) ha chiesto il rimborso di ⟦a⟧ EUR per l'ordine ⟦o⟧. Il rimborso fallisce con \"invalid IBAN\" anche se l'IBAN comunicato sembra corretto:\n\n    ⟦i⟧\n\nHa già chiamato tre volte, il suo numero è ⟦ph⟧. Qualcuno può guardarci oggi?",
              de="Kunde ⟦n⟧ (Kundennr. ⟦c⟧) möchte eine Erstattung über ⟦a⟧ EUR für Bestellung ⟦o⟧. Die Erstattung schlägt mit \"invalid IBAN\" fehl, obwohl die angegebene IBAN korrekt aussieht:\n\n    ⟦i⟧\n\nEr/sie hat schon dreimal angerufen, Rückrufnummer ⟦ph⟧. Kann sich das bitte heute jemand ansehen?",
              fr="Le client ⟦n⟧ (n° client ⟦c⟧) demande le remboursement de ⟦a⟧ EUR pour la commande ⟦o⟧. Le remboursement échoue avec \"invalid IBAN\" alors que l'IBAN fourni semble correct :\n\n    ⟦i⟧\n\nIl/elle a déjà appelé trois fois, numéro de rappel ⟦ph⟧. Quelqu'un peut regarder aujourd'hui ?",
              es="El cliente ⟦n⟧ (n.º de cliente ⟦c⟧) ha pedido el reembolso de ⟦a⟧ EUR del pedido ⟦o⟧. Falla con \"invalid IBAN\" aunque el IBAN que nos dio parece correcto:\n\n    ⟦i⟧\n\nYa ha llamado tres veces, su teléfono es ⟦ph⟧. ¿Alguien puede mirarlo hoy?"),
          n=g.name(cust), c=g.cust(), a=amount, o=x.id(order), i=iban_seg, ph=g.phone(cust)),
        T("\n\nE-mail: ⟦e⟧", e=g.email(cust, "personal")) if r.random() < 0.5 else "",
        "\n"))
    if r.random() < 0.6:
        cust2, colleague = d.person(), d.person(d.locale)
        d.tool("sh", F("jira issue comments ", x.id(key)), F(
            g.name(colleague), " · ", x.ts("space", tick=(600, 4000)), "\n",
            T(_pl(d, colleague,
                  en="Same for ⟦n⟧, IBAN ⟦i⟧ — refund stuck since Monday.",
                  it="Stessa cosa per ⟦n⟧, IBAN ⟦i⟧: rimborso bloccato da lunedì.",
                  de="Gleiches Problem bei ⟦n⟧, IBAN ⟦i⟧ — Erstattung hängt seit Montag.",
                  fr="Pareil pour ⟦n⟧, IBAN ⟦i⟧ — remboursement bloqué depuis lundi.",
                  es="Lo mismo con ⟦n⟧, IBAN ⟦i⟧: el reembolso está parado desde el lunes."),
              n=g.name(cust2), i=g.iban(p=cust2, printed=True)), "\n"))
    code = lines(
        "import re",
        "",
        'IBAN_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")',
        "",
        "",
        "class InvalidIban(ValueError):",
        "    pass",
        "",
        "",
        "def validate_iban(value: str) -> str:",
        "    if not IBAN_RE.match(value):",
        '        raise InvalidIban("invalid IBAN")',
        "    return value",
        "",
        "",
        "def issue_refund(order, iban: str, amount_cents: int):",
        "    target = validate_iban(iban)",
        "    return gateway.payout(order.id, target, amount_cents)",
    )
    if r.random() < 0.5:
        d.tool("grep", '-rn "validate_iban" payments/ api/', J("\n", [
            T("payments/refunds.py:⟦n⟧:def validate_iban(value: str) -> str:", n=x.num(lo=8, hi=12)),
            T("payments/refunds.py:⟦n⟧:    target = validate_iban(iban)", n=x.num(lo=15, hi=19)),
            T("api/payouts.py:⟦n⟧:        iban = validate_iban(payload[\"iban\"])", n=x.num(lo=30, hi=140)),
        ]))
    d.tool("read", "payments/refunds.py", numbered(code, width=3, sep=" "))
    d.agent(say(d, "explain"), "\n", d.L(
        en="`validate_iban` matches the raw input: printed IBANs (groups of four), lowercase input and stray spaces all fail the regex, and the mod-97 checksum is never verified.",
        it="`validate_iban` controlla l'input grezzo: IBAN stampati a gruppi di quattro, minuscole e spazi falliscono la regex, e il checksum mod-97 non viene mai verificato.",
        de="`validate_iban` prüft die Roheingabe: gedruckte IBANs (Vierergruppen), Kleinbuchstaben und Leerzeichen scheitern an der Regex, und die Mod-97-Prüfsumme wird nie geprüft.",
        fr="`validate_iban` teste la saisie brute : les IBAN imprimés (groupes de quatre), les minuscules et les espaces échouent, et la clé mod-97 n'est jamais vérifiée.",
        es="`validate_iban` valida la entrada tal cual: IBAN impresos en grupos de cuatro, minúsculas y espacios fallan la regex, y nunca se comprueba el mod-97."))
    d.tool("edit", "payments/refunds.py", lines(
        " def validate_iban(value: str) -> str:",
        "-    if not IBAN_RE.match(value):",
        '+    compact = re.sub(r"\\s+", "", value).upper()',
        "+    if not IBAN_RE.match(compact) or not _mod97_ok(compact):",
        '         raise InvalidIban("invalid IBAN")',
        "-    return value",
        "+    return compact",
        "+",
        "+",
        "+def _mod97_ok(iban: str) -> bool:",
        "+    rearranged = iban[4:] + iban[:4]",
        '+    digits = "".join(str(int(c, 36)) for c in rearranged)',
        "+    return int(digits) % 97 == 1",
    ))
    d.agent(d.L(en="Adding tests. I'm using the documentation example IBANs, not the customer's.",
                it="Aggiungo i test. Uso gli IBAN di esempio della documentazione, non quelli del cliente.",
                de="Ich ergänze Tests – mit den Beispiel-IBANs aus der Dokumentation, nicht mit denen der Kunden.",
                fr="J'ajoute des tests, avec les IBAN d'exemple de la documentation et non ceux du client.",
                es="Añado tests usando los IBAN de ejemplo de la documentación, no los del cliente."))
    d.tool("write", "tests/test_refund_iban.py", lines(
        "import pytest",
        "from payments.refunds import InvalidIban, validate_iban",
        "",
        "",
        "@pytest.mark.parametrize(\"raw\", [",
        T('    "⟦a⟧",', a=x.ph("iban", "GB82 WEST 1234 5698 7654 32")),
        T('    "⟦a⟧",', a=x.ph("iban", "de89370400440532013000")),
        T('    "  ⟦a⟧ ",', a=x.ph("iban", "FR14 2004 1010 0505 0001 3M02 606")),
        "])",
        "def test_accepts_printed_and_lowercase(raw):",
        "    assert validate_iban(raw).isupper()",
        "",
        "",
        "def test_rejects_bad_checksum():",
        "    with pytest.raises(InvalidIban):",
        T('        validate_iban("⟦a⟧")', a=x.ph("iban", "GB00 WEST 1234 5698 7654 32")),
    ))
    d.tool("sh", "pytest -q tests/test_refund_iban.py", lines(
        "....                                                                     [100%]",
        T("4 passed in ⟦s⟧s", s=f"{r.uniform(0.05, 0.9):.2f}")))
    d.agent(F("Commit ", x.short(7), " fix(refunds): normalise IBAN before validation and check mod-97"))
    d.user(say(d, "thanks"))


# ================================================================ 3. Support e-mail thread


@template("support_email_thread", "plain", "ticket")
def support_email_thread(d):
    g, x, r = d.g, d.x, d.rng
    cust = d.person()
    sup = d.person(d.locale)
    _cl = d.lang_of(cust)
    order = x.id(f"#{r.randint(10000, 99999)}")
    old_addr = g.addr(cust)
    moved = d.person(cust.locale)  # used only for a fresh address
    new_addr = g.addr(moved)
    changed_on = g.date(_today(d) - dt.timedelta(days=r.randint(5, 40)), p=cust)
    sup_mail = F("support@", d.domain)
    short = r.random() < 0.3
    n_msgs = 1 if short else r.randint(2, 4)

    sigs: dict = {}

    def sig(p):
        key = id(p)
        if key not in sigs:
            rows = [F("-- "), F(g.name(p))]
            if r.random() < 0.8:
                rows.append(F(g.phone(p)))
            if r.random() < 0.5:
                rows.append(F(g.addr(p)))
            sigs[key] = J("\n", rows)
        return sigs[key]

    m1 = T(_pl(d, cust,
               en="Hello,\n\nthe invoice for order ⟦o⟧ still shows my old address (⟦a⟧). I moved and updated my account on ⟦c⟧; the new address is ⟦b⟧. My accountant needs a corrected invoice.\n\nThank you",
               it="Buongiorno,\n\nla fattura dell'ordine ⟦o⟧ riporta ancora il mio vecchio indirizzo (⟦a⟧). Ho traslocato e ho aggiornato l'account il ⟦c⟧; il nuovo indirizzo è ⟦b⟧. Il mio commercialista ha bisogno di una fattura corretta.\n\nGrazie",
               de="Guten Tag,\n\nauf der Rechnung zur Bestellung ⟦o⟧ steht noch meine alte Adresse (⟦a⟧). Ich bin umgezogen und habe mein Konto am ⟦c⟧ aktualisiert; die neue Adresse lautet ⟦b⟧. Mein Steuerberater braucht eine korrigierte Rechnung.\n\nVielen Dank",
               fr="Bonjour,\n\nla facture de la commande ⟦o⟧ indique toujours mon ancienne adresse (⟦a⟧). J'ai déménagé et mis à jour mon compte le ⟦c⟧ ; la nouvelle adresse est ⟦b⟧. Mon comptable a besoin d'une facture corrigée.\n\nMerci",
               es="Hola:\n\nla factura del pedido ⟦o⟧ sigue mostrando mi dirección antigua (⟦a⟧). Me mudé y actualicé la cuenta el ⟦c⟧; la nueva dirección es ⟦b⟧. Mi gestor necesita una factura corregida.\n\nGracias",
               nl="Hallo,\n\nop de factuur van bestelling ⟦o⟧ staat nog mijn oude adres (⟦a⟧). Ik ben verhuisd en heb mijn account op ⟦c⟧ bijgewerkt; het nieuwe adres is ⟦b⟧. Mijn boekhouder heeft een gecorrigeerde factuur nodig.\n\nBedankt",
               pt="Olá,\n\na fatura da encomenda ⟦o⟧ ainda mostra a minha morada antiga (⟦a⟧). Mudei de casa e atualizei a conta a ⟦c⟧; a nova morada é ⟦b⟧. O meu contabilista precisa de uma fatura corrigida.\n\nObrigado"),
           o=order, a=old_addr, c=changed_on, b=new_addr)
    m2 = T(_pl(d, cust,
               en="Hello ⟦s⟧,\n\nI downloaded it again today and it is still the old address. Could you please check? You can also call me.",
               it="Buongiorno ⟦s⟧,\n\nl'ho riscaricata oggi ed è ancora con il vecchio indirizzo. Potete verificare? Potete anche chiamarmi.",
               de="Hallo ⟦s⟧,\n\nich habe sie heute erneut heruntergeladen, die alte Adresse steht immer noch drauf. Können Sie das bitte prüfen? Sie können mich auch anrufen.",
               fr="Bonjour ⟦s⟧,\n\nje l'ai retéléchargée aujourd'hui et c'est toujours l'ancienne adresse. Pouvez-vous vérifier ? Vous pouvez aussi m'appeler.",
               es="Hola ⟦s⟧:\n\nla he vuelto a descargar hoy y sigue con la dirección antigua. ¿Podéis revisarlo? También podéis llamarme."),
           s=g.name(sup, "given"))
    sup_reply = T(_pl(d, cust,
                      en="Dear ⟦n⟧,\n\nthank you for your message. I have regenerated the invoice; please download it again from your account. Kind regards,",
                      it="Gentile ⟦n⟧,\n\ngrazie per il messaggio. Ho rigenerato la fattura; può scaricarla di nuovo dal suo account. Cordiali saluti,",
                      de="Sehr geehrte/r ⟦n⟧,\n\nvielen Dank für Ihre Nachricht. Ich habe die Rechnung neu erzeugt; Sie können sie erneut in Ihrem Konto herunterladen. Mit freundlichen Grüßen",
                      fr="Bonjour ⟦n⟧,\n\nmerci pour votre message. J'ai régénéré la facture ; vous pouvez la retélécharger depuis votre compte. Cordialement,",
                      es="Estimado/a ⟦n⟧:\n\ngracias por su mensaje. He regenerado la factura; puede descargarla de nuevo desde su cuenta. Un saludo,"),
                  n=g.name(cust, r.choice(["full", "family"])))

    subj = F("Re: ", _pl(d, cust, en="Invoice for order ", it="Fattura ordine ", de="Rechnung zur Bestellung ",
                          fr="Facture commande ", es="Factura pedido "), order)

    def header(frm_name, frm_mail, to, cc=None):
        rows = [F("From: ", frm_name, " <", frm_mail, ">"),
                F("Sent: " if r.random() < 0.5 else "Date: ", x.ts("rfc2822", tick=(3600, 3 * 86400), local=True)),
                F("To: ", to)]
        if cc is not None:
            rows.append(F("Cc: ", cc))
        rows.append(F("Subject: ", subj))
        return lines(*rows)

    cust_mail = g.email(cust, "personal")
    sup_addr = g.email(sup, "work")
    cust_to = F(g.name(cust), " <", cust_mail, ">")
    sup_to = F(g.name(sup), " <", sup_addr, ">")
    msgs = [F(header(F(g.name(cust)), cust_mail, sup_mail), "\n", m1, "\n\n", sig(cust), "\n")]
    if n_msgs >= 2:
        msgs.append(F(header(F(g.name(sup)), sup_addr, cust_to), "\n", sup_reply, "\n\n", sig(sup), "\n"))
    if n_msgs >= 3:
        msgs.append(F(header(F(g.name(cust)), cust_mail, sup_to), "\n", m2, "\n\n", sig(cust), "\n"))
    if n_msgs >= 4:
        lead = d.person(d.locale)
        lead_to = F(g.name(lead), " <", g.email(lead, "work"), ">")
        msgs.append(F(header(F(g.name(sup)), sup_addr, cust_to, cc=lead_to), "\n",
                      T(_pl(d, cust, en="Looping in ⟦l⟧ from our billing team.", it="Metto in copia ⟦l⟧ del team fatturazione.",
                            de="Ich nehme ⟦l⟧ aus der Buchhaltung in CC.", fr="J'ajoute ⟦l⟧ de l'équipe facturation en copie.",
                            es="Pongo en copia a ⟦l⟧ del equipo de facturación."), l=g.name(lead)),
                      "\n\n", sig(sup), "\n"))
    # newest first, older messages quoted below
    thread: list = []
    for depth, block in enumerate(reversed(msgs)):
        thread.append(prefix_lines(block, "> " * depth) if depth else block)
    d.user(d.L(en="Customer complaint below. Figure out what's wrong on our side and draft a reply in the customer's language.",
               it="Sotto il reclamo di un cliente. Capisci cosa non va da parte nostra e prepara una risposta nella lingua del cliente.",
               de="Unten eine Kundenbeschwerde. Finde heraus, was bei uns schiefläuft, und entwirf eine Antwort in der Sprache des Kunden.",
               fr="Réclamation client ci-dessous. Trouve ce qui ne va pas chez nous et rédige une réponse dans la langue du client.",
               es="Abajo la queja de un cliente. Averigua qué falla por nuestra parte y redacta una respuesta en su idioma."),
           "\n\n", J("\n", thread))
    if short:
        d.agent(d.L(en="This is the known address-snapshot issue on invoice re-issue (the PDF keeps the checkout address). Draft reply:",
                    it="È il problema noto dello snapshot dell'indirizzo nella riemissione fatture (il PDF mantiene l'indirizzo del checkout). Bozza di risposta:",
                    de="Das ist das bekannte Adress-Snapshot-Problem bei der Rechnungs-Neuausstellung (das PDF behält die Checkout-Adresse). Antwortentwurf:",
                    fr="C'est le problème connu d'instantané d'adresse lors de la réémission (le PDF garde l'adresse du paiement). Projet de réponse :",
                    es="Es el problema conocido de la instantánea de dirección al reemitir facturas (el PDF conserva la del checkout). Borrador:"),
                "\n\n", T(_pl(d, cust, en="Dear ⟦n⟧, we will send you a corrected invoice addressed to ⟦b⟧ shortly.",
                                it="Gentile ⟦n⟧, le invieremo a breve una fattura corretta intestata a ⟦b⟧.",
                                de="Sehr geehrte/r ⟦n⟧, Sie erhalten in Kürze eine korrigierte Rechnung an ⟦b⟧.",
                                fr="Bonjour ⟦n⟧, nous vous enverrons rapidement une facture corrigée à l'adresse ⟦b⟧.",
                                es="Estimado/a ⟦n⟧: en breve le enviaremos una factura corregida a nombre de ⟦b⟧."),
                            n=g.name(cust), b=g.addr(moved)))
        return
    d.agent(say(d, "searching", x="billing_address"))
    hits = [
        ("app/invoices/render.py", "address = order.billing_address_snapshot"),
        ("app/invoices/render.py", "# snapshot is taken at checkout time (legal requirement)"),
        ("app/accounts/service.py", "def update_billing_address(account, addr):"),
        ("app/invoices/regenerate.py", "pdf = render(order)  # TODO: use current address for re-issue?"),
    ]
    d.tool("grep", '-rn "billing_address" app/', J("\n", [T("⟦f⟧:⟦n⟧:    ⟦c⟧", f=f, n=x.num(lo=8, hi=240), c=c) for f, c in hits]))
    d.agent(say(d, "explain"), "\n", d.L(
        en="Invoices are rendered from the address snapshot taken at checkout, and `regenerate` re-renders the same snapshot. So the support re-issue never picks up the updated address. A corrected invoice needs a credit note plus a new invoice with the current billing address.",
        it="Le fatture vengono generate dallo snapshot dell'indirizzo preso al checkout e `regenerate` riusa lo stesso snapshot, quindi la riemissione dal supporto non prende mai l'indirizzo aggiornato. Serve una nota di credito più una nuova fattura con l'indirizzo attuale.",
        de="Rechnungen werden aus dem beim Checkout gespeicherten Adress-Snapshot erzeugt, und `regenerate` rendert denselben Snapshot erneut. Die Neuausstellung durch den Support übernimmt die neue Adresse also nie. Nötig sind Gutschrift plus neue Rechnung mit aktueller Adresse.",
        fr="Les factures sont générées à partir de l'instantané d'adresse pris au paiement, et `regenerate` réutilise ce même instantané. La réémission par le support ne prend donc jamais la nouvelle adresse. Il faut un avoir puis une nouvelle facture avec l'adresse actuelle.",
        es="Las facturas se generan con la instantánea de la dirección tomada en el checkout y `regenerate` vuelve a usar esa misma instantánea, así que la reemisión nunca coge la dirección nueva. Hace falta una factura rectificativa y una nueva con la dirección actual."))
    d.agent(d.L(en="Draft reply:", it="Bozza di risposta:", de="Antwortentwurf:", fr="Projet de réponse :", es="Borrador de respuesta:"),
            "\n\n", T(_pl(d, cust,
                          en="Dear ⟦n⟧,\n\nwe are sorry for the trouble. We will cancel the invoice for order ⟦o⟧ with a credit note and issue a new one to ⟦b⟧ within two working days.\n\nBest regards,\n⟦s⟧",
                          it="Gentile ⟦n⟧,\n\nci scusiamo per il disagio. Annulleremo la fattura dell'ordine ⟦o⟧ con una nota di credito ed emetteremo una nuova fattura intestata a ⟦b⟧ entro due giorni lavorativi.\n\nCordiali saluti,\n⟦s⟧",
                          de="Sehr geehrte/r ⟦n⟧,\n\nentschuldigen Sie bitte die Umstände. Wir stornieren die Rechnung zur Bestellung ⟦o⟧ per Gutschrift und stellen innerhalb von zwei Werktagen eine neue an ⟦b⟧ aus.\n\nMit freundlichen Grüßen\n⟦s⟧",
                          fr="Bonjour ⟦n⟧,\n\nnous sommes désolés pour ce désagrément. Nous annulerons la facture de la commande ⟦o⟧ par un avoir et émettrons une nouvelle facture à l'adresse ⟦b⟧ sous deux jours ouvrés.\n\nCordialement,\n⟦s⟧",
                          es="Estimado/a ⟦n⟧:\n\nsentimos las molestias. Anularemos la factura del pedido ⟦o⟧ con una rectificativa y emitiremos una nueva a ⟦b⟧ en un plazo de dos días laborables.\n\nUn saludo,\n⟦s⟧"),
                      n=g.name(cust), o=order, b=g.addr(moved), s=g.name(sup)))
    if r.random() < 0.5:
        d.user(say(d, "thanks"))


# ================================================================ 4. Slack incident thread


@template("slack_incident_thread", "cc", "ticket", "log")
def slack_incident_thread(d):
    g, x, r = d.g, d.x, d.rng
    crew = d.people(r.randint(3, 5), d.locale)
    svc = r.choice(["checkout", "payments-api", "search", "auth", "orders"])
    up_ip = g.ip("private")
    db_ip = g.ip("private")
    client_ip = g.ip("public")
    leaked_pw = g.password()
    leaked_tok = g.secret(r.choice(["datadog", "bearer_opaque", "hex32", "vault_token"]))
    msgs = []
    t0 = d.clock.t

    def msg(p, *parts):
        msgs.append(F(g.name(p), "  ", _hm(d, 30, 240), "\n", *parts, "\n"))

    a, b, c = crew[0], crew[1], crew[2]
    msg(a, T(_pl(d, a, en="@here ⟦s⟧ is returning 502s, error rate ~30%. anyone looking?",
                 it="@here ⟦s⟧ restituisce 502, error rate intorno al 30%. qualcuno ci sta guardando?",
                 de="@here ⟦s⟧ liefert 502er, Fehlerrate ~30 %. Schaut schon jemand?",
                 fr="@here ⟦s⟧ renvoie des 502, ~30 % d'erreurs. quelqu'un regarde ?",
                 es="@here ⟦s⟧ devuelve 502, ~30 % de errores. ¿alguien lo está mirando?"), s=svc))
    msg(b, T(_pl(d, b, en="looking. nginx says upstream timeouts:", it="ci guardo. nginx segnala timeout verso l'upstream:",
                 de="schau ich mir an. nginx meldet Upstream-Timeouts:", fr="je regarde. nginx remonte des timeouts upstream :",
                 es="lo miro. nginx da timeouts del upstream:")),
        "\n```\n",
        T('⟦t⟧ [error] 31#31: *⟦n⟧ upstream timed out (110: Connection timed out) while reading response header from upstream, client: ⟦c⟧, server: api.⟦dom⟧, request: "POST /v1/⟦s⟧ HTTP/1.1", upstream: "http://⟦u⟧:⟦p⟧/v1/⟦s⟧"',
          t=x.ts("slash", tick=(1, 30)), n=x.num(lo=10000, hi=999999), c=client_ip, dom=d.domain, s=svc, u=up_ip, p=x.port(8080)),
        "\n```")
    msg(c, T(_pl(d, c, en="db looks saturated, ⟦n⟧ active connections on ⟦ip⟧. checking pg_stat_activity",
                 it="il db sembra saturo, ⟦n⟧ connessioni attive su ⟦ip⟧. controllo pg_stat_activity",
                 de="DB wirkt ausgelastet, ⟦n⟧ aktive Verbindungen auf ⟦ip⟧. Ich prüfe pg_stat_activity",
                 fr="la base semble saturée, ⟦n⟧ connexions actives sur ⟦ip⟧. je regarde pg_stat_activity",
                 es="la bd parece saturada, ⟦n⟧ conexiones activas en ⟦ip⟧. miro pg_stat_activity"),
             n=x.num(lo=180, hi=500), ip=db_ip))
    leak_kind = r.choice(["pw", "tok"])
    if leak_kind == "pw":
        msg(b, T(_pl(d, b, en="if you don't have access use this: `PGPASSWORD=⟦pw⟧ psql -h ⟦ip⟧ -U ops_admin core`",
                     it="se non hai accesso usa questo: `PGPASSWORD=⟦pw⟧ psql -h ⟦ip⟧ -U ops_admin core`",
                     de="falls du keinen Zugang hast: `PGPASSWORD=⟦pw⟧ psql -h ⟦ip⟧ -U ops_admin core`",
                     fr="si t'as pas les accès : `PGPASSWORD=⟦pw⟧ psql -h ⟦ip⟧ -U ops_admin core`",
                     es="si no tienes acceso usa esto: `PGPASSWORD=⟦pw⟧ psql -h ⟦ip⟧ -U ops_admin core`"),
                 pw=leaked_pw, ip=db_ip))
    else:
        msg(b, T(_pl(d, b, en="dashboard API token if you need it: ⟦t⟧",
                     it="token API della dashboard se ti serve: ⟦t⟧",
                     de="API-Token fürs Dashboard, falls du ihn brauchst: ⟦t⟧",
                     fr="token API du dashboard si besoin : ⟦t⟧",
                     es="token de la API del dashboard por si lo necesitas: ⟦t⟧"), t=leaked_tok))
    msg(a, T(_pl(d, a, en="⟦h⟧ please don't paste creds in channels 🙏 I'll rotate after the incident",
                 it="⟦h⟧ per favore niente credenziali nei canali 🙏 le ruoto dopo l'incidente",
                 de="⟦h⟧ bitte keine Zugangsdaten in Channels posten 🙏 ich rotiere nach dem Incident",
                 fr="⟦h⟧ merci de ne pas coller d'identifiants dans les canaux 🙏 je les renouvelle après l'incident",
                 es="⟦h⟧ por favor no pegues credenciales en los canales 🙏 las roto después del incidente"),
             h=g.handle(b)))
    msg(c, T(_pl(d, c, en="found it: a batch job (report-export) opened ⟦n⟧ connections without pooling. killed it at ⟦t⟧, errors dropping",
                 it="trovato: un job batch (report-export) ha aperto ⟦n⟧ connessioni senza pool. ucciso alle ⟦t⟧, errori in calo",
                 de="gefunden: ein Batch-Job (report-export) hat ⟦n⟧ Verbindungen ohne Pooling geöffnet. Um ⟦t⟧ gekillt, Fehler gehen runter",
                 fr="trouvé : un batch (report-export) a ouvert ⟦n⟧ connexions sans pool. tué à ⟦t⟧, les erreurs baissent",
                 es="encontrado: un batch (report-export) abrió ⟦n⟧ conexiones sin pool. lo maté a las ⟦t⟧, bajan los errores"),
             n=x.num(lo=150, hi=420), t=x.ts("time", tick=(60, 600), local=True)))
    t_fix = d.clock.t
    if r.random() < 0.6:
        deploy = x.ver()
        msg(crew[1], T(_pl(d, crew[1], en="also rolling back the 14:00 deploy just in case (⟦v⟧ → previous, commit ⟦c⟧)",
                            it="faccio anche rollback del deploy delle 14 per sicurezza (⟦v⟧ → precedente, commit ⟦c⟧)",
                            de="ich rolle sicherheitshalber auch das Deploy von 14 Uhr zurück (⟦v⟧ → vorher, Commit ⟦c⟧)",
                            fr="je rollback aussi le déploiement de 14h par précaution (⟦v⟧ → précédent, commit ⟦c⟧)",
                            es="por si acaso hago rollback del despliegue de las 14:00 (⟦v⟧ → anterior, commit ⟦c⟧)"),
                       v=deploy, c=x.short()))
    if r.random() < 0.5:
        msg(crew[0], T(_pl(d, crew[0], en="status page updated. ⟦h⟧ can you own the postmortem?",
                            it="status page aggiornata. ⟦h⟧ ti occupi tu del postmortem?",
                            de="Statusseite aktualisiert. ⟦h⟧ übernimmst du das Postmortem?",
                            fr="page de statut mise à jour. ⟦h⟧ tu prends le postmortem ?",
                            es="página de estado actualizada. ⟦h⟧ ¿te encargas del postmortem?"), h=g.handle(d.me)))
    for extra in crew[3:]:
        msg(extra, T(_pl(d, extra, en="confirming from the client side: ⟦ip⟧ (our office egress) gets 200s again",
                         it="confermo lato client: ⟦ip⟧ (egress dell'ufficio) riceve di nuovo 200",
                         de="bestätige von Client-Seite: ⟦ip⟧ (Office-Egress) bekommt wieder 200er",
                         fr="je confirme côté client : ⟦ip⟧ (sortie du bureau) reçoit de nouveau des 200",
                         es="confirmo desde cliente: ⟦ip⟧ (salida de la oficina) vuelve a recibir 200"), ip=g.ip("public")))
    d.user(d.L(en="Turn this Slack thread into the incident summary for docs/postmortems/. Redact anything sensitive.",
               it="Trasforma questo thread Slack nel riepilogo dell'incidente per docs/postmortems/. Oscura tutto ciò che è sensibile.",
               de="Mach aus diesem Slack-Thread die Incident-Zusammenfassung für docs/postmortems/. Sensibles bitte schwärzen.",
               fr="Transforme ce fil Slack en résumé d'incident pour docs/postmortems/. Masque tout ce qui est sensible.",
               es="Convierte este hilo de Slack en el resumen del incidente para docs/postmortems/. Oculta lo sensible."),
           "\n\n", J("\n", msgs))
    d.agent(say(d, "look_first", x="docs/postmortems/TEMPLATE.md"))
    d.tool("read", "docs/postmortems/TEMPLATE.md", lines(
        "# <title>", "", "- Date:", "- Duration:", "- Severity:", "- Owner (role, not name):", "", "## Impact", "",
        "## Timeline (UTC)", "", "## Root cause", "", "## Action items", "", "_Never paste credentials, customer data or IPs of clients here._"))
    fname = F("docs/postmortems/", x.ts("date"), "-", svc, "-502.md")
    d.tool("write", fname, lines(
        T("# ⟦s⟧ 502s caused by connection exhaustion", s=svc), "",
        T("- Date: ⟦t⟧", t=x.ts("date")), T("- Duration: ⟦m⟧ min", m=x.num(lo=12, hi=95)),
        "- Severity: SEV2", "- Owner: on-call backend engineer", "",
        "## Impact", T("~30% of `POST /v1/⟦s⟧` requests failed with 502.", s=svc), "",
        "## Timeline (UTC)",
        T("- ⟦t⟧ alert in #incidents", t=x.ts("time", t=t0)),
        T("- ⟦t⟧ upstream timeouts confirmed in nginx", t=x.ts("time", t=t0 + dt.timedelta(minutes=r.randint(2, 9)))),
        T("- ⟦t⟧ report-export batch job identified and stopped", t=x.ts("time", t=t_fix)), "",
        "## Root cause",
        "The report-export job opened one connection per chunk without the shared pool, exhausting max_connections.", "",
        "## Action items",
        "- route batch jobs through pgbouncer",
        T("- rotate the credential posted in the channel (value: ⟦r⟧)", r=x.ph("generic", "[REDACTED]")),
    ))
    leaked = leaked_pw if leak_kind == "pw" else leaked_tok
    if leaked.label:
        warn = say(d, "secret_warning", x=d.L(en="the Slack thread", it="il thread Slack", de="der Slack-Thread", fr="le fil Slack", es="el hilo de Slack"))
    else:
        warn = d.L(en="The value pasted in the thread is a placeholder, so nothing to rotate there.",
                   it="Il valore incollato nel thread è un segnaposto, quindi non c'è nulla da ruotare.",
                   de="Der im Thread gepostete Wert ist nur ein Platzhalter, da muss nichts rotiert werden.",
                   fr="La valeur collée dans le fil est un placeholder, rien à renouveler de ce côté.",
                   es="El valor pegado en el hilo es un marcador de posición, no hay nada que rotar.")
    d.agent(warn, "\n", d.L(en="I left people's names, the client IPs and the internal hosts out of the document.",
                      it="Nel documento non ho riportato nomi, IP dei client e host interni.",
                      de="Namen, Client-IPs und interne Hosts habe ich im Dokument weggelassen.",
                      fr="J'ai retiré du document les noms, les IP clientes et les hôtes internes.",
                      es="He dejado fuera del documento los nombres, las IP de clientes y los hosts internos."))


# ================================================================ 5. HR onboarding


_TEAMS = ["Platform", "Payments", "Data", "Mobile", "Customer Care", "Finance", "Logistics", "Security", "Sales Ops"]


@template("hr_onboarding_accounts", "xml", "ticket", "shell")
def hr_onboarding_accounts(d):
    g, x, r = d.g, d.x, d.rng
    hr = d.person(d.locale)
    hires = d.people(r.randint(2, 7))
    managers = d.people(r.randint(1, 2), d.locale)
    key = x.id(f"HR-{r.randint(100, 2400)}")
    start = _future(d, 12, 40)
    date_fmt = V.date_fmt_for(hr.locale, r)
    emp_prefix = r.choice(["EMP", "E-", "PN", "", "HR-"])
    emp_base = r.randint(1000, 90000)
    rows = []
    for h in hires:
        h.extra["team"] = r.choice(_TEAMS)
        h.extra["mgr"] = r.choice(managers)
        emp_base += r.randint(1, 40)
        h.extra["emp"] = g.raw("account_number", f"{emp_prefix}{emp_base:05d}", "generic")
        h.extra["start"] = start + dt.timedelta(days=r.choice([0, 0, 0, 7, 14]))
        h.extra["mobile"] = g.phone(h, intl=True)
        rows.append([g.name(h), g.date(h.extra["start"], date_fmt, hr), h.extra["emp"], g.email(h, "personal"),
                     h.extra["mobile"], h.extra["team"], g.name(h.extra["mgr"])])
    d.user(T(d.L(
        en="HR ticket ⟦k⟧ lists next month's new hires. Create their accounts with scripts/provision.py — dry run first.",
        it="Il ticket HR ⟦k⟧ elenca i nuovi assunti del mese prossimo. Crea gli account con scripts/provision.py, prima in dry run.",
        de="Im HR-Ticket ⟦k⟧ stehen die Neueinstellungen für nächsten Monat. Leg die Accounts mit scripts/provision.py an — zuerst als Dry Run.",
        fr="Le ticket RH ⟦k⟧ liste les arrivées du mois prochain. Crée leurs comptes avec scripts/provision.py — d'abord en dry run.",
        es="El ticket de RR. HH. ⟦k⟧ tiene las incorporaciones del mes que viene. Crea las cuentas con scripts/provision.py, primero en dry run."),
        k=key))
    intro = _pl(d, hr,
                en="Hi IT team,\n\nplease prepare accounts and laptops for the following new colleagues. Personal e-mail is where the welcome mail should go before day one.",
                it="Ciao team IT,\n\nper favore preparate account e portatili per i seguenti nuovi colleghi. L'e-mail personale serve per il messaggio di benvenuto prima del primo giorno.",
                de="Hallo IT-Team,\n\nbitte bereitet Accounts und Laptops für die folgenden neuen Kolleg:innen vor. An die private E-Mail soll vor dem ersten Arbeitstag die Willkommensmail gehen.",
                fr="Bonjour l'équipe IT,\n\nmerci de préparer comptes et ordinateurs pour les nouveaux collègues ci-dessous. L'e-mail personnel sert à envoyer le message de bienvenue avant le premier jour.",
                es="Hola equipo de IT:\n\npreparad cuentas y portátiles para las siguientes incorporaciones. El correo personal es para el mensaje de bienvenida antes del primer día.")
    head = [_pl(d, hr, en="Name", it="Nome", de="Name", fr="Nom", es="Nombre"),
            _pl(d, hr, en="Start date", it="Data inizio", de="Startdatum", fr="Date d'arrivée", es="Fecha de inicio"),
            _pl(d, hr, en="Employee no.", it="Matricola", de="Personalnr.", fr="Matricule", es="N.º empleado"),
            _pl(d, hr, en="Private e-mail", it="E-mail personale", de="Private E-Mail", fr="E-mail perso", es="Correo personal"),
            _pl(d, hr, en="Mobile", it="Cellulare", de="Mobil", fr="Portable", es="Móvil"),
            "Team", "Manager"]
    notes = []
    foreign = [h for h in hires if h.locale != hr.locale]
    if foreign and r.random() < 0.75:
        for h in foreign[:2]:
            expiry = start + dt.timedelta(days=r.randint(200, 3000))
            notes.append(T(_pl(d, hr,
                               en="Note: ⟦n⟧ needs a work permit — passport no. ⟦p⟧ (valid until ⟦v⟧) is already on file.",
                               it="Nota: ⟦n⟧ ha bisogno del permesso di lavoro — passaporto n. ⟦p⟧ (scadenza ⟦v⟧) già in archivio.",
                               de="Hinweis: ⟦n⟧ braucht eine Arbeitserlaubnis — Reisepass Nr. ⟦p⟧ (gültig bis ⟦v⟧) liegt uns vor.",
                               fr="Note : ⟦n⟧ a besoin d'un permis de travail — passeport n° ⟦p⟧ (valable jusqu'au ⟦v⟧) déjà au dossier.",
                               es="Nota: ⟦n⟧ necesita permiso de trabajo; pasaporte n.º ⟦p⟧ (válido hasta ⟦v⟧) ya archivado."),
                           n=g.name(h), p=g.passport(h), v=g.date(expiry, date_fmt, hr)))
            notes.append("\n")
    ticket = F(T("⟦k⟧  [Onboarding] ", k=key), _pl(d, hr, en="New hires", it="Nuovi assunti", de="Neueinstellungen", fr="Nouvelles arrivées", es="Incorporaciones"),
               "\nReporter: ", g.name(hr), " (", g.email(hr, "work"), ")\nStatus: Open   Priority: Medium\nCreated: ",
               x.ts("space", tick=(3600, 86400)), "\n\n", intro, "\n\n", grid(head, rows, style="md"), "\n", notes,
               _pl(d, hr, en="Thanks!", it="Grazie!", de="Danke!", fr="Merci !", es="¡Gracias!"), "\n", g.name(hr, "given"), "\n")
    d.tool("sh", F("jira issue view ", key, " --plain"), ticket)
    d.tool("read", "scripts/provision.py", lines(
        '"""Create directory accounts from a CSV export."""',
        "import argparse, csv, os, secrets",
        "from directory_client import Directory",
        "",
        T('DOMAIN = "⟦dom⟧"', dom=d.domain),
        'TOKEN = os.environ["DIRECTORY_TOKEN"]',
        "",
        "def username(row):",
        '    return f"{row[\'given_name\']}.{row[\'family_name\']}".lower().replace(" ", "")',
        "",
        "def main():",
        "    ap = argparse.ArgumentParser()",
        '    ap.add_argument("--csv", required=True)',
        '    ap.add_argument("--dry-run", action="store_true")',
        "    args = ap.parse_args()",
        "    d = Directory(token=TOKEN)",
        "    for row in csv.DictReader(open(args.csv, encoding=\"utf-8\")):",
        "        email = f\"{username(row)}@{DOMAIN}\"",
        "        if args.dry_run:",
        "            print(f\"[dry-run] would create {email} ({row['employee_id']}) team={row['team']} start={row['start_date']}\")",
        "            continue",
        "        pw = secrets.token_urlsafe(12)",
        "        uid = d.create_user(email=email, employee_id=row['employee_id'], temp_password=pw,",
        "                            recovery_email=row['personal_email'], phone=row['mobile'])",
        "        print(f\"created {email} uid={uid} temp_password={pw}\")",
    ))
    d.agent(d.L(en="Writing the CSV the script expects from the ticket table.",
                it="Scrivo il CSV che lo script si aspetta, partendo dalla tabella del ticket.",
                de="Ich schreibe aus der Tickettabelle die CSV, die das Skript erwartet.",
                fr="J'écris le CSV attendu par le script à partir du tableau du ticket.",
                es="Escribo el CSV que espera el script a partir de la tabla del ticket."))
    csv_rows = ["given_name,family_name,start_date,employee_id,personal_email,mobile,team,manager_email"]
    for h in hires:
        csv_rows.append(F(g.name(h, "given"), ",", g.name(h, "family"), ",", g.date(h.extra["start"], "iso", h), ",",
                          h.extra["emp"], ",", g.email(h, "personal"), ",", h.extra["mobile"], ",", h.extra["team"], ",",
                          g.email(h.extra["mgr"], "work")))
    d.tool("write", "new_hires.csv", lines(*csv_rows))
    d.tool("sh", "python scripts/provision.py --csv new_hires.csv --dry-run", J("\n", [
        T("[dry-run] would create ⟦e⟧ (⟦n⟧) team=⟦t⟧ start=⟦s⟧", e=g.email(h, "work", style=0), n=h.extra["emp"],
          t=h.extra["team"], s=g.date(h.extra["start"], "iso", h)) for h in hires]))
    d.agent(d.L(en="Dry run looks consistent with the ticket. Shall I create the accounts for real?",
                it="Il dry run è coerente con il ticket. Creo gli account per davvero?",
                de="Der Dry Run passt zum Ticket. Soll ich die Accounts jetzt wirklich anlegen?",
                fr="Le dry run correspond au ticket. Je crée les comptes pour de vrai ?",
                es="El dry run cuadra con el ticket. ¿Creo las cuentas de verdad?"))
    d.user(say(d, "go_ahead"))
    out = []
    for h in hires:
        out.append(T("created ⟦e⟧ uid=⟦u⟧ temp_password=⟦p⟧", e=g.email(h, "work", style=0), u=x.num(lo=10400, hi=99000),
                     p=g.raw("secret", V.rand_str(r, V.ALNUM + "-_", 16), "password")))
        if r.random() < 0.4:
            out.append(T("  welcome mail queued -> ⟦m⟧", m=g.email(h, "personal")))
    d.tool("sh", "python scripts/provision.py --csv new_hires.csv", J("\n", out))
    d.agent(say(d, "done"), "\n", d.L(
        en="- accounts created for every row of the ticket\n- the temporary passwords above are in this session's output: hand them over through the password manager, not by mail\n- new_hires.csv contains private e-mails and phone numbers; I'd delete it now",
        it="- account creati per ogni riga del ticket\n- le password temporanee sono nell'output di questa sessione: consegnale tramite il password manager, non via mail\n- new_hires.csv contiene e-mail e numeri privati; lo cancellerei subito",
        de="- Accounts für jede Zeile des Tickets angelegt\n- die temporären Passwörter stehen in dieser Ausgabe: bitte über den Passwortmanager übergeben, nicht per Mail\n- new_hires.csv enthält private Mails und Telefonnummern; ich würde sie jetzt löschen",
        fr="- comptes créés pour chaque ligne du ticket\n- les mots de passe temporaires figurent dans cette sortie : transmets-les via le gestionnaire de mots de passe, pas par mail\n- new_hires.csv contient des e-mails et numéros privés ; je le supprimerais maintenant",
        es="- cuentas creadas para cada fila del ticket\n- las contraseñas temporales están en esta salida: entrégalas por el gestor de contraseñas, no por correo\n- new_hires.csv tiene correos y teléfonos privados; lo borraría ya"))
    if r.random() < 0.5:
        d.tool("sh", "rm new_hires.csv && git status --short", "")


# ================================================================ 6. GDPR request


@template("gdpr_dsar_deletion", "md", "ticket", "shell")
def gdpr_dsar_deletion(d):
    g, x, r = d.g, d.x, d.rng
    req = d.person()
    kind = r.choice(["erasure", "erasure", "access"])
    email = g.email(req, "personal")
    cust_no = g.cust()
    art = "17" if kind == "erasure" else "15"
    letter = T(_pl(d, req,
        en=("Subject: Request to erase my personal data (Art. 17 GDPR)\n\nDear Sir or Madam,\n\nunder Article 17 GDPR I ask you to erase all personal data you hold about me. To identify me: name ⟦n⟧, e-mail ⟦e⟧, postal address ⟦a⟧, customer number ⟦c⟧.\n\nPlease confirm the erasure within one month.\n\n⟦n⟧"
            if kind == "erasure" else
            "Subject: Subject access request (Art. 15 GDPR)\n\nHello,\n\nplease send me a copy of all personal data you process about me. Name ⟦n⟧, e-mail ⟦e⟧, address ⟦a⟧, customer number ⟦c⟧.\n\nRegards,\n⟦n⟧"),
        it=("Oggetto: Richiesta di cancellazione dei dati personali (art. 17 GDPR)\n\nGentili Signori,\n\nai sensi dell'articolo 17 del GDPR vi chiedo di cancellare tutti i dati personali che mi riguardano. Per identificarmi: nome ⟦n⟧, e-mail ⟦e⟧, indirizzo ⟦a⟧, codice cliente ⟦c⟧.\n\nVi prego di confermare l'avvenuta cancellazione entro un mese.\n\n⟦n⟧"
            if kind == "erasure" else
            "Oggetto: Richiesta di accesso ai dati (art. 15 GDPR)\n\nBuongiorno,\n\nvi chiedo copia di tutti i dati personali che trattate su di me. Nome ⟦n⟧, e-mail ⟦e⟧, indirizzo ⟦a⟧, codice cliente ⟦c⟧.\n\nCordiali saluti,\n⟦n⟧"),
        de=("Betreff: Antrag auf Löschung meiner personenbezogenen Daten (Art. 17 DSGVO)\n\nSehr geehrte Damen und Herren,\n\ngemäß Art. 17 DSGVO fordere ich Sie auf, sämtliche bei Ihnen gespeicherten personenbezogenen Daten zu meiner Person zu löschen. Zur Identifikation: Name ⟦n⟧, E-Mail ⟦e⟧, Anschrift ⟦a⟧, Kundennummer ⟦c⟧.\n\nBitte bestätigen Sie mir die Löschung innerhalb eines Monats.\n\nMit freundlichen Grüßen\n⟦n⟧"
            if kind == "erasure" else
            "Betreff: Auskunftsersuchen nach Art. 15 DSGVO\n\nGuten Tag,\n\nbitte übermitteln Sie mir eine Kopie aller personenbezogenen Daten, die Sie über mich verarbeiten. Name ⟦n⟧, E-Mail ⟦e⟧, Anschrift ⟦a⟧, Kundennummer ⟦c⟧.\n\nFreundliche Grüße\n⟦n⟧"),
        fr=("Objet : Demande d'effacement de mes données (article 17 du RGPD)\n\nMadame, Monsieur,\n\nconformément à l'article 17 du RGPD, je vous demande d'effacer l'ensemble des données personnelles me concernant. Pour m'identifier : nom ⟦n⟧, e-mail ⟦e⟧, adresse postale ⟦a⟧, numéro client ⟦c⟧.\n\nMerci de me confirmer l'effacement dans un délai d'un mois.\n\n⟦n⟧"
            if kind == "erasure" else
            "Objet : Demande d'accès (article 15 du RGPD)\n\nBonjour,\n\nje souhaite obtenir une copie de toutes les données personnelles que vous traitez à mon sujet. Nom ⟦n⟧, e-mail ⟦e⟧, adresse ⟦a⟧, numéro client ⟦c⟧.\n\nCordialement,\n⟦n⟧"),
        es=("Asunto: Solicitud de supresión de mis datos personales (art. 17 RGPD)\n\nMuy señores míos:\n\nen virtud del artículo 17 del RGPD les solicito la supresión de todos los datos personales que conservan sobre mí. Para identificarme: nombre ⟦n⟧, correo ⟦e⟧, dirección ⟦a⟧, número de cliente ⟦c⟧.\n\nRuego me confirmen la supresión en el plazo de un mes.\n\n⟦n⟧"
            if kind == "erasure" else
            "Asunto: Solicitud de acceso (art. 15 RGPD)\n\nHola:\n\nsolicito una copia de todos los datos personales que tratan sobre mí. Nombre ⟦n⟧, correo ⟦e⟧, dirección ⟦a⟧, número de cliente ⟦c⟧.\n\nUn saludo,\n⟦n⟧"),
        nl=("Onderwerp: Verzoek tot verwijdering van mijn persoonsgegevens (art. 17 AVG)\n\nGeachte heer/mevrouw,\n\nop grond van artikel 17 AVG verzoek ik u alle persoonsgegevens die u over mij bewaart te verwijderen. Ter identificatie: naam ⟦n⟧, e-mail ⟦e⟧, adres ⟦a⟧, klantnummer ⟦c⟧.\n\nGraag binnen een maand een bevestiging.\n\n⟦n⟧"
            if kind == "erasure" else
            "Onderwerp: Inzageverzoek (art. 15 AVG)\n\nGoedendag,\n\ngraag ontvang ik een kopie van alle persoonsgegevens die u over mij verwerkt. Naam ⟦n⟧, e-mail ⟦e⟧, adres ⟦a⟧, klantnummer ⟦c⟧.\n\nMet vriendelijke groet,\n⟦n⟧")),
        n=g.name(req), e=email, a=g.addr(req), c=cust_no)
    d.user(T(d.L(
        en="Privacy inbox got this request (pasted below). Find everything we hold on this person and prepare the ⟦w⟧. Don't run any DELETE without asking me.",
        it="Alla casella privacy è arrivata questa richiesta (incollata sotto). Trova tutto quello che abbiamo su questa persona e prepara la ⟦w⟧. Non lanciare nessun DELETE senza chiedermelo.",
        de="Im Datenschutz-Postfach kam diese Anfrage (unten). Finde alles, was wir zu der Person speichern, und bereite die ⟦w⟧ vor. Kein DELETE ohne Rücksprache.",
        fr="La boîte privacy a reçu cette demande (collée ci-dessous). Trouve tout ce qu'on détient sur cette personne et prépare l'⟦w⟧. Aucun DELETE sans mon accord.",
        es="Al buzón de privacidad ha llegado esta solicitud (abajo). Encuentra todo lo que tenemos de esta persona y prepara la ⟦w⟧. Nada de DELETE sin preguntarme."),
        w=d.L(en="erasure" if kind == "erasure" else "data export", it="cancellazione" if kind == "erasure" else "esportazione dei dati",
              de="Löschung" if kind == "erasure" else "Datenauskunft", fr="effacement" if kind == "erasure" else "export des données",
              es="supresión" if kind == "erasure" else "exportación de datos")),
        "\n\n---\n", letter, "\n---")
    cid = x.num(lo=1000, hi=990000)
    d.agent(say(d, "searching", x=d.L(en="the customer record", it="il record del cliente", de="den Kundendatensatz",
                                       fr="la fiche client", es="la ficha del cliente")))
    q = F("psql -d app -c \"select id, customer_no, full_name, email, created_at from customers where lower(email) = lower('", email,
          "') or customer_no = '", cust_no, "';\"")
    d.tool("sh", q, grid(["id", "customer_no", "full_name", "email", "created_at"],
                         [[cid, cust_no, g.name(req), email, x.ts("space", t=d.clock.t - dt.timedelta(days=r.randint(200, 2400)))]]))
    tables = [("addresses", r.randint(1, 3)), ("orders", r.randint(0, 40)), ("newsletter_subscriptions", r.randint(0, 1)),
              ("support_tickets", r.randint(0, 6)), ("login_events", r.randint(20, 900)), ("payment_methods", r.randint(0, 2))]
    d.tool("sh", F("psql -d app -f ops/dsar/count_rows.sql -v cid=", cid),
           grid(["table_name", "rows"], [[t, str(n)] for t, n in tables]))
    addr_rows = []
    for i in range(tables[0][1]):
        holder = req if i == 0 else d.person(req.locale)
        addr_rows.append([x.num(lo=100, hi=99999), g.addr(holder, "street"), g.addr(holder, "postcode"), g.addr(holder, "city"),
                          holder.country, "t" if i == 0 else "f"])
    d.tool("sh", F("psql -d app -c \"select id, street, postcode, city, country, is_default from addresses where customer_id = ", cid, ";\""),
           grid(["id", "street", "postcode", "city", "country", "is_default"], addr_rows))
    if r.random() < 0.6:
        ev = []
        times = sorted((d.clock.t - dt.timedelta(seconds=r.randint(3600, 86400 * 60)) for _ in range(r.randint(3, 5))), reverse=True)
        for t_ev in times:
            ev.append([x.ts("space", t=t_ev), g.ip(r.choice(["public", "public", "v6"])),
                       r.choice(["Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4)",
                                 "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"])])
        d.tool("sh", F("psql -d app -c \"select ts, ip, user_agent from login_events where customer_id = ", cid,
                       " order by ts desc limit 5;\""), grid(["ts", "ip", "user_agent"], ev))
    if kind == "erasure":
        sql = lines(
            T("-- DSAR erasure for customer ⟦c⟧ (Art. 17); invoices kept 10 years for tax law", c=cid),
            "BEGIN;",
            T("DELETE FROM addresses WHERE customer_id = ⟦c⟧ AND id NOT IN (SELECT billing_address_id FROM invoices WHERE customer_id = ⟦c⟧);", c=cid),
            T("DELETE FROM newsletter_subscriptions WHERE lower(email) = lower('⟦e⟧');", e=email),
            T("DELETE FROM login_events WHERE customer_id = ⟦c⟧;", c=cid),
            T("DELETE FROM payment_methods WHERE customer_id = ⟦c⟧;", c=cid),
            T("UPDATE support_tickets SET requester_name = NULL, requester_email = NULL, body = '[erased]' WHERE customer_id = ⟦c⟧;", c=cid),
            T("UPDATE customers SET full_name = NULL, phone = NULL, email = 'erased+' || id || '@invalid', erased_at = now() WHERE id = ⟦c⟧;", c=cid),
            "COMMIT;")
        path = F("ops/dsar/", x.ts("date"), "-", cid, ".sql")
        d.tool("write", path, sql)
        d.agent(d.L(en="The script is ready. Invoices and their billing addresses stay because of the statutory retention period; everything else is deleted or anonymised. Run it?",
                    it="Lo script è pronto. Fatture e relativi indirizzi di fatturazione restano per l'obbligo di conservazione; il resto viene cancellato o anonimizzato. Lo eseguo?",
                    de="Das Skript ist fertig. Rechnungen samt Rechnungsadresse bleiben wegen der gesetzlichen Aufbewahrungsfrist; alles andere wird gelöscht oder anonymisiert. Ausführen?",
                    fr="Le script est prêt. Les factures et leurs adresses restent à cause de la durée légale de conservation ; le reste est supprimé ou anonymisé. Je l'exécute ?",
                    es="El script está listo. Las facturas y sus direcciones se conservan por la obligación legal; el resto se borra o anonimiza. ¿Lo ejecuto?"),
                "\n\n", x.url("docs", "https://gdpr-info.eu/art-17-gdpr/"))
        if r.random() < 0.7:
            d.user(say(d, "go_ahead"))
            d.tool("sh", F("psql -d app -v ON_ERROR_STOP=1 -f ", path), lines(
                "BEGIN", T("DELETE ⟦n⟧", n=str(max(tables[0][1] - 1, 0))), T("DELETE ⟦n⟧", n=str(tables[2][1])),
                T("DELETE ⟦n⟧", n=str(tables[4][1])), T("DELETE ⟦n⟧", n=str(tables[5][1])), T("UPDATE ⟦n⟧", n=str(tables[3][1])),
                "UPDATE 1", "COMMIT"))
        else:
            d.user(d.L(en="Wait, the DPO wants to review it first. Leave it there.", it="Aspetta, il DPO vuole rivederlo prima. Lascialo lì.",
                       de="Warte, der DSB will es erst prüfen. Lass es liegen.", fr="Attends, le DPO veut relire d'abord. Laisse-le.",
                       es="Espera, el DPD quiere revisarlo antes. Déjalo ahí."))
    else:
        d.tool("sh", F("psql -d app -v cid=", cid, " -f ops/dsar/export.sql -o ops/dsar/out/", cid, ".json && wc -c ops/dsar/out/", cid, ".json"),
               T("⟦b⟧ ops/dsar/out/⟦c⟧.json\n", b=str(r.randint(4000, 90000)), c=cid))
        d.agent(d.L(en="Export done. It contains the full profile, addresses, orders and login history; send it through the secure upload link, not as an attachment.",
                    it="Export completato. Contiene profilo, indirizzi, ordini e storico accessi; invialo tramite link di upload sicuro, non come allegato.",
                    de="Export fertig. Er enthält Profil, Adressen, Bestellungen und Login-Historie; bitte über den sicheren Upload-Link senden, nicht als Anhang.",
                    fr="Export terminé. Il contient le profil, les adresses, les commandes et l'historique de connexion ; envoie-le via le lien sécurisé, pas en pièce jointe.",
                    es="Exportación hecha. Incluye perfil, direcciones, pedidos e historial de accesos; envíala por el enlace seguro, no como adjunto."),
                "\n\n", x.url("docs", "https://gdpr-info.eu/art-15-gdpr/"))
    d.agent(d.L(en="Draft confirmation to the requester:", it="Bozza di conferma per il richiedente:", de="Entwurf der Bestätigung an die anfragende Person:",
                fr="Projet de confirmation pour le demandeur :", es="Borrador de confirmación para el solicitante:"),
            "\n\n> ", T(_pl(d, req,
                en="Dear ⟦n⟧, we have processed your request under Art. ⟦a⟧ GDPR for customer number ⟦c⟧.",
                it="Gentile ⟦n⟧, abbiamo evaso la sua richiesta ai sensi dell'art. ⟦a⟧ GDPR per il codice cliente ⟦c⟧.",
                de="Sehr geehrte/r ⟦n⟧, wir haben Ihren Antrag nach Art. ⟦a⟧ DSGVO zur Kundennummer ⟦c⟧ bearbeitet.",
                fr="Bonjour ⟦n⟧, nous avons traité votre demande au titre de l'article ⟦a⟧ du RGPD pour le numéro client ⟦c⟧.",
                es="Estimado/a ⟦n⟧: hemos tramitado su solicitud conforme al art. ⟦a⟧ del RGPD para el número de cliente ⟦c⟧.",
                nl="Beste ⟦n⟧, wij hebben uw verzoek op grond van art. ⟦a⟧ AVG voor klantnummer ⟦c⟧ afgehandeld."),
                n=g.name(req), a=art, c=cust_no))


# ================================================================ 7. Clinic appointments


@template("clinic_appointment_bug", "colon", "ticket", "file", "trace")
def clinic_appointment_bug(d):
    g, x, r = d.g, d.x, d.rng
    desk = d.person(d.locale)
    patients = d.people(r.randint(1, 3), d.locale)
    tzname = r.choice(["Europe/Rome", "Europe/Berlin", "Europe/Paris", "Europe/Madrid", "Europe/Amsterdam"])
    for p in patients:
        p.extra["appt"] = _future(d, 2, 25)
        p.extra["time"] = r.choice(["08:30", "09:00", "10:15", "11:40", "14:00", "16:20"])
    p0 = patients[0]
    wrong = p0.extra["appt"] - dt.timedelta(days=1)
    tfmt = V.date_fmt_for(desk.locale, r)
    more = ""
    if len(patients) > 1:
        more = J(", ", [g.name(p) for p in patients[1:]])
    ticket = T(_pl(d, desk,
        en="Hi, patient ⟦n⟧ (born ⟦b⟧) is booked for ⟦a⟧ at ⟦t⟧, but the reminder SMS sent to ⟦ph⟧ said ⟦w⟧. She/he almost came on the wrong day. ⟦m⟧",
        it="Buongiorno, il/la paziente ⟦n⟧ (nato/a il ⟦b⟧) è prenotato/a per il ⟦a⟧ alle ⟦t⟧, ma l'SMS di promemoria inviato al ⟦ph⟧ indicava il ⟦w⟧. Per poco non si presentava il giorno sbagliato. ⟦m⟧",
        de="Hallo, Patient:in ⟦n⟧ (geb. ⟦b⟧) hat einen Termin am ⟦a⟧ um ⟦t⟧, aber die Erinnerungs-SMS an ⟦ph⟧ nannte den ⟦w⟧. Fast wäre sie/er am falschen Tag gekommen. ⟦m⟧",
        fr="Bonjour, le/la patient(e) ⟦n⟧ (né(e) le ⟦b⟧) a rendez-vous le ⟦a⟧ à ⟦t⟧, mais le SMS de rappel envoyé au ⟦ph⟧ indiquait le ⟦w⟧. Il/elle a failli venir le mauvais jour. ⟦m⟧",
        es="Hola, el/la paciente ⟦n⟧ (nacido/a el ⟦b⟧) tiene cita el ⟦a⟧ a las ⟦t⟧, pero el SMS de recordatorio enviado al ⟦ph⟧ decía el ⟦w⟧. Casi viene el día equivocado. ⟦m⟧"),
        n=g.name(p0), b=g.date(p0.birth, tfmt, desk), a=g.date(p0.extra["appt"], tfmt, desk), t=p0.extra["time"], ph=g.phone(p0),
        w=g.date(wrong, tfmt, desk),
        m=(T(_pl(d, desk, en="Same thing for ⟦x⟧.", it="Stessa cosa per ⟦x⟧.", de="Dasselbe bei ⟦x⟧.", fr="Pareil pour ⟦x⟧.",
                  es="Lo mismo con ⟦x⟧."), x=more) if more else ""))
    d.user(d.L(en="Ticket from the front desk, can you find the bug?", it="Ticket dalla reception, trovi il bug?",
               de="Ticket vom Empfang – findest du den Bug?", fr="Ticket de l'accueil, tu trouves le bug ?",
               es="Ticket de recepción, ¿encuentras el bug?"),
           "\n\n", ticket, "\n— ", g.name(desk), ", ", d.L(en="front desk", it="accettazione", de="Empfang", fr="accueil", es="recepción"))
    d.tool("grep", '-n "astimezone\\|combine\\|strftime" reminders/', J("\n", [
        T("reminders/sms.py:⟦n⟧:    start = datetime.combine(appt.day, time.min, tzinfo=CLINIC_TZ).astimezone(timezone.utc)", n=x.num(10)),
        T("reminders/sms.py:⟦n⟧:    return TEMPLATE.format(day=start.strftime(\"%d/%m/%Y\"), time=appt.time.strftime(\"%H:%M\"))", n=x.num(11)),
        T("reminders/schedule.py:⟦n⟧:    send_at = start - timedelta(hours=24)", n=x.num(lo=10, hi=90)),
    ]))
    d.tool("read", "reminders/sms.py", numbered(lines(
        "from datetime import datetime, time, timezone",
        "from zoneinfo import ZoneInfo",
        "",
        T('CLINIC_TZ = ZoneInfo("⟦tz⟧")', tz=tzname),
        'TEMPLATE = "Reminder: appointment on {day} at {time}. Reply CANCEL to cancel."',
        "",
        "",
        "def reminder_text(appt) -> str:",
        "    # appt.day is a date in clinic local time",
        "    start = datetime.combine(appt.day, time.min, tzinfo=CLINIC_TZ).astimezone(timezone.utc)",
        '    return TEMPLATE.format(day=start.strftime("%d/%m/%Y"), time=appt.time.strftime("%H:%M"))',
    ), width=4, sep="  "))
    aid = x.num(lo=1000, hi=99999)
    d.tool("sh", F('python manage.py shell -c "from clinic.models import Appointment as A; from reminders.sms import reminder_text; a=A.objects.get(pk=', aid,
                   '); print(a.patient.full_name, a.patient.birth_date, a.day, a.time, a.patient.mobile); print(reminder_text(a))"'),
           lines(F(g.name(p0), " ", g.birth(p0, "iso"), " ", g.date(p0.extra["appt"], "iso", p0), " ", p0.extra["time"], ":00 ", g.phone(p0, intl=True)),
                 F("Reminder: appointment on ", g.date(wrong, "eu", p0), " at ", p0.extra["time"], ". Reply CANCEL to cancel.")))
    d.agent(say(d, "explain"), "\n", d.L(
        en="Midnight local time converted to UTC falls on the previous calendar day for any zone east of UTC, and the SMS prints that UTC date.",
        it="La mezzanotte locale convertita in UTC cade nel giorno precedente per qualsiasi fuso a est di UTC, e l'SMS stampa proprio quella data UTC.",
        de="Mitternacht Ortszeit nach UTC umgerechnet liegt für jede Zone östlich von UTC am Vortag, und die SMS druckt genau dieses UTC-Datum.",
        fr="Minuit heure locale converti en UTC tombe la veille pour tout fuseau à l'est d'UTC, et le SMS affiche cette date UTC.",
        es="La medianoche local convertida a UTC cae en el día anterior para cualquier zona al este de UTC, y el SMS imprime esa fecha UTC."))
    d.tool("write", "tests/test_sms.py", lines(
        "from datetime import date, time",
        "from reminders.sms import reminder_text",
        "",
        "",
        "class FakeAppt:",
        "    day = date(2026, 3, 14)",
        "    time = time(9, 0)",
        T('    patient_name = "⟦n⟧"', n=x.ph("name", r.choice(["Test Patient", "Jane Doe", "Max Mustermann"]))),
        "",
        "",
        "def test_reminder_uses_local_day():",
        '    assert "14/03/2026" in reminder_text(FakeAppt())'))
    d.tool("sh", "pytest -q tests/test_sms.py", lines(
        "F                                                                        [100%]",
        "=================================== FAILURES ===================================",
        "________________________ test_reminder_uses_local_day _________________________",
        "",
        "    def test_reminder_uses_local_day():",
        '>       assert "14/03/2026" in reminder_text(FakeAppt())',
        "E       AssertionError: assert '14/03/2026' in 'Reminder: appointment on 13/03/2026 at 09:00. Reply CANCEL to cancel.'",
        "",
        T("tests/test_sms.py:⟦n⟧: AssertionError", n=x.num(12)),
        "=========================== short test summary info ============================",
        "FAILED tests/test_sms.py::test_reminder_uses_local_day - AssertionError",
        T("1 failed in ⟦s⟧s", s=f"{r.uniform(0.05, 0.6):.2f}")))
    d.tool("edit", "reminders/sms.py", lines(
        "-    start = datetime.combine(appt.day, time.min, tzinfo=CLINIC_TZ).astimezone(timezone.utc)",
        '-    return TEMPLATE.format(day=start.strftime("%d/%m/%Y"), time=appt.time.strftime("%H:%M"))',
        '+    return TEMPLATE.format(day=appt.day.strftime("%d/%m/%Y"), time=appt.time.strftime("%H:%M"))'))
    d.tool("sh", "pytest -q tests/", lines(T("⟦n⟧ passed in ⟦s⟧s", n=x.num(lo=20, hi=160), s=f"{r.uniform(1, 12):.2f}")))
    if r.random() < 0.6:
        d.agent(d.L(en="Checking which queued reminders were already rendered with the wrong day.",
                    it="Controllo quali promemoria in coda sono già stati generati con il giorno sbagliato.",
                    de="Ich prüfe, welche eingeplanten Erinnerungen schon mit dem falschen Tag erzeugt wurden.",
                    fr="Je vérifie quels rappels en file ont déjà été générés avec le mauvais jour.",
                    es="Compruebo qué recordatorios en cola se generaron ya con el día equivocado."))
        qrows = []
        for p in patients + d.people(r.randint(1, 6), d.locale):
            appt = p.extra.get("appt") or _future(d, 1, 20)
            qrows.append([x.num(lo=1000, hi=99999), g.name(p), g.phone(p, intl=True), g.date(appt, "iso", p),
                          x.ts("space", t=d.clock.t + dt.timedelta(hours=r.randint(1, 300)))])
        d.tool("sh", "psql -d clinic -c \"select id, patient_name, mobile, appt_day, send_at from reminder_queue where status = 'queued' order by send_at;\"",
               grid(["id", "patient_name", "mobile", "appt_day", "send_at"], qrows))
    d.agent(say(d, "done"), "\n", d.L(
        en="- the SMS now prints the clinic-local appointment day\n- regression test added with a fake patient\n- reminders already queued for the affected patients still carry the wrong date; re-send them after deploy",
        it="- l'SMS ora stampa il giorno locale dell'appuntamento\n- aggiunto test di regressione con un paziente fittizio\n- i promemoria già in coda per i pazienti coinvolti hanno ancora la data sbagliata: vanno reinviati dopo il deploy",
        de="- die SMS druckt jetzt den lokalen Termintag\n- Regressionstest mit Fake-Patient ergänzt\n- bereits eingeplante Erinnerungen der betroffenen Patient:innen haben noch das falsche Datum; nach dem Deploy neu senden",
        fr="- le SMS affiche maintenant le jour local du rendez-vous\n- test de non-régression ajouté avec un patient fictif\n- les rappels déjà planifiés pour les patients concernés gardent la mauvaise date ; les renvoyer après le déploiement",
        es="- el SMS muestra ahora el día local de la cita\n- añadido test de regresión con un paciente ficticio\n- los recordatorios ya en cola de los pacientes afectados siguen con la fecha mala; reenviarlos tras el despliegue"))


# ================================================================ 8. Secret scanner triage


_TP_RULES = [
    ("aws-access-token", "AWS Access Key", "aws_akid", ".env.production", "AWS_ACCESS_KEY_ID="),
    ("stripe-access-token", "Stripe Access Token", "stripe_live", "config/settings/prod.py", 'STRIPE_KEY = "'),
    ("github-pat", "GitHub Personal Access Token", "github_pat", "scripts/release.sh", "export GH_TOKEN="),
    ("slack-bot-token", "Slack Bot token", "slack_bot", "ops/notify.py", 'SLACK_TOKEN = "'),
    ("gitlab-pat", "GitLab Personal Access Token", "gitlab_pat", "ci/mirror.sh", "PRIVATE-TOKEN: "),
    ("sendgrid-api-token", "SendGrid API token", "sendgrid", "app/mailer.py", 'SENDGRID_KEY = "'),
    ("openai-api-key", "OpenAI API Key", "openai", "notebooks/summarise.py", 'openai.api_key = "'),
    ("npm-access-token", "npm access token", "npm", ".npmrc", "//registry.npmjs.org/:_authToken="),
    ("telegram-bot-api-token", "Telegram Bot API Token", "telegram", "bots/alerts.py", 'BOT_TOKEN = "'),
]
_FP_RULES = [
    ("aws-access-token", "AWS Access Key", "AKIAIOSFODNN7EXAMPLE", "docs/setup.md", "AWS_ACCESS_KEY_ID="),
    ("stripe-access-token", "Stripe Access Token", "sk_test_XXXXXXXXXXXXXXXXXXXXXXXX", "tests/test_payments.py", 'api_key="'),
    ("generic-api-key", "Generic API Key", "your-api-key-here", "README.md", "API_KEY="),
    ("github-pat", "GitHub Personal Access Token", "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "docs/ci.md", "GH_TOKEN="),
    ("generic-api-key", "Generic API Key", "test-key-not-real", "tests/conftest.py", 'API_KEY = "'),
    ("jwt", "JSON Web Token", "eyJhbGciOi...", "docs/auth.md", "Authorization: Bearer "),
]


@template("secret_scanner_triage", "jsonl", "shell", "file")
def secret_scanner_triage(d):
    g, x, r = d.g, d.x, d.rng
    authors = d.people(r.randint(1, 3))
    n_tp = r.choice([1, 1, 2, 3, 4, 6])
    n_fp = r.randint(1, 5)
    picks = [("tp", t) for t in r.sample(_TP_RULES, n_tp)] + [("fp", t) for t in r.sample(_FP_RULES, n_fp)]
    r.shuffle(picks)
    d.user(d.L(en="The secret scan job failed on my branch. Triage the findings: which ones are real and which are false positives?",
               it="Il job di secret scanning è fallito sul mio branch. Fai il triage: quali sono reali e quali falsi positivi?",
               de="Der Secret-Scan ist auf meinem Branch fehlgeschlagen. Bitte triagieren: was ist echt, was False Positive?",
               fr="Le scan de secrets a échoué sur ma branche. Trie les résultats : lesquels sont réels, lesquels sont des faux positifs ?",
               es="El escaneo de secretos ha fallado en mi rama. Haz el triaje: ¿cuáles son reales y cuáles falsos positivos?"))
    findings = []
    real = []
    fps = []
    commit_t = d.clock.t - dt.timedelta(days=r.randint(3, 60))
    for kind, rule in picks:
        rid, desc, val, path, prefix = rule
        author = r.choice(authors)
        sha = x.sha()
        line = r.randint(3, 220)
        if kind == "tp":
            secret = g.secret(val)
        else:
            secret = x.ph("api_key", val)
        (real if secret.label else fps).append((rid, path, line, secret, sha, prefix))
        commit_t += dt.timedelta(seconds=r.randint(600, 86400 * 2))
        col = len(prefix) + 1
        fp = F(sha, ":", path, ":", rid, ":", x.num(line))
        findings.append(lines(
            " {",
            f'  "Description": "{desc}",',
            T('  "StartLine": ⟦l⟧,', l=x.num(line)),
            T('  "EndLine": ⟦l⟧,', l=x.num(line)),
            f'  "StartColumn": {col},',
            f'  "EndColumn": {col + len(secret.text) - 1},',
            T('  "Match": "⟦m⟧",', m=esc_json(F(prefix, secret))),
            T('  "Secret": "⟦s⟧",', s=secret),
            f'  "File": "{path}",',
            '  "SymlinkFile": "",',
            T('  "Commit": "⟦c⟧",', c=sha),
            f'  "Entropy": {r.uniform(3.1, 5.9):.6f},',
            T('  "Author": "⟦a⟧",', a=g.name(author)),
            T('  "Email": "⟦e⟧",', e=g.email(author, "work")),
            T('  "Date": "⟦t⟧",', t=x.ts("iso_s", t=commit_t)),
            f'  "Message": "{r.choice(["wip", "fix config", "add release script", "temp: debug prod", "update docs", "tests for payments"])}",',
            '  "Tags": [],',
            f'  "RuleID": "{rid}",',
            T('  "Fingerprint": "⟦f⟧"', f=fp),
            " }"))
    report = F("[\n", J(",\n", [f[:-1] if f and f[-1].text == "\n" else f for f in findings]), "\n]\n")
    d.tool("sh", "gitleaks git --report-format json --report-path leaks.json --exit-code 0 . && cat leaks.json",
           F(T("⟦t⟧ INF ⟦n⟧ commits scanned.\n", t=x.ts("time", tick=(1, 4)), n=x.num(lo=40, hi=2400)),
             T("⟦t⟧ INF scanned ~⟦b⟧ bytes in ⟦s⟧s\n", t=x.ts("time", tick=(0, 3)), b=str(r.randint(10**6, 10**8)), s=f"{r.uniform(0.4, 9):.2f}"),
             T("⟦t⟧ WRN leaks found: ⟦n⟧\n", t=x.ts("time", tick=(0, 1)), n=str(len(picks))), report))
    if fps:
        rid, path, line, val, _, prefix = fps[0]
        note = ("Example (placeholder values only):" if path.endswith(".md")
                else "# test fixture: not a real key")
        tail = '"' if prefix.endswith('"') else ""
        d.tool("read", f"{path}", numbered(lines(
            note, F(prefix, x.ph("api_key", val.text), tail), ""), start=max(line - 1, 1), width=4, sep="  "))
    verdict = []
    for rid, path, line, val, _, _p in real:
        verdict.append(T("- REAL `⟦r⟧` in ⟦p⟧:⟦l⟧ (⟦m⟧) → rotate, then purge from history", r=rid, p=path, l=x.num(line),
                         m=x.ph("generic", val.text[:4] + "****")))
    for rid, path, line, val, _, _p in fps:
        verdict.append(T("- false positive `⟦r⟧` in ⟦p⟧:⟦l⟧ (documentation/test placeholder)", r=rid, p=path, l=x.num(line)))
    d.agent(d.L(en="Triage:", it="Triage:", de="Triage:", fr="Tri :", es="Triaje:"), "\n", J("\n", verdict))
    if fps:
        d.tool("write", ".gitleaksignore", lines(*[F(sha, ":", p, ":", rid, ":", x.num(length)) for rid, p, length, _, sha, _p in fps]))
    if real:
        d.agent(say(d, "secret_warning", x=real[0][1]), "\n", d.L(
            en="Rewriting history does not revoke a key, so rotation comes first.",
            it="Riscrivere la history non revoca la chiave, quindi prima va ruotata.",
            de="History umschreiben widerruft keinen Schlüssel – also zuerst rotieren.",
            fr="Réécrire l'historique ne révoque pas la clé, il faut d'abord la renouveler.",
            es="Reescribir el historial no revoca la clave, así que primero hay que rotarla."))
        d.user(say(d, "rotate_later"))
    else:
        d.agent(d.L(en="Nothing real in there: every finding is a placeholder from docs or tests. The ignore file silences them.",
                    it="Niente di reale: sono tutti segnaposto di documentazione o test. Il file di ignore li silenzia.",
                    de="Nichts Echtes dabei: alles Platzhalter aus Doku oder Tests. Die Ignore-Datei bringt sie zum Schweigen.",
                    fr="Rien de réel : uniquement des placeholders de doc ou de tests. Le fichier d'ignore les fait taire.",
                    es="Nada real: todo son marcadores de documentación o tests. El fichero de ignore los silencia."))


# ================================================================ 9. SEPA payroll batch


_BICS = {"IT": ["BCITITMM", "UNCRITMM", "BPMOIT22"], "DE": ["DEUTDEFF", "COBADEFF", "GENODEM1GLS"],
         "FR": ["BNPAFRPP", "SOGEFRPP", "CRLYFRPP"], "ES": ["CAIXESBB", "BBVAESMM", "BSCHESMM"],
         "NL": ["INGBNL2A", "RABONL2U", "ABNANL2A"], "GB": ["NWBKGB2L", "BARCGB22"], "PT": ["CGDIPTPL", "BCOMPTPL"],
         "PL": ["PKOPPLPW", "BPKOPLPW"]}
_SEPA_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-?:().,'+ ")


@template("payroll_sepa_xml", "tslog", "file", "ticket")
def payroll_sepa_xml(d):
    g, x, r = d.g, d.x, d.rng
    sepa_loc = d.locale if d.locale != "en_US" else "en_GB"
    acc = d.person(sepa_loc)
    staff = d.people(r.choice([r.randint(3, 8), r.randint(6, 16), r.randint(14, 30)]), sepa_loc)
    country = V.IBAN_COUNTRY_OF[V.COUNTRY_OF[sepa_loc]]
    month = _today(d).replace(day=1)
    period = f"{month.month:02d}/{month.year}"
    accented = [p for p in staff if any(c not in _SEPA_OK for c in p.full)]
    bug = "charset" if accented and r.random() < 0.6 else r.choice(["ampersand", "iban_spaces"])
    fname = f"out/payroll-{month.year}-{month.month:02d}.xml"
    codes = {"charset": ("CH16", "Element content formally incorrect"), "ampersand": ("FF01", "Invalid file format"),
             "iban_spaces": ("AC01", "Incorrect account number")}
    code, msg = codes[bug]
    pay_day = month + dt.timedelta(days=r.choice([26, 27, 28]))
    d.user(d.L(en="Accounting says the bank rejected this month's payroll file. Ticket text below — can you check what we generate?",
               it="La contabilità dice che la banca ha rifiutato il file stipendi di questo mese. Sotto il testo del ticket: puoi controllare cosa generiamo?",
               de="Die Buchhaltung sagt, die Bank hat die Gehaltsdatei für diesen Monat abgelehnt. Tickettext unten – kannst du prüfen, was wir erzeugen?",
               fr="La compta dit que la banque a rejeté le fichier de paie du mois. Texte du ticket ci-dessous — tu peux vérifier ce qu'on génère ?",
               es="Contabilidad dice que el banco ha rechazado el fichero de nóminas de este mes. Abajo el ticket: ¿puedes revisar lo que generamos?"),
           "\n\n", T(_pl(d, acc,
               en="The bank rejected the SEPA batch ⟦f⟧ with code ⟦c⟧ (\"⟦m⟧\"). Salaries for ⟦p⟧ must be paid by ⟦d⟧. Please fix asap. — ⟦n⟧, ⟦ph⟧",
               it="La banca ha rifiutato il flusso SEPA ⟦f⟧ con codice ⟦c⟧ (\"⟦m⟧\"). Gli stipendi di ⟦p⟧ vanno pagati entro il ⟦d⟧. Per favore sistemate al più presto. — ⟦n⟧, ⟦ph⟧",
               de="Die Bank hat den SEPA-Sammelauftrag ⟦f⟧ mit Code ⟦c⟧ (\"⟦m⟧\") abgelehnt. Die Gehälter für ⟦p⟧ müssen bis ⟦d⟧ raus. Bitte schnell beheben. — ⟦n⟧, ⟦ph⟧",
               fr="La banque a rejeté le lot SEPA ⟦f⟧ avec le code ⟦c⟧ (\"⟦m⟧\"). Les salaires de ⟦p⟧ doivent partir avant le ⟦d⟧. Merci de corriger rapidement. — ⟦n⟧, ⟦ph⟧",
               es="El banco ha rechazado la remesa SEPA ⟦f⟧ con el código ⟦c⟧ (\"⟦m⟧\"). Las nóminas de ⟦p⟧ tienen que pagarse antes del ⟦d⟧. Arreglad lo antes posible. — ⟦n⟧, ⟦ph⟧"),
               f=fname, c=x.id(code), m=msg, p=period, d=x.ts("date", t=dt.datetime.combine(pay_day, dt.time(9), tzinfo=dt.timezone.utc)),
               n=g.name(acc), ph=g.phone(acc)))
    total = 0.0
    tx_blocks = []
    bad_line = None
    bad_value = None
    line_no = 18
    emp_prefix = r.choice(["EMP", "MAT", "PN", ""])
    for i, p in enumerate(staff):
        amt = round(r.uniform(1450, 5200), 2)
        total += amt
        iban = g.iban(p=p, printed=(bug == "iban_spaces" and i == len(staff) // 2))
        emp = g.raw("account_number", f"{emp_prefix}{r.randint(1000, 99999):05d}", "generic")
        _, tax = g.natid(p)
        name = g.name(p)
        ustrd = F(_pl(d, acc, en="Salary", it="Stipendio", de="Gehalt", fr="Salaire", es="Nómina"), " ", period,
                  " & bonus" if bug == "ampersand" and i == 0 else "", " ", emp, " ", tax)
        blk = [
            "      <CdtTrfTxInf>",
            T("        <PmtId><EndToEndId>⟦e⟧</EndToEndId></PmtId>", e=x.id(f"SAL{month.year}{month.month:02d}-{i + 1:03d}")),
            f'        <Amt><InstdAmt Ccy="EUR">{amt:.2f}</InstdAmt></Amt>',
            T("        <Cdtr><Nm>⟦n⟧</Nm></Cdtr>", n=name),
            T("        <CdtrAcct><Id><IBAN>⟦i⟧</IBAN></Id></CdtrAcct>", i=iban),
            T("        <RmtInf><Ustrd>⟦u⟧</Ustrd></RmtInf>", u=ustrd),
            "      </CdtTrfTxInf>",
        ]
        if bug == "charset" and p is accented[0]:
            bad_line, bad_value = line_no + 3, name
        if bug == "iban_spaces" and i == len(staff) // 2:
            bad_line, bad_value = line_no + 4, iban
        if bug == "ampersand" and i == 0:
            bad_line = line_no + 5
        tx_blocks.extend(blk)
        line_no += len(blk)
    head = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">',
        "  <CstmrCdtTrfInitn>",
        "    <GrpHdr>",
        T("      <MsgId>⟦m⟧</MsgId>", m=x.id(f"PAYROLL-{month.year}{month.month:02d}-{r.randint(1, 9)}")),
        T("      <CreDtTm>⟦t⟧</CreDtTm>", t=x.ts("iso_s", tick=(60, 600))),
        f"      <NbOfTxs>{len(staff)}</NbOfTxs>",
        f"      <CtrlSum>{total:.2f}</CtrlSum>",
        f"      <InitgPty><Nm>{d.company}</Nm></InitgPty>",
        "    </GrpHdr>",
        "    <PmtInf>",
        T("      <PmtInfId>⟦m⟧</PmtInfId>", m=x.id(f"SAL-{month.year}-{month.month:02d}")),
        "      <PmtMtd>TRF</PmtMtd>",
        T("      <ReqdExctnDt>⟦t⟧</ReqdExctnDt>", t=x.ts("date", t=dt.datetime.combine(pay_day, dt.time(9), tzinfo=dt.timezone.utc))),
        f"      <Dbtr><Nm>{d.company}</Nm></Dbtr>",
        T("      <DbtrAcct><Id><IBAN>⟦i⟧</IBAN></Id></DbtrAcct>", i=g.iban(country, printed=False)),
        T("      <DbtrAgt><FinInstnId><BIC>⟦b⟧</BIC></FinInstnId></DbtrAgt>", b=x.id(r.choice(_BICS.get(country, ["DEUTDEFF"])))),
    ]
    tail = ["    </PmtInf>", "  </CstmrCdtTrfInitn>", "</Document>"]
    xml = lines(*head, *tx_blocks, *tail)
    d.agent(say(d, "look_first", x=fname))
    d.tool("read", fname, numbered(xml, width=4, sep="  "))
    if bug == "ampersand":
        lint = lines(T("⟦f⟧:⟦l⟧: parser error : xmlParseEntityRef: no name", f=fname, l=x.num(bad_line)),
                     "        <RmtInf><Ustrd>... & bonus ...</Ustrd></RmtInf>",
                     "                              ^",
                     T("⟦f⟧ fails to validate", f=fname))
    elif bug == "charset":
        lint = lines(T("⟦f⟧:⟦l⟧: element Nm: Schemas validity error : Element '{urn:iso:std:iso:20022:tech:xsd:pain.001.001.03}Nm': [facet 'pattern'] The value '⟦v⟧' is not accepted by the pattern '([A-Za-z0-9]|[\\+|\\?|/|\\-|:|\\(|\\)|\\.|,|'| ]){1,70}'.",
                       f=fname, l=x.num(bad_line), v=bad_value),
                     T("⟦f⟧ fails to validate", f=fname))
    else:
        lint = lines(T("⟦f⟧:⟦l⟧: element IBAN: Schemas validity error : Element '{urn:iso:std:iso:20022:tech:xsd:pain.001.001.03}IBAN': [facet 'pattern'] The value '⟦v⟧' is not accepted by the pattern '[A-Z]{2,2}[0-9]{2,2}[a-zA-Z0-9]{1,30}'.",
                       f=fname, l=x.num(bad_line), v=bad_value),
                     T("⟦f⟧ fails to validate", f=fname))
    d.tool("sh", F("xmllint --noout --schema schemas/pain.001.001.03.xsd ", fname), lint)
    fixes = {
        "ampersand": ("text is interpolated into the XML without escaping, so `&` breaks the document",
                      ["-    ustrd = f\"{label} {period} {extra} {emp_no} {tax_id}\"",
                       "+    ustrd = xml_escape(f\"{label} {period} {extra} {emp_no} {tax_id}\")"]),
        "charset": ("names are written as-is, but the bank only accepts the SEPA Latin character set",
                    ["-    nm = employee.full_name[:70]",
                     "+    nm = to_sepa_charset(employee.full_name)[:70]  # ä->ae, ł->l, é->e ..."]),
        "iban_spaces": ("one IBAN is stored in print format (groups of four) and copied verbatim",
                        ["-    iban = employee.iban",
                         "+    iban = re.sub(r\"\\s+\", \"\", employee.iban).upper()"]),
    }
    why, diff = fixes[bug]
    d.agent(say(d, "explain"), " ", d.L(en=f"in payroll/sepa.py the {why}.",
                                       it=f"in payroll/sepa.py: {why}.",
                                       de=f"in payroll/sepa.py: {why}.",
                                       fr=f"dans payroll/sepa.py : {why}.",
                                       es=f"en payroll/sepa.py: {why}."))
    d.tool("edit", "payroll/sepa.py", lines(*diff))
    d.tool("sh", F("python -m payroll.sepa --period ", f"{month.year}-{month.month:02d}", " --out ", fname,
                   " && xmllint --noout --schema schemas/pain.001.001.03.xsd ", fname),
           lines(T("wrote ⟦n⟧ transactions, control sum ⟦s⟧ EUR", n=str(len(staff)), s=f"{total:.2f}"),
                 T("⟦f⟧ validates", f=fname)))
    d.agent(say(d, "done"), "\n", T(d.L(
        en="- payroll/sepa.py fixed, file regenerated and valid against the pain.001.001.03 schema\n- reply for accounting: \"⟦r⟧\"",
        it="- corretto payroll/sepa.py, file rigenerato e valido rispetto allo schema pain.001.001.03\n- risposta per la contabilità: \"⟦r⟧\"",
        de="- payroll/sepa.py korrigiert, Datei neu erzeugt und gegen pain.001.001.03 valide\n- Antwort an die Buchhaltung: \"⟦r⟧\"",
        fr="- payroll/sepa.py corrigé, fichier régénéré et valide selon le schéma pain.001.001.03\n- réponse pour la compta : \"⟦r⟧\"",
        es="- corregido payroll/sepa.py, fichero regenerado y válido según el esquema pain.001.001.03\n- respuesta para contabilidad: \"⟦r⟧\""),
        r=T(_pl(d, acc, en="Hi ⟦n⟧, the corrected file is ready, you can upload it again.",
                it="Ciao ⟦n⟧, il file corretto è pronto, puoi ricaricarlo.",
                de="Hallo ⟦n⟧, die korrigierte Datei liegt bereit, du kannst sie erneut hochladen.",
                fr="Bonjour ⟦n⟧, le fichier corrigé est prêt, tu peux le renvoyer.",
                es="Hola ⟦n⟧, el fichero corregido está listo, puedes volver a subirlo."), n=g.name(acc, "given"))))


# ================================================================ 10. pandas notebook


@template("pandas_notebook_cleaning", "box", "file", "trace")
def pandas_notebook_cleaning(d):
    g, x, r = d.g, d.x, d.rng
    people = d.people(r.randint(5, 10))
    twin_src = people[0]
    twin = d.person(twin_src.locale)
    twin.given, twin.family = twin_src.given, twin_src.family
    if twin_src.placeholder:
        twin.placeholder = True
    people.insert(r.randint(2, len(people)), twin)
    nb = "notebooks/customers_clean.ipynb"
    csv_name = ("data/fixtures/customers_sample.csv" if d.clean
                else f"data/customers_{_today(d).year}-{_today(d).month:02d}.csv")
    d.user(T(d.L(
        en="In ⟦nb⟧ the dedup step drops way too many rows, and I keep getting a SettingWithCopyWarning. Can you have a look?",
        it="In ⟦nb⟧ lo step di deduplica elimina troppe righe e continuo a vedere un SettingWithCopyWarning. Puoi darci un'occhiata?",
        de="In ⟦nb⟧ wirft der Dedup-Schritt viel zu viele Zeilen raus, und ich bekomme ständig eine SettingWithCopyWarning. Schaust du mal?",
        fr="Dans ⟦nb⟧ l'étape de dédoublonnage supprime beaucoup trop de lignes et j'ai toujours un SettingWithCopyWarning. Tu peux regarder ?",
        es="En ⟦nb⟧ el paso de deduplicado elimina demasiadas filas y me sale todo el rato un SettingWithCopyWarning. ¿Le echas un vistazo?"),
        nb=nb))
    d.tool("sh", F("jupyter nbconvert --to script ", nb, " --stdout 2>/dev/null"), lines(
        "#!/usr/bin/env python", "# coding: utf-8", "",
        "# In[1]:", "", "import pandas as pd", f'df = pd.read_csv("../{csv_name}", dtype={{"national_id": str, "phone": str}})',
        "df.head(8)", "", "",
        "# In[2]:", "", 'active = df[df["status"] == "active"]', 'active["email"] = active["email"].str.strip().str.lower()', "", "",
        "# In[3]:", "", 'dedup = active.drop_duplicates(subset=["full_name"])', "print(len(df), len(active), len(dedup))"))
    rows = [["", "customer_id", "full_name", "email", "phone", "city", "birth_date", "national_id", "status"]]
    for i, p in enumerate(people[:8]):
        _, nid = g.natid(p)
        rows.append([str(i), g.cust(), g.name(p), g.email(p, "personal"), g.phone(p, intl=True), g.addr(p, "city"),
                     g.birth(p, "iso"), nid, r.choice(["active", "active", "active", "churned"])])
    d.tool("sh", F("python -c \"import pandas as pd; print(pd.read_csv('", csv_name, "', dtype=str).head(8).to_string())\""),
           table(rows, gap=2))
    if r.random() < 0.5:
        info = [["#", "Column", "Non-Null Count", "Dtype"], ["---", "------", "--------------", "-----"]]
        n_rows = r.randint(8000, 60000)
        for i, col in enumerate(["customer_id", "full_name", "email", "phone", "city", "birth_date", "national_id", "status"]):
            info.append([f" {i}", col, f"{n_rows - r.randint(0, 40)} non-null", "object"])
        d.tool("sh", F("python -c \"import pandas as pd; pd.read_csv('", csv_name, "', dtype=str).info()\""),
               F("<class 'pandas.core.frame.DataFrame'>\n", f"RangeIndex: {n_rows} entries, 0 to {n_rows - 1}\n",
                 "Data columns (total 8 columns):\n", table(info, gap=2), "dtypes: object(8)\n",
                 f"memory usage: {n_rows * 64 / 1024 / 1024:.1f}+ MB\n"))
    n_total = r.randint(8000, 60000)
    n_active = int(n_total * r.uniform(0.6, 0.9))
    n_dedup = int(n_active * r.uniform(0.7, 0.85))
    d.tool("sh", F("jupyter nbconvert --execute --to notebook --inplace ", nb),
           lines(T("[NbConvertApp] Converting notebook ⟦nb⟧ to notebook", nb=nb),
                 T("⟦c⟧/notebooks/customers_clean.py:⟦l⟧: SettingWithCopyWarning:", c=d.cwd(), l=x.num(15)),
                 "A value is trying to be set on a copy of a slice from a DataFrame.",
                 "Try using .loc[row_indexer,col_indexer] = value instead",
                 "",
                 T("See the caveats in the documentation: ⟦u⟧", u=x.url(text="https://pandas.pydata.org/pandas-docs/stable/user_guide/indexing.html#returning-a-view-versus-a-copy")),
                 '  active["email"] = active["email"].str.strip().str.lower()',
                 f"{n_total} {n_active} {n_dedup}",
                 T("[NbConvertApp] Writing ⟦b⟧ bytes to ⟦nb⟧", b=str(r.randint(20000, 400000)), nb=nb)))
    d.agent(d.L(en="Two separate problems. Let me show the rows the dedup treats as duplicates.",
                it="Sono due problemi distinti. Ti mostro le righe che la deduplica considera duplicati.",
                de="Zwei getrennte Probleme. Ich zeige die Zeilen, die die Deduplizierung als Duplikate behandelt.",
                fr="Deux problèmes distincts. Je montre les lignes que le dédoublonnage considère comme doublons.",
                es="Son dos problemas distintos. Te enseño las filas que el deduplicado trata como duplicadas."))
    dup_rows = [["", "customer_id", "full_name", "email", "birth_date", "city"]]
    for p in (twin_src, twin):
        dup_rows.append([str(r.randint(10, 9000)), g.cust(), g.name(p), g.email(p, "personal"), g.birth(p, "iso"), g.addr(p, "city")])
    d.tool("sh", "python -c \"import pandas as pd; df = pd.read_csv('...'); print(df[df.duplicated('full_name', keep=False)].head(2).to_string())\"",
           table(dup_rows, gap=2))
    if not d.clean and r.random() < 0.5:
        real_dup = people[-1]
        e = g.email(real_dup, "personal")
        dup2 = [["", "customer_id", "full_name", "email", "birth_date"]]
        dup2.append([str(r.randint(10, 9000)), g.cust(), g.name(real_dup), e, g.birth(real_dup, "iso")])
        dup2.append([str(r.randint(10, 9000)), g.cust(), g.name(real_dup),
                     g.raw("private_email", e.text.upper() if e.label else e.text, "email"), g.birth(real_dup, "iso")])
        d.tool("sh", "python -c \"...; print(df[df.duplicated(['full_name', 'birth_date'], keep=False)].head(2).to_string())\"",
               table(dup2, gap=2))
    d.agent(say(d, "explain"), "\n", d.L(
        en="1. `drop_duplicates(subset=[\"full_name\"])` merges different people who share a name (different e-mail and birth date above).\n2. `active` is a slice of `df`, so the assignment triggers SettingWithCopyWarning; take an explicit `.copy()`.",
        it="1. `drop_duplicates(subset=[\"full_name\"])` fonde persone diverse con lo stesso nome (e-mail e data di nascita diverse qui sopra).\n2. `active` è una slice di `df`, quindi l'assegnazione genera il SettingWithCopyWarning; serve un `.copy()` esplicito.",
        de="1. `drop_duplicates(subset=[\"full_name\"])` fasst verschiedene Personen mit gleichem Namen zusammen (oben: andere E-Mail, anderes Geburtsdatum).\n2. `active` ist ein Slice von `df`, daher die SettingWithCopyWarning; ein explizites `.copy()` behebt das.",
        fr="1. `drop_duplicates(subset=[\"full_name\"])` fusionne des personnes différentes qui portent le même nom (e-mail et date de naissance différents ci-dessus).\n2. `active` est une tranche de `df`, d'où le SettingWithCopyWarning ; il faut un `.copy()` explicite.",
        es="1. `drop_duplicates(subset=[\"full_name\"])` junta personas distintas con el mismo nombre (correo y fecha de nacimiento distintos arriba).\n2. `active` es un slice de `df`, por eso salta el SettingWithCopyWarning; hace falta un `.copy()` explícito."))
    d.tool("edit", nb, lines(
        "-active = df[df[\"status\"] == \"active\"]",
        "+active = df[df[\"status\"] == \"active\"].copy()",
        " active[\"email\"] = active[\"email\"].str.strip().str.lower()",
        "-dedup = active.drop_duplicates(subset=[\"full_name\"])",
        "+dedup = active.drop_duplicates(subset=[\"email\", \"birth_date\"])"))
    n_dedup2 = n_active - r.randint(3, max(4, n_active // 200))
    d.tool("sh", F("jupyter nbconvert --execute --to notebook --inplace ", nb, " && jupyter nbconvert --to script ", nb, " --stdout | tail -1"),
           lines(T("[NbConvertApp] Converting notebook ⟦nb⟧ to notebook", nb=nb), f"{n_total} {n_active} {n_dedup2}"))
    d.agent(say(d, "done"), "\n", T(d.L(
        en="- no more warning\n- dedup now keys on normalised e-mail + birth date: ⟦a⟧ rows kept instead of ⟦b⟧",
        it="- niente più warning\n- la deduplica ora usa e-mail normalizzata + data di nascita: ⟦a⟧ righe invece di ⟦b⟧",
        de="- keine Warnung mehr\n- Dedup nutzt jetzt normalisierte E-Mail + Geburtsdatum: ⟦a⟧ Zeilen statt ⟦b⟧",
        fr="- plus d'avertissement\n- le dédoublonnage se base sur e-mail normalisé + date de naissance : ⟦a⟧ lignes au lieu de ⟦b⟧",
        es="- sin warning\n- el deduplicado usa ahora correo normalizado + fecha de nacimiento: ⟦a⟧ filas en lugar de ⟦b⟧"),
        a=str(n_dedup2), b=str(n_dedup)))
    if r.random() < 0.5:
        d.agent(say(d, "pii_warning"))


# ================================================================ 11. Insurance claim parser


_CLAIM_LABELS = {
    "en": ("MOTOR CLAIM NOTIFICATION", ["Policyholder", "Date of birth", "Address", "Phone", "Driving licence no.",
                                        "Registration", "VIN", "Date of accident", "Location (GPS)", "Description"], ":"),
    "it": ("DENUNCIA DI SINISTRO AUTO", ["Contraente", "Data di nascita", "Indirizzo", "Telefono", "N. patente",
                                         "Targa", "Telaio (VIN)", "Data del sinistro", "Luogo (GPS)", "Dinamica"], ":"),
    "de": ("KFZ-SCHADENMELDUNG", ["Versicherungsnehmer", "Geburtsdatum", "Anschrift", "Telefon", "Führerscheinnummer",
                                  "Kennzeichen", "FIN", "Schadentag", "Schadenort (GPS)", "Hergang"], ":"),
    "fr": ("DÉCLARATION DE SINISTRE AUTOMOBILE", ["Assuré", "Date de naissance", "Adresse", "Téléphone", "N° de permis",
                                                  "Immatriculation", "VIN", "Date du sinistre", "Lieu (GPS)", "Circonstances"], " :"),
    "es": ("PARTE DE SINIESTRO DE AUTOMÓVIL", ["Tomador", "Fecha de nacimiento", "Dirección", "Teléfono", "N.º de permiso",
                                               "Matrícula", "Bastidor (VIN)", "Fecha del siniestro", "Ubicación (GPS)", "Descripción"], ":"),
}


@template("insurance_claim_parser", "hai", "file", "ticket")
def insurance_claim_parser(d):
    g, x, r = d.g, d.x, d.rng
    ph = d.person()
    lang = d.lang_of(ph) if d.lang_of(ph) in _CLAIM_LABELS else "en"
    title, labels, colon = _CLAIM_LABELS[lang]
    other = d.person(ph.locale)
    acc_day = _today(d) - dt.timedelta(days=r.randint(1, 20))
    fmt = r.choice([f for f in ("eu", "de", "us", "long") if f != "iso"])
    key = x.id(f"CLM-{r.randint(10000, 99999)}")
    vin = g.vin()
    plate = g.plate(ph)
    dl = g.dl(ph)
    geo = g.geo(ph)
    desc = T(d.Lp(lang,
        en="While waiting at a red light I was hit from behind by a van, registration ⟦p⟧, driven by ⟦o⟧. Rear bumper and tailgate damaged.",
        it="Mentre ero fermo al semaforo rosso sono stato tamponato da un furgone targato ⟦p⟧, guidato da ⟦o⟧. Danni al paraurti posteriore e al portellone.",
        de="Beim Warten an einer roten Ampel fuhr mir ein Transporter mit dem Kennzeichen ⟦p⟧, Fahrer ⟦o⟧, hinten auf. Stoßstange und Heckklappe beschädigt.",
        fr="Arrêté à un feu rouge, j'ai été percuté par l'arrière par une camionnette immatriculée ⟦p⟧, conduite par ⟦o⟧. Pare-chocs arrière et hayon endommagés.",
        es="Estando parado en un semáforo en rojo, una furgoneta con matrícula ⟦p⟧, conducida por ⟦o⟧, me golpeó por detrás. Daños en el parachoques trasero y el portón."),
        p=g.plate(other), o=g.name(other))
    values = [g.name(ph), g.birth(ph, fmt), g.addr(ph), g.phone(ph), dl, plate, vin, g.date(acc_day, fmt, ph), geo, desc]
    width = max(len(lb) for lb in labels) + len(colon) + 1
    form = F(title, "\n", "=" * len(title), "\n",
             J("\n", [F((lb + colon).ljust(width), " ", v) for lb, v in zip(labels, values)]), "\n")
    d.user(T(d.L(en="The claim intake parser fails on this claim (⟦k⟧). This is the text the customer submitted:",
                 it="Il parser delle denunce fallisce su questo sinistro (⟦k⟧). Questo è il testo inviato dal cliente:",
                 de="Der Schaden-Parser scheitert an dieser Meldung (⟦k⟧). Das hier hat der Kunde eingereicht:",
                 fr="Le parseur de déclarations échoue sur ce sinistre (⟦k⟧). Voici le texte envoyé par le client :",
                 es="El parser de partes falla con este siniestro (⟦k⟧). Este es el texto que envió el cliente:"), k=key),
           "\n\n", form)
    if r.random() < 0.5:
        img = f"IMG_{r.randint(1000, 9999)}.jpg"
        la, lo = V.city_latlon(ph.locale, ph.city_rec)
        la += r.uniform(-0.05, 0.05)
        lo += r.uniform(-0.05, 0.05)

        def dms(v: float, pos: str, neg: str) -> str:
            a = abs(v)
            deg = int(a)
            mins = int((a - deg) * 60)
            secs = (a - deg - mins / 60) * 3600
            return f"{deg} deg {mins}' {secs:.2f}\" {pos if v >= 0 else neg}"

        shot = dt.datetime.combine(acc_day, dt.time(r.randint(6, 21), r.randint(0, 59), r.randint(0, 59)))
        d.agent(d.L(en="Checking the photo attached to the claim as well.", it="Controllo anche la foto allegata alla denuncia.",
                    de="Ich prüfe auch das angehängte Foto.", fr="Je regarde aussi la photo jointe.", es="Miro también la foto adjunta."))
        d.tool("sh", F("exiftool -Model -DateTimeOriginal -GPSPosition attachments/", key, "/", img), lines(
            f"Camera Model Name               : {r.choice(['iPhone 14', 'SM-S911B', 'Pixel 8', 'iPhone 15 Pro', 'M2101K6G'])}",
            F("Date/Time Original              : ", Seg(shot.strftime("%Y:%m:%d %H:%M:%S"), cls="machine_timestamp")),
            F("GPS Position                    : ", g.raw("private_geolocation", f"{dms(la, 'N', 'S')}, {dms(lo, 'E', 'W')}", "geo"))))
    d.tool("read", "claims/parser.py", lines(
        "import re",
        "",
        "FIELDS = {",
        '    "policyholder": r"^Policyholder:\\s*(.+)$",',
        '    "licence": r"^Driving licence no\\.:\\s*(\\S+)$",',
        '    "plate": r"^Registration:\\s*([A-Z0-9 ]+)$",',
        '    "vin": r"^VIN:\\s*([A-HJ-NPR-Z0-9]{17})$",',
        '    "accident_date": r"^Date of accident:\\s*(\\d{4}-\\d{2}-\\d{2})$",',
        '    "gps": r"^Location \\(GPS\\):\\s*(-?\\d+\\.\\d+),\\s*(-?\\d+\\.\\d+)$",',
        "}",
        "",
        "",
        "def parse(text: str) -> dict:",
        "    out = {}",
        "    for key, rx in FIELDS.items():",
        "        m = re.search(rx, text, re.M)",
        "        if not m:",
        '            raise ValueError(f"could not parse field {key!r}")',
        "        out[key] = m.groups() if key == \"gps\" else m.group(1)",
        "    return out"))
    failing = "policyholder" if lang != "en" else "accident_date"
    sample = F("samples/", key, ".txt")
    d.tool("sh", F("python -m claims.parser ", sample), lines(
        "Traceback (most recent call last):",
        '  File "<frozen runpy>", line 198, in _run_module_as_main',
        T('  File "⟦c⟧/claims/parser.py", line ⟦n⟧, in <module>', c=d.cwd(), n=x.num(lo=30, hi=40)),
        "    print(json.dumps(parse(open(sys.argv[1]).read()), indent=2))",
        T('  File "⟦c⟧/claims/parser.py", line ⟦n⟧, in parse', c=d.cwd(), n=x.num(18)),
        '    raise ValueError(f"could not parse field {key!r}")',
        f"ValueError: could not parse field '{failing}'"))
    d.agent(d.L(
        en="The regexes only know the English labels and an ISO date. This claim uses " + ("localized labels" if lang != "en" else "a non-ISO date") + ". I'll map labels per language, accept the usual date formats and allow dashes in plates.",
        it="Le regex conoscono solo le etichette inglesi e la data ISO. Questa denuncia usa " + ("etichette localizzate" if lang != "en" else "una data non ISO") + ". Mappo le etichette per lingua, accetto i formati di data comuni e i trattini nelle targhe.",
        de="Die Regexe kennen nur die englischen Labels und ISO-Daten. Diese Meldung nutzt " + ("lokalisierte Labels" if lang != "en" else "ein Nicht-ISO-Datum") + ". Ich mappe die Labels pro Sprache, akzeptiere übliche Datumsformate und Bindestriche in Kennzeichen.",
        fr="Les regex ne connaissent que les libellés anglais et la date ISO. Cette déclaration utilise " + ("des libellés localisés" if lang != "en" else "une date non ISO") + ". Je mappe les libellés par langue, j'accepte les formats de date usuels et les tirets dans les plaques.",
        es="Las regex solo conocen las etiquetas en inglés y la fecha ISO. Este parte usa " + ("etiquetas localizadas" if lang != "en" else "una fecha no ISO") + ". Mapeo las etiquetas por idioma, acepto los formatos de fecha habituales y guiones en las matrículas."))
    d.tool("edit", "claims/parser.py", lines(
        "+LABELS = {",
        '+    "policyholder": ["Policyholder", "Contraente", "Versicherungsnehmer", "Assuré", "Tomador"],',
        '+    "licence": ["Driving licence no.", "N. patente", "Führerscheinnummer", "N° de permis", "N.º de permiso"],',
        '+    "plate": ["Registration", "Targa", "Kennzeichen", "Immatriculation", "Matrícula"],',
        "+    ...",
        "+}",
        '+DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y", "%B %d, %Y"]',
        '-    "plate": r"^Registration:\\s*([A-Z0-9 ]+)$",',
        '+    "plate": r"([A-Z0-9][A-Z0-9 \\-]{3,10})$",'))
    lat, lon = g.geo_parts(ph)
    out = lines(
        "{",
        T('  "claim": "⟦k⟧",', k=key),
        T('  "policyholder": "⟦n⟧",', n=g.name(ph)),
        T('  "licence": "⟦l⟧",', l=dl),
        T('  "plate": "⟦p⟧",', p=plate),
        T('  "vin": "⟦v⟧",', v=vin),
        T('  "accident_date": "⟦a⟧",', a=g.date(acc_day, "iso", ph)),
        T('  "gps": [⟦la⟧, ⟦lo⟧],', la=lat, lo=lon),
        f'  "language": "{lang}"',
        "}")
    d.tool("sh", F("python -m claims.parser ", sample), out)
    d.tool("sh", "pytest -q tests/test_parser.py", lines(T("⟦n⟧ passed in ⟦s⟧s", n=x.num(lo=6, hi=40), s=f"{r.uniform(0.1, 1.5):.2f}")))
    d.agent(say(d, "done"), "\n", d.L(
        en="- labels mapped for en/it/de/fr/es\n- dates normalised to ISO, plates may contain dashes\n- I did not add this customer's claim text to the test fixtures",
        it="- etichette mappate per en/it/de/fr/es\n- date normalizzate in ISO, targhe con trattini ammesse\n- non ho aggiunto il testo di questo cliente alle fixture di test",
        de="- Labels für en/it/de/fr/es gemappt\n- Datum nach ISO normalisiert, Kennzeichen dürfen Bindestriche enthalten\n- den Text dieses Kunden habe ich nicht in die Test-Fixtures übernommen",
        fr="- libellés mappés pour en/it/de/fr/es\n- dates normalisées en ISO, plaques avec tirets acceptées\n- je n'ai pas ajouté le texte de ce client aux fixtures de test",
        es="- etiquetas mapeadas para en/it/de/fr/es\n- fechas normalizadas a ISO, matrículas con guiones admitidas\n- no he añadido el texto de este cliente a los fixtures de test"))


# ================================================================ 12. CSV customer import


_CSV_HEADERS = {
    "it_IT": "nome;cognome;email;telefono;indirizzo;cap;citta;iban",
    "de_DE": "Vorname;Nachname;E-Mail;Telefon;Straße;PLZ;Ort;IBAN",
    "fr_FR": "prenom;nom;courriel;telephone;adresse;code_postal;ville;iban",
    "es_ES": "nombre;apellidos;email;telefono;direccion;cp;ciudad;iban",
    "pt_PT": "nome;apelido;email;telefone;morada;codigo_postal;localidade;iban",
}
_COUNTRY_WORD = {
    "it_IT": {"en": "Italy", "it": "Italia", "de": "Italien", "fr": "Italie", "es": "Italia"},
    "de_DE": {"en": "Germany", "it": "Germania", "de": "Deutschland", "fr": "Allemagne", "es": "Alemania"},
    "fr_FR": {"en": "France", "it": "Francia", "de": "Frankreich", "fr": "France", "es": "Francia"},
    "es_ES": {"en": "Spain", "it": "Spagna", "de": "Spanien", "fr": "Espagne", "es": "España"},
    "pt_PT": {"en": "Portugal", "it": "Portogallo", "de": "Portugal", "fr": "Portugal", "es": "Portugal"},
}


@template("csv_customer_import", "irc", "file", "trace")
def csv_customer_import(d):
    g, x, r = d.g, d.x, d.rng
    loc = r.choice(sorted(_CSV_HEADERS))
    rows_p = d.people(r.randint(4, 14), loc)
    path = "data/partner_export.csv"
    d.user(T(d.L(en="scripts/import_customers.py crashes on the export from our new partner in ⟦c⟧, can you fix it?",
                 it="scripts/import_customers.py va in crash sull'export del nuovo partner in ⟦c⟧, puoi sistemarlo?",
                 de="scripts/import_customers.py stürzt beim Export unseres neuen Partners aus ⟦c⟧ ab, kannst du das fixen?",
                 fr="scripts/import_customers.py plante sur l'export de notre nouveau partenaire (⟦c⟧), tu peux corriger ?",
                 es="scripts/import_customers.py peta con el export del nuevo partner de ⟦c⟧, ¿lo arreglas?"),
             c=d.L(**_COUNTRY_WORD[loc])))
    d.tool("sh", F("python scripts/import_customers.py ", path), lines(
        "Traceback (most recent call last):",
        T('  File "⟦c⟧/scripts/import_customers.py", line ⟦n⟧, in <module>', c=d.cwd(), n=x.num(lo=60, hi=90)),
        "    main(sys.argv[1])",
        T('  File "⟦c⟧/scripts/import_customers.py", line ⟦n⟧, in main', c=d.cwd(), n=x.num(lo=20, hi=40)),
        "    for row in csv.DictReader(fh):",
        '  File "/usr/lib/python3.12/csv.py", line 115, in __next__',
        "    self.fieldnames",
        '  File "<frozen codecs>", line 322, in decode',
        T("UnicodeDecodeError: 'utf-8' codec can't decode byte 0x⟦b⟧ in position ⟦p⟧: invalid continuation byte",
          b=r.choice(["e9", "e8", "f6", "fc", "e0", "e7", "f1", "e3"]), p=str(r.randint(30, 9000)))))
    d.tool("sh", F("file ", path, " && wc -l ", path), lines(
        F(path, ": ISO-8859 text, with CRLF line terminators"), T("⟦n⟧ ", n=str(r.randint(300, 4000))) + F(path)))
    body = [F(_CSV_HEADERS[loc])]
    for p in rows_p:
        body.append(F(g.name(p, "given"), ";", g.name(p, "family"), ";", g.email(p, "personal"), ";", g.phone(p), ";",
                      g.addr(p, "street"), ";", g.addr(p, "postcode"), ";", g.addr(p, "city"), ";", g.iban(p=p, printed=False)))
    d.tool("sh", F("iconv -f latin1 -t utf-8 ", path, " | head -n ", str(len(body))), lines(*body))
    d.tool("read", "scripts/import_customers.py", numbered(lines(
        "import csv, sys",
        "from app.customers import upsert_customer",
        "",
        'COLUMNS = ["first_name", "last_name", "email", "phone", "street", "zip", "city", "iban"]',
        "",
        "",
        "def main(path):",
        "    with open(path) as fh:",
        "        for row in csv.DictReader(fh):",
        "            upsert_customer({k: row[k] for k in COLUMNS})"), start=18, width=3, sep=" "))
    d.agent(say(d, "explain"), " ", d.L(
        en="the file is Latin-1 with `;` separators and localized headers, while the script assumes UTF-8, commas and English column names.",
        it="il file è Latin-1 con separatore `;` e intestazioni localizzate, mentre lo script si aspetta UTF-8, virgole e colonne in inglese.",
        de="die Datei ist Latin-1 mit `;` als Trenner und lokalisierten Spaltennamen; das Skript erwartet UTF-8, Kommas und englische Spalten.",
        fr="le fichier est en Latin-1 avec des `;` et des en-têtes localisés, alors que le script attend de l'UTF-8, des virgules et des colonnes en anglais.",
        es="el fichero es Latin-1 con `;` y cabeceras localizadas, y el script espera UTF-8, comas y columnas en inglés."))
    d.tool("edit", "scripts/import_customers.py", lines(
        "+ALIASES = {",
        '+    "first_name": {"nome", "vorname", "prenom", "nombre"},',
        '+    "last_name": {"cognome", "nachname", "nom", "apellidos", "apelido"},',
        '+    "zip": {"cap", "plz", "code_postal", "cp", "codigo_postal"},',
        "+    ...",
        "+}",
        "-    with open(path) as fh:",
        "-        for row in csv.DictReader(fh):",
        '+    raw = open(path, "rb").read()',
        "+    text = decode_best_effort(raw)  # utf-8, then cp1252/latin-1",
        '+    dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,")',
        "+    for row in csv.DictReader(io.StringIO(text), dialect=dialect):",
        "+        row = normalise_headers(row, ALIASES)"))
    total = r.randint(300, 4000)
    skipped = d.people(r.randint(1, 3), loc)
    skip_lines = [T("  line ⟦l⟧: missing email (⟦n⟧)", l=x.num(lo=2, hi=total), n=g.name(p)) for p in skipped]
    d.tool("sh", F("python scripts/import_customers.py ", path), lines(
        T("imported ⟦n⟧ customers, skipped ⟦s⟧", n=str(total - len(skipped) - 1), s=str(len(skipped))), *skip_lines))
    d.agent(say(d, "done"), "\n", d.L(
        en="- encoding detected instead of assumed, delimiter sniffed, localized headers mapped\n- the skipped rows have no e-mail; the partner should resend them",
        it="- encoding rilevato invece che presunto, separatore individuato, intestazioni localizzate mappate\n- le righe saltate non hanno e-mail; il partner dovrebbe reinviarle",
        de="- Encoding wird erkannt statt angenommen, Trenner per Sniffer, lokalisierte Spalten gemappt\n- die übersprungenen Zeilen haben keine E-Mail; der Partner sollte sie nachliefern",
        fr="- encodage détecté au lieu d'être supposé, séparateur détecté, en-têtes localisés mappés\n- les lignes ignorées n'ont pas d'e-mail ; le partenaire doit les renvoyer",
        es="- codificación detectada en lugar de asumida, separador detectado, cabeceras localizadas mapeadas\n- las filas omitidas no tienen correo; el partner debería reenviarlas"))
    if r.random() < 0.6:
        d.user(say(d, "thanks"))
