# SPDX-License-Identifier: Apache-2.0
"""Templates centred on git output: log, blame, diff, bisect, shortlog,
rebase conflicts, remotes, signatures, pull-request reviews, history
rewriting and mailing-list patches."""

from __future__ import annotations

from .. import values as V
from ..core import F, J, T, Seg, esc_json, grid, lines, numbered, table
from ..phrases import say
from . import template

# ---------------------------------------------------------------- shared helpers (private to this module)

_BOTS = [
    ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
    ("renovate[bot]", "29139614+renovate[bot]@users.noreply.github.com"),
    ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com"),
    ("pre-commit-ci[bot]", "66853113+pre-commit-ci[bot]@users.noreply.github.com"),
]

_SCOPES = ["api", "billing", "export", "auth", "ui", "worker", "db", "notifications", "checkout", "customers",
           "i18n", "search", "reports"]
_FEATS = ["add CSV export for invoices", "support multiple billing addresses", "add retry with backoff to webhook sender",
          "expose readiness probe", "add dark mode toggle to settings", "allow filtering orders by status",
          "add audit trail for role changes", "paginate customer search results",
          "add idempotency keys to payment intents", "send weekly digest email", "add Italian and German translations",
          "cache exchange rates for 10 minutes", "add bulk archive action", "support SSO login via OIDC"]
_FIXES = ["handle empty cart in checkout", "return 404 for unknown order id", "round discounts per line item",
          "avoid double charge on retried webhook", "fix timezone offset in invoice dates",
          "escape commas in CSV export", "close DB cursor on early return", "prevent N+1 query in order list",
          "trim whitespace in postcode validation", "fix race in session refresh",
          "use UTC when scheduling reminders", "stop logging full request bodies", "keep sort order after refresh",
          "do not retry on 4xx responses"]
_OTHERS = [("refactor", "split pricing module"), ("docs", "document local setup with docker compose"),
           ("test", "add regression test for refund flow"), ("ci", "cache pip downloads"),
           ("perf", "batch inserts in nightly import"), ("chore", "remove unused feature flags"),
           ("build", "pin node to 20.x"), ("style", "apply formatter to legacy modules"),
           ("refactor", "extract mailer into its own service"), ("test", "stabilise flaky checkout e2e test")]
_DEPS = ["axios", "requests", "lodash", "django", "express", "pydantic", "jackson-databind", "golang.org/x/net",
         "actions/checkout", "eslint", "urllib3", "sqlalchemy", "spring-boot-starter-web", "serde"]


class _Dev:
    """A committer identity: name/email/username/handle segments reused at every mention."""

    def __init__(self, p, name, email, user, handle, bot: bool):
        self.p, self.name, self.email, self.user, self.handle, self.bot = p, name, email, user, handle, bot


def _dev(d, p=None, kind: str | None = None) -> _Dev:
    p = p or d.person()
    kind = kind or ("work" if d.rng.random() < 0.75 else "personal")
    return _Dev(p, d.g.name(p), d.g.email(p, kind), d.g.user(p), d.g.handle(p), False)


def _bot(d, which: tuple | None = None) -> _Dev:
    name, mail = which or d.rng.choice(_BOTS)
    return _Dev(None, d.x.ent(name), d.x.ent(mail), d.x.ent(name), d.x.ent("@" + name.replace("[bot]", "")), True)


def _team(d, n: int) -> list:
    if d.clean:
        return [_dev(d) for _ in range(min(n, 2))]
    return [_dev(d) for _ in range(n)]


def _sha(d) -> str:
    return V.rand_str(d.rng, V.HEX, 40)


def _pick_unused(d, pool: list, key: str):
    used = d.state.setdefault(key, [])
    fresh = [p for p in pool if p not in used] or pool
    choice = d.rng.choice(fresh)
    used.append(choice)
    return choice


def _subject_parts(d, kind: str | None = None) -> tuple[str, str, str, list]:
    """(type, scope, text, pr-suffix fragment) of a conventional-commit subject without personal data."""
    r = d.rng
    kind = kind or r.choice(["feat", "feat", "fix", "fix", "fix", "other"])
    scope = r.choice(_SCOPES)
    if kind == "feat":
        text = _pick_unused(d, _FEATS, "_feats")
    elif kind == "fix":
        text = _pick_unused(d, _FIXES, "_fixes")
    else:
        kind, text = _pick_unused(d, _OTHERS, "_others")
    pr = F(" (#", d.x.num(lo=120, hi=2400), ")") if r.random() < 0.45 else []
    return kind, scope, text, pr


def _subject(d, kind: str | None = None) -> tuple[str, list]:
    """(type, fragment) for a conventional-commit subject without personal data."""
    kind, scope, text, pr = _subject_parts(d, kind)
    return kind, F(f"{kind}({scope}): {text}", pr)


def _bump(d) -> tuple:
    r = d.rng
    a = [r.randint(0, 6), r.randint(0, 30), r.randint(0, 20)]
    b = list(a)
    which = r.choice([1, 2, 2, 2])
    b[which] += r.randint(1, 4)
    if which == 1:
        b[2] = 0
    return d.x.ver(".".join(map(str, a))), d.x.ver(".".join(map(str, b)))


def _bot_subject(d) -> list:
    a, b = _bump(d)
    return T("chore(deps): bump ⟦lib⟧ from ⟦a⟧ to ⟦b⟧", lib=d.rng.choice(_DEPS), a=a, b=b)


def _repo_path(d) -> str:
    return f"{d.slug}/{d.project}"


def _repo_url(d, scheme: str = "https://github.com/", suffix: str = ".git") -> Seg:
    return d.g.raw("private_url", f"{scheme}{_repo_path(d)}{suffix}", "url")


_PH_ADDR = {"street": ["Musterstraße 1", "123 Main Street", "Via Roma 1", "1 rue de l'Exemple"],
            "postcode": ["00000", "12345", "XXXXX"], "city": ["Anytown", "Musterstadt", "Città", "Ville"]}


def _addr_field(d, p, form: str) -> Seg:
    """Structured address field; field-shaped placeholder in clean documents."""
    if d.clean or p.placeholder:
        return d.x.ph("address", d.rng.choice(_PH_ADDR[form]))
    return d.g.addr(p, form)


def _pad(seg_text: str, width: int) -> str:
    return " " * max(1, width - len(seg_text))


# ---------------------------------------------------------------- 1. changelog from git log


@template("git_log_changelog", "react", "git")
def git_log_changelog(d):
    g, x, r = d.g, d.x, d.rng
    devs = _team(d, r.randint(3, 7))
    bots = [_bot(d) for _ in range(r.randint(1, 2))]
    major, minor, patch = r.randint(0, 4), r.randint(1, 25), r.randint(0, 9)
    prev = f"v{major}.{minor}.{patch}"
    new = f"v{major}.{minor + 1}.0" if r.random() < 0.6 else f"v{major}.{minor}.{patch + 1}"
    d.user(T(d.L(
        en="Prepare the CHANGELOG entry for ⟦v⟧ from everything merged since the last tag. Credit the contributors with their GitHub handles, skip the dependency bumps if they're noisy.",
        it="Prepara la voce del CHANGELOG per la ⟦v⟧ con tutto quello che è entrato dall'ultimo tag. Cita i contributor con l'handle GitHub e salta i bump delle dipendenze se sono troppi.",
        de="Bereite den CHANGELOG-Eintrag für ⟦v⟧ vor, mit allem, was seit dem letzten Tag gemergt wurde. Nenn die Contributors mit ihrem GitHub-Handle, Dependency-Bumps kannst du weglassen, wenn es zu viele sind.",
        fr="Prépare l'entrée du CHANGELOG pour la ⟦v⟧ avec tout ce qui a été mergé depuis le dernier tag. Crédite les contributeurs avec leur pseudo GitHub, et laisse tomber les bumps de dépendances s'ils sont trop nombreux.",
        es="Prepara la entrada del CHANGELOG para la ⟦v⟧ con todo lo que se ha mergeado desde el último tag. Menciona a los contributors con su handle de GitHub y omite los bumps de dependencias si hay demasiados."),
        v=x.ver(new)))
    d.agent(say(d, "look_first", x=d.L(en="the latest tag", it="l'ultimo tag", de="den letzten Tag", fr="le dernier tag",
                                       es="el último tag")))
    d.tool("sh", "git describe --tags --abbrev=0", F(x.ver(prev), "\n"))
    n = r.randint(40, 62) if r.random() < 0.2 else r.randint(6, 30)
    commits = []
    for _ in range(n):
        t = d.clock.tick(1800, 2.5 * 86400)
        if r.random() < 0.18:
            who = r.choice(bots)
            kind, subj = "deps", _bot_subject(d)
        else:
            who = r.choice(devs)
            kind, scope, text, pr = _subject_parts(d)
            subj = F(f"{kind}({scope}): {text}", pr)
            entry = F(f"**{scope}:** {text}", pr)
        commits.append({"sha": _sha(d), "t": t, "who": who, "kind": kind, "subj": subj,
                        "entry": entry if kind != "deps" else subj})
    log_rows = []
    for c in reversed(commits):
        log_rows.append(T("⟦h⟧ ⟦n⟧ <⟦e⟧> ⟦t⟧ ⟦s⟧", h=x.id(c["sha"][:7]), n=c["who"].name, e=c["who"].email,
                          t=x.ts("git_iso", t=c["t"], local=True), s=c["subj"]))
    d.tool("sh", F("git log ", x.ver(prev), "..HEAD --no-merges --date=iso --pretty=format:'%h %an <%ae> %ad %s'"),
           lines(*log_rows))
    humans = [c for c in commits if not c["who"].bot]
    if not d.clean and humans:
        d.agent(d.L(en="The log only has names and e-mails. I'll ask the API for the GitHub logins behind each commit.",
                    it="Il log ha solo nomi ed e-mail. Chiedo all'API i login GitHub associati a ogni commit.",
                    de="Im Log stehen nur Namen und E-Mails. Ich frage die API nach den GitHub-Logins zu jedem Commit.",
                    fr="Le log ne contient que des noms et des e-mails. Je demande à l'API les logins GitHub de chaque commit.",
                    es="El log solo tiene nombres y correos. Pido a la API los logins de GitHub de cada commit."))
        rows = [T("⟦h⟧\t⟦u⟧", h=x.id(c["sha"][:7]), u=c["who"].user) for c in reversed(commits)]
        d.tool("sh", F("gh api 'repos/", _repo_path(d), "/compare/", x.ver(prev), "...main' --jq '.commits[] | [.sha[0:7], .author.login] | @tsv'"),
               lines(*rows))
    sections = {"Added": [], "Fixed": [], "Changed": [], "Dependencies": []}
    for c in commits:
        sec = {"feat": "Added", "fix": "Fixed", "deps": "Dependencies"}.get(c["kind"], "Changed")
        sections[sec].append(c)
    skip_deps = len(sections["Dependencies"]) > 2 or r.random() < 0.4
    out = [T("## [⟦v⟧] - ⟦t⟧", v=x.ver(new[1:]), t=x.ts("date", tick=(3600, 7200))), ""]
    for sec in ("Added", "Fixed", "Changed", "Dependencies"):
        items = sections[sec]
        if not items or (sec == "Dependencies" and skip_deps):
            continue
        out.append(f"### {sec}")
        for c in items:
            thanks = "" if (c["who"].bot or d.clean) else T(" — thanks ⟦h⟧", h=c["who"].handle)
            out.append(F("- ", c["entry"], " (", x.id(c["sha"][:7]), ")", thanks))
        out.append("")
    if skip_deps and sections["Dependencies"]:
        out += [T("_⟦n⟧ dependency updates omitted._", n=x.num(len(sections["Dependencies"]))), ""]
    if not d.clean and r.random() < 0.6:
        uniq = []
        for c in commits:
            if not c["who"].bot and c["who"] not in uniq:
                uniq.append(c["who"])
        if uniq:
            out += ["### Contributors", "", J(", ", [T("⟦n⟧ (⟦h⟧)", n=u.name, h=u.handle) for u in uniq]), ""]
    out.append(T("[⟦v⟧]: ⟦u⟧", v=x.ver(new[1:]),
                 u=g.raw("private_url", f"https://github.com/{_repo_path(d)}/compare/{prev}...{new}", "url")))
    d.tool("write", "CHANGELOG.md", T("Prepended ⟦n⟧ lines to CHANGELOG.md (above ## [⟦p⟧]):\n", n=x.num(len(out)), p=x.ver(prev[1:])),
           lines(*out))
    d.agent(say(d, "done"), "\n",
            T(d.L(en="- ⟦n⟧ commits grouped into Added/Fixed/Changed; format follows ⟦u⟧",
                  it="- ⟦n⟧ commit raggruppati in Added/Fixed/Changed; formato secondo ⟦u⟧",
                  de="- ⟦n⟧ Commits in Added/Fixed/Changed gruppiert; Format nach ⟦u⟧",
                  fr="- ⟦n⟧ commits regroupés en Added/Fixed/Changed ; format selon ⟦u⟧",
                  es="- ⟦n⟧ commits agrupados en Added/Fixed/Changed; formato según ⟦u⟧"),
              n=x.num(n), u=x.url("license", "https://keepachangelog.com/en/1.1.0/")),
            "\n", d.L(en="- bot commits are not credited", it="- i commit dei bot non sono citati",
                      de="- Bot-Commits werden nicht genannt", fr="- les commits des bots ne sont pas crédités",
                      es="- los commits de bots no se mencionan"))


# ---------------------------------------------------------------- 2. blame a regression


_BLAME_PY = [
    "def apply_discount(order, rule):",
    '    """Apply a percentage discount rule to an order total."""',
    "    if not rule.active or not order.items:",
    "        return order.total",
    "    pct = Decimal(rule.percent) / Decimal(100)",
    "    # round per line item so invoices match the PDF",
    "    lines = [round(item.price * (1 - pct), 2) for item in order.items]",
    "    total = sum(lines)",
    "    if rule.cap is not None:",
    "        total = max(total, order.total - rule.cap)",
    "    return total.quantize(CENT, rounding=ROUND_HALF_UP)",
]
_BLAME_TS = [
    "export function applyDiscount(order: Order, rule: DiscountRule): Money {",
    "  // percentage rules only; fixed rules live in fixedDiscount.ts",
    "  if (!rule.active || order.items.length === 0) return order.total;",
    "  const pct = rule.percent / 100;",
    "  // round per line item so invoices match the PDF",
    "  const lines = order.items.map((i) => Math.round(i.price * (1 - pct) * 100) / 100);",
    "  let total = lines.reduce((a, b) => a + b, 0);",
    "  if (rule.cap !== undefined) total = Math.max(total, order.total - rule.cap);",
    "  return roundHalfUp(total, 2);",
    "}",
]


@template("git_blame_regression", "steps", "git", "file")
def git_blame_regression(d):
    g, x, r = d.g, d.x, d.rng
    py = r.random() < 0.55
    path = "src/pricing/discount.py" if py else "src/pricing/discount.ts"
    code = _BLAME_PY if py else _BLAME_TS
    start = r.randint(24, 140)
    devs = _team(d, r.randint(2, 4))
    culprit = devs[0]
    reviewer = devs[-1] if len(devs) > 1 else None
    d.user(d.L(
        en="Since last week's release, orders with several items get a discount one cent off compared to the invoice PDF. Can you find which change caused it?",
        it="Dal rilascio della settimana scorsa, gli ordini con più articoli hanno uno sconto che differisce di un centesimo dal PDF della fattura. Riesci a trovare quale modifica l'ha causato?",
        de="Seit dem Release letzte Woche weicht der Rabatt bei Bestellungen mit mehreren Artikeln um einen Cent vom Rechnungs-PDF ab. Findest du die Änderung, die das verursacht hat?",
        fr="Depuis la release de la semaine dernière, les commandes avec plusieurs articles ont une remise décalée d'un centime par rapport au PDF de la facture. Tu peux trouver le changement responsable ?",
        es="Desde la release de la semana pasada, los pedidos con varios artículos tienen un descuento que difiere en un céntimo del PDF de la factura. ¿Puedes encontrar qué cambio lo causó?"))
    d.agent(say(d, "searching", x="apply_discount" if py else "applyDiscount"))
    hits = [(path, start, code[0])]
    for extra in r.sample(["src/invoices/pdf.py" if py else "src/invoices/pdf.ts",
                           "tests/test_discount.py" if py else "test/discount.test.ts",
                           "src/checkout/summary.py" if py else "src/checkout/summary.ts"], r.randint(1, 3)):
        hits.append((extra, r.randint(10, 300), ("total = apply_discount(order, rule)" if py else "const total = applyDiscount(order, rule);")))
    d.tool("grep", "apply_discount" if py else "applyDiscount",
           lines(*[T("⟦p⟧:⟦n⟧:⟦c⟧", p=p, n=x.num(n), c=c) for p, n, c in hits]))
    end = start + len(code) - 1
    older = []
    for dv in (devs[1:] or devs)[: r.randint(1, 3)]:
        older.append((_sha(d), d.clock.tick(20 * 86400, 120 * 86400), dv))
    new_sha = _sha(d)
    new_t = d.clock.tick(5 * 86400, 20 * 86400)
    changed = {5, 6, 7} if py else {4, 5, 6}
    width = max(len(dv.name.text) for dv in devs)
    blame_rows = []
    for i, src in enumerate(code):
        if i in changed:
            dv, sha, t = culprit, new_sha, new_t
        else:
            sha, t, dv = older[0] if i < 2 or len(older) == 1 else r.choice(older)
        blame_rows.append(T("⟦h⟧ (⟦n⟧⟦pad⟧⟦t⟧ ⟦ln⟧) ⟦src⟧", h=x.id(sha[:8]), n=dv.name, pad=_pad(dv.name.text, width + 1),
                            t=x.ts("git_iso", t=t, local=True), ln=x.num(start + i), src=src))
    d.tool("sh", F("git blame -L ", x.num(start), ",", x.num(end), " ", path), lines(*blame_rows))
    d.agent(d.L(en="Lines in the rounding block come from a single recent commit; let me look at it.",
                it="Le righe dell'arrotondamento vengono tutte da un unico commit recente; lo guardo.",
                de="Die Rundungszeilen stammen alle aus einem einzigen, neuen Commit; den schaue ich mir an.",
                fr="Les lignes de l'arrondi viennent toutes d'un seul commit récent ; je le regarde.",
                es="Las líneas del redondeo vienen todas de un único commit reciente; lo miro."))
    body_txt = d.Lp(d.lang_of(culprit.p) if culprit.p else "en",
                    en="Invoices are rounded per line, the checkout rounded the total. Align both.",
                    it="Le fatture arrotondano per riga, il checkout arrotondava il totale. Allineo i due.",
                    de="Rechnungen runden pro Position, der Checkout rundete die Summe. Beides angleichen.",
                    fr="Les factures arrondissent par ligne, le checkout arrondissait le total. On aligne les deux.",
                    es="Las facturas redondean por línea y el checkout redondeaba el total. Los alineo.")
    show = [T("commit ⟦s⟧", s=x.id(new_sha)), T("Author: ⟦n⟧ <⟦e⟧>", n=culprit.name, e=culprit.email),
            T("Date:   ⟦t⟧", t=x.ts("git", t=new_t, local=True)), "",
            "    fix(pricing): round discounts per line item", "", "    " + body_txt]
    if reviewer is not None and r.random() < 0.6:
        show += ["", T("    Reviewed-by: ⟦n⟧ <⟦e⟧>", n=reviewer.name, e=reviewer.email)]
    if r.random() < 0.5:
        show += [T("    Refs: ⟦u⟧", u=g.url("internal", path=f"/browse/PAY-{r.randint(100, 999)}"))]
    show += ["", f"diff --git a/{path} b/{path}", T("index ⟦a⟧..⟦b⟧ 100644", a=x.short(9), b=x.short(9)),
             f"--- a/{path}", f"+++ b/{path}", T("@@ -⟦a⟧,6 +⟦b⟧,7 @@", a=x.num(start + 3), b=x.num(start + 3))]
    if py:
        show += [" " + code[3], " " + code[4], "-    total = round(order.total * (1 - pct), 2)", "+" + code[5],
                 "+" + code[6], "+" + code[7], " " + code[8]]
    else:
        show += [" " + code[2], " " + code[3], "-  let total = Math.round(order.total * (1 - pct) * 100) / 100;",
                 "+" + code[4], "+" + code[5], "+" + code[6], " " + code[7]]
    d.tool("sh", F("git show ", x.id(new_sha[:8])), lines(*show))
    d.tool("read", path, numbered(lines(*code), start=start))
    d.agent(say(d, "explain"), "\n",
            d.L(en="Per-line rounding happens before the cap is applied, and the result is rounded again with HALF_UP, so a 3-item order can lose one cent. The invoice code rounds per line but never re-rounds the sum.",
                it="L'arrotondamento per riga avviene prima di applicare il tetto, e il risultato viene riarrotondato con HALF_UP: un ordine da 3 articoli può perdere un centesimo. La fattura arrotonda per riga ma non riarrotonda la somma.",
                de="Pro Position wird vor dem Deckel gerundet und das Ergebnis danach nochmals HALF_UP gerundet; eine Bestellung mit 3 Artikeln verliert so einen Cent. Die Rechnung rundet pro Position, die Summe aber nicht erneut.",
                fr="L'arrondi par ligne se fait avant le plafond, puis le résultat est réarrondi en HALF_UP : une commande de 3 articles peut perdre un centime. La facture arrondit par ligne mais ne réarrondit jamais la somme.",
                es="El redondeo por línea se hace antes del tope y luego el resultado se vuelve a redondear con HALF_UP, así que un pedido de 3 artículos puede perder un céntimo. La factura redondea por línea pero nunca vuelve a redondear la suma."))
    d.agent(say(d, "applying"))
    if py:
        diff = lines("@@", "-    return total.quantize(CENT, rounding=ROUND_HALF_UP)", "+    return total  # already rounded per line")
    else:
        diff = lines("@@", "-  return roundHalfUp(total, 2);", "+  return total; // already rounded per line")
    d.tool("edit", path, diff)
    test_cmd = "pytest tests/test_discount.py -q" if py else "npx jest test/discount.test.ts"
    n_tests = r.randint(6, 18)
    if py:
        out = lines(T("⟦dots⟧                                                    [100%]", dots="." * n_tests),
                    T("⟦n⟧ passed in ⟦s⟧s", n=x.num(n_tests), s=f"{r.uniform(0.2, 2.5):.2f}"))
    else:
        out = lines(" PASS  test/discount.test.ts", T("Tests:       ⟦n⟧ passed, ⟦n⟧ total", n=x.num(n_tests)),
                    T("Time:        ⟦s⟧ s", s=f"{r.uniform(0.8, 4):.3f}"))
    d.tool("sh", test_cmd, out)
    if not d.clean and r.random() < 0.7:
        d.agent(say(d, "done"), "\n",
                T(d.L(en="- regression introduced in ⟦h⟧ by ⟦n⟧; you may want to ping ⟦u⟧ on the PR",
                      it="- regressione introdotta in ⟦h⟧ da ⟦n⟧; magari avvisa ⟦u⟧ sulla PR",
                      de="- Regression kam mit ⟦h⟧ von ⟦n⟧; ggf. ⟦u⟧ im PR anpingen",
                      fr="- régression introduite dans ⟦h⟧ par ⟦n⟧ ; tu peux mentionner ⟦u⟧ sur la PR",
                      es="- regresión introducida en ⟦h⟧ por ⟦n⟧; quizá avisa a ⟦u⟧ en la PR"),
                  h=x.id(new_sha[:8]), n=culprit.name, u=culprit.handle))
    else:
        d.agent(say(d, "done"), "\n", say(d, "not_committed"))


# ---------------------------------------------------------------- 3. staged secret review


@template("git_diff_staged_secret", "aider", "git")
def git_diff_staged_secret(d):
    g, x, r = d.g, d.x, d.rng
    d.user(d.L(
        en="Before I commit: can you review what's staged? It's the S3 export job config plus a test for it.",
        it="Prima di committare: puoi rivedere cosa c'è in stage? È la config del job di export su S3 più un test.",
        de="Bevor ich committe: kannst du dir anschauen, was gestaged ist? Die Config für den S3-Export-Job plus ein Test dazu.",
        fr="Avant que je committe : tu peux relire ce qui est stagé ? C'est la config du job d'export S3 plus un test.",
        es="Antes de hacer commit: ¿puedes revisar lo que está en stage? Es la config del job de exportación a S3 y un test."))
    cfg = r.choice(["config/export.yml", "deploy/export-job.yaml", "jobs/s3_export.yml"])
    fixture = r.choice(["tests/fixtures/customers.json", "tests/data/export_sample.json", "spec/fixtures/customers.json"])
    n_cust = r.randint(2, 5)
    owner = d.me
    sftp = r.random() < 0.6
    body = ["export:", '  schedule: "0 2 * * *"', f"  bucket: {d.slug}-exports-prod", "  region: eu-central-1",
            T("  aws_access_key_id: ⟦k⟧", k=g.secret("aws_akid")),
            T("  aws_secret_access_key: ⟦k⟧", k=g.secret("aws_secret")),
            "  notify:",
            T("    slack_webhook: ⟦k⟧", k=g.secret("slack_webhook")),
            T("    email: ⟦e⟧", e=g.email(owner, "work"))]
    if sftp:
        body += ["  sftp_mirror:", T("    host: ⟦ip⟧", ip=g.ip("public")), T("    user: ⟦u⟧", u=g.user(owner)),
                 T("    password: ⟦p⟧", p=g.password())]
    recs = []
    for i in range(n_cust):
        p = d.person()
        recs += ["  {", T('    "id": ⟦i⟧,', i=x.num(lo=1000, hi=99999)),
                 T('    "customer_no": "⟦c⟧",', c=g.cust()),
                 T('    "name": "⟦n⟧",', n=g.name(p)), T('    "email": "⟦e⟧",', e=g.email(p, "personal")),
                 T('    "phone": "⟦t⟧",', t=g.phone(p)),
                 T('    "street": "⟦s⟧",', s=_addr_field(d, p, "street")),
                 T('    "postcode": "⟦c⟧",', c=_addr_field(d, p, "postcode")),
                 T('    "city": "⟦c⟧",', c=_addr_field(d, p, "city")),
                 T('    "birth_date": "⟦b⟧",', b=g.birth(p, "iso")),
                 T('    "iban": "⟦i⟧"', i=g.iban(p=p, printed=False)), "  }" + ("," if i < n_cust - 1 else "")]
    recs = ["["] + recs + ["]"]
    n_test = r.randint(20, 60)
    d.tool("sh", "git diff --cached --stat",
           lines(T(" ⟦f⟧ | ⟦n⟧ ⟦b⟧", f=cfg.ljust(34), n=x.num(len(body)), b="+" * min(len(body), 20)),
                 T(" ⟦f⟧ | ⟦n⟧ ⟦b⟧", f=fixture.ljust(34), n=x.num(len(recs)), b="+" * 30),
                 T(" ⟦f⟧ | ⟦n⟧ ⟦b⟧", f="tests/test_export.py".ljust(34), n=x.num(n_test), b="+" * 22),
                 T(" 3 files changed, ⟦n⟧ insertions(+)", n=x.num(len(body) + len(recs) + n_test))))

    def added(path, rows):
        return [f"diff --git a/{path} b/{path}", "new file mode 100644", T("index 0000000..⟦h⟧", h=x.short(7)),
                "--- /dev/null", f"+++ b/{path}", T("@@ -0,0 +1,⟦n⟧ @@", n=x.num(len(rows)))] + [F("+", row) for row in rows]

    d.tool("sh", "git diff --cached -- " + cfg + " " + fixture, lines(*added(cfg, body), *added(fixture, recs)))
    issues = []
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x=cfg))
        issues.append(d.L(en=f"{cfg} hardcodes cloud credentials, a webhook{' and an SFTP password' if sftp else ''}; they should come from the environment / secret store.",
                          it=f"{cfg} contiene in chiaro credenziali cloud e un webhook{' e una password SFTP' if sftp else ''}: devono arrivare da variabili d'ambiente / secret store.",
                          de=f"{cfg} enthält Cloud-Zugangsdaten und einen Webhook{' sowie ein SFTP-Passwort' if sftp else ''} im Klartext; die gehören in Umgebungsvariablen bzw. den Secret Store.",
                          fr=f"{cfg} contient en dur des identifiants cloud et un webhook{' ainsi qu’un mot de passe SFTP' if sftp else ''} ; ils doivent venir de l'environnement / du coffre à secrets.",
                          es=f"{cfg} lleva en claro credenciales cloud y un webhook{' y una contraseña SFTP' if sftp else ''}; deberían venir del entorno o del gestor de secretos."))
    if d.gold_ok:
        issues.append(d.L(en=f"{fixture} looks like a dump of real customer records (names, addresses, birth dates, IBANs); fixtures should be synthetic.",
                          it=f"{fixture} sembra un estratto di clienti reali (nomi, indirizzi, date di nascita, IBAN); le fixture devono essere sintetiche.",
                          de=f"{fixture} sieht nach einem Auszug echter Kundendaten aus (Namen, Adressen, Geburtsdaten, IBANs); Fixtures sollten synthetisch sein.",
                          fr=f"{fixture} ressemble à un extrait de vrais clients (noms, adresses, dates de naissance, IBAN) ; les fixtures doivent être synthétiques.",
                          es=f"{fixture} parece un volcado de clientes reales (nombres, direcciones, fechas de nacimiento, IBAN); los fixtures deben ser sintéticos."))
    if not issues:
        d.agent(d.L(en="Looks fine: the config only references placeholders and the fixture uses dummy identities. One nit: the bucket name could come from the environment too, so staging can reuse the file.",
                    it="Mi sembra a posto: la config usa solo segnaposto e la fixture identità fittizie. Solo un dettaglio: anche il nome del bucket potrebbe arrivare dall'ambiente, così staging riusa il file.",
                    de="Sieht gut aus: Die Config enthält nur Platzhalter und die Fixture Dummy-Identitäten. Nur ein Detail: Der Bucket-Name könnte auch aus der Umgebung kommen, dann kann Staging die Datei mitnutzen.",
                    fr="Ça me paraît bon : la config ne contient que des placeholders et la fixture des identités factices. Un détail : le nom du bucket pourrait aussi venir de l'environnement, pour que staging réutilise le fichier.",
                    es="Me parece bien: la config solo tiene placeholders y el fixture identidades ficticias. Un detalle: el nombre del bucket también podría venir del entorno para que staging reutilice el fichero."))
        d.user(say(d, "go_ahead"))
        d.tool("edit", cfg, lines("@@", f"-  bucket: {d.slug}-exports-prod", '+  bucket: "${EXPORT_BUCKET}"'))
        d.tool("sh", "python -m pytest -q tests/test_export.py",
               lines(T("⟦n⟧ passed in ⟦s⟧s", n=x.num(r.randint(3, 12)), s=f"{r.uniform(0.3, 2):.2f}")))
        d.agent(say(d, "tests_pass"), " ", say(d, "not_committed"))
        return
    d.agent(d.L(en="Problems before this can be committed:", it="Problemi prima del commit:",
                de="Probleme vor dem Commit:", fr="Problèmes avant de committer :", es="Problemas antes del commit:"),
            "\n", J("\n", [f"{i + 1}. {t}" for i, t in enumerate(issues)]), "\n",
            d.L(en="I'd unstage the affected files, fix them and stage again. OK?",
                it="Tolgo dallo stage i file coinvolti, li sistemo e li rimetto in stage. Va bene?",
                de="Ich würde die betroffenen Dateien unstagen, korrigieren und neu stagen. Okay?",
                fr="Je propose de retirer ces fichiers du stage, de les corriger puis de les restager. OK ?",
                es="Propongo quitar del stage esos ficheros, corregirlos y volver a añadirlos. ¿Vale?"))
    d.user(say(d, "go_ahead") if r.random() < 0.6 else say(d, "dont_commit"))
    d.tool("sh", f"git restore --staged {cfg} {fixture}", F(""))
    if d.secret_ok:
        env_cfg = ["export:", '  schedule: "0 2 * * *"', f"  bucket: {d.slug}-exports-prod", "  region: eu-central-1",
                   T("  aws_access_key_id: ⟦p⟧", p=x.ph("api_key", "${AWS_ACCESS_KEY_ID}")),
                   T("  aws_secret_access_key: ⟦p⟧", p=x.ph("api_key", "${AWS_SECRET_ACCESS_KEY}")),
                   "  notify:", T("    slack_webhook: ⟦p⟧", p=x.ph("url", "${EXPORT_SLACK_WEBHOOK}")),
                   T("    email: ⟦p⟧", p=x.ph("email", "${EXPORT_NOTIFY_EMAIL}"))]
        if sftp:
            env_cfg += ["  sftp_mirror:", "    host: ${SFTP_HOST}", "    user: ${SFTP_USER}",
                        T("    password: ⟦p⟧", p=x.ph("password", "${SFTP_PASSWORD}"))]
        d.tool("write", cfg, lines(*env_cfg))
    fake = []
    for i in range(min(n_cust, 3)):
        fake += ["  {", T('    "id": ⟦i⟧,', i=x.num(i + 1)), T('    "name": "⟦n⟧",', n=x.ph("name")),
                 T('    "email": "⟦e⟧",', e=x.ph("email")), T('    "iban": "⟦i⟧"', i=x.ph("iban")),
                 "  }" + ("," if i < min(n_cust, 3) - 1 else "")]
    d.tool("write", fixture, lines("[", *fake, "]"))
    status = ["M  .gitignore"] if d.secret_ok else []
    cmd = "git add " + cfg + " " + fixture + " && git status --short"
    if d.secret_ok:
        cmd = "printf '\\n.env.export\\n' >> .gitignore && git add .gitignore " + cfg + " " + fixture + " && git status --short"
    d.tool("sh", cmd, lines(*status, f"A  {cfg}", f"A  {fixture}", "A  tests/test_export.py"))
    summary = []
    if d.secret_ok:
        summary.append(d.L(en="- credentials replaced by env references; .env.export added to .gitignore",
                           it="- credenziali sostituite da variabili d'ambiente; .env.export aggiunto a .gitignore",
                           de="- Zugangsdaten durch Env-Referenzen ersetzt; .env.export in .gitignore aufgenommen",
                           fr="- identifiants remplacés par des variables d'environnement ; .env.export ajouté au .gitignore",
                           es="- credenciales sustituidas por variables de entorno; .env.export añadido a .gitignore"))
    summary.append(d.L(en="- fixture regenerated with placeholder data", it="- fixture rigenerata con dati segnaposto",
                       de="- Fixture mit Platzhalterdaten neu erzeugt", fr="- fixture régénérée avec des données factices",
                       es="- fixture regenerado con datos ficticios"))
    d.agent(say(d, "done"), "\n", J("\n", summary), "\n", say(d, "not_committed"))


# ---------------------------------------------------------------- 4. bisect


@template("git_bisect_session", "plain", "git", "trace")
def git_bisect_session(d):
    g, x, r = d.g, d.x, d.rng
    devs = _team(d, r.randint(2, 5))
    good = f"v{r.randint(1, 3)}.{r.randint(0, 19)}.0"
    test_name = r.choice(["test_export_csv_header", "test_orders_csv_columns", "test_export_matches_public_format"])
    test_file = r.choice(["tests/test_export.py", "tests/export/test_csv.py", "tests/integration/test_exports.py"])
    d.user(T(d.L(
        en="⟦t⟧ passes on ⟦v⟧ and fails on main. Can you bisect it and tell me which commit broke it?",
        it="⟦t⟧ passa su ⟦v⟧ e fallisce su main. Puoi fare un bisect e dirmi quale commit l'ha rotto?",
        de="⟦t⟧ läuft auf ⟦v⟧ durch und schlägt auf main fehl. Kannst du bisecten und mir sagen, welcher Commit es kaputt gemacht hat?",
        fr="⟦t⟧ passe sur ⟦v⟧ et échoue sur main. Tu peux faire un bisect et me dire quel commit l'a cassé ?",
        es="⟦t⟧ pasa en ⟦v⟧ y falla en main. ¿Puedes hacer un bisect y decirme qué commit lo rompió?"),
        t=test_name, v=x.ver(good)))
    if r.random() < 0.6:
        rng_rows = []
        for _ in range(r.randint(6, 14)):
            dv = r.choice(devs)
            rng_rows.append(F(x.id(_sha(d)[:7]), " ", dv.name, " ", _subject(d)[1]))
        d.tool("sh", F("git log --format='%h %an %s' ", x.ver(good), "..main -- src/export tests | head -n 14"),
               lines(*rng_rows))
    revs = r.randint(12, 140)
    steps = max(3, revs.bit_length() - 1)
    first = _sha(d)
    out = [T("Bisecting: ⟦n⟧ revisions left to test after this (roughly ⟦s⟧ steps)", n=x.num(revs // 2), s=x.num(steps)),
           T("[⟦h⟧] ⟦s⟧", h=x.id(first), s=_subject(d)[1])]
    d.tool("sh", F("git bisect start main ", x.ver(good)), lines(*out))
    run = []
    left = revs // 2
    bad_sha = _sha(d)
    for i in range(steps):
        ok = r.random() < 0.5
        run.append(F("running  'python' '-m' 'pytest' '-x' '-q' '", test_file, "::", test_name, "'"))
        if ok:
            run.append(T("1 passed in ⟦s⟧s", s=f"{r.uniform(0.3, 3):.2f}"))
        else:
            run.append(F("F"))
            run.append(F("FAILED ", test_file, "::", test_name, " - AssertionError"))
            run.append(T("1 failed in ⟦s⟧s", s=f"{r.uniform(0.3, 3):.2f}"))
        left = max(0, left // 2)
        if i < steps - 1:
            run.append(T("Bisecting: ⟦n⟧ revisions left to test after this (roughly ⟦s⟧ steps)", n=x.num(left),
                         s=x.num(max(0, steps - i - 2))))
            run.append(T("[⟦h⟧] ⟦s⟧", h=x.id(_sha(d)), s=_subject(d)[1]))
    author = devs[0]
    coauth = devs[1] if len(devs) > 1 else None
    t_bad = d.clock.tick(3 * 86400, 30 * 86400)
    run += [T("⟦h⟧ is the first bad commit", h=x.id(bad_sha)), T("commit ⟦h⟧", h=x.id(bad_sha)),
            T("Author: ⟦n⟧ <⟦e⟧>", n=author.name, e=author.email), T("Date:   ⟦t⟧", t=x.ts("git", t=t_bad, local=True)), "",
            "    refactor(export): build CSV rows from serializer", "",
            "    " + d.Lp(d.lang_of(author.p) if author.p else "en",
                          en="Reuse the API serializer so CSV and JSON stay in sync.",
                          it="Riusa il serializer dell'API così CSV e JSON restano allineati.",
                          de="Den API-Serializer wiederverwenden, damit CSV und JSON synchron bleiben.",
                          fr="Réutilise le serializer de l'API pour garder CSV et JSON alignés.",
                          es="Reutiliza el serializer de la API para que CSV y JSON no diverjan."), ""]
    if coauth is not None:
        run.append(T("    Co-authored-by: ⟦n⟧ <⟦e⟧>", n=coauth.name, e=coauth.email))
    run.append(T("    Signed-off-by: ⟦n⟧ <⟦e⟧>", n=author.name, e=author.email))
    run += ["", T(" src/export/csv.py        | ⟦a⟧ ++++----", a=x.num(r.randint(8, 30))),
            T(" src/export/serializer.py | ⟦a⟧ ++", a=x.num(r.randint(2, 9))),
            T(" 2 files changed, ⟦a⟧ insertions(+), ⟦b⟧ deletions(-)", a=x.num(r.randint(10, 30)), b=x.num(r.randint(3, 15))),
            "bisect found first bad commit"]
    d.tool("sh", F("git bisect run python -m pytest -x -q ", test_file, "::", test_name), lines(*run))
    d.tool("sh", F("git checkout -q ", x.id(bad_sha[:10]), " && python -m pytest -x -q ", test_file, "::", test_name, " 2>&1 | tail -n 22"),
           lines("F",
                 "=================================== FAILURES ===================================",
                 f"___________________________ {test_name} ___________________________", "",
                 "    def " + test_name + "(client, sample_orders):",
                 '        resp = client.get("/exports/orders.csv")',
                 "        header = resp.text.splitlines()[0]",
                 '>       assert header == "order_id,created_at,email,total,currency"',
                 "E       AssertionError: assert 'id,created,customer_email,total_cents,currency' == 'order_id,created_at,email,total,currency'",
                 "E         - order_id,created_at,email,total,currency",
                 "E         + id,created,customer_email,total_cents,currency", "",
                 T("⟦f⟧:⟦n⟧: AssertionError", f=test_file, n=x.num(lo=20, hi=240)),
                 "=========================== short test summary info ============================",
                 F("FAILED ", test_file, "::", test_name, " - AssertionError"),
                 T("1 failed in ⟦s⟧s", s=f"{r.uniform(0.4, 2):.2f}")))
    d.tool("sh", "git bisect reset",
           lines(T("Previous HEAD position was ⟦h⟧ refactor(export): build CSV rows from serializer", h=x.id(bad_sha[:7])),
                 "Switched to branch 'main'", "Your branch is up to date with 'origin/main'."))
    d.agent(say(d, "explain"), "\n",
            T(d.L(en="⟦h⟧ switched the CSV export to the API serializer, which uses different field names (customer_email, total_cents). The test still expects the old header. Either map the serializer fields back to the public CSV column names, or version the export format.",
                  it="⟦h⟧ ha fatto passare l'export CSV dal serializer dell'API, che usa nomi di campo diversi (customer_email, total_cents). Il test si aspetta ancora la vecchia intestazione. O rimappiamo i campi sui nomi colonna pubblici del CSV, o versioniamo il formato.",
                  de="⟦h⟧ hat den CSV-Export auf den API-Serializer umgestellt, der andere Feldnamen nutzt (customer_email, total_cents). Der Test erwartet noch den alten Header. Entweder die Felder auf die öffentlichen CSV-Spaltennamen zurückmappen oder das Exportformat versionieren.",
                  fr="⟦h⟧ a basculé l'export CSV sur le serializer de l'API, qui utilise d'autres noms de champs (customer_email, total_cents). Le test attend toujours l'ancien en-tête. Soit on remappe les champs vers les noms de colonnes publics du CSV, soit on versionne le format.",
                  es="⟦h⟧ cambió la exportación CSV al serializer de la API, que usa otros nombres de campo (customer_email, total_cents). El test sigue esperando la cabecera antigua. O remapeamos los campos a los nombres públicos de columna, o versionamos el formato."),
              h=x.id(bad_sha[:7])))
    if r.random() < 0.6:
        d.user(d.L(en="Map them back, the CSV format is public.", it="Rimappa, il formato CSV è pubblico.",
                   de="Zurückmappen, das CSV-Format ist öffentlich.", fr="Remappe, le format CSV est public.",
                   es="Remapea, el formato CSV es público."))
        d.tool("edit", "src/export/csv.py",
               lines("@@", "+CSV_COLUMNS = {", '+    "id": "order_id",', '+    "created": "created_at",',
                     '+    "customer_email": "email",', '+    "total_cents": "total",', "+}",
                     "-    header = list(rows[0].keys())", "+    header = [CSV_COLUMNS.get(k, k) for k in rows[0].keys()]"))
        d.tool("sh", F("python -m pytest -q ", test_file),
               lines(T("⟦n⟧ passed in ⟦s⟧s", n=x.num(r.randint(4, 30)), s=f"{r.uniform(0.5, 4):.2f}")))
        d.agent(say(d, "tests_pass"), " ", say(d, "not_committed"))


# ---------------------------------------------------------------- 5. shortlog + mailmap


@template("git_shortlog_mailmap", "cc", "git", "file")
def git_shortlog_mailmap(d):
    g, x, r = d.g, d.x, d.rng
    d.user(d.L(
        en="Our contributor stats are off — several people show up twice with different e-mails or spellings. Can you sort it out with a .mailmap?",
        it="Le statistiche dei contributor non tornano: diverse persone compaiono due volte con e-mail o grafie diverse. Puoi sistemare con un .mailmap?",
        de="Unsere Contributor-Statistik stimmt nicht – mehrere Leute tauchen doppelt mit verschiedenen E-Mails oder Schreibweisen auf. Kannst du das mit einer .mailmap glattziehen?",
        fr="Les stats des contributeurs sont fausses : plusieurs personnes apparaissent deux fois avec des e-mails ou des graphies différentes. Tu peux arranger ça avec un .mailmap ?",
        es="Las estadísticas de contributors no cuadran: varias personas salen dos veces con correos o grafías distintas. ¿Lo arreglas con un .mailmap?"))
    n = r.randint(3, 8)
    people = [d.person() for _ in range(n)]
    entries = []   # (count, name_seg, email_seg, canonical index)
    canon = []
    for i, p in enumerate(people):
        work = g.email(p, "work")
        name = g.name(p)
        canon.append((name, work, p))
        entries.append((r.randint(20, 900), name, work, i))
        variant = r.random()
        if variant < 0.45:
            entries.append((r.randint(1, 60), name, g.email(p, "personal"), i))
        elif variant < 0.7:
            entries.append((r.randint(1, 40), g.user(p), work, i))
        elif variant < 0.85:
            alt_dom = r.choice(["users.noreply.github.com", d.domain.split(".")[0] + ".local", "MacBook-Pro.local"])
            entries.append((r.randint(1, 25), g.name(p, "initial"),
                            g.raw("private_email", f"{p.username()}@{alt_dom}", "email"), i))
    if r.random() < 0.7:
        b = _bot(d)
        entries.append((r.randint(5, 120), b.name, b.email, None))
    entries.sort(key=lambda e: -e[0])
    rows = [T("⟦c⟧\t⟦n⟧ <⟦e⟧>", c=f"{c:>6}", n=nm, e=em) for c, nm, em, _ in entries]
    d.tool("sh", "git shortlog -sne --all", lines(*rows))
    existing = r.random() < 0.4
    if existing:
        p0 = canon[0]
        d.tool("read", ".mailmap", numbered(lines("# canonical identities, see `git help mailmap`",
                                                   T("⟦n⟧ <⟦e⟧>", n=p0[0], e=p0[1]))))
    else:
        d.tool("read", ".mailmap", F("File does not exist."))
    mm = ["# Canonical name and e-mail for each contributor.", T("# Format: ⟦u⟧", u=x.url("docs", "https://git-scm.com/docs/gitmailmap")), ""]
    for i, (name, work, p) in enumerate(canon):
        alts = [e for e in entries if e[3] == i and (e[2] is not work or e[1] is not name)]
        for _, nm, em, _ in alts:
            if em is work:
                mm.append(T("⟦n⟧ <⟦e⟧> ⟦a⟧ <⟦e2⟧>", n=name, e=work, a=nm, e2=work))
            else:
                mm.append(T("⟦n⟧ <⟦e⟧> <⟦a⟧>", n=name, e=work, a=em))
    d.tool("write", ".mailmap", T("Wrote ⟦n⟧ lines to .mailmap:\n", n=x.num(len(mm))), lines(*mm))
    dup = [e for e in entries if e[3] is not None and e[2] is not canon[e[3]][1]]
    if dup:
        e = dup[0]
        d.tool("sh", F('git check-mailmap "<', e[2], '>"'), F(canon[e[3]][0], " <", canon[e[3]][1], ">\n"))
    merged: dict[int, int] = {}
    for c, _, _, i in entries:
        if i is not None:
            merged[i] = merged.get(i, 0) + c
    order = sorted(merged, key=lambda i: -merged[i])
    rows2 = [T("⟦c⟧\t⟦n⟧ <⟦e⟧>", c=f"{merged[i]:>6}", n=canon[i][0], e=canon[i][1]) for i in order[: min(6, len(order))]]
    d.tool("sh", "git shortlog -sne --all | head -n 6", lines(*rows2))
    d.agent(say(d, "done"), "\n",
            T(d.L(en="- .mailmap maps ⟦n⟧ alternate identities onto ⟦m⟧ canonical ones\n- history is untouched; only display changes",
                  it="- il .mailmap associa ⟦n⟧ identità alternative a ⟦m⟧ canoniche\n- la history non cambia, cambia solo la visualizzazione",
                  de="- die .mailmap bildet ⟦n⟧ alternative Identitäten auf ⟦m⟧ kanonische ab\n- die History bleibt unverändert, nur die Anzeige ändert sich",
                  fr="- le .mailmap rattache ⟦n⟧ identités alternatives à ⟦m⟧ identités canoniques\n- l'historique n'est pas modifié, seul l'affichage change",
                  es="- el .mailmap asigna ⟦n⟧ identidades alternativas a ⟦m⟧ canónicas\n- el historial no cambia, solo la visualización"),
              n=str(sum(1 for e in entries if e[3] is not None) - len(canon)), m=str(len(canon))))


# ---------------------------------------------------------------- 6. rebase conflict


@template("git_rebase_conflict", "xml", "git", "file")
def git_rebase_conflict(d):
    g, x, r = d.g, d.x, d.rng
    path = r.choice(["config/notifications.yml", "config/alerts.yaml", "ops/alerting.yml"])
    branch = r.choice(["feature/refund-alerts", "feat/payments-alerts", "alerts-refunds"])
    d.user(T(d.L(
        en="I'm rebasing ⟦b⟧ onto main and hit a conflict in ⟦p⟧. Can you help me resolve it without losing anything from main?",
        it="Sto facendo il rebase di ⟦b⟧ su main e ho un conflitto in ⟦p⟧. Mi aiuti a risolverlo senza perdere niente di main?",
        de="Ich rebase ⟦b⟧ auf main und habe einen Konflikt in ⟦p⟧. Hilfst du mir, ihn aufzulösen, ohne etwas von main zu verlieren?",
        fr="Je rebase ⟦b⟧ sur main et j'ai un conflit dans ⟦p⟧. Tu m'aides à le résoudre sans rien perdre de main ?",
        es="Estoy haciendo rebase de ⟦b⟧ sobre main y tengo un conflicto en ⟦p⟧. ¿Me ayudas a resolverlo sin perder nada de main?"),
        b=branch, p=path))
    onto, mine1, mine2, nxt = _sha(d), _sha(d), _sha(d), _sha(d)
    d.tool("sh", "git status",
           lines(T("interactive rebase in progress; onto ⟦h⟧", h=x.id(onto[:7])),
                 "Last commands done (2 commands done):",
                 T("   pick ⟦h⟧ feat(alerts): add refund failure rule", h=x.id(mine1[:7])),
                 T("   pick ⟦h⟧ feat(alerts): notify payments channel on refund failures", h=x.id(mine2[:7])),
                 "Next commands to do (1 remaining command):",
                 T("   pick ⟦h⟧ docs(alerts): describe refund alert", h=x.id(nxt[:7])),
                 '  (use "git rebase --edit-todo" to view and edit)',
                 T("You are currently rebasing branch '⟦b⟧' on '⟦h⟧'.", b=branch, h=x.id(onto[:7])),
                 '  (fix conflicts and then run "git rebase --continue")',
                 '  (use "git rebase --skip" to skip this patch)',
                 '  (use "git rebase --abort" to check out the original branch)', "",
                 "Unmerged paths:", '  (use "git restore --staged <file>..." to unstage)',
                 '  (use "git add <file>..." to mark resolution)', f"\tboth modified:   {path}", "",
                 'no changes added to commit (use "git add" and/or "git commit -a")'))
    oncall = [d.person() for _ in range(r.randint(2, 4))]
    newbie = d.person()
    relay_ip = g.ip("private")
    rk_new = g.secret("datadog")
    rk_old = g.secret("datadog")
    slack = g.secret("slack_webhook")
    em = {id(p): g.email(p, "work") for p in oncall + [newbie]}
    head = ["  recipients:"] + [T("    - ⟦e⟧", e=em[id(p)]) for p in oncall] + \
           [T("  pagerduty_routing_key: ⟦k⟧", k=rk_new)]
    theirs = ["  recipients:"] + [T("    - ⟦e⟧", e=em[id(p)]) for p in oncall[:-1]] + [T("    - ⟦e⟧", e=em[id(newbie)])] + \
             [T("  pagerduty_routing_key: ⟦k⟧", k=rk_old), T("  slack_webhook: ⟦k⟧", k=slack),
              '  slack_channel: "#payments-alerts"']
    top = ["alerts:", T("  smtp_relay: ⟦ip⟧:⟦p⟧", ip=relay_ip, p=x.port(r.choice([25, 587]))),
           f"  sender: alerts@{d.domain}"]
    bottom = ["  rules:", "    - name: refund_failed", "      threshold: 3", "      window: 10m",
              "    - name: payout_delayed", "      threshold: 1", "      window: 1h"]
    conflict = top + [T("<<<<<<< HEAD")] + head + ["======="] + theirs + \
        [T(">>>>>>> ⟦h⟧ (feat(alerts): notify payments channel on refund failures)", h=x.id(mine2[:7]))] + bottom
    d.tool("read", path, numbered(lines(*conflict)))
    main_author = _dev(d, oncall[0]) if not d.clean else _bot(d, _BOTS[2])
    graph = [T("* ⟦h⟧ (origin/main, main) chore(alerts): rotate PagerDuty routing key", h=x.id(onto[:7]))]
    for _ in range(r.randint(0, 3)):
        graph.append(F("* ", x.id(_sha(d)[:7]), " ", _subject(d)[1]))
    graph += [T("| * ⟦h⟧ (⟦b⟧) docs(alerts): describe refund alert", h=x.id(nxt[:7]), b=branch),
              T("| * ⟦h⟧ feat(alerts): notify payments channel on refund failures", h=x.id(mine2[:7])),
              T("| * ⟦h⟧ feat(alerts): add refund failure rule", h=x.id(mine1[:7])), "|/",
              F("* ", x.id(_sha(d)[:7]), " ", _subject(d)[1])]
    d.tool("sh", F("git log --oneline --graph -n 8 main ", branch), lines(*graph))
    d.tool("sh", F("git log -1 --format='%an <%ae>%n%ad%n%s' ", x.id(onto[:7])),
           lines(F(main_author.name, " <", main_author.email, ">"), x.ts("git", tick=(3600, 86400), local=True),
                 "chore(alerts): rotate PagerDuty routing key"))
    d.agent(d.L(
        en="Main rotated the PagerDuty routing key and kept the full on-call list; your commit adds a recipient and the Slack webhook but still carries the old key. Resolution: main's recipients plus the new one, main's routing key, and your Slack settings.",
        it="Su main hanno ruotato la routing key di PagerDuty e tenuto la lista on-call completa; il tuo commit aggiunge un destinatario e il webhook Slack ma ha ancora la vecchia chiave. Risoluzione: i destinatari di main più quello nuovo, la routing key di main e le tue impostazioni Slack.",
        de="Auf main wurde der PagerDuty-Routing-Key rotiert und die komplette On-Call-Liste behalten; dein Commit fügt einen Empfänger und den Slack-Webhook hinzu, enthält aber noch den alten Key. Lösung: Empfänger von main plus der neue, der Routing-Key von main und deine Slack-Einstellungen.",
        fr="Sur main, la routing key PagerDuty a été renouvelée et la liste d'astreinte complète conservée ; ton commit ajoute un destinataire et le webhook Slack mais garde l'ancienne clé. Résolution : les destinataires de main plus le nouveau, la routing key de main et tes réglages Slack.",
        es="En main rotaron la routing key de PagerDuty y mantuvieron la lista de guardia completa; tu commit añade un destinatario y el webhook de Slack pero conserva la clave antigua. Resolución: los destinatarios de main más el nuevo, la routing key de main y tu configuración de Slack."))
    resolved = top + ["  recipients:"] + [T("    - ⟦e⟧", e=em[id(p)]) for p in oncall] + \
        [T("    - ⟦e⟧", e=em[id(newbie)]), T("  pagerduty_routing_key: ⟦k⟧", k=rk_new), T("  slack_webhook: ⟦k⟧", k=slack),
         '  slack_channel: "#payments-alerts"'] + bottom
    d.tool("write", path, lines(*resolved))
    new_sha = _sha(d)
    d.tool("sh", F("git add ", path, " && GIT_EDITOR=true git rebase --continue"),
           lines(T("[detached HEAD ⟦h⟧] feat(alerts): notify payments channel on refund failures", h=x.id(new_sha[:7])),
                 T(" 1 file changed, ⟦a⟧ insertions(+)", a=x.num(4)),
                 T("Successfully rebased and updated refs/heads/⟦b⟧.", b=branch)))
    if d.secret_ok and r.random() < 0.5:
        d.agent(say(d, "secret_warning", x=path))
    d.agent(say(d, "done"), "\n",
            d.L(en="- conflict resolved, rebase finished; nothing pushed yet (you'll need --force-with-lease)",
                it="- conflitto risolto e rebase completato; non ho fatto push (servirà --force-with-lease)",
                de="- Konflikt gelöst, Rebase abgeschlossen; noch nichts gepusht (du brauchst --force-with-lease)",
                fr="- conflit résolu, rebase terminé ; rien n'est poussé (il faudra --force-with-lease)",
                es="- conflicto resuelto y rebase terminado; no he hecho push (necesitarás --force-with-lease)"))


# ---------------------------------------------------------------- 7. push fails: credentials in the remote URL


@template("git_remote_push_auth", "md", "git", "shell")
def git_remote_push_auth(d):
    g, x, r = d.g, d.x, d.rng
    me = d.me
    branch = r.choice(["feature/csv-export", "fix/session-timeout", "chore/upgrade-node", "feat/sso"])
    host = r.choice(["github.com", "github.com", "gitlab.com"])
    path = _repo_path(d)
    d.user(d.L(
        en="git push fails with 403 since yesterday, pull still works. Can you check what's wrong?",
        it="Da ieri git push fallisce con 403, mentre il pull funziona. Puoi vedere cosa non va?",
        de="Seit gestern schlägt git push mit 403 fehl, pull geht noch. Kannst du nachsehen, was los ist?",
        fr="Depuis hier git push échoue avec une 403, le pull marche encore. Tu peux regarder ce qui cloche ?",
        es="Desde ayer git push falla con 403, el pull sigue funcionando. ¿Puedes ver qué pasa?"))
    if d.clean:
        embedded = x.ph("url", f"https://USERNAME:TOKEN@{host}/ORG/REPO.git")
        plain_url = x.ph("url", f"https://{host}/ORG/REPO.git")
    else:
        tok = g.secret("github_pat" if host == "github.com" else "gitlab_pat")
        embedded = F("https://", g.user(me), ":", tok, "@", g.raw("private_url", f"{host}/{path}.git", "url"))
        plain_url = g.raw("private_url", f"https://{host}/{path}.git", "url")
    d.tool("sh", F("git push origin ", branch),
           lines(F("remote: Permission to ", path, ".git denied to ", g.user(me), "."),
                 F("fatal: unable to access '", plain_url, "/': The requested URL returned error: 403")))
    d.tool("sh", "git remote -v", lines(F("origin\t", embedded, " (fetch)"), F("origin\t", embedded, " (push)")))
    home = d.home()
    cfg = [F("file:", home, "/.gitconfig\tuser.name=", g.name(me)),
           F("file:", home, "/.gitconfig\tuser.email=", g.email(me, r.choice(["work", "personal"]))),
           F("file:", home, "/.gitconfig\tcore.editor=", r.choice(["vim", "nano", "code --wait"])),
           F("file:", home, "/.gitconfig\tpull.rebase=true"),
           F("file:", home, "/.gitconfig\tinit.defaultbranch=main")]
    helper = r.choice(["store", "osxkeychain", "cache --timeout=3600", "manager"])
    cfg.append(F("file:", home, "/.gitconfig\tcredential.helper=", helper))
    if r.random() < 0.5:
        cfg.append(F("file:", home, "/.gitconfig\tincludeif.gitdir:~/work/.path=~/.gitconfig-work"))
        cfg.append(F("file:", home, "/.gitconfig-work\tuser.email=", g.email(me, "work")))
    cfg += [F("file:.git/config\tcore.repositoryformatversion=0"), F("file:.git/config\tcore.bare=false"),
            F("file:.git/config\tremote.origin.url=", embedded),
            F("file:.git/config\tremote.origin.fetch=+refs/heads/*:refs/remotes/origin/*"),
            F("file:.git/config\tbranch.main.remote=origin")]
    d.tool("sh", "git config --list --show-origin", lines(*cfg))
    if helper == "store" and r.random() < 0.7:
        cred = x.ph("url", f"https://USERNAME:TOKEN@{host}") if d.clean else \
            F("https://", g.user(me), ":", g.secret("github_pat" if host == "github.com" else "gitlab_pat"), "@", host)
        d.tool("sh", "cat ~/.git-credentials", lines(cred))
    d.agent(say(d, "explain"), "\n\n",
            d.L(en="The remote URL has a personal access token baked into it, and git uses that instead of the credential helper. The token was most likely revoked or expired (read-only access to public refs still works, which is why pull succeeds). Fix: drop the token from the URL and let the helper/gh supply credentials.",
                it="L'URL del remote contiene un personal access token, e git usa quello invece del credential helper. Il token è stato probabilmente revocato o è scaduto (il pull funziona ancora). Soluzione: togliere il token dall'URL e lasciare che sia l'helper/gh a fornire le credenziali.",
                de="In der Remote-URL steckt ein Personal Access Token, und git nimmt den statt des Credential Helpers. Das Token ist vermutlich widerrufen oder abgelaufen (Pull funktioniert noch). Lösung: Token aus der URL entfernen und die Zugangsdaten vom Helper bzw. gh liefern lassen.",
                fr="L'URL du remote contient un personal access token, et git l'utilise à la place du credential helper. Le token a probablement été révoqué ou a expiré (le pull fonctionne encore). Correctif : retirer le token de l'URL et laisser le helper/gh fournir les identifiants.",
                es="La URL del remote lleva un personal access token incrustado y git lo usa en lugar del credential helper. Lo más probable es que el token se haya revocado o caducado (el pull sigue funcionando). Solución: quitar el token de la URL y dejar que el helper/gh aporte las credenciales."),
            "\n\n", x.url("docs", "https://docs.github.com/en/get-started/getting-started-with-git/caching-your-github-credentials-in-git"))
    d.user(say(d, "go_ahead"))
    login = g.user(me)
    status = lines(host, F("  ✓ Logged in to ", host, " account ", login, " (keyring)"), "  - Active account: true",
                   "  - Git operations protocol: https", T("  - Token: ⟦t⟧", t=x.ph("token", "gho_************************************")),
                   "  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'")
    d.tool("sh", F("git remote set-url origin ", plain_url, " && gh auth setup-git && gh auth status"), status)
    old, new = _sha(d), _sha(d)
    d.tool("sh", F("git push origin ", branch),
           lines(T("Enumerating objects: ⟦n⟧, done.", n=x.num(lo=5, hi=60)),
                 T("Writing objects: 100% (⟦n⟧/⟦n⟧), ⟦k⟧ KiB | ⟦s⟧ MiB/s, done.", n=x.num(lo=3, hi=40), k=f"{r.uniform(0.5, 30):.2f}", s=f"{r.uniform(0.5, 9):.2f}"),
                 F("To ", plain_url),
                 T("   ⟦a⟧..⟦b⟧  ⟦br⟧ -> ⟦br⟧", a=x.id(old[:7]), b=x.id(new[:7]), br=branch)))
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x=".git/config"), " ",
                d.L(en="Revoke the old token in your account settings even if it already looks dead.",
                    it="Revoca il vecchio token dalle impostazioni dell'account anche se sembra già morto.",
                    de="Widerrufe das alte Token in den Kontoeinstellungen, auch wenn es schon tot aussieht.",
                    fr="Révoque l'ancien token dans les paramètres du compte, même s'il semble déjà mort.",
                    es="Revoca el token antiguo en los ajustes de la cuenta aunque parezca ya inválido."))
    d.agent(say(d, "done"), "\n",
            d.L(en="- token removed from the remote URL\n- git now authenticates through gh's credential helper\n- push succeeded",
                it="- token rimosso dall'URL del remote\n- git ora si autentica tramite il credential helper di gh\n- push riuscito",
                de="- Token aus der Remote-URL entfernt\n- git authentifiziert sich jetzt über den Credential Helper von gh\n- Push erfolgreich",
                fr="- token retiré de l'URL du remote\n- git s'authentifie désormais via le credential helper de gh\n- push réussi",
                es="- token eliminado de la URL del remote\n- git ahora se autentica con el credential helper de gh\n- push correcto"))


# ---------------------------------------------------------------- 8. who changed the prod config (fuller log + signature)


@template("git_show_commit_metadata", "colon", "git")
def git_show_commit_metadata(d):
    g, x, r = d.g, d.x, d.rng
    path = r.choice(["deploy/prod/payments.yaml", "infra/prod/values-payments.yaml", "config/prod/payments.yml"])
    d.user(T(d.L(
        en="Somebody changed ⟦p⟧ last week and since then the payment webhooks fail in prod. Who changed it and what exactly?",
        it="Qualcuno ha modificato ⟦p⟧ la settimana scorsa e da allora i webhook dei pagamenti falliscono in prod. Chi l'ha cambiato e cosa esattamente?",
        de="Jemand hat letzte Woche ⟦p⟧ geändert und seitdem schlagen die Payment-Webhooks in Prod fehl. Wer war das und was genau wurde geändert?",
        fr="Quelqu'un a modifié ⟦p⟧ la semaine dernière et depuis les webhooks de paiement échouent en prod. Qui l'a changé et quoi exactement ?",
        es="Alguien cambió ⟦p⟧ la semana pasada y desde entonces fallan los webhooks de pago en prod. ¿Quién lo cambió y qué exactamente?"),
        p=path))
    devs = _team(d, r.randint(2, 4))
    n = r.randint(2, 4)
    entries = []
    for i in range(n):
        ta = d.clock.tick(2 * 86400, 25 * 86400)
        tc = d.clock.tick(60, 2 * 86400)
        a = r.choice(devs)
        c = a if r.random() < 0.6 else r.choice(devs)
        entries.append((_sha(d), a, c, ta, tc))
    entries.reverse()
    log = []
    others = ["fix(payments): raise connect timeout", "chore(payments): rotate webhook signing secret",
              "feat(payments): enable 3DS for EU cards", "chore(prod): bump payments chart",
              "fix(payments): correct merchant contact"]
    r.shuffle(others)
    subjects = ["chore(payments): move webhook to internal gateway"] + others
    for (sha, a, c, ta, tc), subj in zip(entries, subjects):
        log += [T("commit ⟦h⟧", h=x.id(sha)), T("Author:     ⟦n⟧ <⟦e⟧>", n=a.name, e=a.email),
                T("AuthorDate: ⟦t⟧", t=x.ts("git", t=ta, local=True)), T("Commit:     ⟦n⟧ <⟦e⟧>", n=c.name, e=c.email),
                T("CommitDate: ⟦t⟧", t=x.ts("git", t=tc, local=True)), "", "    " + subj, ""]
    d.tool("sh", F("git log --format=fuller -n ", str(n), " -- ", path), lines(*log))
    sha, a, c, ta, tc = entries[0]
    subj0 = subjects[0]
    key = V.rand_str(r, "0123456789ABCDEF", 40)
    signed = r.random() < 0.7
    show = []
    if signed:
        show += [T("gpg: Signature made ⟦t⟧", t=x.ts("rfc2822", t=tc, local=True)),
                 T("gpg:                using RSA key ⟦k⟧", k=x.id(key))]
        if r.random() < 0.75:
            show.append(T('gpg: Good signature from "⟦n⟧ <⟦e⟧>" [⟦tr⟧]', n=c.name, e=c.email, tr=r.choice(["ultimate", "full", "unknown"])))
        else:
            show.append("gpg: Can't check signature: No public key")
    show += [T("commit ⟦h⟧", h=x.id(sha)), T("Author: ⟦n⟧ <⟦e⟧>", n=a.name, e=a.email),
             T("Date:   ⟦t⟧", t=x.ts("git", t=ta, local=True)), "", "    " + subj0, "",
             T(" ⟦p⟧ | ⟦n⟧ ++++++----", p=path, n=x.num(r.randint(6, 14))),
             T(" 1 file changed, ⟦a⟧ insertions(+), ⟦b⟧ deletions(-)", a=x.num(r.randint(3, 8)), b=x.num(r.randint(3, 7)))]
    d.tool("sh", F("git show --stat --show-signature ", x.id(sha[:10])), lines(*show))
    contact = d.person()
    gw = r.choice(["payments-gw", "pay-edge", "webhooks", "psp-gateway"])
    old_hook = g.raw("private_url", f"https://{gw}.{d.int_domain}/hooks/stripe", "url")
    new_hook = g.raw("private_url", f"https://{gw}.{d.int_domain}/v2/hooks/payments", "url")
    old_ips = [g.ip("public") for _ in range(r.randint(1, 3))]
    new_ip = g.ip("public")
    diff = [f"diff --git a/{path} b/{path}", T("index ⟦a⟧..⟦b⟧ 100644", a=x.short(9), b=x.short(9)), f"--- a/{path}",
            f"+++ b/{path}", T("@@ -⟦a⟧,14 +⟦a⟧,14 @@ payments:", a=x.num(lo=3, hi=40)),
            "   provider: stripe", "   mode: live",
            F("-  webhook_url: ", old_hook), F("+  webhook_url: ", new_hook),
            T("-  webhook_secret: ⟦s⟧", s=g.secret("stripe_whsec")), T("+  webhook_secret: ⟦s⟧", s=g.secret("stripe_whsec")),
            "   merchant_contact:", T("     name: ⟦n⟧", n=g.name(contact)), T("     email: ⟦e⟧", e=g.email(contact, "work")),
            T("     phone: \"⟦p⟧\"", p=g.phone(contact, True)), "   ip_allowlist:"]
    diff += [T("-    - ⟦ip⟧", ip=ip) for ip in old_ips] + [T("+    - ⟦ip⟧", ip=new_ip)]
    diff += ["   timeouts:", "     connect_ms: 2000"]
    d.tool("sh", F("git show ", x.id(sha[:10]), " -- ", path), lines(*diff))
    who = F(a.name) if a is c else F(a.name, d.L(en=" (committed by ", it=" (commit di ", de=" (committet von ",
                                                    fr=" (committé par ", es=" (commit de "), c.name, ")")
    d.agent(say(d, "explain"), "\n",
            T(d.L(en="The change is ⟦h⟧ by ⟦w⟧. It moved the webhook to a new path and replaced the IP allowlist with a single address, so deliveries from the provider's other egress IPs are now rejected; the signing secret was rotated in the same commit.",
                  it="La modifica è ⟦h⟧ di ⟦w⟧. Ha spostato il webhook su un nuovo path e ha sostituito l'allowlist IP con un solo indirizzo, quindi le chiamate dagli altri IP del provider vengono rifiutate; nello stesso commit è stato ruotato anche il secret di firma.",
                  de="Die Änderung ist ⟦h⟧ von ⟦w⟧. Der Webhook wurde auf einen neuen Pfad verschoben und die IP-Allowlist durch eine einzige Adresse ersetzt, daher werden Zustellungen von den anderen Egress-IPs des Anbieters abgelehnt; im selben Commit wurde das Signing-Secret rotiert.",
                  fr="Le changement est ⟦h⟧ par ⟦w⟧. Il a déplacé le webhook vers un nouveau chemin et remplacé l'allowlist IP par une seule adresse : les appels depuis les autres IP du fournisseur sont rejetés ; le secret de signature a été renouvelé dans le même commit.",
                  es="El cambio es ⟦h⟧ de ⟦w⟧. Movió el webhook a una ruta nueva y sustituyó la allowlist de IP por una sola dirección, así que se rechazan las entregas desde las otras IP del proveedor; en el mismo commit se rotó el secreto de firma."),
              h=x.id(sha[:10]), w=who))
    d.user(d.L(en="Restore the old allowlist entries but keep the new URL and secret.",
               it="Ripristina le vecchie voci dell'allowlist ma tieni il nuovo URL e il nuovo secret.",
               de="Stell die alten Allowlist-Einträge wieder her, aber behalte die neue URL und das neue Secret.",
               fr="Remets les anciennes entrées de l'allowlist mais garde la nouvelle URL et le nouveau secret.",
               es="Restaura las entradas antiguas de la allowlist pero mantén la URL y el secreto nuevos."))
    d.tool("edit", path, lines("@@", "   ip_allowlist:", *[T("+    - ⟦ip⟧", ip=ip) for ip in old_ips], T("     - ⟦ip⟧", ip=new_ip)))
    d.agent(say(d, "done"), "\n",
            d.L(en="- allowlist now contains the old and the new egress addresses\n- webhook URL and secret unchanged",
                it="- l'allowlist contiene sia i vecchi sia il nuovo indirizzo\n- URL e secret del webhook invariati",
                de="- die Allowlist enthält alte und neue Egress-Adressen\n- Webhook-URL und Secret unverändert",
                fr="- l'allowlist contient les anciennes et la nouvelle adresse\n- URL et secret du webhook inchangés",
                es="- la allowlist contiene las direcciones antiguas y la nueva\n- URL y secreto del webhook sin cambios"),
            "\n", say(d, "not_committed"))


# ---------------------------------------------------------------- 9. pull-request review thread


def _review_comment(d, rv, topic: str) -> str:
    lang = d.lang_of(rv.p) if rv.p is not None else "en"
    texts = {
        "fixture": dict(
            en="The sample payload in the description and in the fixture looks like a real customer from staging. Please replace it with dummy data before we merge.",
            it="Il payload di esempio nella descrizione e nella fixture sembra un cliente reale di staging. Per favore sostituiscilo con dati fittizi prima del merge.",
            de="Die Beispiel-Payload in der Beschreibung und in der Fixture sieht nach einem echten Kunden aus Staging aus. Bitte vor dem Merge durch Dummy-Daten ersetzen.",
            fr="Le payload d'exemple dans la description et dans la fixture ressemble à un vrai client de staging. Merci de le remplacer par des données factices avant le merge.",
            es="El payload de ejemplo de la descripción y del fixture parece un cliente real de staging. Sustitúyelo por datos ficticios antes del merge, por favor."),
        "logging": dict(
            en="We shouldn't log the requester's e-mail here. Log the user id, or use redact_email() from utils.",
            it="Qui non dovremmo loggare l'e-mail di chi fa la richiesta. Logga l'id utente oppure usa redact_email() da utils.",
            de="Hier sollten wir die E-Mail des Anfragenden nicht loggen. Lieber die User-ID loggen oder redact_email() aus utils verwenden.",
            fr="On ne devrait pas logger l'e-mail du demandeur ici. Logge l'id utilisateur, ou utilise redact_email() de utils.",
            es="Aquí no deberíamos loguear el e-mail del solicitante. Loguea el id de usuario o usa redact_email() de utils."),
        "limit": dict(
            en="nit: the export can get big for old accounts, maybe stream it instead of building the whole JSON in memory?",
            it="nit: per gli account vecchi l'export può diventare grande, magari conviene lo streaming invece di costruire tutto il JSON in memoria?",
            de="nit: Bei alten Konten kann der Export groß werden, vielleicht lieber streamen statt das ganze JSON im Speicher zu bauen?",
            fr="nit : l'export peut devenir gros pour les vieux comptes, peut-être streamer au lieu de construire tout le JSON en mémoire ?",
            es="nit: para cuentas antiguas el export puede ser grande, ¿quizá hacer streaming en vez de construir todo el JSON en memoria?"),
        "naming": dict(
            en="Naming: serialize_full is a bit vague, maybe serialize_for_export?",
            it="Naming: serialize_full è un po' vago, magari serialize_for_export?",
            de="Benennung: serialize_full ist etwas vage, vielleicht serialize_for_export?",
            fr="Nommage : serialize_full est un peu vague, peut-être serialize_for_export ?",
            es="Nombres: serialize_full es algo vago, ¿quizá serialize_for_export?"),
        "auth": dict(
            en="Who can call this? I'd restrict it to the customer themselves and to support staff with the privacy role.",
            it="Chi può chiamarlo? Lo limiterei al cliente stesso e al supporto con il ruolo privacy.",
            de="Wer darf das aufrufen? Ich würde es auf den Kunden selbst und Support mit der Privacy-Rolle beschränken.",
            fr="Qui peut appeler ça ? Je le limiterais au client lui-même et au support avec le rôle privacy.",
            es="¿Quién puede llamar a esto? Lo limitaría al propio cliente y al soporte con el rol de privacidad."),
        "lgtm": dict(
            en="LGTM once the logging comment is addressed.",
            it="Per me ok appena sistemato il commento sul logging.",
            de="Passt für mich, sobald der Logging-Kommentar erledigt ist.",
            fr="OK pour moi une fois le commentaire sur les logs traité.",
            es="Por mi parte bien en cuanto se resuelva el comentario del logging."),
    }
    return d.Lp(lang, **texts[topic])


@template("pr_review_thread", "jsonl", "ticket", "git")
def pr_review_thread(d):
    g, x, r = d.g, d.x, d.rng
    num = r.randint(120, 2400)
    branch = r.choice(["feature/gdpr-export", "feat/account-export", "privacy/data-export"])
    d.user(T(d.L(
        en="Can you go through the review comments on PR #⟦n⟧ and address them?",
        it="Puoi guardare i commenti della review sulla PR #⟦n⟧ e sistemarli?",
        de="Kannst du dir die Review-Kommentare in PR #⟦n⟧ ansehen und sie umsetzen?",
        fr="Tu peux passer sur les commentaires de review de la PR #⟦n⟧ et les traiter ?",
        es="¿Puedes revisar los comentarios de la review de la PR #⟦n⟧ y resolverlos?"), n=x.num(num)))
    author = _dev(d, d.me)
    reviewers = [_dev(d) for _ in range(r.randint(2, 3))]
    cust = d.person()
    cust_id = g.cust()
    sample = ["```json", "{", T('  "customer_id": "⟦c⟧",', c=cust_id), T('  "name": "⟦n⟧",', n=g.name(cust)),
              T('  "email": "⟦e⟧",', e=g.email(cust, "personal")), T('  "phone": "⟦p⟧",', p=g.phone(cust)),
              T('  "address": "⟦a⟧",', a=g.addr(cust)), T('  "created_at": "⟦t⟧",', t=x.ts("iso_s", tick=(1, 5))),
              T('  "orders": ⟦n⟧', n=x.num(lo=1, hi=80)), "}", "```"]
    view = [T("feat(customers): add GDPR data export endpoint #⟦n⟧", n=x.num(num)),
            T("Open • ⟦a⟧ wants to merge ⟦c⟧ commits into main from ⟦b⟧ • +⟦p⟧ −⟦m⟧", a=author.user, c=x.num(lo=2, hi=9),
              b=branch, p=x.num(lo=120, hi=600), m=x.num(lo=5, hi=80)),
            F("Reviewers: ", J(", ", [F(rv.user, " (", "Changes requested" if i == 0 else r.choice(["Approved", "Commented"]), ")")
                                      for i, rv in enumerate(reviewers)])),
            "Labels: backend, privacy", "",
            "  Adds GET /v1/customers/{id}/export returning everything we store about a customer",
            "  (art. 15 requests). Example response from staging:", ""]
    view += [F("  ", row) for row in sample]
    view += ["", T("  Spec: ⟦u⟧", u=x.url("docs", "https://gdpr-info.eu/art-17-gdpr/")), "",
             "———————— Comments ————————", ""]
    topics = ["fixture", "logging"] + (["limit"] if r.random() < 0.5 else [])
    extra = r.sample(["naming", "auth"], r.randint(0, 2))
    for i, rv in enumerate(reviewers + [r.choice(reviewers) for _ in extra]):
        topic = topics[i] if i < len(topics) else ("lgtm" if i < len(reviewers) else extra[i - len(reviewers)])
        when = x.ts("iso_s", tick=(3600, 86400))
        if topic == "logging":
            view += [F(rv.user, " commented on src/customers/export.py line ", x.num(lo=30, hi=120), " • ", when),
                     "  > logger.info(\"export requested by %s\", request.user.email)", "  " + _review_comment(d, rv, topic), ""]
        else:
            view += [F(rv.user, " commented • ", when), "  " + _review_comment(d, rv, topic), ""]
        if topic == "fixture" and r.random() < 0.6:
            view += [F(author.user, " commented • ", x.ts("iso_s", tick=(600, 7200))),
                     "  " + d.Lp(d.lang_of(author.p) if author.p else "en",
                                 en="Good catch, it was copied from the staging admin. Will replace.",
                                 it="Giusto, l'avevo copiato dall'admin di staging. Lo sostituisco.",
                                 de="Guter Punkt, das habe ich aus dem Staging-Admin kopiert. Ersetze ich.",
                                 fr="Bien vu, je l'avais copié depuis l'admin de staging. Je remplace.",
                                 es="Bien visto, lo copié del admin de staging. Lo cambio."), ""]
    d.tool("sh", F("gh pr view ", x.num(num), " --comments"), lines(*view))
    if r.random() < 0.5:
        checks = []
        for name in r.sample(["lint", "unit-tests", "integration-tests", "build-image", "sonar", "secret-scan"], r.randint(3, 5)):
            state = r.choice(["pass", "pass", "pass", "fail"])
            checks.append([name, state, f"{r.randint(0, 9)}m{r.randint(1, 59)}s",
                           g.url("internal", path=f"/job/{d.project}/{r.randint(100, 9999)}/")])
        d.tool("sh", F("gh pr checks ", x.num(num)), table(checks, gap=2))
    fx = "tests/fixtures/export_customer.json"
    diff = ["diff --git a/src/customers/export.py b/src/customers/export.py", T("index ⟦a⟧..⟦b⟧ 100644", a=x.short(9), b=x.short(9)),
            "--- a/src/customers/export.py", "+++ b/src/customers/export.py", T("@@ -⟦a⟧,6 +⟦a⟧,24 @@", a=x.num(lo=20, hi=80)),
            "+@router.get(\"/v1/customers/{customer_id}/export\")",
            "+def export_customer(customer_id: str, request: Request):",
            "+    logger.info(\"export requested by %s\", request.user.email)",
            "+    customer = repo.get(customer_id)",
            "+    payload = serialize_full(customer)",
            "+    return JSONResponse(payload)",
            f"diff --git a/{fx} b/{fx}", "new file mode 100644", T("index 0000000..⟦h⟧", h=x.short(7)), "--- /dev/null",
            f"+++ b/{fx}", T("@@ -0,0 +1,⟦n⟧ @@", n=x.num(len(sample) - 2))]
    diff += [F("+", row) for row in sample[1:-1]]
    d.tool("sh", F("gh pr diff ", x.num(num)), lines(*diff))
    d.agent(d.L(en="Two actionable comments: drop the e-mail from the log line, and replace the copied staging customer in the fixture (and in the PR description). I'll do both.",
                it="Due commenti da sistemare: togliere l'e-mail dalla riga di log e sostituire il cliente di staging copiato nella fixture (e nella descrizione della PR). Faccio entrambe le cose.",
                de="Zwei umsetzbare Kommentare: die E-Mail aus der Logzeile entfernen und den kopierten Staging-Kunden in der Fixture (und in der PR-Beschreibung) ersetzen. Ich mache beides.",
                fr="Deux commentaires à traiter : retirer l'e-mail de la ligne de log et remplacer le client de staging copié dans la fixture (et dans la description de la PR). Je fais les deux.",
                es="Dos comentarios a resolver: quitar el e-mail de la línea de log y sustituir el cliente de staging copiado en el fixture (y en la descripción de la PR). Hago ambas cosas."))
    d.tool("edit", "src/customers/export.py",
           lines("@@", "-    logger.info(\"export requested by %s\", request.user.email)",
                 "+    logger.info(\"export requested by user_id=%s\", request.user.id)"))
    fake = ["{", T('  "customer_id": "⟦c⟧",', c=x.ph("generic", "CUST-0000000")), T('  "name": "⟦n⟧",', n=x.ph("name")),
            T('  "email": "⟦e⟧",', e=x.ph("email")), T('  "phone": "⟦p⟧",', p=x.ph("phone")),
            T('  "address": "⟦a⟧",', a=x.ph("address")), T('  "created_at": "⟦t⟧",', t=x.ts("iso_s")), '  "orders": 3', "}"]
    d.tool("write", fx, lines(*fake))
    d.tool("sh", "python -m pytest -q tests/customers",
           lines(T("⟦n⟧ passed in ⟦s⟧s", n=x.num(lo=8, hi=60), s=f"{r.uniform(0.5, 6):.2f}")))
    rv0 = reviewers[0]
    reply = d.L(en="Replaced the sample customer with placeholder data and removed the e-mail from the log line. Also edited the PR description.",
                it="Ho sostituito il cliente di esempio con dati segnaposto e tolto l'e-mail dal log. Aggiornata anche la descrizione della PR.",
                de="Den Beispielkunden durch Platzhalterdaten ersetzt und die E-Mail aus der Logzeile entfernt. PR-Beschreibung ebenfalls angepasst.",
                fr="Client d'exemple remplacé par des données factices et e-mail retiré de la ligne de log. Description de la PR mise à jour aussi.",
                es="He sustituido el cliente de ejemplo por datos ficticios y quitado el e-mail del log. También he editado la descripción de la PR.")
    d.tool("sh", F("gh pr comment ", x.num(num), ' --body "', rv0.handle, " ", reply, '"'),
           F(g.raw("private_url", f"https://github.com/{_repo_path(d)}/pull/{num}#issuecomment-{r.randint(10**9, 3 * 10**9)}", "url"), "\n"))
    if d.gold_ok:
        d.agent(say(d, "pii_warning"))
    left = (["limit"] if "limit" in topics else []) + extra
    d.agent(say(d, "done"), "\n",
            d.L(en="- log line no longer contains the e-mail\n- fixture uses placeholders\n- replied on the PR",
                it="- la riga di log non contiene più l'e-mail\n- la fixture usa segnaposto\n- risposto sulla PR",
                de="- Logzeile enthält keine E-Mail mehr\n- Fixture nutzt Platzhalter\n- auf der PR geantwortet",
                fr="- la ligne de log ne contient plus l'e-mail\n- la fixture utilise des placeholders\n- réponse postée sur la PR",
                es="- la línea de log ya no contiene el e-mail\n- el fixture usa placeholders\n- respondido en la PR"),
            F("\n", d.L(en="- left for a follow-up: ", it="- rimandati a un follow-up: ", de="- für ein Follow-up offen: ",
                         fr="- laissés pour un suivi : ", es="- pendientes para un follow-up: "),
              ", ".join({"limit": "streaming", "naming": "naming", "auth": "authorization"}[t] for t in left)) if left else "")


# ---------------------------------------------------------------- 10. purge a leaked file from history


@template("git_filter_repo_purge", "tslog", "git", "shell")
def git_filter_repo_purge(d):
    g, x, r = d.g, d.x, d.rng
    leak = r.choice(["config/secrets.json", "secrets.json", "deploy/credentials.json", ".secrets/prod.json"])
    d.user(T(d.L(
        en="We committed ⟦f⟧ months ago and deleted it later, but it's still in the history. Can you purge it? The repo is shared with a few people.",
        it="Mesi fa abbiamo committato ⟦f⟧ e poi l'abbiamo cancellato, ma è ancora nella history. Puoi eliminarlo del tutto? Il repo è condiviso con alcune persone.",
        de="Wir haben vor Monaten ⟦f⟧ committet und später gelöscht, aber es steckt noch in der History. Kannst du es entfernen? Ein paar Leute arbeiten mit dem Repo.",
        fr="On a committé ⟦f⟧ il y a des mois puis on l'a supprimé, mais il est toujours dans l'historique. Tu peux le purger ? Le dépôt est partagé avec quelques personnes.",
        es="Hace meses subimos ⟦f⟧ y luego lo borramos, pero sigue en el historial. ¿Puedes purgarlo? El repo lo usan varias personas."),
        f=leak))
    devs = _team(d, r.randint(3, 6))
    n = r.randint(2, 4)
    hist = [(_sha(d), _subject(d)[1]) for _ in range(n)]
    hist[0] = (hist[0][0], F(f"chore: remove {leak}"))
    d.tool("sh", F("git log --all --oneline -- ", leak), lines(*[F(x.id(h[:7]), " ", s) for h, s in hist]))
    sha = hist[-1][0]
    contact = d.person()
    js = ["{", '  "database": {', T('    "host": "⟦ip⟧",', ip=g.ip("private")), T('    "port": ⟦p⟧,', p=x.port(5432)),
          '    "user": "app",', T('    "password": "⟦p⟧"', p=g.password()), "  },",
          T('  "stripe_secret_key": "⟦k⟧",', k=g.secret("stripe_live")),
          '  "aws": {', T('    "access_key_id": "⟦k⟧",', k=g.secret("aws_akid")),
          T('    "secret_access_key": "⟦k⟧"', k=g.secret("aws_secret")), "  },"]
    if r.random() < 0.6:
        js += [T('  "sendgrid_api_key": "⟦k⟧",', k=g.secret("sendgrid"))]
    if r.random() < 0.5:
        js += [T('  "jwt_signing_key": "⟦k⟧",', k=g.secret("hex32"))]
    js += ['  "ops_contact": {', T('    "name": "⟦n⟧",', n=g.name(contact)), T('    "email": "⟦e⟧",', e=g.email(contact, "work")),
           T('    "phone": "⟦p⟧"', p=g.phone(contact, True)), "  }", "}"]
    d.tool("sh", F("git show ", x.id(sha[:7]), ":", leak), lines(*js))
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x=leak), " ",
                d.L(en="Rewriting history does not undo the exposure: every clone and fork still has these values, so rotation is mandatory regardless.",
                    it="Riscrivere la history non annulla l'esposizione: ogni clone e fork ha ancora questi valori, quindi la rotazione è obbligatoria in ogni caso.",
                    de="Das Umschreiben der History macht die Offenlegung nicht rückgängig: Jeder Clone und Fork hat die Werte noch, rotieren ist also Pflicht.",
                    fr="Réécrire l'historique n'annule pas l'exposition : chaque clone et fork a encore ces valeurs, la rotation est donc obligatoire.",
                    es="Reescribir el historial no deshace la exposición: cada clon y fork sigue teniendo estos valores, así que la rotación es obligatoria igualmente."))
    commits = r.randint(300, 4800)
    d.tool("sh", F("git filter-repo --invert-paths --path ", leak, " --force"),
           lines(T("Parsed ⟦n⟧ commits", n=x.num(commits)),
                 T("New history written in ⟦s⟧ seconds; now repacking/cleaning...", s=f"{r.uniform(0.6, 9):.2f}"),
                 "Repacking your repo and cleaning out old unneeded objects",
                 F("HEAD is now at ", x.id(_sha(d)[:7]), " ", _subject(d)[1]),
                 T("Enumerating objects: ⟦n⟧, done.", n=x.num(lo=2000, hi=90000)),
                 T("Counting objects: 100% (⟦n⟧/⟦n⟧), done.", n=x.num(lo=2000, hi=90000)),
                 T("Compressing objects: 100% (⟦n⟧/⟦n⟧), done.", n=x.num(lo=500, hi=30000)),
                 T("Total ⟦n⟧ (delta ⟦m⟧), reused ⟦n⟧ (delta ⟦m⟧), pack-reused 0", n=x.num(lo=2000, hi=90000), m=x.num(lo=500, hi=50000)),
                 T("Completely finished after ⟦s⟧ seconds.", s=f"{r.uniform(1, 25):.2f}")))
    d.tool("sh", F("git log --all --oneline -- ", leak, " | wc -l"), F("0\n"))
    d.agent(d.L(en="History is clean locally. Pushing requires a force-push, and everyone with a clone must re-clone, otherwise the file comes back with their next push. Let me list who has been active on the repo.",
                it="La history locale è pulita. Per pubblicarla serve un force-push, e chiunque abbia un clone deve riclonare, altrimenti il file torna al loro prossimo push. Vediamo chi è stato attivo sul repo.",
                de="Lokal ist die History sauber. Zum Veröffentlichen braucht es einen Force-Push, und alle mit einem Clone müssen neu klonen, sonst kommt die Datei beim nächsten Push zurück. Ich schaue, wer auf dem Repo aktiv war.",
                fr="L'historique local est propre. Il faut un force-push, et tous ceux qui ont un clone doivent recloner, sinon le fichier reviendra à leur prochain push. Je regarde qui a été actif sur le dépôt.",
                es="El historial local está limpio. Hace falta un force-push y todo el que tenga un clon debe volver a clonar, si no el fichero vuelve con su siguiente push. Miro quién ha estado activo en el repo."))
    rows = [F(dv.name, " <", dv.email, ">") for dv in sorted(devs, key=lambda dv: dv.name.text)]
    d.tool("sh", "git log --since='6 months ago' --format='%an <%ae>' | sort -u", lines(*rows))
    if not d.clean and r.random() < 0.7:
        d.tool("sh", F("gh api repos/", _repo_path(d), "/collaborators --jq '.[].login'"), lines(*[dv.user for dv in devs]))
    note = [d.L(en="Draft notice for the team:", it="Bozza di avviso per il team:", de="Entwurf für die Info ans Team:",
                fr="Brouillon du message pour l'équipe :", es="Borrador del aviso para el equipo:"), "",
            F("To: ", J(", ", [dv.email for dv in devs])),
            F("Subject: [", d.project, "] history rewritten — please re-clone"), "",
            d.L(en=f"Hi all, {leak} was removed from the whole history. Please delete your local clone and clone again before pushing anything. Do not merge old branches back.",
                it=f"Ciao a tutti, {leak} è stato rimosso da tutta la history. Cancellate il vostro clone locale e riclonate prima di fare push. Non rimergiate branch vecchi.",
                de=f"Hallo zusammen, {leak} wurde aus der gesamten History entfernt. Bitte lokalen Clone löschen und neu klonen, bevor ihr etwas pusht. Alte Branches bitte nicht wieder mergen.",
                fr=f"Bonjour à tous, {leak} a été retiré de tout l'historique. Supprimez votre clone local et reclonez avant de pousser quoi que ce soit. Ne remergez pas d'anciennes branches.",
                es=f"Hola a todos, {leak} se ha eliminado de todo el historial. Borrad vuestro clon local y volved a clonar antes de hacer push. No volváis a mergear ramas antiguas.")]
    d.agent(J("\n", note))
    if r.random() < 0.6:
        d.user(d.L(en="Ok, force push it.", it="Ok, fai il force push.", de="Ok, force-push.", fr="Ok, force-push.",
                   es="Vale, haz el force push."))
        d.tool("sh", "git push origin --force --all && git push origin --force --tags",
               lines(F("To ", _repo_url(d)),
                     T(" + ⟦a⟧...⟦b⟧ main -> main (forced update)", a=x.id(_sha(d)[:7]), b=x.id(_sha(d)[:7])),
                     T(" + ⟦a⟧...⟦b⟧ develop -> develop (forced update)", a=x.id(_sha(d)[:7]), b=x.id(_sha(d)[:7]))))
        d.agent(say(d, "done"), "\n", d.L(en="- history rewritten and force-pushed\n- rotate the exposed keys and send the notice above",
                                           it="- history riscritta e force-push fatto\n- ruota le chiavi esposte e manda l'avviso qui sopra",
                                           de="- History umgeschrieben und force-gepusht\n- die offengelegten Keys rotieren und die Info oben verschicken",
                                           fr="- historique réécrit et force-pushé\n- renouvelle les clés exposées et envoie le message ci-dessus",
                                           es="- historial reescrito y con force push\n- rota las claves expuestas y envía el aviso de arriba"))
    else:
        d.user(d.L(en="I'll do the force push myself after the standup.", it="Il force push lo faccio io dopo lo standup.",
                   de="Den Force-Push mache ich selbst nach dem Standup.", fr="Je ferai le force-push moi-même après le standup.",
                   es="El force push lo hago yo después del standup."))


# ---------------------------------------------------------------- 11. mailing-list patch


@template("git_format_patch_email", "box", "git")
def git_format_patch_email(d):
    g, x, r = d.g, d.x, d.rng
    proj = r.choice(["tinycsv", "libdsv", "rowreader", "csvtool-ng", "quillcsv"])
    lst = f"{proj}-devel@lists.{proj}.org"
    me = _dev(d, d.me, "personal")
    d.user(T(d.L(
        en="I fixed the CRLF handling bug in our vendored ⟦p⟧. I'd like to send it upstream to their mailing list — can you prepare the patch and figure out who to Cc?",
        it="Ho corretto il bug sui CRLF nella copia vendorizzata di ⟦p⟧. Vorrei mandarlo upstream sulla loro mailing list: puoi preparare la patch e capire chi mettere in Cc?",
        de="Ich habe den CRLF-Bug in unserer vendorten Kopie von ⟦p⟧ behoben und möchte ihn upstream an die Mailingliste schicken — kannst du den Patch vorbereiten und herausfinden, wer in Cc gehört?",
        fr="J'ai corrigé le bug de gestion des CRLF dans notre copie de ⟦p⟧. J'aimerais l'envoyer upstream sur leur liste de diffusion : tu peux préparer le patch et voir qui mettre en Cc ?",
        es="He corregido el bug de los CRLF en nuestra copia de ⟦p⟧. Quiero enviarlo upstream a su lista de correo: ¿puedes preparar el parche y ver a quién poner en Cc?"),
        p=proj))
    slug = r.choice(["parser-skip-CR-before-LF-in-quoted-fields", "parser-handle-CRLF-line-endings", "reader-do-not-split-on-bare-CR"])
    fname = f"outgoing/0001-{slug}.patch"
    d.tool("sh", "git format-patch -1 HEAD -o outgoing/", F(fname, "\n"))
    sha = _sha(d)
    t = d.clock.tick(600, 7200)
    head, rest = slug.split("-", 1)
    subj = f"{head}: {rest.replace('-', ' ')}"
    reporter = d.person() if r.random() < 0.6 else None
    patch = [T("From ⟦h⟧ ⟦t⟧", h=x.id(sha), t=Seg("Mon Sep 17 00:00:00 2001", cls="machine_timestamp")),
             T("From: ⟦n⟧ <⟦e⟧>", n=me.name, e=me.email), T("Date: ⟦t⟧", t=x.ts("rfc2822", t=t, local=True)),
             f"Subject: [PATCH] {subj}", "",
             "A quoted field that spans lines written on Windows ends up with a",
             "stray '\\r' at the end of every line except the last, because the",
             "reader only strips CR when it is followed by LF outside quotes.", "",
             "Skip CR when the next byte is LF, regardless of the quoting state."]
    if reporter is not None:
        patch += ["", T("Reported-by: ⟦n⟧ <⟦e⟧>", n=g.name(reporter), e=g.email(reporter, "personal"))]
    patch += [T("Signed-off-by: ⟦n⟧ <⟦e⟧>", n=me.name, e=me.email), "---",
              T(" src/parser.c | ⟦n⟧ ++++++--", n=x.num(8)), " 1 file changed, 6 insertions(+), 2 deletions(-)", "",
              "diff --git a/src/parser.c b/src/parser.c", T("index ⟦a⟧..⟦b⟧ 100644", a=x.short(7), b=x.short(7)),
              "--- a/src/parser.c", "+++ b/src/parser.c",
              T("@@ -⟦a⟧,9 +⟦a⟧,13 @@ static int read_field(struct csv_reader *r, struct buf *out)", a=x.num(lo=120, hi=480)),
              " \tint c, in_quotes = 0;", " ", " \twhile ((c = next_char(r)) != EOF) {",
              "-\t\tif (c == '\\r' && !in_quotes)", "-\t\t\tcontinue;",
              "+\t\tif (c == '\\r') {", "+\t\t\tif (peek_char(r) == '\\n')", "+\t\t\t\tcontinue;",
              "+\t\t\tif (!in_quotes)", "+\t\t\t\tcontinue;", "+\t\t}",
              " \t\tif (c == '\"') {", " \t\t\tin_quotes = !in_quotes;", " \t\t\tcontinue;", "-- ",
              T("⟦v⟧", v=x.ver(f"2.{r.randint(39, 47)}.{r.randint(0, 3)}"))]
    d.tool("read", fname, lines(*patch))
    maint = [(d.person(), "M"), (d.person(), "M")] + [(d.person(), "R") for _ in range(r.randint(0, 2))]
    mt = ["List of maintainers", "===================", "", "CSV PARSER"]
    for p, role in maint:
        mt.append(F(f"{role}:\t", g.name(p), " <", g.email(p, "personal"), ">"))
    mt += [f"L:\t{lst}", "S:\tMaintained", "F:\tsrc/parser.c", "F:\tsrc/reader.c", "", "DOCUMENTATION"]
    doc_m = d.person()
    mt += [F("M:\t", g.name(doc_m), " <", g.email(doc_m, "personal"), ">"), f"L:\t{lst}", "S:\tOdd fixes", "F:\tdocs/"]
    d.tool("read", f"vendor/{proj}/MAINTAINERS", lines(*mt))
    d.agent(d.L(en="The parser section lists two maintainers and the reviewers; I'll Cc them and send to the list. Dry run first.",
                it="La sezione del parser elenca due maintainer e i reviewer; li metto in Cc e mando alla lista. Prima un dry run.",
                de="Für den Parser sind zwei Maintainer und die Reviewer eingetragen; die setze ich in Cc und schicke an die Liste. Erst ein Dry-Run.",
                fr="La section du parser liste deux mainteneurs et les relecteurs ; je les mets en Cc et j'envoie à la liste. D'abord un dry run.",
                es="La sección del parser lista dos maintainers y los revisores; los pongo en Cc y envío a la lista. Primero un dry run."))
    cc_lines = [F("(mbox) Adding cc: ", me.name, " <", me.email, "> from line 'From: ", me.name, " <", me.email, ">'")]
    if reporter is not None:
        cc_lines.append(F("(body) Adding cc: ", g.name(reporter), " <", g.email(reporter, "personal"), "> from line 'Reported-by: ",
                          g.name(reporter), " <", g.email(reporter, "personal"), ">'"))
    cc_lines.append(F("(body) Adding cc: ", me.name, " <", me.email, "> from line 'Signed-off-by: ", me.name, " <", me.email, ">'"))
    ccs = []
    for p, _ in maint:
        nm, em = g.name(p), g.email(p, "personal")
        ccs.append((nm, em))
        cc_lines.append(F("(cc-cmd) Adding cc: ", nm, " <", em, "> from: 'scripts/get_maintainer.sh'"))
    t2 = d.clock.tick(30, 600)
    msgid_ts = x.id(f"{t2:%Y%m%d%H%M%S}.{r.randint(1000, 99999)}-1")
    dry = [fname] + cc_lines + ["Dry-OK. Log says:",
                                F("Sendmail: /usr/sbin/sendmail -i ", lst, " ", J(" ", [em for _, em in ccs])),
                                F("From: ", me.name, " <", me.email, ">"), f"To: {lst}",
                                F("Cc: ", J(",\n    ", [F(nm, " <", em, ">") for nm, em in ccs])),
                                f"Subject: [PATCH] {subj}", T("Date: ⟦t⟧", t=x.ts("rfc2822", t=t2, local=True)),
                                F("Message-ID: <", msgid_ts, "-", me.email, ">"),
                                T("X-Mailer: git-send-email ⟦v⟧", v=x.ver(f"2.{r.randint(39, 47)}.{r.randint(0, 3)}")),
                                "MIME-Version: 1.0", "Content-Transfer-Encoding: 8bit", "", "Result: OK"]
    d.tool("sh", F("git send-email --dry-run --to=", lst, " --cc-cmd=scripts/get_maintainer.sh ", fname), lines(*dry))
    d.agent(d.L(en="Dry run looks right. Want me to send it for real, or do you prefer to review the text first?",
                it="Il dry run è corretto. Vuoi che la invii davvero o preferisci rileggere prima il testo?",
                de="Der Dry-Run sieht gut aus. Soll ich ihn wirklich verschicken, oder willst du den Text erst lesen?",
                fr="Le dry run est bon. Je l'envoie pour de vrai, ou tu préfères relire le texte d'abord ?",
                es="El dry run está bien. ¿Lo envío de verdad o prefieres revisar antes el texto?"))
    d.user(d.L(en="I'll read it once more and send it myself, thanks.",
                                                    it="La rileggo un'altra volta e la mando io, grazie.",
                                                    de="Ich lese ihn nochmal und schicke ihn selbst, danke.",
                                                    fr="Je le relis encore une fois et je l'envoie moi-même, merci.",
                                                    es="Lo releo una vez más y lo envío yo, gracias."))
