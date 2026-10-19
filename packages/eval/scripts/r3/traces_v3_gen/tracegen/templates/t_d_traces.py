# SPDX-License-Identifier: Apache-2.0
"""Templates centred on stack traces and test-runner output."""

from __future__ import annotations

import datetime as dt

from .. import values as V
from ..core import F, J, T, Seg, esc_json, grid, lines, numbered, table
from ..phrases import say
from . import template

# ---------------------------------------------------------------- private helpers


def _ok(d, label: str) -> bool:
    return d.secret_ok if label == "secret" else d.gold_ok


def _gv(d, label: str, value: str, ph_text: str) -> Seg:
    """Gold value, or a fixed stand-in (tagged placeholder) when the mode forbids it."""
    if _ok(d, label):
        return Seg(value, label=label)
    return d.x.ph(text=ph_text)


def _pair(d, label: str, a: str, b: str, ph_a: str, ph_b: str | None = None) -> tuple[Seg, Seg]:
    """Two renderings of the same value (e.g. electronic and printed IBAN)."""
    if _ok(d, label):
        return Seg(a, label=label), Seg(b, label=label)
    return d.x.ph(text=ph_a), d.x.ph(text=ph_b or ph_a)


def _mts(text: str) -> Seg:
    return Seg(text, cls="machine_timestamp")


def _now(d, lo: float = 0.0, hi: float = 2.0) -> dt.datetime:
    return d.clock.local(d.clock.tick(lo, hi))


def _off_colon(t: dt.datetime) -> str:
    z = t.strftime("%z") or "+0000"
    return z[:3] + ":" + z[3:]


def _pyval(v) -> list:
    """Python repr of a string value that may be a Seg."""
    if isinstance(v, Seg):
        q = '"' if "'" in v.text else "'"
        return F(q, v, q)
    if isinstance(v, (list, tuple)):
        return F("'", v, "'")
    if isinstance(v, int):
        return F(str(v))
    return F(repr(v))


def _pydict(items: list) -> list:
    return F("{", J(", ", [F(repr(k), ": ", _pyval(v)) for k, v in items]), "}")


def _iban_pair(d, p) -> tuple[Seg, Seg]:
    raw = V.iban(d.rng, V.IBAN_COUNTRY_OF[p.country])
    return _pair(d, "account_number", raw, V.iban_print(raw), "DE00000000000000000000", "DE00 0000 0000 0000 0000 00")


def _hexaddr(d) -> str:
    return "0x7f" + V.rand_str(d.rng, V.HEX, 10)


_ADDR_PH = {
    "street_full": ["123 Main Street", "Musterstraße 1", "Via Roma 1", "1 rue de l'Exemple"],
    "street": ["123 Main Street", "Musterstraße 1", "Via Roma 1", "1 rue de l'Exemple"],
    "postcode": ["00000", "12345", "AB1 2CD"],
    "city": ["Anytown", "Musterstadt", "Springfield", "Exampleville"],
    "city_line": ["Anytown, ST 00000", "12345 Musterstadt", "00000 Città"],
}


def _addr(d, p, form: str) -> Seg:
    """Address part; in a clean document a stand-in of the same shape."""
    if d.gold_ok and not p.placeholder:
        return d.g.addr(p, form)
    if form == "oneline":
        return d.g.addr(p, form)
    return d.x.ph(text=d.rng.choice(_ADDR_PH[form]))


# ================================================================ 1. pytest -l


@template("pytest_showlocals", "box", "trace")
def pytest_showlocals(d):
    g, x, r = d.g, d.x, d.rng
    p = d.person()
    iban_e, iban_p = _iban_pair(d, p)
    name, email, birth, cust, city = g.name(p), g.email(p, "personal"), g.birth(p, "iso"), g.cust(), _addr(d, p, "city")
    test = r.choice(["test_export_row_format", "test_csv_row_matches_bank_layout", "test_sepa_export_line"])
    tfile = r.choice(["tests/test_export.py", "tests/unit/test_exporter.py"])
    lineno = r.randint(30, 140)
    n_total = r.randint(6, 34)
    pyver = r.choice(["3.11.9", "3.12.3", "3.12.4", "3.13.0"])
    ticket = x.id(f"SUP-{r.randint(1000, 9999)}")
    d.user(d.L(
        en=f"{test} fails since the IBAN formatting change landed. Can you take a look? Run it with -l so we see the locals.",
        it=f"{test} fallisce da quando è entrato il cambio sulla formattazione dell'IBAN. Ci dai un'occhiata? Lancialo con -l così vediamo le variabili locali.",
        de=f"{test} schlägt fehl, seit die Änderung an der IBAN-Formatierung drin ist. Schaust du mal? Bitte mit -l laufen lassen, damit wir die Locals sehen.",
        fr=f"{test} échoue depuis le changement sur le formatage de l'IBAN. Tu peux regarder ? Lance-le avec -l pour voir les variables locales.",
        es=f"{test} falla desde que entró el cambio del formato del IBAN. ¿Le echas un vistazo? Lánzalo con -l para ver las variables locales."))
    cust_items = [("customer_no", cust), ("name", name), ("email", email), ("iban", iban_e), ("birth_date", birth),
                  ("city", city)]
    if r.random() < 0.5:
        cust_items.insert(3, ("phone", g.phone(p, intl=True)))
    sorted_items = sorted(cust_items, key=lambda kv: kv[0])
    row_got = F(cust, ";", name, ";", email, ";", iban_p, ";", birth)
    row_exp = F(cust, ";", name, ";", email, ";", iban_e, ";", birth)
    addr = _hexaddr(d)
    before = r.randint(1, n_total - 1)
    dots = "." * before
    after = ""
    out = [
        "============================= test session starts ==============================\n",
        T("platform ⟦os⟧ -- Python ⟦pv⟧, pytest-⟦ptv⟧, pluggy-⟦plv⟧\n", os=r.choice(["linux", "darwin"]),
          pv=x.ver(pyver), ptv=x.ver(r.choice(["8.2.1", "8.3.2", "8.3.3"])), plv=x.ver("1.5.0")),
        T("rootdir: ⟦cwd⟧\n", cwd=d.cwd()),
        "configfile: pyproject.toml\n",
    ]
    if r.random() < 0.6:
        out.append(T("plugins: cov-⟦a⟧, mock-⟦b⟧\n", a=x.ver("5.0.0"), b=x.ver("3.14.0")))
    out += [
        f"collected {n_total} items\n\n",
        f"{tfile} {dots}F{after}\n\n",
        "=================================== FAILURES ===================================\n",
        f"{('_' * 20)} {test} {('_' * 20)}\n\n",
        T("customer = ⟦c⟧\nexporter = <app.export.CsvExporter object at ⟦a⟧>\n\n", c=_pydict(sorted_items), a=x.id(addr)),
        f"    def {test}(customer, exporter):\n",
        "        row = exporter.format_row(customer)\n",
        ">       assert row == expected_row(customer)\n",
        T("E       AssertionError: assert '⟦got⟧' == '⟦exp⟧'\n", got=row_got, exp=row_exp),
        "E         \n",
        T("E         - ⟦exp⟧\n", exp=row_exp),
        T("E         + ⟦got⟧\n\n", got=row_got),
        T("customer   = ⟦c⟧\n", c=_pydict(sorted_items)),
        T("exporter   = <app.export.CsvExporter object at ⟦a⟧>\n", a=x.id(addr)),
        T("row        = '⟦got⟧'\n\n", got=row_got),
        T("⟦f⟧:⟦n⟧: AssertionError\n", f=tfile, n=x.num(lineno)),
        "=========================== short test summary info ============================\n",
        f"FAILED {tfile}::{test} - AssertionError: assert ...\n",
        "!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!\n",
        T("========================= 1 failed, ⟦ok⟧ passed in ⟦s⟧s ==========================\n",
          ok=str(before + len(after)), s=f"{r.uniform(0.3, 3.9):.2f}"),
    ]
    d.tool("sh", f"pytest {tfile} -l -x", F(*out))
    d.agent(d.L(en="The row now contains the IBAN in print format (groups of four) while the expected value is the electronic format. Let me look at the fixture and the exporter.",
                it="La riga ora contiene l'IBAN in formato cartaceo (gruppi da quattro) mentre il valore atteso è in formato elettronico. Guardo la fixture e l'exporter.",
                de="Die Zeile enthält die IBAN jetzt im Papierformat (Vierergruppen), erwartet wird aber das elektronische Format. Ich schaue mir Fixture und Exporter an.",
                fr="La ligne contient maintenant l'IBAN au format papier (groupes de quatre) alors que la valeur attendue est au format électronique. Je regarde la fixture et l'exporteur.",
                es="La fila ahora lleva el IBAN en formato impreso (grupos de cuatro) y lo esperado es el formato electrónico. Miro el fixture y el exportador."))
    comment = (T("# copied from ⟦t⟧ to reproduce the bank rejection — TODO anonymise", t=ticket) if not d.clean
               else F("# sample customer"))
    fixture_rows = [F(f'        "{k}": ', '"', v, '",') for k, v in cust_items]
    conftest = F(
        "import pytest\n\nfrom app.export import CsvExporter\n\n\n@pytest.fixture\ndef exporter():\n",
        '    return CsvExporter(delimiter=";", date_format="%Y-%m-%d")\n\n\n@pytest.fixture\ndef customer():\n',
        "    ", comment, "\n    return {\n", J("\n", fixture_rows), "\n    }\n")
    d.tool("read", "tests/conftest.py", conftest)
    l1, l2 = r.randint(8, 20), r.randint(30, 70)
    d.tool("grep", 'iban app/export.py',
           T("⟦a⟧:from app.banking import format_iban\n⟦b⟧:            iban=format_iban(c[\"iban\"]),\n",
             a=x.num(l1), b=x.num(l2)))
    fix_in_exporter = r.random() < 0.6
    if fix_in_exporter:
        d.agent(d.L(en="The bank layout wants the electronic IBAN; format_iban() is meant for display only. I'll stop using it in the CSV exporter.",
                    it="Il tracciato della banca vuole l'IBAN elettronico; format_iban() serve solo per la visualizzazione. Lo tolgo dall'exporter CSV.",
                    de="Das Bankformat verlangt die elektronische IBAN; format_iban() ist nur für die Anzeige gedacht. Ich entferne es aus dem CSV-Exporter.",
                    fr="Le format de la banque exige l'IBAN électronique ; format_iban() ne sert qu'à l'affichage. Je le retire de l'exporteur CSV."))
        d.tool("edit", "app/export.py",
               T("@@ -⟦n⟧,7 +⟦n⟧,7 @@\n-            iban=format_iban(c[\"iban\"]),\n+            iban=c[\"iban\"].replace(\" \", \"\").upper(),\n",
                 n=x.num(l2 - 3)))
    else:
        d.agent(d.L(en="The new grouped format is what the bank portal accepts now (see the ticket), so the test helper is outdated. Updating expected_row().",
                    it="Il nuovo formato a gruppi è quello che il portale della banca accetta ora (vedi ticket), quindi è l'helper del test a essere vecchio. Aggiorno expected_row().",
                    de="Das neue gruppierte Format akzeptiert das Bankportal inzwischen (siehe Ticket), also ist der Test-Helper veraltet. Ich passe expected_row() an.",
                    fr="Le nouveau format groupé est celui qu'accepte désormais le portail bancaire (voir le ticket), c'est donc le helper de test qui est obsolète. Je mets à jour expected_row()."))
        d.tool("edit", tfile, T("-    return \";\".join([c[\"customer_no\"], c[\"name\"], c[\"email\"], c[\"iban\"], c[\"birth_date\"]])\n"
                                "+    return \";\".join([c[\"customer_no\"], c[\"name\"], c[\"email\"], format_iban(c[\"iban\"]), c[\"birth_date\"]])\n"))
    d.tool("sh", f"pytest {tfile} -q", T("⟦n⟧ passed in ⟦s⟧s\n", n=str(n_total), s=f"{r.uniform(0.3, 3.9):.2f}"))
    if d.gold_ok and r.random() < 0.7:
        d.agent(say(d, "pii_warning"), " ", d.L(en="The customer fixture looks like real data; want me to swap it for obvious fake values?",
                                                 it="La fixture del cliente sembra contenere dati reali; vuoi che la sostituisca con valori palesemente finti?",
                                                 de="Die Kunden-Fixture sieht nach echten Daten aus; soll ich sie durch offensichtliche Dummy-Werte ersetzen?",
                                                 fr="La fixture client ressemble à de vraies données ; tu veux que je la remplace par des valeurs manifestement fictives ?",
                                                 es="El fixture del cliente parece contener datos reales; ¿lo cambio por valores claramente ficticios?"))
        d.user(say(d, "go_ahead"))
        new_rows = [("name", x.ph("name", r.choice(["Jane Doe", "Max Mustermann", "Mario Rossi"]))),
                    ("email", x.ph("email", "jane.doe@example.com")),
                    ("iban", x.ph("iban", "DE00 0000 0000 0000 0000 00")),
                    ("birth_date", x.ph("date", "1970-01-01"))]
        diff = []
        for k, v in cust_items:
            if k in ("name", "email", "iban", "birth_date"):
                nv = dict(new_rows)[k]
                diff.append(F(f'-        "{k}": "', v, '",\n'))
                diff.append(F(f'+        "{k}": "', nv, '",\n'))
        d.tool("edit", "tests/conftest.py", F(*diff))
    d.agent(say(d, "done"), "\n- ", d.L(en="exporter/test aligned on one IBAN format", it="exporter e test allineati su un unico formato IBAN",
                                         de="Exporter und Test nutzen jetzt dasselbe IBAN-Format", fr="exporteur et test alignés sur un seul format d'IBAN",
                                         es="exportador y test alineados con un único formato de IBAN"),
            "\n- ", say(d, "not_committed"))


# ================================================================ 2. jest snapshot


@template("jest_snapshot_user", "hai", "trace")
def jest_snapshot_user(d):
    g, x, r = d.g, d.x, d.rng
    p = d.person()
    bug = r.random() < 0.45
    runner = r.choice(["npx jest", "pnpm jest", "yarn jest"])
    spec = r.choice(["src/components/ProfileCard.test.tsx", "src/features/account/ProfileCard.test.tsx"])
    name, email = g.name(p), g.email(p, r.choice(["work", "personal"]))
    if d.gold_ok:
        ph_fmt = V.phone_format(p, r, intl=True)
        compact = "".join(c for c in ph_fmt if c.isdigit() or c == "+")
        phone_a, phone_b = Seg(ph_fmt, label="private_phone"), Seg(compact, label="private_phone")
    else:
        phone_a, phone_b = x.ph(text="+1 555-0100"), x.ph(text="+15550100")
    one = g.addr(p)
    street, cityline = _addr(d, p, "street_full"), _addr(d, p, "city_line")
    joined = g.date(V.random_date(r, 2017, 2025), "iso", p)
    d.user(d.L(
        en=f"The ProfileCard snapshot test broke after I touched the address formatting. Should I just update the snapshot or is it a real bug?",
        it=f"Il test snapshot di ProfileCard si è rotto dopo che ho toccato la formattazione dell'indirizzo. Aggiorno lo snapshot o è un bug vero?",
        de=f"Der Snapshot-Test von ProfileCard ist kaputt, seit ich die Adressformatierung angefasst habe. Snapshot einfach aktualisieren oder ist das ein echter Bug?",
        fr=f"Le test snapshot de ProfileCard a cassé après ma modif du formatage d'adresse. Je mets juste à jour le snapshot ou c'est un vrai bug ?",
        es=f"El test de snapshot de ProfileCard se rompió al tocar el formato de la dirección. ¿Actualizo el snapshot o es un bug de verdad?"))
    d.agent(d.L(en="Let me run that suite and read the diff first.", it="Lancio la suite e leggo prima il diff.",
                de="Ich lasse die Suite laufen und lese zuerst den Diff.", fr="Je lance la suite et je lis d'abord le diff.",
                es="Lanzo la suite y leo primero el diff."))
    n_minus = 3 + (1 if bug else 0)
    n_plus = 5 + (1 if bug else 0)
    ln = r.randint(18, 40)
    diff = [
        T("    - Snapshot  - ⟦a⟧\n    + Received  + ⟦b⟧\n\n", a=str(n_minus), b=str(n_plus)),
        T("    @@ -⟦a⟧,15 +⟦a⟧,17 @@\n", a=str(r.randint(3, 9))),
        "          <h2\n            className=\"profile-card__name\"\n          >\n",
        T("            ⟦n⟧\n", n=name),
        "          </h2>\n          <a\n            className=\"profile-card__email\"\n",
        T("            href=\"mailto:⟦e⟧\"\n          >\n            ⟦e⟧\n          </a>\n", e=email),
    ]
    if bug:
        diff += [T("    -     <span className=\"profile-card__phone\">⟦a⟧</span>\n", a=phone_a),
                 T("    +     <span className=\"profile-card__phone\">⟦b⟧</span>\n", b=phone_b)]
    else:
        diff += [T("          <span className=\"profile-card__phone\">⟦a⟧</span>\n", a=phone_a)]
    diff += [
        "    -     <address>\n", T("    -       ⟦o⟧\n", o=one), "    -     </address>\n",
        "    +     <address>\n", T("    +       ⟦s⟧\n", s=street), "    +       <br />\n",
        T("    +       ⟦c⟧\n", c=cityline), "    +     </address>\n",
    ]
    out = F(
        T(" FAIL  ⟦s⟧\n", s=spec),
        "  ProfileCard\n",
        T("    ✓ renders avatar initials (⟦a⟧ ms)\n", a=str(r.randint(8, 60))),
        T("    ✕ renders contact block (⟦a⟧ ms)\n", a=str(r.randint(20, 90))),
        "    ✓ hides phone when not shared (12 ms)\n" if r.random() < 0.5 else "",
        "\n  ● ProfileCard › renders contact block\n\n    expect(received).toMatchSnapshot()\n\n",
        "    Snapshot name: `ProfileCard renders contact block 1`\n\n",
        *diff,
        T("\n      ⟦a⟧ |   it(\"renders contact block\", () => {\n", a=str(ln - 2)),
        T("      ⟦a⟧ |     const { asFragment } = render(<ProfileCard user={user} />);\n", a=str(ln - 1)),
        T("    > ⟦a⟧ |     expect(asFragment()).toMatchSnapshot();\n", a=x.num(ln)),
        "         |                          ^\n",
        T("      ⟦a⟧ |   });\n\n", a=str(ln + 1)),
        T("      at Object.toMatchSnapshot (⟦s⟧:⟦n⟧:26)\n\n", s=spec, n=x.num(ln)),
        " › 1 snapshot failed.\nSnapshot Summary\n",
        " › 1 snapshot failed from 1 test suite. Inspect your code changes or run `npm test -- -u` to update them.\n\n",
        "Test Suites: 1 failed, 1 total\nTests:       1 failed, 1 passed, 2 total\n",
        "Snapshots:   1 failed, 1 total\n",
        T("Time:        ⟦t⟧ s\nRan all test suites matching /ProfileCard/i.\n", t=f"{r.uniform(1.1, 6.5):.3f}"),
    )
    d.tool("sh", f"{runner} {spec}", out)
    uid = x.id("usr_" + V.rand_str(r, V.ALNUM, 12)) if r.random() < 0.5 else g.cust()
    fixture = F(
        'import { render } from "@testing-library/react";\n', 'import { ProfileCard } from "./ProfileCard";\n\n',
        "const user = {\n", T('  id: "⟦u⟧",\n', u=uid), T('  name: "⟦n⟧",\n', n=name), T('  email: "⟦e⟧",\n', e=email),
        T('  phone: "⟦p⟧",\n', p=phone_a), "  address: {\n",
        T('    street: "⟦s⟧",\n', s=street), T('    postcode: "⟦c⟧",\n', c=_addr(d, p, "postcode")),
        T('    city: "⟦c⟧",\n', c=_addr(d, p, "city")), f'    country: "{p.country}",\n', "  },\n",
        T('  memberSince: "⟦j⟧",\n', j=joined), "};\n\n", 'describe("ProfileCard", () => {\n',
        '  it("renders avatar initials", () => {\n', "    // ...\n  });\n\n",
        '  it("renders contact block", () => {\n',
        "    const { asFragment } = render(<ProfileCard user={user} />);\n",
        "    expect(asFragment()).toMatchSnapshot();\n  });\n});\n")
    if r.random() < 0.7 or d.gold_ok:
        d.tool("read", spec, fixture)
    if bug:
        d.agent(say(d, "explain"), "\n",
                d.L(en="The address change is intended, but the phone line is a regression: formatPhone() now strips the spaces because the new sanitiser runs before the display formatter. Snapshot update alone would hide that.",
                    it="Il cambio sull'indirizzo è voluto, ma la riga del telefono è una regressione: formatPhone() ora toglie gli spazi perché il nuovo sanitizer gira prima del formatter. Aggiornare solo lo snapshot nasconderebbe il problema.",
                    de="Die Adressänderung ist gewollt, die Telefonzeile aber eine Regression: formatPhone() entfernt jetzt die Leerzeichen, weil der neue Sanitizer vor dem Formatter läuft. Nur den Snapshot zu aktualisieren würde das verdecken.",
                    fr="Le changement d'adresse est voulu, mais la ligne du téléphone est une régression : formatPhone() supprime maintenant les espaces car le nouveau sanitizer passe avant le formateur. Mettre à jour le snapshot masquerait le problème."))
        d.tool("edit", "src/utils/formatPhone.ts",
               F("-  const digits = sanitize(raw);\n-  return digits;\n",
                 "+  const parsed = parsePhoneNumber(sanitize(raw), defaultCountry);\n+  return parsed ? parsed.formatInternational() : raw;\n"))
    else:
        d.agent(say(d, "explain"), "\n",
                d.L(en="Only the <address> block changed, and that's exactly the multi-line rendering you introduced. It's an intended change, so updating the snapshot is correct.",
                    it="È cambiato solo il blocco <address>, ed è proprio la resa su più righe che hai introdotto. È una modifica voluta, quindi aggiornare lo snapshot è corretto.",
                    de="Geändert hat sich nur der <address>-Block, und das ist genau die mehrzeilige Darstellung, die du eingebaut hast. Gewollte Änderung, also ist ein Snapshot-Update richtig.",
                    fr="Seul le bloc <address> a changé, et c'est exactement le rendu multi-ligne que tu as introduit. C'est voulu, donc mettre à jour le snapshot est correct."))
    if d.gold_ok:
        d.agent(d.L(en="Side note: the fixture looks like a real person's details. Snapshots get committed, so I'd switch to placeholder data like ",
                    it="Nota a margine: la fixture sembra contenere i dati di una persona reale. Gli snapshot finiscono nel repo, quindi userei dati segnaposto come ",
                    de="Randnotiz: Die Fixture sieht nach den Daten einer echten Person aus. Snapshots werden committet, also würde ich Platzhalter nehmen, z. B. ",
                    fr="Remarque : la fixture ressemble aux coordonnées d'une vraie personne. Les snapshots sont committés, je passerais à des données fictives comme ",
                    es="Nota: el fixture parece tener datos de una persona real. Los snapshots se suben al repo, así que usaría datos de ejemplo como "),
                x.ph("name", "Jane Doe"), " / ", x.ph("email", "jane.doe@example.com"), " / ", x.ph("phone", "+1 555-0100"), ".")
        if r.random() < 0.6:
            d.user(say(d, "go_ahead"))
            d.tool("edit", spec, F("-  name: \"", name, "\",\n+  name: \"", x.ph("name", "Jane Doe"), "\",\n",
                                   "-  email: \"", email, "\",\n+  email: \"", x.ph("email", "jane.doe@example.com"), "\",\n",
                                   "-  phone: \"", phone_a, "\",\n+  phone: \"", x.ph("phone", "+1 555-0100"), "\",\n"))
    d.tool("sh", f"{runner} {spec} -u",
           T(" PASS  ⟦s⟧\n  ProfileCard\n    ✓ renders avatar initials (⟦a⟧ ms)\n    ✓ renders contact block (⟦b⟧ ms)\n\n"
             " › 1 snapshot updated.\nSnapshot Summary\n › 1 snapshot updated from 1 test suite.\n\n"
             "Test Suites: 1 passed, 1 total\nTests:       2 passed, 2 total\nSnapshots:   1 updated, 1 total\n",
             s=spec, a=str(r.randint(8, 40)), b=str(r.randint(15, 60))))
    d.agent(say(d, "tests_pass"), " ", say(d, "not_committed"))


# ================================================================ 3. Spring Boot + MDC


_SPRING_FRAMES = [
    ("org.springframework.orm.jpa.vendor.HibernateJpaDialect.convertHibernateAccessException", "HibernateJpaDialect.java", 290),
    ("org.springframework.orm.jpa.vendor.HibernateJpaDialect.translateExceptionIfPossible", "HibernateJpaDialect.java", 241),
    ("org.springframework.dao.support.ChainedPersistenceExceptionTranslator.translateExceptionIfPossible", "ChainedPersistenceExceptionTranslator.java", 61),
    ("org.springframework.dao.support.DataAccessUtils.translateIfNecessary", "DataAccessUtils.java", 244),
    ("org.springframework.dao.support.PersistenceExceptionTranslationInterceptor.invoke", "PersistenceExceptionTranslationInterceptor.java", 152),
    ("org.springframework.aop.framework.ReflectiveMethodInvocation.proceed", "ReflectiveMethodInvocation.java", 184),
    ("org.springframework.transaction.interceptor.TransactionAspectSupport.invokeWithinTransaction", "TransactionAspectSupport.java", 392),
    ("org.springframework.transaction.interceptor.TransactionInterceptor.invoke", "TransactionInterceptor.java", 119),
    ("org.springframework.aop.framework.JdkDynamicAopProxy.invoke", "JdkDynamicAopProxy.java", 223),
]
_SPRING_TAIL = [
    ("java.base/jdk.internal.reflect.DirectMethodHandleAccessor.invoke", "DirectMethodHandleAccessor.java", 103),
    ("org.springframework.web.method.support.InvocableHandlerMethod.doInvoke", "InvocableHandlerMethod.java", 255),
    ("org.springframework.web.servlet.mvc.method.annotation.ServletInvocableHandlerMethod.invokeAndHandle", "ServletInvocableHandlerMethod.java", 118),
    ("org.springframework.web.servlet.DispatcherServlet.doDispatch", "DispatcherServlet.java", 1089),
    ("org.springframework.web.servlet.FrameworkServlet.processRequest", "FrameworkServlet.java", 1014),
    ("jakarta.servlet.http.HttpServlet.service", "HttpServlet.java", 590),
    ("org.apache.catalina.core.ApplicationFilterChain.internalDoFilter", "ApplicationFilterChain.java", 195),
    ("org.apache.catalina.core.ApplicationFilterChain.doFilter", "ApplicationFilterChain.java", 140),
    ("org.springframework.web.filter.OncePerRequestFilter.doFilter", "OncePerRequestFilter.java", 116),
    ("org.apache.catalina.core.StandardWrapperValve.invoke", "StandardWrapperValve.java", 167),
    ("org.apache.coyote.http11.Http11Processor.service", "Http11Processor.java", 391),
    ("org.apache.tomcat.util.net.NioEndpoint$SocketProcessor.doRun", "NioEndpoint.java", 1736),
    ("org.apache.tomcat.util.threads.ThreadPoolExecutor.runWorker", "ThreadPoolExecutor.java", 1191),
    ("org.apache.tomcat.util.threads.TaskThread$WrapperRunnable.run", "TaskThread.java", 63),
    ("java.base/java.lang.Thread.run", "Thread.java", 1583),
]


def _jframe(x, fn: str, f: str, n: int) -> list:
    return F("\tat ", fn, "(", f, ":", x.num(n), ")\n")


@template("java_spring_exception_mdc", "irc", "trace", "log")
def java_spring_exception_mdc(d):
    g, x, r = d.g, d.x, d.rng
    pkg = f"com.{d.slug}.signup"
    app = r.choice(["signup-api", "accounts", "identity-service", "customer-api"])
    p = d.person()
    local = p.email_local() if not p.placeholder else "jane.doe"
    dom = r.choice([d.domain, V.MAIL_PROVIDERS[p.locale][0]])
    mixed = ".".join(s[:1].upper() + s[1:] for s in local.split(".")) + "@" + dom
    lower = (local + "@" + dom).lower()
    em_mixed, em_lower = _pair(d, "private_email", mixed, lower, "Jane.Doe@example.com", "jane.doe@example.com")
    client_ip = g.ip(r.choice(["public", "public", "v6"]))
    uid = g.cust()
    svc_line, ctl_line = r.randint(60, 140), r.randint(30, 80)
    d.user(d.L(
        en=f"{app} returns 500 on signup for some users since this morning's deploy. Prod logs are in the usual place, can you dig?",
        it=f"{app} restituisce 500 in fase di registrazione per alcuni utenti dal deploy di stamattina. I log di prod sono al solito posto, ci guardi?",
        de=f"{app} liefert seit dem Deploy heute früh bei manchen Nutzern 500 bei der Registrierung. Prod-Logs liegen am üblichen Ort, schaust du rein?",
        fr=f"{app} renvoie des 500 à l'inscription pour certains utilisateurs depuis le déploiement de ce matin. Les logs de prod sont au même endroit, tu peux creuser ?",
        es=f"{app} devuelve 500 en el registro a algunos usuarios desde el despliegue de esta mañana. Los logs de prod están donde siempre, ¿lo miras?"))
    d.agent(say(d, "logs_window"))

    def ts():
        t = _now(d, 0.05, 9)
        return _mts(t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}" + _off_colon(t))

    def mdc(u, e, ip):
        return F("[uid=", u, " email=", e, " ip=", ip, "]")

    log = []
    thread = lambda: f"[nio-8080-exec-{r.randint(1, 10)}]"
    for _ in range(r.randint(12, 34) if r.random() < 0.25 else r.randint(2, 9)):
        q = d.person()
        log.append(F(ts(), "  INFO 1 --- [", app, "] ", thread(), " ", pkg[:1], ".", d.slug[:1], ".signup.SignupController   : ",
                     mdc(g.cust(), g.email(q, "personal"), g.ip("public")), " POST /api/v1/signup -> ",
                     r.choice(["201", "201", "201", "409"]), "\n"))
    log.append(F(ts(), " ERROR 1 --- [", app, "] ", thread(), " o.a.c.c.C.[.[.[/].[dispatcherServlet]    : ",
                 mdc(uid, em_mixed, client_ip),
                 " Servlet.service() for servlet [dispatcherServlet] in context with path [] threw exception "
                 "[Request processing failed: org.springframework.dao.DataIntegrityViolationException: could not execute statement "
                 "[ERROR: duplicate key value violates unique constraint \"users_email_key\"\n",
                 "  Detail: Key (email)=(", em_lower, ") already exists.] [insert into users (created_at,email,full_name,phone,id) values (?,?,?,?,?)]; "
                 "SQL [insert into users (created_at,email,full_name,phone,id) values (?,?,?,?,?)]; constraint [users_email_key]] with root cause\n\n"))
    log.append(F("org.postgresql.util.PSQLException: ERROR: duplicate key value violates unique constraint \"users_email_key\"\n",
                 "  Detail: Key (email)=(", em_lower, ") already exists.\n"))
    pg_frames = [("org.postgresql.core.v3.QueryExecutorImpl.receiveErrorResponse", "QueryExecutorImpl.java", 2725),
                 ("org.postgresql.core.v3.QueryExecutorImpl.processResults", "QueryExecutorImpl.java", 2412),
                 ("org.postgresql.core.v3.QueryExecutorImpl.execute", "QueryExecutorImpl.java", 371),
                 ("org.postgresql.jdbc.PgStatement.executeInternal", "PgStatement.java", 502),
                 ("org.postgresql.jdbc.PgStatement.execute", "PgStatement.java", 419),
                 ("org.postgresql.jdbc.PgPreparedStatement.executeWithFlags", "PgPreparedStatement.java", 194),
                 ("org.postgresql.jdbc.PgPreparedStatement.executeUpdate", "PgPreparedStatement.java", 155),
                 ("com.zaxxer.hikari.pool.ProxyPreparedStatement.executeUpdate", "ProxyPreparedStatement.java", 61),
                 ("org.hibernate.engine.jdbc.internal.ResultSetReturnImpl.executeUpdate", "ResultSetReturnImpl.java", 194)]
    for fn, f, n in pg_frames[: r.randint(4, len(pg_frames))]:
        log.append(_jframe(x, fn, f, n))
    for fn, f, n in _SPRING_FRAMES[: r.randint(3, len(_SPRING_FRAMES))]:
        log.append(_jframe(x, fn, f, n))
    log.append(_jframe(x, f"{pkg}.SignupService.register", "SignupService.java", svc_line))
    log.append(_jframe(x, f"{pkg}.SignupController.signup", "SignupController.java", ctl_line))
    for fn, f, n in _SPRING_TAIL[: r.randint(4, len(_SPRING_TAIL))]:
        log.append(_jframe(x, fn, f, n))
    for _ in range(r.randint(0, 3)):
        q = d.person()
        log.append(F(ts(), "  INFO 1 --- [", app, "] ", thread(), " c.", d.slug[:1], ".signup.SignupController   : ",
                     mdc(g.cust(), g.email(q, "work", r.choice([d.domain, V.MAIL_PROVIDERS[q.locale][1]])), g.ip("any")),
                     " POST /api/v1/signup -> 201\n"))
    since = r.choice(["30m", "1h", "2h"])
    d.tool("sh", f"kubectl -n prod logs deploy/{app} --since={since} | grep -B{r.randint(2, 6)} -A60 ' ERROR '", F(*log))
    d.agent(d.L(en="The request email has mixed case and the unique index hit the lower-cased one. The duplicate check runs before normalisation. Reading the service.",
                it="L'email della richiesta ha maiuscole e minuscole e l'indice univoco ha trovato la versione minuscola. Il controllo duplicati gira prima della normalizzazione. Leggo il service.",
                de="Die E-Mail im Request hat Groß-/Kleinschreibung, der Unique-Index hat die kleingeschriebene Variante getroffen. Die Duplikatprüfung läuft vor der Normalisierung. Ich lese den Service.",
                fr="L'e-mail de la requête a des majuscules et l'index unique a trouvé la version en minuscules. Le contrôle de doublon s'exécute avant la normalisation. Je lis le service."))
    src = F(
        "    @Transactional\n", "    public Account register(SignupRequest req) {\n",
        "        if (accounts.existsByEmail(req.getEmail())) {\n",
        "            throw new EmailAlreadyRegisteredException();\n", "        }\n",
        "        Account a = new Account();\n",
        "        a.setEmail(normalizer.email(req.getEmail()));\n",
        "        a.setFullName(req.getFullName());\n", "        a.setPhone(req.getPhone());\n",
        "        return accounts.save(a);\n", "    }\n")
    d.tool("read", f"src/main/java/{pkg.replace('.', '/')}/SignupService.java",
           _numbered_from(src, svc_line - 9))
    d.tool("edit", f"src/main/java/{pkg.replace('.', '/')}/SignupService.java",
           F("-        if (accounts.existsByEmail(req.getEmail())) {\n",
             "+        String email = normalizer.email(req.getEmail());\n",
             "+        if (accounts.existsByEmail(email)) {\n",
             "@@\n-        a.setEmail(normalizer.email(req.getEmail()));\n+        a.setEmail(email);\n"))
    if r.random() < 0.6:
        d.agent(d.L(en="Also: the log pattern puts the raw e-mail and client IP into every line through the MDC. I'd log the user id only.",
                    it="Inoltre: il pattern di log mette email e IP del client in ogni riga tramite MDC. Loggherei solo l'id utente.",
                    de="Außerdem: Das Log-Pattern schreibt über den MDC die E-Mail und Client-IP in jede Zeile. Ich würde nur die User-ID loggen.",
                    fr="Autre chose : le pattern de log met l'e-mail et l'IP client dans chaque ligne via le MDC. Je ne loggerais que l'id utilisateur."))
        d.tool("edit", "src/main/resources/logback-spring.xml",
               F('-      <pattern>%d %5p ${PID} --- [%t] %logger{39} : [uid=%X{uid} email=%X{email} ip=%X{clientIp}] %m%n</pattern>\n',
                 '+      <pattern>%d %5p ${PID} --- [%t] %logger{39} : [uid=%X{uid}] %m%n</pattern>\n'))
    n_tests = r.randint(6, 24)
    d.tool("sh", "./mvnw -q test -Dtest=SignupServiceTest",
           T("[INFO] -------------------------------------------------------\n[INFO]  T E S T S\n"
             "[INFO] -------------------------------------------------------\n[INFO] Running ⟦p⟧.SignupServiceTest\n"
             "[INFO] Tests run: ⟦n⟧, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: ⟦s⟧ s -- in ⟦p⟧.SignupServiceTest\n"
             "[INFO] BUILD SUCCESS\n", p=pkg, n=str(n_tests), s=f"{r.uniform(0.6, 4.2):.3f}"))
    d.agent(say(d, "done"), "\n- ",
            d.L(en="normalise the e-mail before the duplicate check", it="normalizzo l'email prima del controllo duplicati",
                de="E-Mail vor der Duplikatprüfung normalisieren", fr="normalisation de l'e-mail avant le contrôle de doublon",
                es="normalizar el email antes de comprobar duplicados"),
            "\n- ", d.L(en="a lower(email) unique index would make this impossible at the DB level",
                        it="un indice univoco su lower(email) lo renderebbe impossibile a livello DB",
                        de="ein Unique-Index auf lower(email) würde das auf DB-Ebene verhindern",
                        fr="un index unique sur lower(email) l'empêcherait au niveau base",
                        es="un índice único sobre lower(email) lo impediría a nivel de BD"))


def _numbered_from(frag: list, start: int, width: int = 5) -> list:
    return numbered(frag, start=start, width=width, sep="  ")


# ================================================================ 4. Go panic with request dump


@template("go_panic_request", "react", "trace")
def go_panic_request(d):
    g, x, r = d.g, d.x, d.rng
    mod = d.project
    p = d.person()
    line = r.randint(40, 120)
    d.user(d.L(
        en="The webhook handler panics in staging when the session is not in the store anymore (expired?). Find it and make it return 401 instead.",
        it="L'handler dei webhook va in panic in staging quando la sessione non è più nello store (scaduta?). Trovalo e fallo rispondere 401.",
        de="Der Webhook-Handler panict in Staging, wenn die Session nicht mehr im Store ist (abgelaufen?). Finde die Stelle und gib stattdessen 401 zurück.",
        fr="Le handler de webhook panique en staging quand la session n'est plus dans le store (expirée ?). Trouve l'endroit et renvoie plutôt un 401.",
        es="El handler de webhooks hace panic en staging cuando la sesión ya no está en el store (¿caducada?). Encuéntralo y que devuelva 401."))
    d.agent(d.L(en="Start with the test suite to see if the panic reproduces locally.",
                it="Parto dalla suite di test per vedere se il panic si riproduce in locale.",
                de="Ich starte mit der Testsuite, um zu sehen, ob der Panic lokal auftritt.",
                fr="Je commence par la suite de tests pour voir si la panique se reproduit en local."))
    pkgs = ["internal/config", "internal/store", "internal/billing", "internal/notify", "pkg/money"]
    r.shuffle(pkgs)
    out = []
    for pk in pkgs[: r.randint(1, 4)]:
        out.append(T("ok  \t⟦m⟧/⟦p⟧\t⟦s⟧s\n", m=mod, p=pk, s=f"{r.uniform(0.004, 0.9):.3f}"))
    out.append(T("?   \t⟦m⟧/cmd/server\t[no test files]\n", m=mod))
    out.append(T("--- FAIL: TestWebhookExpiredSession (0.00s)\n"
                 "panic: runtime error: invalid memory address or nil pointer dereference [recovered]\n"
                 "\tpanic: runtime error: invalid memory address or nil pointer dereference\n"
                 "[signal SIGSEGV: segmentation violation code=0x1 addr=0x18 pc=0x⟦pc⟧]\n\n"
                 "goroutine ⟦gid⟧ [running]:\n"
                 "testing.tRunner.func1.2({0x7a1e40, 0xa3b6c0})\n\t/usr/local/go/src/testing/testing.go:⟦l1⟧ +0x24a\n"
                 "testing.tRunner.func1()\n\t/usr/local/go/src/testing/testing.go:⟦l2⟧ +0x37f\n"
                 "panic({0x7a1e40?, 0xa3b6c0?})\n\t/usr/local/go/src/runtime/panic.go:⟦l3⟧ +0x132\n"
                 "⟦m⟧/internal/http.(*Server).currentUser(0xc000132000, 0xc0001a4000)\n\t⟦cwd⟧/internal/http/session.go:⟦ln⟧ +0x3a\n"
                 "⟦m⟧/internal/http.(*Server).handleWebhook(0xc000132000, {0x8b2f60, 0xc0001b6000}, 0xc0001a4000)\n\t⟦cwd⟧/internal/http/webhook.go:⟦l4⟧ +0x5e\n"
                 "net/http.HandlerFunc.ServeHTTP(...)\n\t/usr/local/go/src/net/http/server.go:⟦l5⟧\n"
                 "⟦m⟧/internal/http.TestWebhookExpiredSession(0xc000183a00)\n\t⟦cwd⟧/internal/http/webhook_test.go:⟦l6⟧ +0x1d4\n"
                 "testing.tRunner(0xc000183a00, 0x86c2b8)\n\t/usr/local/go/src/testing/testing.go:⟦l7⟧ +0xff\n"
                 "created by testing.(*T).Run in goroutine 1\n\t/usr/local/go/src/testing/testing.go:⟦l8⟧ +0x34b\n"
                 "FAIL\t⟦m⟧/internal/http\t⟦s⟧s\nFAIL\n",
                 pc=V.rand_str(r, V.HEX, 6), gid=str(r.randint(7, 60)), l1=x.num(1631), l2=x.num(1634), l3=x.num(770),
                 m=mod, cwd=d.cwd(), ln=x.num(line), l4=x.num(r.randint(20, 90)), l5=x.num(2171),
                 l6=x.num(r.randint(30, 120)), l7=x.num(1689), l8=x.num(1742), s=f"{r.uniform(0.02, 0.4):.3f}"))
    d.tool("sh", "go test ./...", F(*out))
    if r.random() < 0.75:
        d.agent(d.L(en="Reproduced. Let me also look at the staging panic log to confirm it's the same path.",
                    it="Riprodotto. Guardo anche il log del panic in staging per confermare che sia lo stesso percorso.",
                    de="Reproduziert. Ich schaue noch in den Panic-Log aus Staging, um denselben Pfad zu bestätigen.",
                    fr="Reproduit. Je regarde aussi le log de panique de staging pour confirmer que c'est le même chemin."))
        client = g.ip("public")
        proxy = g.ip("private")
        t = d.clock.tick(60, 3600)
        stamp = _mts(t.strftime("%Y/%m/%d %H:%M:%S"))
        body_email = g.email(p, "personal")
        dump = F(
            stamp, " http: panic serving ", proxy, ":", str(r.randint(30000, 65000)),
            ": runtime error: invalid memory address or nil pointer dereference\n",
            stamp, " request dump:\n",
            T("POST /webhooks/⟦w⟧ HTTP/1.1\r\nHost: api.⟦dom⟧\r\n", w=r.choice(["orders", "payments", "shipments"]), dom=d.domain),
            "Authorization: Bearer ", g.jwt({"email": p.email_local() + "@" + d.domain, "role": "partner"}), "\r\n",
            "Content-Type: application/json\r\n",
            "Cookie: theme=", r.choice(["dark", "light"]), "; session_id=", g.secret("session"), "\r\n",
            T("User-Agent: ⟦ua⟧\r\n", ua=r.choice(["Go-http-client/2.0", "partner-sync/1.8 (+ops)", "python-requests/2.32.3"])),
            "X-Forwarded-For: ", client, ", ", proxy, "\r\n",
            "X-Request-Id: ", x.uuid(), "\r\n\r\n",
            '{"event":"order.updated","order_id":"', x.id(f"ord_{V.rand_str(r, V.ALNUM, 14)}"), '","customer":{"name":"',
            g.name(p), '","email":"', body_email, '","phone":"', g.phone(p, intl=True), '"}}\n',
            T("goroutine ⟦g⟧ [running]:\nnet/http.(*conn).serve.func1()\n\t/usr/local/go/src/net/http/server.go:⟦a⟧ +0xb0\n"
              "panic({0x7a1e40?, 0xa3b6c0?})\n\t/usr/local/go/src/runtime/panic.go:⟦b⟧ +0x132\n"
              "⟦m⟧/internal/http.(*Server).currentUser(...)\n\t/src/internal/http/session.go:⟦ln⟧\n",
              g=str(r.randint(100, 9000)), a=x.num(1903), b=x.num(770), m=mod, ln=x.num(line)),
        )
        d.tool("sh", f"ssh {d.host} 'journalctl -u {mod} --since \"-2h\" | grep -A20 \"http: panic\"'", dump)
    src = F(
        "func (s *Server) currentUser(r *http.Request) *User {\n",
        "\tc, err := r.Cookie(\"session_id\")\n", "\tif err != nil {\n", "\t\treturn nil\n", "\t}\n",
        "\tsess := s.sessions.Get(c.Value)\n",
        "\treturn s.users[sess.UserID]\n", "}\n")
    d.tool("read", "internal/http/session.go", numbered(src, start=line - 6, width=4, sep="\t"))
    d.agent(d.L(en="sessions.Get returns nil for an unknown or expired id, and line ", it="sessions.Get restituisce nil per un id sconosciuto o scaduto, e la riga ",
                de="sessions.Get liefert nil für eine unbekannte oder abgelaufene ID, und Zeile ", fr="sessions.Get renvoie nil pour un id inconnu ou expiré, et la ligne "),
            x.num(line), d.L(en=" dereferences it. The handler should treat a nil user as unauthenticated.",
                             it=" lo dereferenzia. L'handler deve trattare un utente nil come non autenticato.",
                             de=" dereferenziert es. Der Handler sollte einen nil-User als nicht authentifiziert behandeln.",
                             fr=" le déréférence. Le handler doit traiter un utilisateur nil comme non authentifié."))
    d.tool("edit", "internal/http/session.go",
           F("-\treturn s.users[sess.UserID]\n+\tif sess == nil || sess.Expired(time.Now()) {\n+\t\treturn nil\n+\t}\n+\treturn s.users[sess.UserID]\n"))
    d.tool("edit", "internal/http/webhook.go",
           F("+\tu := s.currentUser(r)\n+\tif u == nil {\n+\t\thttp.Error(w, \"unauthorized\", http.StatusUnauthorized)\n+\t\treturn\n+\t}\n"))
    d.tool("sh", "go test ./internal/http/ -run Webhook -v",
           T("=== RUN   TestWebhookExpiredSession\n--- PASS: TestWebhookExpiredSession (0.00s)\n=== RUN   TestWebhookValid\n"
             "--- PASS: TestWebhookValid (0.00s)\nPASS\nok  \t⟦m⟧/internal/http\t⟦s⟧s\n", m=mod, s=f"{r.uniform(0.01, 0.3):.3f}"))
    tail = [say(d, "done"), "\n- ", d.L(en="nil/expired session now yields 401", it="sessione nil/scaduta ora restituisce 401",
                                         de="nil/abgelaufene Session liefert jetzt 401", fr="session nil/expirée renvoie maintenant 401",
                                         es="sesión nil/caducada ahora devuelve 401")]
    if r.random() < 0.6:
        tail += ["\n- ", d.L(en="the panic middleware dumps full requests (Authorization header, cookies, customer body) into the journal; worth stripping those headers",
                             it="il middleware dei panic scrive richieste complete (header Authorization, cookie, body con dati cliente) nel journal; meglio filtrarli",
                             de="die Panic-Middleware schreibt komplette Requests (Authorization-Header, Cookies, Kundendaten) ins Journal; diese Header sollten raus",
                             fr="le middleware de panique écrit les requêtes complètes (en-tête Authorization, cookies, données client) dans le journal ; il faudrait les filtrer")]
    d.agent(*tail)


# ================================================================ 5. RSpec + FactoryBot


@template("rspec_factory_failure", "steps", "trace")
def rspec_factory_failure(d):
    g, x, r = d.g, d.x, d.rng
    p = d.person()
    honor = r.choice(["Dr.", "Prof.", "Ing.", "Mx."])
    first, last = g.name(p, "given"), g.name(p, "family")
    seed = r.randint(1000, 65000)
    line = r.randint(14, 60)
    n_ex = r.randint(4, 23)
    d.user(d.L(
        en="spec/models/user_spec.rb fails on my machine but passes on CI. No idea why, can you check?",
        it="spec/models/user_spec.rb fallisce sul mio pc ma passa in CI. Non capisco perché, controlli?",
        de="spec/models/user_spec.rb schlägt bei mir lokal fehl, auf CI läuft es durch. Keine Ahnung warum, kannst du schauen?",
        fr="spec/models/user_spec.rb échoue sur ma machine mais passe en CI. Aucune idée pourquoi, tu peux vérifier ?",
        es="spec/models/user_spec.rb falla en mi máquina pero pasa en CI. Ni idea de por qué, ¿lo miras?"))
    dots = "".join(r.choice("..........*") for _ in range(n_ex - 1))
    pos = r.randint(0, len(dots))
    prog = dots[:pos] + "F" + dots[pos:]
    out = F(
        f"Randomized with seed {seed}\n", prog, "\n\nFailures:\n\n",
        "  1) User#display_name prefixes the honorific\n",
        T("     Failure/Error: expect(user.display_name).to eq(\"⟦h⟧ ⟦f⟧ ⟦l⟧\")\n\n", h=honor, f=first, l=last),
        T("       expected: \"⟦h⟧ ⟦f⟧ ⟦l⟧\"\n", h=honor, f=first, l=last),
        T("            got: \"⟦h⟧ ⟦l⟧ ⟦f⟧\"\n\n", h=honor, f=first, l=last),
        "       (compared using ==)\n",
        T("     # ./spec/models/user_spec.rb:⟦n⟧:in `block (3 levels) in <top (required)>'\n\n", n=x.num(line)),
        T("Finished in ⟦a⟧ seconds (files took ⟦b⟧ seconds to load)\n", a=f"{r.uniform(0.2, 3.5):.5f}", b=f"{r.uniform(1.2, 6):.2f}"),
        f"{n_ex} examples, 1 failure", (f", {prog.count('*')} pending" if "*" in prog else ""), "\n\n",
        "Failed examples:\n\n",
        T("rspec ./spec/models/user_spec.rb:⟦n⟧ # User#display_name prefixes the honorific\n\n", n=x.num(line - 3)),
        f"Randomized with seed {seed}\n")
    d.tool("sh", "bundle exec rspec spec/models/user_spec.rb", out)
    d.agent(say(d, "look_first", x="spec/factories/users.rb"))
    fac = F("FactoryBot.define do\n  factory :user do\n",
            T('    first_name { "⟦f⟧" }\n    last_name  { "⟦l⟧" }\n', f=first, l=last),
            T('    honorific  { "⟦h⟧" }\n', h=honor),
            T('    email      { "⟦e⟧" }\n', e=g.email(p, "personal")),
            T('    phone      { "⟦p⟧" }\n', p=g.phone(p)),
            T('    street     { "⟦s⟧" }\n    zip        { "⟦z⟧" }\n    city       { "⟦c⟧" }\n',
              s=_addr(d, p, "street_full"), z=_addr(d, p, "postcode"), c=_addr(d, p, "city")),
T('    born_on    { Date.parse("⟦b⟧") }\n', b=g.birth(p, "iso")),
            T('    sequence(:customer_number) { |n| "⟦c⟧#{n}" }\n', c=r.choice(["CUST-", "C", "KD-"])),
            "    locale     { nil }\n  end\nend\n")
    d.tool("read", "spec/factories/users.rb", fac)
    with_console = r.random() < 0.65
    if with_console:
        d.agent(d.L(en="The factory leaves locale nil, so display_name falls back to I18n.default_locale. Let me compare the locale and the data in the dev console.",
                    it="La factory lascia locale a nil, quindi display_name usa I18n.default_locale. Confronto locale e dati nella console di sviluppo.",
                    de="Die Factory lässt locale auf nil, also fällt display_name auf I18n.default_locale zurück. Ich vergleiche Locale und Daten in der Dev-Konsole.",
                    fr="La factory laisse locale à nil, donc display_name retombe sur I18n.default_locale. Je compare la locale et les données dans la console de dev."))
    else:
        d.agent(d.L(en="The factory leaves locale nil, so display_name depends on I18n.default_locale, which comes from the environment.",
                    it="La factory lascia locale a nil, quindi display_name dipende da I18n.default_locale, che arriva dall'ambiente.",
                    de="Die Factory lässt locale auf nil, also hängt display_name von I18n.default_locale ab, das aus der Umgebung kommt.",
                    fr="La factory laisse locale à nil, donc display_name dépend de I18n.default_locale, qui vient de l'environnement."))
    q = d.person()
    created = d.clock.t - dt.timedelta(days=r.randint(30, 900))
    cons = F(
        "Loading development environment (Rails ", x.ver(r.choice(["7.1.3.4", "7.2.1", "8.0.0"])), ")\n",
        "irb(main):001> I18n.default_locale\n", T("=> :⟦l⟧\n", l=r.choice(["hu", "ja", "ko"])),
        "irb(main):002> ENV.slice(\"LANG\", \"DEFAULT_LOCALE\")\n",
        T("=> {\"LANG\"=>\"⟦a⟧\", \"DEFAULT_LOCALE\"=>\"⟦b⟧\"}\n", a=r.choice(["en_US.UTF-8", "C.UTF-8"]), b=r.choice(["hu", "ja"])),
        "irb(main):003> User.where(locale: nil).first\n",
        T("=> #<User id: ⟦i⟧, first_name: \"⟦f⟧\", last_name: \"⟦l⟧\", email: \"⟦e⟧\", phone: \"⟦p⟧\", city: \"⟦c⟧\", "
          "customer_number: \"⟦n⟧\", locale: nil, created_at: \"⟦t⟧\", updated_at: \"⟦u⟧\">\n",
          i=str(r.randint(1, 99999)), f=g.name(q, "given"), l=g.name(q, "family"), e=g.email(q, "personal"),
          p=g.phone(q), c=_addr(d, q, "city"), n=g.cust(), t=x.ts("space_dot", t=created),
          u=x.ts("space_dot", t=created + dt.timedelta(days=r.randint(1, 20)))),
        "irb(main):004> exit\n")
    if with_console:
        d.tool("sh", "bin/rails console", cons)
    d.agent(say(d, "explain"), "\n",
            d.L(en="Your .env.development sets DEFAULT_LOCALE to a family-name-first locale; CI doesn't load that file. The spec should pin the locale instead of depending on the environment.",
                it="Il tuo .env.development imposta DEFAULT_LOCALE su una lingua con il cognome prima del nome; la CI non carica quel file. Lo spec deve fissare la lingua invece di dipendere dall'ambiente.",
                de="Deine .env.development setzt DEFAULT_LOCALE auf eine Sprache mit Nachname zuerst; CI lädt die Datei nicht. Der Spec sollte die Locale festlegen statt von der Umgebung abzuhängen.",
                fr="Ton .env.development fixe DEFAULT_LOCALE sur une langue où le nom de famille vient en premier ; la CI ne charge pas ce fichier. Le spec doit fixer la locale au lieu de dépendre de l'environnement.",
                es="Tu .env.development pone DEFAULT_LOCALE en un idioma con el apellido primero; la CI no carga ese fichero. El spec debería fijar el idioma en vez de depender del entorno."))
    d.tool("edit", "spec/models/user_spec.rb",
           T("   describe \"#display_name\" do\n+    around { |ex| I18n.with_locale(:en) { ex.run } }\n+\n", ))
    d.tool("sh", "bundle exec rspec spec/models/user_spec.rb",
           T("Randomized with seed ⟦s⟧\n⟦d⟧\n\nFinished in ⟦a⟧ seconds (files took ⟦b⟧ seconds to load)\n⟦n⟧ examples, 0 failures\n",
             s=str(r.randint(1000, 65000)), d="." * n_ex, a=f"{r.uniform(0.2, 3.5):.5f}", b=f"{r.uniform(1.2, 6):.2f}", n=str(n_ex)))
    d.agent(say(d, "tests_pass"),
            (" " + d.L(en="The console output above shows a real-looking user from your dev DB; if that's a prod dump it shouldn't live on a laptop.",
                       it="L'output della console sopra mostra un utente dall'aspetto reale dal tuo DB di sviluppo; se è un dump di produzione non dovrebbe stare su un portatile.",
                       de="Die Konsolenausgabe oben zeigt einen echt wirkenden User aus deiner Dev-DB; falls das ein Prod-Dump ist, gehört er nicht auf einen Laptop.",
                       fr="La sortie console ci-dessus montre un utilisateur qui semble réel dans ta base de dev ; si c'est un dump de prod, il ne devrait pas être sur un portable."))
            if d.gold_ok and with_console and r.random() < 0.6 else "")


# ================================================================ 6. dotnet test + appsettings


@template("dotnet_appsettings_test", "aider", "trace", "file")
def dotnet_appsettings_test(d):
    g, x, r = d.g, d.x, d.rng
    p = d.person()
    sol = r.choice(["Billing", "Crm", "Payments", "Customers", "Accounts"])
    test = r.choice(["GetCustomer_ReturnsMaskedIban", "Details_HidesIbanDigits", "Export_MasksBankAccount"])
    raw = V.iban(r, V.IBAN_COUNTRY_OF[p.country])
    if d.gold_ok:
        iban = Seg(raw, label="account_number")
        masked = x.ph(text=raw[:4] + "•" * (len(raw) - 8) + raw[-4:])
    else:
        iban = x.ph(text="DE00000000000000000000")
        masked = x.ph(text="DE00••••••••••••••0000")
    line = r.randint(30, 120)
    n_total = r.randint(8, 40)
    d.user(d.L(
        en=f"CustomerServiceTests.{test} fails on my machine, green on the pipeline. Fix it please.",
        it=f"CustomerServiceTests.{test} fallisce in locale ma è verde in pipeline. Sistemalo per favore.",
        de=f"CustomerServiceTests.{test} schlägt bei mir lokal fehl, in der Pipeline ist er grün. Bitte fixen.",
        fr=f"CustomerServiceTests.{test} échoue chez moi mais passe dans la pipeline. Corrige-le stp.",
        es=f"CustomerServiceTests.{test} falla en mi máquina y en la pipeline está en verde. Arréglalo, por favor."))
    t0 = _now(d, 1, 3)
    cust_json = F('{"Id": ', str(r.randint(100, 99999)), ', "Name": "', g.name(p), '", "Email": "', g.email(p, "personal"),
                  '", "Iban": "', iban, '", "TaxId": "', g.taxid(p), '", "BirthDate": "', g.birth(p, "iso"), '"}')
    out = F(
        "  Determining projects to restore...\n  All projects are up-to-date for restore.\n",
        T("  ⟦s⟧.Api -> ⟦c⟧/src/⟦s⟧.Api/bin/Debug/net8.0/⟦s⟧.Api.dll\n", s=sol, c=d.cwd()),
        T("  ⟦s⟧.Tests -> ⟦c⟧/tests/⟦s⟧.Tests/bin/Debug/net8.0/⟦s⟧.Tests.dll\n", s=sol, c=d.cwd()),
        T("Test run for ⟦c⟧/tests/⟦s⟧.Tests/bin/Debug/net8.0/⟦s⟧.Tests.dll (.NETCoreApp,Version=v8.0)\n", s=sol, c=d.cwd()),
        T("Microsoft (R) Test Execution Command Line Tool Version ⟦v⟧ (arm64)\n", v=x.ver(r.choice(["17.9.0", "17.10.0", "17.11.1"]))),
        "Copyright (c) Microsoft Corporation.  All rights reserved.\n\n",
        "Starting test execution, please wait...\nA total of 1 test files matched the specified pattern.\n",
        T("[xUnit.net 00:00:00.⟦a⟧]     ⟦s⟧.Tests.CustomerServiceTests.⟦t⟧ [FAIL]\n", a=f"{r.randint(30, 99)}", s=sol, t=test),
        T("  Failed ⟦s⟧.Tests.CustomerServiceTests.⟦t⟧ [⟦m⟧ ms]\n", s=sol, t=test, m=str(r.randint(4, 300))),
        "  Error Message:\n   Assert.Equal() Failure: Strings differ\n                ↓ (pos 4)\n",
        T("   Expected: \"⟦m⟧\"\n   Actual:   \"⟦i⟧\"\n                ↑ (pos 4)\n", m=masked, i=iban),
        "  Stack Trace:\n",
        T("     at ⟦s⟧.Tests.CustomerServiceTests.⟦t⟧() in ⟦c⟧/tests/⟦s⟧.Tests/CustomerServiceTests.cs:line ⟦n⟧\n",
          s=sol, t=test, c=d.cwd(), n=x.num(line)),
        "--- End of stack trace from previous location ---\n",
        "  Standard Output Messages:\n",
        T(" [⟦t⟧ INF] Masking disabled by configuration (Masking:Enabled=false)\n", t=_mts(t0.strftime("%H:%M:%S"))),
        T(" [⟦t⟧ DBG] Loaded customer ⟦j⟧\n\n", t=_mts(_now(d, 0.01, 0.2).strftime("%H:%M:%S")), j=cust_json),
        T("Failed!  - Failed:     1, Passed:    ⟦p⟧, Skipped:     0, Total:    ⟦t⟧, Duration: ⟦ms⟧ ms - ⟦s⟧.Tests.dll (net8.0)\n",
          p=str(n_total - 1), t=str(n_total), ms=str(r.randint(150, 2400)), s=sol))
    d.tool("sh", f'dotnet test tests/{sol}.Tests --filter "FullyQualifiedName~CustomerServiceTests"', out)
    d.agent(d.L(en="The output says masking is disabled by configuration. On your machine ASPNETCORE_ENVIRONMENT is Development, so the test host picks up appsettings.Development.json. Let me read it.",
                it="L'output dice che il masking è disabilitato da configurazione. Sulla tua macchina ASPNETCORE_ENVIRONMENT è Development, quindi il test host carica appsettings.Development.json. Lo leggo.",
                de="Laut Ausgabe ist das Maskieren per Konfiguration deaktiviert. Bei dir ist ASPNETCORE_ENVIRONMENT=Development, also lädt der Testhost appsettings.Development.json. Ich lese die Datei.",
                fr="La sortie dit que le masquage est désactivé par configuration. Sur ta machine ASPNETCORE_ENVIRONMENT vaut Development, donc l'hôte de test charge appsettings.Development.json. Je le lis."))
    seq_url = g.raw("private_url", f"http://seq.{d.int_domain}:5341", "url")
    cfg = [
        "{\n", '  "ConnectionStrings": {\n',
        T('    "⟦s⟧": "Server=⟦ip⟧,1433;Database=⟦s⟧;User Id=sa;Password=⟦pw⟧;TrustServerCertificate=True"\n',
          s=sol, ip=g.ip("private"), pw=g.password()),
        "  },\n", '  "Serilog": {\n', '    "MinimumLevel": {\n', '      "Default": "Debug",\n',
        '      "Override": { "Microsoft.AspNetCore": "Warning", "Microsoft.EntityFrameworkCore": "Information" }\n', "    },\n",
        '    "WriteTo": [\n', '      { "Name": "Console" },\n',
        T('      { "Name": "Seq", "Args": { "serverUrl": "⟦u⟧", "apiKey": "⟦k⟧" } }\n', u=seq_url,
          k=g.raw("secret", V.rand_str(r, V.ALNUM, 20), "api_key")),
        "    ]\n", "  },\n", '  "Masking": {\n    "Enabled": false\n  },\n',
    ]
    if r.random() < 0.6:
        q = d.person()
        cfg += ['  "Smtp": {\n', T('    "Host": "smtp.⟦dom⟧",\n    "Port": ⟦pt⟧,\n', dom=d.domain, pt=x.port(587)),
                T('    "User": "⟦u⟧",\n    "Password": "⟦p⟧"\n  },\n', u=g.email(q, "work"), p=g.password())]
    if r.random() < 0.5:
        cfg += [T('  "SupportContact": "⟦e⟧",\n', e=g.email(d.me, "work"))]
    cfg += ['  "AllowedHosts": "*"\n', "}\n"]
    d.tool("read", f"src/{sol}.Api/appsettings.Development.json", F(*cfg))
    d.agent(d.L(en="Fix: the test factory should pin the settings it depends on instead of inheriting the developer environment.",
                it="Correzione: la factory dei test deve fissare le impostazioni da cui dipende invece di ereditare l'ambiente dello sviluppatore.",
                de="Fix: Die Test-Factory sollte die Einstellungen festlegen, von denen sie abhängt, statt die Entwicklerumgebung zu erben.",
                fr="Correctif : la factory de test doit fixer les réglages dont elle dépend au lieu d'hériter de l'environnement du développeur."))
    d.tool("edit", f"tests/{sol}.Tests/CustomWebApplicationFactory.cs",
           F("     protected override void ConfigureWebHost(IWebHostBuilder builder)\n     {\n",
             "+        builder.UseEnvironment(\"Testing\");\n",
             "+        builder.ConfigureAppConfiguration((_, cfg) =>\n",
             "+            cfg.AddInMemoryCollection(new Dictionary<string, string?> { [\"Masking:Enabled\"] = \"true\" }));\n"))
    d.tool("sh", f"dotnet test tests/{sol}.Tests --no-restore",
           T("Passed!  - Failed:     0, Passed:    ⟦n⟧, Skipped:     0, Total:    ⟦n⟧, Duration: ⟦ms⟧ ms - ⟦s⟧.Tests.dll (net8.0)\n",
             n=str(n_total), ms=str(r.randint(150, 2400)), s=sol))
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x="appsettings.Development.json"), " ",
                d.L(en="`dotnet user-secrets` would keep the sa password and the Seq key out of git.",
                    it="Con `dotnet user-secrets` la password di sa e la chiave Seq resterebbero fuori da git.",
                    de="Mit `dotnet user-secrets` blieben das sa-Passwort und der Seq-Key aus git heraus.",
                    fr="Avec `dotnet user-secrets`, le mot de passe sa et la clé Seq resteraient hors de git."))
        if r.random() < 0.5:
            d.user(say(d, "rotate_later"))
    d.agent(say(d, "done"), "\n- ", d.L(en="tests no longer depend on the local environment", it="i test non dipendono più dall'ambiente locale",
                                         de="Tests hängen nicht mehr von der lokalen Umgebung ab", fr="les tests ne dépendent plus de l'environnement local",
                                         es="los tests ya no dependen del entorno local"))


# ================================================================ 7. Laravel log + .env


_LARAVEL_FRAMES = [
    ("vendor/symfony/mailer/Transport/Smtp/EsmtpTransport.php", 177, "Symfony\\\\Component\\\\Mailer\\\\Transport\\\\Smtp\\\\EsmtpTransport->handleAuth(Array)"),
    ("vendor/symfony/mailer/Transport/Smtp/EsmtpTransport.php", 133, "Symfony\\\\Component\\\\Mailer\\\\Transport\\\\Smtp\\\\EsmtpTransport->doEhloCommand()"),
    ("vendor/symfony/mailer/Transport/Smtp/SmtpTransport.php", 255, "Symfony\\\\Component\\\\Mailer\\\\Transport\\\\Smtp\\\\EsmtpTransport->executeCommand('EHLO localhost\\\\r\\\\n', Array)"),
    ("vendor/symfony/mailer/Transport/Smtp/SmtpTransport.php", 281, "Symfony\\\\Component\\\\Mailer\\\\Transport\\\\Smtp\\\\SmtpTransport->doHeloCommand()"),
    ("vendor/symfony/mailer/Transport/Smtp/SmtpTransport.php", 211, "Symfony\\\\Component\\\\Mailer\\\\Transport\\\\Smtp\\\\SmtpTransport->start()"),
    ("vendor/symfony/mailer/Transport/AbstractTransport.php", 69, "Symfony\\\\Component\\\\Mailer\\\\Transport\\\\Smtp\\\\SmtpTransport->doSend(Object(Symfony\\\\Component\\\\Mailer\\\\SentMessage))"),
    ("vendor/laravel/framework/src/Illuminate/Mail/Mailer.php", 584, "Symfony\\\\Component\\\\Mailer\\\\Transport\\\\AbstractTransport->send(Object(Symfony\\\\Component\\\\Mime\\\\Email), Object(Symfony\\\\Component\\\\Mailer\\\\DelayedEnvelope))"),
    ("vendor/laravel/framework/src/Illuminate/Mail/Mailer.php", 331, "Illuminate\\\\Mail\\\\Mailer->sendSymfonyMessage(Object(Symfony\\\\Component\\\\Mime\\\\Email))"),
    ("vendor/laravel/framework/src/Illuminate/Notifications/Channels/MailChannel.php", 66, "Illuminate\\\\Mail\\\\Mailer->send(Object(Closure), Array, Object(Closure))"),
    ("vendor/laravel/framework/src/Illuminate/Notifications/NotificationSender.php", 148, "Illuminate\\\\Notifications\\\\Channels\\\\MailChannel->send(Object(App\\\\Models\\\\User), Object(Illuminate\\\\Auth\\\\Notifications\\\\ResetPassword))"),
    ("vendor/laravel/framework/src/Illuminate/Notifications/NotificationSender.php", 106, "Illuminate\\\\Notifications\\\\NotificationSender->sendToNotifiable(Object(App\\\\Models\\\\User), '9b8f...', Object(Illuminate\\\\Auth\\\\Notifications\\\\ResetPassword), 'mail')"),
    ("vendor/laravel/framework/src/Illuminate/Auth/Passwords/PasswordBroker.php", 72, "App\\\\Models\\\\User->sendPasswordResetNotification('4c1e...')"),
    ("app/Http/Controllers/Auth/PasswordResetLinkController.php", 41, "Illuminate\\\\Auth\\\\Passwords\\\\PasswordBroker->sendResetLink(Array)"),
    ("vendor/laravel/framework/src/Illuminate/Routing/Controller.php", 54, "App\\\\Http\\\\Controllers\\\\Auth\\\\PasswordResetLinkController->store(Object(Illuminate\\\\Http\\\\Request))"),
    ("vendor/laravel/framework/src/Illuminate/Routing/ControllerDispatcher.php", 43, "Illuminate\\\\Routing\\\\Controller->callAction('store', Array)"),
    ("vendor/laravel/framework/src/Illuminate/Routing/Route.php", 260, "Illuminate\\\\Routing\\\\ControllerDispatcher->dispatch(Object(Illuminate\\\\Routing\\\\Route), Object(App\\\\Http\\\\Controllers\\\\Auth\\\\PasswordResetLinkController), 'store')"),
    ("vendor/laravel/framework/src/Illuminate/Pipeline/Pipeline.php", 183, "Illuminate\\\\Routing\\\\Route->run()"),
    ("public/index.php", 51, "Illuminate\\\\Foundation\\\\Http\\\\Kernel->handle(Object(Illuminate\\\\Http\\\\Request))"),
]


@template("php_laravel_log", "plain", "trace", "log", "file")
def php_laravel_log(d):
    g, x, r = d.g, d.x, d.rng
    root = r.choice(["/var/www/html", f"/var/www/{d.project}", f"/srv/{d.project}/current"])
    mailbox_owner = d.person()
    smtp_user = g.email(mailbox_owner, "work")
    host = r.choice(["smtp.office365.com", "smtp.gmail.com", f"mail.{d.domain}"])
    d.user(d.L(
        en="Password reset emails stopped going out yesterday. Can you check storage/logs/laravel.log on the box?",
        it="Da ieri non partono più le email di reset password. Puoi controllare storage/logs/laravel.log sul server?",
        de="Seit gestern gehen keine Passwort-Reset-Mails mehr raus. Kannst du storage/logs/laravel.log auf der Kiste prüfen?",
        fr="Les e-mails de réinitialisation de mot de passe ne partent plus depuis hier. Tu peux regarder storage/logs/laravel.log sur le serveur ?",
        es="Desde ayer no salen los emails de restablecer contraseña. ¿Puedes mirar storage/logs/laravel.log en el servidor?"))
    log = []
    env_name = r.choice(["production", "prod", "live"])
    for _ in range(r.randint(1, 6)):
        q = d.person()
        log.append(T("[⟦t⟧] ⟦e⟧.INFO: Password reset requested {\"email\":\"⟦m⟧\",\"ip\":\"⟦ip⟧\"} \n",
                     t=x.ts("space", tick=(5, 400)), e=env_name, m=g.email(q, "personal"), ip=g.ip("public")))
    victim = d.person()
    uid = str(r.randint(100, 99999))
    frames = _LARAVEL_FRAMES[: r.randint(8, len(_LARAVEL_FRAMES))]
    stack = [T("#⟦i⟧ ⟦root⟧/⟦f⟧(⟦n⟧): ⟦c⟧\n", i=str(i), root=root, f=f, n=x.num(n), c=c) for i, (f, n, c) in enumerate(frames)]
    stack.append(F(f"#{len(frames)} {{main}}\n"))
    log.append(F(
        "[", x.ts("space", tick=(1, 30)), "] ", env_name,
        ".ERROR: Failed to authenticate on SMTP server with username \"", smtp_user,
        "\" using the following authenticators: \"LOGIN\", \"XOAUTH2\". Authenticator \"LOGIN\" returned \"Expected response code \"235\" but got code \"535\", with message \"535 5.7.3 Authentication unsuccessful\".\". {\"userId\":",
        uid, ",\"email\":\"", g.email(victim, "personal"), "\",\"exception\":\"[object] (Symfony\\\\Component\\\\Mailer\\\\Exception\\\\TransportException(code: 535): Failed to authenticate on SMTP server with username \\\"",
        smtp_user, "\\\" using the following authenticators ... at ", root, "/vendor/symfony/mailer/Transport/Smtp/EsmtpTransport.php:",
        x.num(247), ")\n[stacktrace]\n", *stack, "\"} \n"))
    if r.random() < 0.5:
        q = d.person()
        log.append(T("[⟦t⟧] ⟦e⟧.WARNING: Login throttled {\"email\":\"⟦m⟧\",\"ip\":\"⟦ip⟧\",\"attempts\":5} \n",
                     t=x.ts("space", tick=(5, 300)), e=env_name, m=g.email(q, "personal"), ip=g.ip("any")))
    d.tool("sh", f"ssh deploy@{d.host} 'tail -n 80 {root}/storage/logs/laravel.log'", F(*log))
    d.agent(say(d, "explain"), " ",
            d.L(en="SMTP auth is rejected (535) for the mailbox configured as MAIL_USERNAME. Checking the mail settings in .env.",
                it="L'autenticazione SMTP viene rifiutata (535) per la casella configurata in MAIL_USERNAME. Controllo le impostazioni mail nel .env.",
                de="Die SMTP-Anmeldung wird für das in MAIL_USERNAME konfigurierte Postfach abgelehnt (535). Ich prüfe die Mail-Einstellungen in der .env.",
                fr="L'authentification SMTP est refusée (535) pour la boîte configurée dans MAIL_USERNAME. Je vérifie les réglages mail du .env.",
                es="El SMTP rechaza la autenticación (535) del buzón configurado en MAIL_USERNAME. Reviso la configuración de correo del .env."))
    dbname = r.choice(["shop", "crm", "portal", "app"])
    env = [
        T("APP_NAME=\"⟦c⟧\"\nAPP_ENV=production\n", c=d.company),
        T("APP_KEY=⟦k⟧\n", k=g.secret("app_key")),
        "APP_DEBUG=false\n", f"APP_URL=https://{d.domain}\n\n",
        "LOG_CHANNEL=daily\nLOG_LEVEL=info\n\n",
        T("DB_CONNECTION=mysql\nDB_HOST=⟦ip⟧\nDB_PORT=⟦pt⟧\nDB_DATABASE=⟦db⟧\nDB_USERNAME=⟦db⟧_app\nDB_PASSWORD=⟦pw⟧\n\n",
          ip=g.ip("private"), pt=x.port(3306), db=dbname, pw=g.password()),
        T("MAIL_MAILER=smtp\nMAIL_HOST=⟦h⟧\nMAIL_PORT=⟦pt⟧\nMAIL_USERNAME=⟦u⟧\nMAIL_PASSWORD=⟦pw⟧\nMAIL_ENCRYPTION=tls\n",
          h=host, pt=x.port(587), u=smtp_user, pw=g.password()),
        f"MAIL_FROM_ADDRESS=\"noreply@{d.domain}\"\nMAIL_FROM_NAME=\"${{APP_NAME}}\"\n",
    ]
    if r.random() < 0.5:
        env.append(T("\nAWS_ACCESS_KEY_ID=⟦a⟧\nAWS_SECRET_ACCESS_KEY=⟦s⟧\nAWS_DEFAULT_REGION=eu-central-1\nAWS_BUCKET=⟦b⟧-uploads\n",
                     a=g.secret("aws_akid"), s=g.secret("aws_secret"), b=d.slug))
    d.tool("sh", f"ssh deploy@{d.host} 'cat {root}/.env'", F(*env))
    d.agent(d.L(en="MAIL_USERNAME is a personal mailbox. If that account was disabled or its password changed, every reset mail fails. A shared/service sender is the safer setup.",
                it="MAIL_USERNAME è una casella personale. Se quell'account è stato disattivato o ha cambiato password, ogni mail di reset fallisce. Un mittente condiviso/di servizio è più sicuro.",
                de="MAIL_USERNAME ist ein persönliches Postfach. Wurde das Konto deaktiviert oder das Passwort geändert, scheitert jede Reset-Mail. Ein Service-Absender ist robuster.",
                fr="MAIL_USERNAME est une boîte personnelle. Si ce compte a été désactivé ou son mot de passe changé, chaque e-mail de réinitialisation échoue. Un expéditeur de service est plus sûr."))
    if mailbox_owner.female:
        left = d.L(en="Right, she left last week. IT made a service mailbox, password is ",
                   it="Giusto, se n'è andata la settimana scorsa. L'IT ha creato una casella di servizio, la password è ",
                   de="Stimmt, sie ist letzte Woche gegangen. Die IT hat ein Service-Postfach angelegt, Passwort ist ",
                   fr="Oui, elle est partie la semaine dernière. L'IT a créé une boîte de service, le mot de passe est ",
                   es="Cierto, se fue la semana pasada. IT creó un buzón de servicio, la contraseña es ")
    else:
        left = d.L(en="Right, he left last week. IT made a service mailbox, password is ",
                   it="Giusto, se n'è andato la settimana scorsa. L'IT ha creato una casella di servizio, la password è ",
                   de="Stimmt, er ist letzte Woche gegangen. Die IT hat ein Service-Postfach angelegt, Passwort ist ",
                   fr="Oui, il est parti la semaine dernière. L'IT a créé une boîte de service, le mot de passe est ",
                   es="Cierto, se fue la semana pasada. IT creó un buzón de servicio, la contraseña es ")
    d.user(left,
           g.password())
    d.tool("edit", ".env", F("-MAIL_USERNAME=", smtp_user, "\n+MAIL_USERNAME=noreply@", d.domain, "\n",
                             "-MAIL_PASSWORD=", x.ph(text="<previous>"), "\n+MAIL_PASSWORD=", x.ph(text="<new service password>"), "\n"))
    d.tool("sh", f"ssh deploy@{d.host} 'cd {root} && php artisan config:clear && php artisan config:cache && php artisan queue:retry all'",
           T("\n   INFO  Configuration cache cleared successfully.\n\n   INFO  Configuration cached successfully.\n\n"
             "   INFO  Pushing failed queue jobs back onto the queue.\n\n  ⟦u⟧ .......................... ⟦ms⟧ms DONE\n",
             u=x.uuid(), ms=f"{r.uniform(1, 40):.2f}"))
    d.agent(say(d, "done"), "\n- ", d.L(en="sender switched to the service mailbox, config cache rebuilt, failed jobs retried",
                                         it="mittente passato alla casella di servizio, cache di config ricostruita, job falliti rilanciati",
                                         de="Absender aufs Service-Postfach umgestellt, Config-Cache neu gebaut, fehlgeschlagene Jobs erneut eingereiht",
                                         fr="expéditeur basculé sur la boîte de service, cache de config reconstruit, jobs en échec relancés",
                                         es="remitente cambiado al buzón de servicio, caché de config regenerada, jobs fallidos relanzados"),
            "\n- ", d.L(en="the log also records requester e-mails and IPs at INFO level; consider dropping them",
                        it="il log registra anche email e IP dei richiedenti a livello INFO; valuterei di toglierli",
                        de="das Log enthält auf INFO-Level auch E-Mails und IPs der Anfragenden; die würde ich entfernen",
                        fr="le log enregistre aussi les e-mails et IP des demandeurs au niveau INFO ; à retirer"))


# ================================================================ 8. cargo build / test


@template("rust_cargo_build", "cc", "trace", "file")
def rust_cargo_build(d):
    g, x, r = d.g, d.x, d.rng
    crate = d.project
    a1, a2 = d.person(), d.person()
    owner = d.person()
    pline = r.randint(60, 160)
    tline = r.randint(170, 260)
    d.user(d.L(
        en="cargo build is broken after the serde/tokio bump. While you're at it, Cargo.toml still lists personal names and emails as authors; we're publishing to the internal registry, clean that up.",
        it="cargo build è rotto dopo l'aggiornamento di serde/tokio. Già che ci sei, Cargo.toml elenca ancora nomi ed email personali come autori; pubblichiamo sul registry interno, sistemalo.",
        de="cargo build ist seit dem serde/tokio-Bump kaputt. Und wenn du schon dabei bist: Cargo.toml listet noch persönliche Namen und E-Mails als Autoren; wir veröffentlichen in die interne Registry, bitte aufräumen.",
        fr="cargo build est cassé depuis la montée de version serde/tokio. Au passage, Cargo.toml liste encore des noms et e-mails personnels comme auteurs ; on publie sur le registre interne, nettoie ça.",
        es="cargo build está roto tras subir serde/tokio. Ya que estás, Cargo.toml aún lista nombres y emails personales como autores; publicamos en el registro interno, límpialo."))
    errs = [
        T("error[E0308]: mismatched types\n  --> src/ingest/parser.rs:⟦n⟧:24\n   |\n⟦n2⟧ |         let ts: i64 = record.timestamp;\n"
          "   |                 ---   ^^^^^^^^^^^^^^^^ expected `i64`, found `Option<i64>`\n   |                 |\n"
          "   |                 expected due to this\n   |\n   = note: expected type `i64`\n              found enum `Option<i64>`\n"
          "help: consider using `Option::expect` to unwrap the `Option<i64>` value, panicking if the value is an `Option::None`\n"
          "   |\n⟦n2⟧ |         let ts: i64 = record.timestamp.expect(\"REASON\");\n   |                                       +++++++++++++++++\n\n",
          n=x.num(pline), n2=str(pline)),
    ]
    if r.random() < 0.6:
        l2 = pline + r.randint(5, 30)
        errs.append(T("error[E0599]: no method named `as_deref` found for type `f64` in the current scope\n  --> src/ingest/parser.rs:⟦n⟧:31\n"
                      "   |\n⟦n2⟧ |         let lat = record.lat.as_deref();\n   |                               ^^^^^^^^ method not found in `f64`\n\n",
                      n=x.num(l2), n2=str(l2)))
    if r.random() < 0.4:
        l3 = r.randint(10, 50)
        errs.append(T("warning: unused import: `serde::de::Error`\n --> src/model.rs:⟦n⟧:5\n  |\n⟦n2⟧ | use serde::de::Error;\n  |     ^^^^^^^^^^^^^^^^\n"
                      "  |\n  = note: `#[warn(unused_imports)]` on by default\n\n", n=x.num(l3), n2=str(l3)))
    n_err = sum(1 for e in errs if e[0].text.startswith("error"))
    out = F(T("   Compiling ⟦c⟧ v⟦v⟧ (⟦cwd⟧)\n", c=crate, v=x.ver("0." + str(r.randint(1, 9)) + "." + str(r.randint(0, 9))), cwd=d.cwd()),
            *errs, "Some errors have detailed explanations: E0308", ", E0599" if n_err > 1 else "", ".\n",
            "For more information about an error, try `rustc --explain E0308`.\n",
            T("error: could not compile `⟦c⟧` (bin \"⟦c⟧\") due to ⟦n⟧ previous error⟦s⟧\n", c=crate, n=str(n_err),
              s="s" if n_err > 1 else ""))
    d.tool("sh", "cargo build", out)
    d.agent(d.L(en="The new schema made timestamp optional. I'll handle None explicitly instead of unwrapping.",
                it="Il nuovo schema rende timestamp opzionale. Gestisco esplicitamente None invece di fare unwrap.",
                de="Mit dem neuen Schema ist timestamp optional. Ich behandle None explizit statt zu unwrappen.",
                fr="Le nouveau schéma rend timestamp optionnel. Je gère None explicitement au lieu de faire un unwrap."))
    d.tool("edit", "src/ingest/parser.rs",
           F("-        let ts: i64 = record.timestamp;\n+        let ts = record.timestamp.unwrap_or_else(|| received_at.timestamp_millis());\n",
             "-        let lat = record.lat.as_deref();\n+        let lat = record.lat;\n" if n_err > 1 else ""))
    dev = g.raw("private_ip", V.ipv4_private(r), "generic") if r.random() < 0.3 else x.id("dev-" + V.rand_str(r, V.HEX, 8))
    lat, lon = g.geo_parts(owner)
    mac = g.mac(0)
    owner_mail = g.email(owner, "personal")
    epoch = x.ts("epoch_ms", tick=(0, 1))
    n_tests = r.randint(4, 18)
    test_out = F(
        T("   Compiling ⟦c⟧ v⟦v⟧ (⟦cwd⟧)\n    Finished `test` profile [unoptimized + debuginfo] target(s) in ⟦s⟧s\n", c=crate,
          v=x.ver("0.4.2"), cwd=d.cwd(), s=f"{r.uniform(2, 40):.2f}"),
        T("     Running unittests src/main.rs (target/debug/deps/⟦c⟧-⟦h⟧)\n\nrunning ⟦n⟧ tests\n", c=crate.replace("-", "_"),
          h=x.short(16), n=str(n_tests)),
        "test ingest::parser::tests::parses_minimal ... ok\n",
        "test ingest::parser::tests::parses_device_record ... FAILED\n",
        "test ingest::parser::tests::rejects_garbage ... ok\n",
        "\nfailures:\n\n---- ingest::parser::tests::parses_device_record stdout ----\n",
        T("thread 'ingest::parser::tests::parses_device_record' panicked at src/ingest/parser.rs:⟦n⟧:9:\n", n=x.num(tline)),
        "assertion `left == right` failed\n",
        "  left: Record { device: ", dev if isinstance(dev, Seg) else dev, ", owner: \"", owner_mail, "\", mac: \"", mac,
        "\", lat: ", lat, ", lon: ", lon, ", timestamp: Some(", epoch, ") }\n",
        " right: Record { device: ", dev, ", owner: \"", owner_mail, "\", mac: \"", mac,
        "\", lat: ", lat, ", lon: ", lon, ", timestamp: None }\n",
        "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\n\n\nfailures:\n",
        "    ingest::parser::tests::parses_device_record\n\n",
        T("test result: FAILED. ⟦a⟧ passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in ⟦s⟧s\n\n",
          a=str(n_tests - 1), s=f"{r.uniform(0.0, 0.5):.2f}"),
        "error: test failed, to rerun pass `--bin ", crate, "`\n")
    d.tool("sh", "cargo test", test_out)
    d.agent(d.L(en="That test asserted the old behaviour (missing timestamp stays None). With the fallback the expectation changes; updating the test to use a fixed received_at.",
                it="Quel test verificava il vecchio comportamento (timestamp mancante resta None). Con il fallback l'aspettativa cambia; aggiorno il test usando un received_at fisso.",
                de="Der Test prüfte das alte Verhalten (fehlender Timestamp bleibt None). Mit dem Fallback ändert sich die Erwartung; ich passe den Test mit festem received_at an.",
                fr="Ce test vérifiait l'ancien comportement (timestamp absent reste None). Avec le repli l'attente change ; je mets à jour le test avec un received_at fixe."))
    d.tool("edit", "src/ingest/parser.rs",
           F("-        assert_eq!(parse_line(LINE).unwrap(), expected(None));\n",
             "+        let rx = Utc.timestamp_millis_opt(RECEIVED_AT).unwrap();\n",
             "+        assert_eq!(parse_line_at(LINE, rx).unwrap(), expected(Some(RECEIVED_AT)));\n"))
    toml = F(
        "[package]\n", f'name = "{crate}"\n', T('version = "⟦v⟧"\n', v=x.ver("0.4.2")), 'edition = "2021"\n',
        'authors = [\n', T('    "⟦n⟧ <⟦e⟧>",\n', n=g.name(a1), e=g.email(a1, "work")),
        T('    "⟦n⟧ <⟦e⟧>",\n', n=g.name(a2), e=g.email(a2, r.choice(["work", "personal"]))), "]\n",
        'description = "Device telemetry ingestion"\n',
        T('repository = "⟦u⟧"\n', u=g.url("repo", a1)),
        'license = "LicenseRef-Proprietary"\n', T('publish = ["⟦s⟧"]\n\n', s=d.slug),
        "[dependencies]\n",
        T('serde = { version = "⟦a⟧", features = ["derive"] }\nserde_json = "⟦b⟧"\n', a=x.ver("1.0.210"), b=x.ver("1.0.128")),
        T('tokio = { version = "⟦a⟧", features = ["full"] }\nchrono = { version = "⟦b⟧", features = ["serde"] }\n',
          a=x.ver("1.40"), b=x.ver("0.4.38")),
        T('thiserror = "⟦a⟧"\ntracing = "⟦b⟧"\n', a=x.ver("1.0.64"), b=x.ver("0.1.40")))
    d.tool("read", "Cargo.toml", toml)
    d.tool("edit", "Cargo.toml",
           F("-authors = [\n-    \"", g.name(a1), " <", g.email(a1, "work"), ">\",\n-    \"", g.name(a2), " <...>\",\n-]\n",
             "+authors = [\"Platform Team <platform@", d.domain, ">\"]\n"))
    d.tool("sh", "cargo test 2>&1 | tail -n 3",
           T("test result: ok. ⟦n⟧ passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in ⟦s⟧s\n\n", n=str(n_tests),
             s=f"{r.uniform(0.0, 0.5):.2f}"))
    d.agent(say(d, "done"), "\n- ", d.L(en="missing timestamps fall back to receive time", it="i timestamp mancanti usano l'orario di ricezione",
                                         de="fehlende Timestamps fallen auf die Empfangszeit zurück", fr="les timestamps manquants retombent sur l'heure de réception"),
            "\n- ", d.L(en="authors replaced by the team address", it="autori sostituiti con l'indirizzo del team",
                        de="Autoren durch die Team-Adresse ersetzt", fr="auteurs remplacés par l'adresse de l'équipe"),
            ("\n- " + d.L(en="the test fixture still contains an owner e-mail, MAC and coordinates; consider synthetic values",
                          it="la fixture del test contiene ancora email, MAC e coordinate di un proprietario; meglio valori sintetici",
                          de="die Test-Fixture enthält noch E-Mail, MAC und Koordinaten eines Besitzers; besser synthetische Werte",
                          fr="la fixture de test contient encore l'e-mail, la MAC et les coordonnées d'un propriétaire ; mieux vaut des valeurs synthétiques"))
            if d.gold_ok else "")


# ================================================================ 9. Android logcat crash


def _logcat_ts(d, lo: float = 0.0, hi: float = 0.4) -> Seg:
    t = _now(d, lo, hi)
    return _mts(t.strftime("%m-%d %H:%M:%S.") + f"{t.microsecond // 1000:03d}")


@template("android_crash_location", "xml", "trace", "log")
def android_crash_location(d):
    g, x, r = d.g, d.x, d.rng
    pkg = f"com.{d.slug}.{r.choice(['fleet', 'driver', 'courier', 'field'])}"
    ver = r.choice(["3.14.0", "3.14.1", "4.2.0", "2.9.3"])
    code = ver.replace(".", "") + "0"
    pid, tid = r.randint(2000, 32000), 0
    tid = pid
    driver = d.person()
    line = r.randint(50, 140)
    d.user(d.L(
        en=f"Since {ver} the app crashes on start for some drivers. QA attached a logcat dump to the ticket, it's in crash/. Can you find the cause?",
        it=f"Dalla {ver} l'app crasha all'avvio per alcuni autisti. Il QA ha allegato un logcat al ticket, è in crash/. Trovi la causa?",
        de=f"Seit {ver} stürzt die App bei manchen Fahrern beim Start ab. QA hat einen Logcat-Dump ans Ticket gehängt, liegt in crash/. Findest du die Ursache?",
        fr=f"Depuis la {ver}, l'appli plante au démarrage chez certains chauffeurs. La QA a joint un dump logcat au ticket, il est dans crash/. Tu trouves la cause ?",
        es=f"Desde la {ver} la app se cierra al arrancar a algunos conductores. QA adjuntó un logcat al ticket, está en crash/. ¿Encuentras la causa?"))
    first = ("I", "ActivityManager", F(f"Start proc {pid}:{pkg}/u0a{r.randint(100, 400)} for pre-top-activity {{{pkg}/.MainActivity}}"))
    noise = [
        [("D", "CrashReporter", F("setCustomKey(\"app_version\", \"", x.ver(ver), " (", code, ")\")"))],
        [("D", "CrashReporter", F("setUserId(\"", g.cust(), "\")")),
         ("D", "CrashReporter", F("setCustomKey(\"user_email\", \"", g.email(driver, r.choice(["work", "personal"])), "\")"))],
        [("I", "BleScanner", F("Connected to OBD-II dongle ", g.mac(r.choice([1, 2])), " (RSSI -", str(r.randint(40, 90)), ")"))],
        [("D", "TripService", F("resuming trip ", x.uuid(), " vehicle=", g.plate(driver), " driver=", g.name(driver)))],
        [("I", "chatty", F("uid=10312(", pkg, ") identical ", str(r.randint(2, 40)), " lines"))],
        [("D", "OkHttp", F("--> GET https://api.", d.domain, "/v2/assignments?since=", x.ts("epoch", tick=(0, 0.1)))),
         ("D", "OkHttp", F("<-- 200 OK https://api.", d.domain, "/v2/assignments (", str(r.randint(80, 900)), "ms)"))],
        [("W", "FusedLocation", F("location settings check failed, falling back to lastKnown"))],
    ]
    r.shuffle(noise)
    noise = [first] + [e for grp in noise for e in grp]
    stale_s = r.randint(40000, 900000)
    loc_line = ("D", "LocationRepository", F("lastKnown=Location[fused ", g.geo(driver, sep=","), " hAcc=", f"{r.uniform(3, 40):.1f}",
                                            " et=+", str(stale_s // 86400), "d", str((stale_s % 86400) // 3600), "h alt=",
                                            f"{r.uniform(5, 600):.1f}", " vAcc=", str(r.randint(2, 30)), "]"))
    pool = [("Choreographer", "Skipped 34 frames!  The application may be doing too much work on its main thread."),
            ("OpenGLRenderer", "Davey! duration=812ms; Flags=1, FrameTimelineVsyncId=4417"),
            ("EGL_emulation", "Initialized EGL, version 1.4"),
            ("WM-WorkerWrapper", "Worker result SUCCESS for Work [ id=SyncWorker, tags={ periodic } ]"),
            ("SyncRepository", "Sync: assignments up to date"),
            ("ViewRootImpl", "Relayout returned: old=[0,0][1080,2400] new=[0,0][1080,2400]"),
            ("ProfileInstaller", "Installing profile for " + pkg),
            ("Room", "Opened database fleet.db (version 14)")]
    extra = []
    if r.random() < 0.45:
        for _ in range(r.randint(40, 90) if r.random() < 0.4 else r.randint(6, 30)):
            tg, msg = r.choice(pool)
            extra.append((r.choice("DIV"), tg, F(msg)))
    entries = noise + extra + [loc_line, ("W", "LocationRepository", F("last fix is ", str(stale_s), "s old, rejecting"))]
    rows = ["--------- beginning of main\n"]
    for lvl, tag, msg in entries:
        t2 = r.randint(pid, pid + 60) if r.random() < 0.4 else pid
        rows.append(F(_logcat_ts(d, 0.0, 0.6), f"  {pid:5d}  {t2:5d} {lvl} {tag}: ", msg, "\n"))
    rows.append("--------- beginning of crash\n")
    crash_frames = [
        (f"{pkg}.tracking.LocationRepository.lastFix", "LocationRepository.kt", line),
        (f"{pkg}.tracking.TripResumer.resume", "TripResumer.kt", r.randint(20, 90)),
        (f"{pkg}.MainViewModel$onStart$1.invokeSuspend", "MainViewModel.kt", r.randint(40, 200)),
        ("kotlin.coroutines.jvm.internal.BaseContinuationImpl.resumeWith", "ContinuationImpl.kt", 33),
        ("kotlinx.coroutines.DispatchedTask.run", "DispatchedTask.kt", 108),
        ("android.os.Handler.handleCallback", "Handler.java", 958),
        ("android.os.Handler.dispatchMessage", "Handler.java", 99),
        ("android.os.Looper.loopOnce", "Looper.java", 205),
        ("android.os.Looper.loop", "Looper.java", 294),
        ("android.app.ActivityThread.main", "ActivityThread.java", 8177),
        ("java.lang.reflect.Method.invoke", "Native Method", None),
        ("com.android.internal.os.RuntimeInit$MethodAndArgsCaller.run", "RuntimeInit.java", 552),
        ("com.android.internal.os.ZygoteInit.main", "ZygoteInit.java", 971),
    ]
    ts = _logcat_ts(d, 0.01, 0.2)
    head = [F("FATAL EXCEPTION: main"), F("Process: ", pkg, ", PID: ", str(pid)),
            F("java.lang.IllegalStateException: Last known location is stale (age=", str(stale_s), "s)")]
    for h in head:
        rows.append(F(ts, f"  {pid:5d}  {pid:5d} E AndroidRuntime: ", h, "\n"))
    for fn, f, n in crash_frames:
        loc = F(f, ":", x.num(n)) if n else F(f)
        rows.append(F(ts, f"  {pid:5d}  {pid:5d} E AndroidRuntime: \tat ", fn, "(", loc, ")\n"))
    rows.append(F(_logcat_ts(d, 0.05, 0.3), f"  {pid:5d}  {pid:5d} I Process: Sending signal. PID: {pid} SIG: 9\n"))
    fname = F("crash/logcat-", x.ts("date"), ".txt")
    d.tool("read", fname, F(*rows))
    d.agent(d.L(en="The crash is an explicit check() in LocationRepository.lastFix: the fused provider returns a fix that is days old (device was off), and the code throws instead of requesting a fresh one.",
                it="Il crash è un check() esplicito in LocationRepository.lastFix: il provider fused restituisce una posizione vecchia di giorni (dispositivo spento) e il codice lancia un'eccezione invece di chiederne una nuova.",
                de="Der Absturz ist ein explizites check() in LocationRepository.lastFix: Der Fused Provider liefert einen tagealten Fix (Gerät war aus), und der Code wirft, statt einen frischen anzufordern.",
                fr="Le crash vient d'un check() explicite dans LocationRepository.lastFix : le fournisseur fused renvoie une position vieille de plusieurs jours (appareil éteint) et le code lève une exception au lieu d'en demander une nouvelle."))
    src = F("    suspend fun lastFix(): Location {\n", "        val loc = fused.lastLocation.await()\n",
            "            ?: return requestFresh()\n", "        val age = SystemClock.elapsedRealtimeNanos() - loc.elapsedRealtimeNanos\n",
            "        check(age < MAX_AGE_NANOS) { \"Last known location is stale (age=${age / 1_000_000_000}s)\" }\n",
            "        return loc\n", "    }\n")
    d.tool("read", f"app/src/main/java/{pkg.replace('.', '/')}/tracking/LocationRepository.kt", numbered(src, start=line - 4, width=5, sep=" "))
    d.tool("edit", f"app/src/main/java/{pkg.replace('.', '/')}/tracking/LocationRepository.kt",
           F("-        check(age < MAX_AGE_NANOS) { \"Last known location is stale (age=${age / 1_000_000_000}s)\" }\n-        return loc\n",
             "+        return if (age < MAX_AGE_NANOS) loc else requestFresh(timeout = 10.seconds)\n"))
    if d.gold_ok and r.random() < 0.7:
        d.agent(d.L(en="Also, the crash reporter gets the driver's e-mail as a custom key, and the location line logs precise coordinates at DEBUG. I'd drop both.",
                    it="Inoltre il crash reporter riceve l'email dell'autista come chiave custom, e la riga della posizione logga coordinate precise in DEBUG. Toglierei entrambe.",
                    de="Außerdem bekommt der Crash-Reporter die E-Mail des Fahrers als Custom Key, und die Standortzeile loggt genaue Koordinaten auf DEBUG. Beides würde ich entfernen.",
                    fr="Par ailleurs, le crash reporter reçoit l'e-mail du chauffeur comme clé personnalisée, et la ligne de position logge des coordonnées précises en DEBUG. Je retirerais les deux."))
        d.tool("edit", f"app/src/main/java/{pkg.replace('.', '/')}/CrashReporting.kt",
               F("-        reporter.setCustomKey(\"user_email\", session.email)\n",
                 "-        Log.d(TAG, \"lastKnown=$loc\")\n+        Log.d(TAG, \"lastKnown age=${age}ns acc=${loc.accuracy}\")\n"))
    d.tool("sh", "./gradlew :app:testDebugUnitTest --console=plain | tail -n 5",
           T("> Task :app:testDebugUnitTest\n\nBUILD SUCCESSFUL in ⟦s⟧s\n⟦n⟧ actionable tasks: ⟦e⟧ executed, ⟦u⟧ up-to-date\n",
             s=str(r.randint(12, 140)), n=str(r.randint(20, 60)), e=str(r.randint(3, 12)), u=str(r.randint(10, 40))))
    d.agent(say(d, "done"), "\n- ", d.L(en="stale last-known location now triggers a fresh request instead of a crash",
                                         it="una posizione vecchia ora provoca una nuova richiesta invece del crash",
                                         de="veralteter Standort löst jetzt eine neue Anfrage statt eines Absturzes aus",
                                         fr="une position périmée déclenche maintenant une nouvelle demande au lieu d'un crash"))


# ================================================================ 10. Sentry event via API


def _jind(n: int) -> str:
    return "  " * n


@template("sentry_issue_event", "md", "trace", "http")
def sentry_issue_event(d):
    g, x, r = d.g, d.x, d.rng
    p = d.person()
    proj = d.project
    short = x.id(f"{proj.upper()}-{V.rand_str(r, 'ABCDEFGHJKLMNPQRSTUVWXYZ0123456789', 3)}")
    issue_id = str(r.randint(10**9, 6 * 10**9))
    selfhosted = r.random() < 0.4
    base = f"https://sentry.{d.int_domain}" if selfhosted else "https://sentry.io"
    org = d.slug
    literal = r.random() < 0.5
    tok = g.raw("secret", "sntryu_" + V.rand_str(r, V.HEX, 64), "token") if literal else x.ph(text="$SENTRY_AUTH_TOKEN")
    if literal:
        d.user(d.L(en="Can you triage Sentry issue ", it="Puoi fare il triage della issue Sentry ", de="Kannst du das Sentry-Issue ",
                   fr="Tu peux trier l'issue Sentry ", es="¿Puedes hacer el triage de la incidencia de Sentry "), short,
               d.L(en="? Use this token for the API: ", it="? Usa questo token per l'API: ", de=" triagieren? Nimm dieses Token für die API: ",
                   fr=" ? Utilise ce jeton pour l'API : ", es="? Usa este token para la API: "), tok)
    else:
        d.user(d.L(en="Can you triage Sentry issue ", it="Puoi fare il triage della issue Sentry ", de="Kannst du das Sentry-Issue ",
                   fr="Tu peux trier l'issue Sentry ", es="¿Puedes hacer el triage de la incidencia de Sentry "), short,
               d.L(en="? API token is in SENTRY_AUTH_TOKEN.", it="? Il token API è in SENTRY_AUTH_TOKEN.",
                   de=" triagieren? Das API-Token steht in SENTRY_AUTH_TOKEN.", fr=" ? Le jeton d'API est dans SENTRY_AUTH_TOKEN.",
                   es="? El token de la API está en SENTRY_AUTH_TOKEN."))
    issue_url = g.raw("private_url", f"{base}/api/0/organizations/{org}/issues/{issue_id}/", "url")
    perma = g.raw("private_url", (f"{base}/organizations/{org}/issues/{issue_id}/" if selfhosted
                                  else f"https://{org}.sentry.io/issues/{issue_id}/"), "url")
    first = d.clock.t - dt.timedelta(hours=r.randint(3, 80), microseconds=r.randint(0, 999999))
    count, users = r.randint(15, 4000), r.randint(3, 400)
    ver = x.ver()
    summary = F(
        "{\n",
        '  "shortId": "', short, '",\n',
        '  "title": "KeyError: \'vat_number\'",\n',
        '  "culprit": "billing.pdf in render_invoice",\n',
        '  "count": "', str(count), '",\n',
        '  "userCount": ', str(users), ",\n",
        '  "firstSeen": "', x.ts("iso_us", t=first), '",\n',
        '  "lastSeen": "', x.ts("iso_us", tick=(0, 5)), '",\n',
        '  "permalink": "', perma, '"\n',
        "}\n")
    d.tool("sh", F('curl -s -H "Authorization: Bearer ', tok, '" ', issue_url,
                   " | jq '{shortId, title, culprit, count, userCount, firstSeen, lastSeen, permalink}'"), summary)
    d.agent(d.L(en="Now the latest event, keeping only the parts we need.", it="Ora l'ultimo evento, tenendo solo le parti utili.",
                de="Jetzt das letzte Event, nur mit den nötigen Teilen.", fr="Maintenant le dernier événement, en ne gardant que l'utile.",
                es="Ahora el último evento, solo con lo necesario."))
    cust_id = str(r.randint(100, 99999))
    inv = x.id(f"INV-{r.randint(2024, 2026)}-{r.randint(1, 99999):05d}")
    email = g.email(p, "personal")
    ip = g.ip(r.choice(["public", "public", "v6"]))
    req_url = F(g.raw("private_url", f"https://app.{d.domain}/api/invoices/{inv.text}/pdf", "url"))
    crumbs = []
    n_crumbs = r.randint(3, 14)
    for i in range(n_crumbs):
        kind = r.choice(["query", "query", "http", "log", "nav"])
        tsx = x.ts("iso_z", tick=(0.01, 2))
        if kind == "query":
            msg = F(r.choice(['SELECT \\"invoices\\".\\"id\\", \\"invoices\\".\\"customer_id\\", \\"invoices\\".\\"total\\" FROM \\"invoices\\" WHERE \\"invoices\\".\\"number\\" = %s',
                              'SELECT \\"customers\\".\\"id\\", \\"customers\\".\\"name\\", \\"customers\\".\\"address\\" FROM \\"customers\\" WHERE \\"customers\\".\\"id\\" = %s',
                              'SELECT \\"invoice_lines\\".* FROM \\"invoice_lines\\" WHERE \\"invoice_lines\\".\\"invoice_id\\" = %s ORDER BY \\"position\\"']))
            crumbs.append(F('    {"timestamp": "', tsx, '", "category": "query", "message": "', msg, '"}'))
        elif kind == "http":
            crumbs.append(F('    {"timestamp": "', tsx, '", "category": "httplib", "data": {"method": "GET", "url": "',
                            x.url(text="https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"), '", "status_code": 200}}'))
        elif kind == "log":
            crumbs.append(F('    {"timestamp": "', tsx, '", "category": "billing.pdf", "level": "info", "message": "Rendering invoice ',
                            inv, ' for ', g.name(p), '"}'))
        else:
            crumbs.append(F('    {"timestamp": "', tsx, '", "category": "django.request", "message": "GET /api/invoices/', inv, '/pdf"}'))
    ev = ["{\n", F('  "eventID": "', x.short(32), '",\n'), F('  "dateCreated": "', x.ts("iso_z"), '",\n'),
          '  "user": {\n', F('    "id": "', cust_id, '",\n'),
          F('    "email": "', email, '",\n'), F('    "ip_address": "', ip, '",\n'),
          F('    "username": "', g.user(p), '"\n'), "  },\n",
          '  "request": {\n', F('    "url": "', req_url, '",\n'), '    "method": "GET",\n', '    "headers": [\n',
          '      ["Accept", "application/pdf"],\n',
          F('      ["Cookie", "csrftoken=', g.raw("secret", V.rand_str(r, V.ALNUM, 32), "token"), '; sessionid=', g.secret("session"), '"],\n'),
          F('      ["Referer", "', g.url("user_resource", p), '"],\n'),
          '      ["User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"],\n',
          F('      ["X-Forwarded-For", "', ip, '"]\n'), "    ]\n", "  },\n",
          '  "tags": [\n', '    {"key": "environment", "value": "production"},\n',
          F('    {"key": "release", "value": "', proj, "@", ver, '"},\n'),
          F('    {"key": "server_name", "value": "', d.host, '"},\n'),
          F('    {"key": "user", "value": "email:', email, '"}\n'), "  ],\n",
          '  "breadcrumbs": [\n']
    ev.append(J(",\n", crumbs))
    ln_view, ln_pdf = r.randint(30, 120), r.randint(60, 200)
    ev += ["\n  ],\n", '  "frames": [\n',
           F('    {"filename": "django/core/handlers/base.py", "function": "_get_response", "lineNo": ', x.num(197), "},\n"),
           F('    {"filename": "billing/views.py", "function": "invoice_pdf", "lineNo": ', x.num(ln_view),
             ', "context_line": "    pdf = render_invoice(invoice, customer)"},\n'),
           F('    {"filename": "billing/pdf.py", "function": "render_invoice", "lineNo": ', x.num(ln_pdf),
             ', "context_line": "    vat = customer[\\"vat_number\\"]",\n',
             '     "vars": {"customer": {"id": ', cust_id, ', "name": "', g.name(p), '", "address": "', g.addr(p),
             '", "kind": "individual"}, "invoice": "<Invoice: ', inv, '>"}}\n'),
           "  ]\n}\n"]
    jq = ("'{eventID, dateCreated, user, request: {url: .request.url, method: .request.method, headers: .request.headers}, tags, "
          "breadcrumbs: [.entries[] | select(.type==\"breadcrumbs\") | .data.values[-" + str(n_crumbs) + ":][]], "
          "frames: [.entries[] | select(.type==\"exception\") | .data.values[0].stacktrace.frames[-3:][]]}'")
    ev_url = g.raw("private_url", f"{base}/api/0/organizations/{org}/issues/{issue_id}/events/latest/", "url")
    d.tool("sh", F('curl -s -H "Authorization: Bearer ', tok, '" ', ev_url, " | jq ", jq), F(*ev))
    d.agent(say(d, "explain"), "\n\n",
            d.L(en="Customers of kind \"individual\" (created by the new self-signup flow) have no VAT number, and render_invoice indexes it unconditionally.",
                it="I clienti di tipo \"individual\" (creati dal nuovo flusso di self-signup) non hanno partita IVA, e render_invoice la legge senza controlli.",
                de="Kunden vom Typ \"individual\" (aus dem neuen Self-Signup) haben keine USt-IdNr., und render_invoice greift ohne Prüfung darauf zu.",
                fr="Les clients de type \"individual\" (créés par le nouveau parcours d'inscription) n'ont pas de numéro de TVA, et render_invoice y accède sans condition.",
                es="Los clientes de tipo \"individual\" (del nuevo alta autónoma) no tienen NIF-IVA y render_invoice lo lee sin comprobar."))
    src = F("def render_invoice(invoice, customer):\n", "    ctx = base_context(invoice)\n", "    vat = customer[\"vat_number\"]\n",
            "    ctx[\"vat_line\"] = _(\"VAT no. %s\") % vat\n", "    return html_to_pdf(\"invoice.html\", ctx)\n")
    d.tool("read", "billing/pdf.py", numbered(src, start=ln_pdf - 2, width=5, sep="\t"))
    d.tool("edit", "billing/pdf.py",
           F("-    vat = customer[\"vat_number\"]\n-    ctx[\"vat_line\"] = _(\"VAT no. %s\") % vat\n",
             "+    vat = customer.get(\"vat_number\")\n+    ctx[\"vat_line\"] = _(\"VAT no. %s\") % vat if vat else \"\"\n"))
    d.tool("sh", "pytest tests/billing -q",
           T("⟦a⟧ passed, 1 warning in ⟦s⟧s\n", a=str(r.randint(12, 140)), s=f"{r.uniform(0.8, 12):.2f}"))
    tail = [say(d, "done"), "\n\n",
            "- ", d.L(en="cause: VAT number missing for private customers", it="causa: partita IVA assente per i clienti privati",
                      de="Ursache: fehlende USt-IdNr. bei Privatkunden", fr="cause : numéro de TVA absent pour les particuliers",
                      es="causa: falta el NIF-IVA en clientes particulares"),
            "\n- ", d.L(en="impact: ", it="impatto: ", de="Auswirkung: ", fr="impact : ", es="impacto: "), str(users),
            d.L(en=" users, ", it=" utenti, ", de=" Nutzer, ", fr=" utilisateurs, ", es=" usuarios, "), str(count),
            d.L(en=" events since release ", it=" eventi dalla release ", de=" Events seit Release ", fr=" événements depuis la release ",
                es=" eventos desde la release "), ver]
    d.agent(*tail)
    if r.random() < 0.65:
        d.agent(d.L(en="One more thing: the event carries e-mail, IP, cookies and a postal address because send_default_pii is on. I'd turn it off.",
                    it="Un'altra cosa: l'evento contiene email, IP, cookie e indirizzo postale perché send_default_pii è attivo. Lo disattiverei.",
                    de="Noch etwas: Das Event enthält E-Mail, IP, Cookies und Postadresse, weil send_default_pii aktiv ist. Ich würde es abschalten.",
                    fr="Autre chose : l'événement contient e-mail, IP, cookies et adresse postale parce que send_default_pii est activé. Je le désactiverais."))
        dsn = g.secret("sentry_dsn") if r.random() < 0.5 else None
        d.tool("edit", "config/settings/production.py",
               F(" sentry_sdk.init(\n",
                 F('     dsn="', dsn, '",\n') if dsn is not None else '     dsn=os.environ["SENTRY_DSN"],\n',
                 "     integrations=[DjangoIntegration()],\n-    send_default_pii=True,\n+    send_default_pii=False,\n"))


# ================================================================ 11. Celery retries


@template("python_celery_retry", "colon", "trace", "log")
def python_celery_retry(d):
    g, x, r = d.g, d.x, d.rng
    app = r.choice(["billing", "invoicing", "notifications"])
    task_fn = r.choice(["send_invoice_email", "email_invoice", "send_receipt"])
    task = f"{app}.tasks.{task_fn}"
    sender = d.person()
    smtp_user = g.email(sender, "work")
    worker_cmd = r.choice(["docker compose logs --no-log-prefix --tail=150 worker",
                           "journalctl -u celery-worker -n 150 --no-pager -o cat"])
    d.user(d.L(
        en=f"Invoice emails are stuck. Celery keeps retrying {task_fn}. Can you look at the worker log and tell me what's wrong?",
        it=f"Le email delle fatture sono bloccate. Celery continua a ritentare {task_fn}. Guardi il log del worker e mi dici cosa non va?",
        de=f"Die Rechnungs-Mails hängen. Celery wiederholt {task_fn} ständig. Schaust du ins Worker-Log und sagst mir, was los ist?",
        fr=f"Les e-mails de facture sont bloqués. Celery relance {task_fn} en boucle. Tu regardes le log du worker et tu me dis ce qui cloche ?",
        es=f"Los emails de facturas están atascados. Celery reintenta {task_fn} sin parar. ¿Miras el log del worker y me dices qué pasa?"))
    d.agent(say(d, "logs_window"))

    def stamp(lo=0.01, hi=3.0):
        return x.ts("space_ms", tick=(lo, hi))

    gurl = x.url(text="https://support.google.com/mail/?p=BadCredentials")
    resp = F("b'5.7.8 Username and Password not accepted. For more information, go to\\n5.7.8  ", gurl, " ",
             V.rand_str(r, "abcdefghijklmnopqrstuvwxyz0123456789", 16), " - gsmtp'")
    log = []
    n_jobs = r.randint(10, 17) if r.random() < 0.25 else r.randint(2, 8)
    last_uuid = None
    for i in range(n_jobs):
        c = d.person()
        tid = x.uuid()
        last_uuid = tid
        worker = f"ForkPoolWorker-{r.randint(1, 8)}"
        inv = x.id(f"INV-{r.randint(2024, 2026)}-{r.randint(1, 99999):05d}")
        log.append(F("[", stamp(1, 40), ": INFO/MainProcess] Task ", task, "[", tid, "] received\n"))
        log.append(F("[", stamp(), f": WARNING/{worker}] {task_fn}: sending ", inv, " to ",
                     _pydict([("name", g.name(c)), ("email", g.email(c, "personal")), ("iban", g.iban(p=c, printed=False)),
                              ("amount", f"{r.uniform(9, 2400):.2f}")]), "\n"))
        log.append(F("[", stamp(), f": INFO/{worker}] Task ", task, "[", tid, "] retry: Retry in ", str(r.choice([60, 120, 300])),
                     "s: SMTPAuthenticationError(535, ", resp, ")\n"))
    w = f"ForkPoolWorker-{r.randint(1, 8)}"
    ln_login, ln_retry = r.randint(40, 70), r.randint(71, 90)
    tb = F("[", stamp(5, 90), f": ERROR/{w}] Task ", task, "[", last_uuid, "] raised unexpected: SMTPAuthenticationError(535, ", resp, ")\n",
           "Traceback (most recent call last):\n",
           '  File "/app/.venv/lib/python3.12/site-packages/celery/app/trace.py", line ', x.num(453), ", in trace_task\n",
           "    R = retval = fun(*args, **kwargs)\n                 ^^^^^^^^^^^^^^^^^^^^\n",
           '  File "/app/.venv/lib/python3.12/site-packages/celery/app/trace.py", line ', x.num(736), ", in __protected_call__\n",
           "    return self.run(*args, **kwargs)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^\n",
           f'  File "/app/{app}/tasks.py", line ', x.num(ln_retry), f", in {task_fn}\n",
           "    raise self.retry(exc=exc, countdown=60)\n",
           '  File "/app/.venv/lib/python3.12/site-packages/celery/app/task.py", line ', x.num(743), ", in retry\n",
           "    raise_with_context(exc)\n",
           f'  File "/app/{app}/tasks.py", line ', x.num(ln_login), f", in {task_fn}\n",
           "    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)\n",
           '  File "/usr/local/lib/python3.12/smtplib.py", line ', x.num(750), ", in login\n", "    raise last_exception\n",
           '  File "/usr/local/lib/python3.12/smtplib.py", line ', x.num(739), ", in login\n",
           "    (code, resp) = self.auth(\n                   ^^^^^^^^^^\n",
           '  File "/usr/local/lib/python3.12/smtplib.py", line ', x.num(662), ", in auth\n",
           "    raise SMTPAuthenticationError(code, resp)\n",
           "smtplib.SMTPAuthenticationError: (535, ", resp, ")\n")
    log.append(tb)
    d.tool("sh", worker_cmd, F(*log))
    d.agent(d.L(en="Every task fails at smtp.login with 535, so it's the credentials, not the payload. Checking what the running worker actually has in its environment.",
                it="Ogni task fallisce su smtp.login con 535, quindi sono le credenziali, non il payload. Controllo cosa ha davvero nell'ambiente il worker in esecuzione.",
                de="Jeder Task scheitert bei smtp.login mit 535, also liegt es an den Zugangsdaten, nicht am Payload. Ich prüfe, was der laufende Worker tatsächlich in der Umgebung hat.",
                fr="Chaque tâche échoue sur smtp.login avec 535 : ce sont les identifiants, pas le contenu. Je vérifie ce que le worker en cours a réellement dans son environnement."))
    old_pw = g.password()
    d.tool("sh", "docker compose exec worker env | grep -E '^SMTP_'",
           T("SMTP_HOST=smtp.gmail.com\nSMTP_PORT=⟦p⟧\nSMTP_USER=⟦u⟧\nSMTP_PASSWORD=⟦pw⟧\n", p=x.port(587), u=smtp_user, pw=old_pw))
    new_pw = g.password()
    d.tool("sh", "grep -n '^SMTP_' .env", T("⟦a⟧:SMTP_HOST=smtp.gmail.com\n⟦b⟧:SMTP_PORT=587\n⟦c⟧:SMTP_USER=⟦u⟧\n⟦e⟧:SMTP_PASSWORD=⟦pw⟧\n",
                                            a=x.num(14), b=x.num(15), c=x.num(16), e=x.num(17), u=smtp_user, pw=new_pw))
    d.agent(say(d, "explain"), " ",
            d.L(en="The .env already has the new app password, but `docker compose restart` doesn't re-read env_file, so the worker still runs with the old one. It needs to be recreated.",
                it="Il .env ha già la nuova app password, ma `docker compose restart` non rilegge env_file, quindi il worker gira ancora con quella vecchia. Va ricreato.",
                de="Die .env enthält schon das neue App-Passwort, aber `docker compose restart` liest env_file nicht neu ein; der Worker läuft also mit dem alten. Er muss neu erstellt werden.",
                fr="Le .env contient déjà le nouveau mot de passe d'application, mais `docker compose restart` ne relit pas env_file : le worker tourne toujours avec l'ancien. Il faut le recréer."))
    d.user(say(d, "go_ahead"))
    d.tool("sh", "docker compose up -d --force-recreate worker && sleep 20 && docker compose logs --no-log-prefix --since 30s worker",
           F(" ✔ Container ", d.project, "-worker-1  Started\n",
             "[", stamp(2, 6), ": INFO/MainProcess] Connected to redis://redis:", x.port(6379), "/0\n",
             "[", stamp(), ": INFO/MainProcess] celery@", x.short(12), " ready.\n",
             "[", stamp(1, 9), ": INFO/MainProcess] Task ", task, "[", last_uuid, "] received\n",
             "[", stamp(0.2, 2), f": INFO/{w}] Task ", task, "[", last_uuid, "] succeeded in ", f"{r.uniform(0.2, 3):.3f}", "s: None\n"))
    if r.random() < 0.7:
        d.agent(d.L(en="Delivery works again. Separately, the WARNING line logs the whole customer dict (name, e-mail, IBAN) on every attempt; changing it to log only the invoice number.",
                    it="L'invio funziona di nuovo. A parte questo, la riga WARNING logga l'intero dict del cliente (nome, email, IBAN) a ogni tentativo; la cambio per loggare solo il numero fattura.",
                    de="Der Versand klappt wieder. Unabhängig davon loggt die WARNING-Zeile bei jedem Versuch das komplette Kunden-Dict (Name, E-Mail, IBAN); ich ändere das auf nur die Rechnungsnummer.",
                    fr="L'envoi refonctionne. À part ça, la ligne WARNING logge tout le dict client (nom, e-mail, IBAN) à chaque tentative ; je la change pour ne logger que le numéro de facture."))
        d.tool("edit", f"{app}/tasks.py",
               F(f'-    logger.warning("{task_fn}: sending %s to %r", invoice.number, customer)\n',
                 f'+    logger.info("{task_fn}: sending %s (customer_id=%s)", invoice.number, customer["id"])\n'))
    d.agent(say(d, "done"), "\n- ", d.L(en="worker recreated with the current SMTP credentials", it="worker ricreato con le credenziali SMTP attuali",
                                         de="Worker mit den aktuellen SMTP-Zugangsdaten neu erstellt", fr="worker recréé avec les identifiants SMTP actuels",
                                         es="worker recreado con las credenciales SMTP actuales"),
            "\n- ", str(n_jobs), d.L(en=" queued tasks will drain on their next retry", it=" task in coda verranno smaltiti al prossimo retry",
                                     de=" wartende Tasks laufen beim nächsten Retry durch", fr=" tâches en attente partiront au prochain essai",
                                     es=" tareas en cola saldrán en el próximo reintento"))
