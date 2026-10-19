# SPDX-License-Identifier: Apache-2.0
"""Templates around vehicles, travel documents and managed devices."""

from __future__ import annotations

import datetime as dt

from .. import values as V
from ..core import F, J, T, Seg, grid, lines, numbered, table
from ..phrases import say
from . import template

_MON3 = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _today(d) -> dt.date:
    return d.clock.t.date()


# ================================================================ ANPR parking gate


def _compact_plate(seg: Seg) -> Seg:
    """The plate as the camera reads it: upper case, no separators."""
    if seg.label:
        return Seg("".join(c for c in seg.text.upper() if c.isalnum()), label=seg.label)
    return seg


@template("alpr_parking_events", "plain", "log", "file")
def alpr_parking_events(d):
    g, x, r = d.g, d.x, d.rng
    staff = d.people(r.randint(3, 8), d.locale)
    for p in staff:
        p.extra["plate"] = g.plate(p)
        p.extra["emp"] = g.emp()
    visitors = [g.plate(d.person()) for _ in range(r.randint(1, 4))]
    gate = r.choice(["gate2-in", "garage-north", "p1-entry", "tor-ost"])
    d.user(d.L(
        en="This morning the garage barrier refused several colleagues although their plates are registered. Logs are in /var/log/anpr/. What's going on?",
        it="Stamattina la sbarra del garage non si è alzata per diversi colleghi anche se le targhe sono registrate. I log sono in /var/log/anpr/. Cosa succede?",
        de="Heute Morgen hat die Garagenschranke mehrere Kolleg:innen nicht reingelassen, obwohl ihre Kennzeichen registriert sind. Logs liegen unter /var/log/anpr/. Was ist da los?",
        fr="Ce matin la barrière du parking a refusé plusieurs collègues alors que leurs plaques sont enregistrées. Les logs sont dans /var/log/anpr/. Qu'est-ce qui se passe ?",
        es="Esta mañana la barrera del garaje no se abrió para varios compañeros aunque sus matrículas están registradas. Los logs están en /var/log/anpr/. ¿Qué pasa?"))
    d.agent(say(d, "logs_window"))
    n = r.choice([8, 14, 22, 35, 60])
    rows = []
    d.clock.tick(3600 * 5, 3600 * 7)
    spaced = [p for p in staff if p.extra["plate"].label and not p.extra["plate"].text.isalnum()]
    for _ in range(n):
        t = x.ts("iso_off", tick=(15, 240), local=True)
        if r.random() < 0.2 and visitors:
            rows.append(T("⟦t⟧ cam=⟦c⟧ read=⟦p⟧ conf=0.⟦k⟧ decision=DENY reason=not_registered", t=t, c=gate,
                          p=_compact_plate(r.choice(visitors)), k=str(r.randint(70, 99))))
            continue
        p = r.choice(staff)
        plate = p.extra["plate"]
        compact = _compact_plate(plate)
        ok = plate.text.isalnum() if plate.label else True
        rows.append(T("⟦t⟧ cam=⟦c⟧ read=⟦p⟧ conf=0.⟦k⟧ decision=⟦dec⟧", t=t, c=gate, p=compact, k=str(r.randint(80, 99)),
                      dec=F("ALLOW permit=", p.extra["emp"]) if ok else "DENY reason=not_registered"))
    d.tool("sh", f"tail -n {n} /var/log/anpr/{gate}.log", lines(*rows))
    d.agent(d.L(en="The camera reads plates without separators. Let me compare with the permit registry.",
                it="La telecamera legge le targhe senza separatori. Confronto con l'anagrafica dei permessi.",
                de="Die Kamera liest Kennzeichen ohne Trennzeichen. Ich vergleiche mit dem Berechtigungsregister.",
                fr="La caméra lit les plaques sans séparateurs. Je compare avec le registre des autorisations.",
                es="La cámara lee las matrículas sin separadores. Comparo con el registro de permisos."))
    head = ["employee_no", "name", "email", "plate", "valid_until"]
    body = []
    for p in staff:
        until = _today(d) + dt.timedelta(days=r.randint(-20, 400))
        body.append([p.extra["emp"], g.name(p), g.email(p), p.extra["plate"], g.date(until, "iso", p)])
    if r.random() < 0.5:
        d.tool("sh", 'sqlite3 -header -column /srv/anpr/permits.db "SELECT employee_no, name, email, plate, valid_until FROM permits WHERE active = 1;"',
               table([head] + body, gap=2))
    else:
        d.tool("read", "/srv/anpr/permits.csv", lines(",".join(head), *[J(",", row) for row in body]))
    code = lines(
        "import re",
        "",
        "def normalize(plate: str) -> str:",
        '    """Canonical form used for registry lookups."""',
        "    return plate.strip().upper()",
        "",
        "def lookup(read: str, permits: dict[str, Permit]) -> Permit | None:",
        "    return permits.get(normalize(read))",
        "",
        "def load_permits(rows) -> dict[str, Permit]:",
        "    return {normalize(row.plate): row for row in rows if row.active}",
    )
    d.tool("read", "anpr/match.py", numbered(code))
    d.agent(say(d, "explain"), "\n",
            d.L(en="the registry stores plates as typed in the HR form (with spaces or dashes), the camera sends them compact, and `normalize()` only upper-cases. Any plate entered with a separator never matches.",
                it="l'anagrafica salva le targhe come digitate nel modulo HR (con spazi o trattini), la telecamera le manda compatte e `normalize()` fa solo l'upper-case. Ogni targa inserita con un separatore non corrisponde mai.",
                de="das Register speichert Kennzeichen so, wie sie im HR-Formular eingegeben wurden (mit Leerzeichen oder Bindestrich), die Kamera liefert sie kompakt, und `normalize()` macht nur Großbuchstaben. Jedes Kennzeichen mit Trennzeichen passt nie.",
                fr="le registre stocke les plaques telles que saisies dans le formulaire RH (avec espaces ou tirets), la caméra les envoie compactes et `normalize()` ne fait que mettre en majuscules. Toute plaque saisie avec un séparateur ne correspond jamais.",
                es="el registro guarda las matrículas tal como se escribieron en el formulario de RR. HH. (con espacios o guiones), la cámara las envía compactas y `normalize()` solo pasa a mayúsculas. Ninguna matrícula con separador coincide nunca."))
    d.tool("edit", "anpr/match.py", lines("-    return plate.strip().upper()", '+    return re.sub(r"[^A-Z0-9]", "", plate.upper())'))
    d.tool("sh", "python -m pytest tests/test_match.py -q",
           lines(f"{'.' * r.randint(5, 14)}{' ' * 30}[100%]", f"{r.randint(5, 14)} passed in 0.{r.randint(10, 90)}s"))
    if spaced and r.random() < 0.6:
        p = spaced[0]
        d.tool("sh", T("python -c 'from anpr.match import normalize; print(normalize(\"⟦p⟧\"))'", p=p.extra["plate"]),
               lines(_compact_plate(p.extra["plate"])))
    d.agent(say(d, "done"), "\n",
            d.L(en="- `normalize()` strips separators on both sides of the lookup\n- note: the gate log keeps plate reads with permit ids for every passage; check that its retention matches the privacy notice",
                it="- `normalize()` toglie i separatori da entrambe le parti del confronto\n- nota: il log del varco conserva le letture targa con l'id del permesso per ogni passaggio; verifica che la retention sia quella dell'informativa privacy",
                de="- `normalize()` entfernt Trennzeichen auf beiden Seiten des Abgleichs\n- Hinweis: das Schrankenlog speichert jede Durchfahrt mit Kennzeichen und Berechtigungs-ID; prüft, ob die Aufbewahrungsdauer zur Datenschutzerklärung passt",
                fr="- `normalize()` retire les séparateurs des deux côtés de la comparaison\n- note : le log de la barrière garde chaque passage avec plaque et identifiant d'autorisation ; vérifiez que la durée de conservation correspond à la notice de confidentialité",
                es="- `normalize()` quita los separadores en ambos lados de la comparación\n- nota: el log de la barrera guarda cada paso con matrícula e id de permiso; revisad que la retención cuadre con la política de privacidad"))
    if r.random() < 0.4:
        d.user(say(d, "thanks"))


# ================================================================ airline booking import (PNR / APIS)


def _pnr_name(d, p) -> Seg:
    v = f"{V.fold(p.family, p.locale).upper().replace(' ', '')}/{V.fold(p.given, p.locale).upper()}"
    if p.placeholder or not d.gold_ok:
        return d.x.ph("name", r"DOE/JANE" if p.female else "DOE/JOHN")
    return Seg(v, label="private_person")


def _pnr_date(d, day: dt.date, p, two_digit_year: bool = True) -> Seg:
    v = f"{day.day:02d}{_MON3[day.month - 1]}{day.year % 100:02d}" if two_digit_year else f"{day.day:02d}{_MON3[day.month - 1]}"
    if p.placeholder or not d.gold_ok:
        return d.x.ph("date", "01JAN70" if two_digit_year else "01JAN")
    return Seg(v, label="private_date")


_NAT = {"IT": "ITA", "DE": "DEU", "FR": "FRA", "ES": "ESP", "NL": "NLD", "GB": "GBR", "US": "USA", "PT": "PRT", "PL": "POL"}
_ROUTES = [("AZ", "LIN", "FCO"), ("LH", "MUC", "FRA"), ("AF", "CDG", "NCE"), ("IB", "MAD", "BCN"), ("KL", "AMS", "LHR"),
           ("TP", "LIS", "OPO"), ("LO", "WAW", "KRK"), ("BA", "LHR", "EDI"), ("UA", "SFO", "ORD"), ("U2", "MXP", "BER")]


@template("travel_booking_pnr", "react", "file", "trace")
def travel_booking_pnr(d):
    g, x, r = d.g, d.x, d.rng
    fname = F("imports/", d.x.ts("date"), "_bookings.txt")
    d.user(T(d.L(
        en="The travel import job crashes on today's export from the agency (⟦f⟧). Can you fix the parser?",
        it="Il job di import viaggi va in crash sull'export di oggi dell'agenzia (⟦f⟧). Riesci a sistemare il parser?",
        de="Der Reise-Import stürzt beim heutigen Export der Agentur ab (⟦f⟧). Kannst du den Parser reparieren?",
        fr="Le job d'import des voyages plante sur l'export du jour de l'agence (⟦f⟧). Tu peux corriger le parser ?",
        es="El job de importación de viajes falla con el export de hoy de la agencia (⟦f⟧). ¿Puedes arreglar el parser?"),
        f=fname))
    n_pnr = r.choice([2, 3, 4, 6, 9])
    blocks = []
    multi_word = None
    for _ in range(n_pnr):
        pax = d.people(r.choice([1, 1, 2, 3]))
        loc = V.rand_str(r, "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", 6)
        carrier, a, b = r.choice(_ROUTES)
        fly = _today(d) + dt.timedelta(days=r.randint(3, 60))
        blk = [T("PNR ⟦l⟧  CREATED ⟦t⟧  AGENT ⟦a⟧", l=x.id(loc), t=x.ts("iso_s", tick=(60, 900)),
                 a=r.choice(["TVL/MIL3", "TVL/MUC1", "TVL/PAR2", "TVL/MAD1"]))]
        blk.append(J("  ", [T("⟦i⟧.1⟦n⟧ ⟦t⟧", i=str(i + 1), n=_pnr_name(d, p), t="MS" if p.female else "MR") for i, p in enumerate(pax)]))
        blk.append(T(" 1 ⟦c⟧ ⟦f⟧ Y ⟦d1⟧ ⟦a⟧⟦b⟧ HK⟦k⟧  0710 0825", c=carrier, f=x.num(lo=100, hi=9999), d1=_pnr_date(d, fly, pax[0], False),
                     a=a, b=b, k=str(len(pax))))
        if r.random() < 0.7:
            back = fly + dt.timedelta(days=r.randint(1, 6))
            blk.append(T(" 2 ⟦c⟧ ⟦f⟧ Y ⟦d1⟧ ⟦b⟧⟦a⟧ HK⟦k⟧  1855 2010", c=carrier, f=x.num(lo=100, hi=9999), d1=_pnr_date(d, back, pax[0], False),
                         a=a, b=b, k=str(len(pax))))
        for i, p in enumerate(pax):
            expiry = _today(d) + dt.timedelta(days=r.randint(200, 3500))
            if " " in p.family and not p.placeholder and multi_word is None:
                multi_word = p
            blk.append(T("SSR DOCS ⟦c⟧ HK1 P/⟦n1⟧/⟦pp⟧/⟦n2⟧/⟦dob⟧/⟦s⟧/⟦exp⟧/⟦fam⟧/⟦giv⟧/P⟦i⟧", c=carrier, n1=_NAT[p.country],
                         pp=g.passport(p), n2=_NAT[p.country], dob=_pnr_date(d, p.birth, p), s="F" if p.female else "M",
                         exp=_pnr_date(d, expiry, p), fam=_pnr_part(d, p, "family"), giv=_pnr_part(d, p, "given"), i=str(i + 1)))
            mail = g.email(p, r.choice(["work", "personal"]))
            mail_pnr = Seg(mail.text.upper().replace("@", "//"), label=mail.label) if mail.label else mail
            blk.append(T("SSR CTCE ⟦c⟧ HK1 ⟦m⟧/P⟦i⟧", c=carrier, m=mail_pnr, i=str(i + 1)))
            if r.random() < 0.7:
                ph = g.phone(p, intl=True)
                ph_pnr = Seg("".join(ch for ch in ph.text if ch.isdigit()), label=ph.label) if ph.label else ph
                blk.append(T("SSR CTCM ⟦c⟧ HK1 ⟦m⟧/P⟦i⟧", c=carrier, m=ph_pnr, i=str(i + 1)))
            if r.random() < 0.5:
                blk.append(T("FQTV ⟦c⟧ ⟦n⟧/P⟦i⟧", c=carrier, n=g.raw("account_number", V.rand_str(r, "0123456789", r.choice([9, 10, 12])), "generic"),
                             i=str(i + 1)))
        blk.append(T("OSI ⟦c⟧ CORP ⟦co⟧ COSTCENTER ⟦cc⟧", c=carrier, co=V.slug(d.company).upper()[:12], cc=x.num(lo=1000, hi=9999)))
        blocks.append(lines(*blk))
    d.tool("read", fname, J("\n", blocks))
    tb_line = x.num(lo=40, hi=95)
    d.tool("sh", F("python -m travel.import_bookings ", fname), lines(
        "Traceback (most recent call last):",
        T('  File "⟦h⟧/travel/import_bookings.py", line ⟦n⟧, in <module>', h=d.cwd(), n=x.num(lo=100, hi=140)),
        "    main(sys.argv[1])",
        T('  File "⟦h⟧/travel/import_bookings.py", line ⟦n⟧, in main', h=d.cwd(), n=x.num(lo=60, hi=99)),
        "    pax.update(parse_docs(line))",
        T('  File "⟦h⟧/travel/pnr.py", line ⟦n⟧, in parse_docs', h=d.cwd(), n=tb_line),
        "    _, _, _, doc_type, nat, number, issuer, dob, sex, expiry, family, given, ref = re.split(r\"[ /]\", line)",
        "ValueError: " + r.choice(["too many values to unpack (expected 13)", "not enough values to unpack (expected 13, got 12)"]),
    ))
    code = lines(
        "import re",
        "from datetime import datetime",
        "",
        "def _date(s: str) -> str:",
        '    return datetime.strptime(s, "%d%b%y").date().isoformat()',
        "",
        "def parse_docs(line: str) -> dict:",
        '    """SSR DOCS free text: P/nat/number/issuer/dob/sex/expiry/family/given/Pn"""',
        "    _, _, _, doc_type, nat, number, issuer, dob, sex, expiry, family, given, ref = re.split(r\"[ /]\", line)",
        '    return {"doc": number, "nationality": nat, "dob": _date(dob), "sex": sex,',
        '            "doc_expiry": _date(expiry), "family": family, "given": given, "pax": ref}',
    )
    d.tool("read", "travel/pnr.py", numbered(code, start=tb_line.text and int(tb_line.text) - 8))
    d.agent(d.L(en="The line is split on spaces *and* slashes, so the field count changes whenever a name contains a space (multi-word surnames) or the agency adds an optional field. DOCS is slash-separated after the status code; I'll split only the free text on '/'.",
                it="La riga viene divisa su spazi *e* slash, quindi il numero di campi cambia appena un nome contiene uno spazio (cognomi composti) o l'agenzia aggiunge un campo opzionale. DOCS è separato da slash dopo il codice di stato; divido solo il testo libero su '/'.",
                de="Die Zeile wird an Leerzeichen *und* Schrägstrichen getrennt; die Feldanzahl ändert sich also, sobald ein Name ein Leerzeichen enthält (mehrteilige Nachnamen) oder die Agentur ein optionales Feld ergänzt. DOCS ist nach dem Statuscode durch Schrägstriche getrennt; ich splitte nur den Freitext an '/'.",
                fr="La ligne est découpée sur les espaces *et* les slashs, donc le nombre de champs change dès qu'un nom contient un espace (noms composés) ou que l'agence ajoute un champ optionnel. DOCS est séparé par des slashs après le code de statut ; je ne découpe que le texte libre sur '/'.",
                es="La línea se parte por espacios *y* barras, así que el número de campos cambia en cuanto un nombre tiene un espacio (apellidos compuestos) o la agencia añade un campo opcional. DOCS va separado por barras tras el código de estado; parto solo el texto libre por '/'."))
    d.tool("edit", "travel/pnr.py", lines(
        "-    _, _, _, doc_type, nat, number, issuer, dob, sex, expiry, family, given, ref = re.split(r\"[ /]\", line)",
        "+    head, _, free = line.partition(\" HK1 \")",
        "+    parts = free.split(\"/\")",
        "+    doc_type, nat, number, issuer, dob, sex, expiry, family, given = parts[:9]",
        "+    ref = parts[9] if len(parts) > 9 else None"))
    imported = sum(1 for _ in blocks)
    d.tool("sh", F("python -m travel.import_bookings ", fname),
           lines(T("⟦t⟧ INFO imported ⟦n⟧ bookings (⟦p⟧ passengers), 0 errors", t=x.ts("space_ms", tick=(30, 90)),
                   n=str(imported), p=str(r.randint(imported, imported * 3)))))
    if multi_word is not None and r.random() < 0.7:
        d.agent(T(d.L(en="Checked the record that triggered it — ⟦n⟧ now parses with the full surname.",
                      it="Ho verificato il record che lo causava: ⟦n⟧ ora viene letto con il cognome completo.",
                      de="Den auslösenden Datensatz geprüft — ⟦n⟧ wird jetzt mit vollem Nachnamen gelesen.",
                      fr="J'ai vérifié l'enregistrement fautif : ⟦n⟧ est maintenant lu avec le nom complet.",
                      es="He comprobado el registro que lo provocaba: ⟦n⟧ se lee ahora con el apellido completo."),
                  n=g.name(multi_word)))
    d.agent(say(d, "pii_warning"), " ",
            d.L(en="APIS data (passport numbers, birth dates) should be dropped from the import table after the return flight; there's no purge job yet.",
                it="I dati APIS (numeri di passaporto, date di nascita) andrebbero eliminati dalla tabella di import dopo il volo di ritorno; non esiste ancora un job di pulizia.",
                de="APIS-Daten (Passnummern, Geburtsdaten) sollten nach dem Rückflug aus der Importtabelle gelöscht werden; einen Lösch-Job gibt es noch nicht.",
                fr="Les données APIS (numéros de passeport, dates de naissance) devraient être supprimées de la table d'import après le vol retour ; il n'existe pas encore de purge.",
                es="Los datos APIS (números de pasaporte, fechas de nacimiento) deberían borrarse de la tabla de importación tras el vuelo de vuelta; aún no hay job de purga."))


def _pnr_part(d, p, which: str) -> Seg:
    raw = p.family if which == "family" else p.given
    v = V.fold(raw, p.locale).upper()
    if p.placeholder or not d.gold_ok:
        return d.x.ph("name", "DOE" if which == "family" else "JANE")
    return Seg(v, label="private_person")


# ================================================================ MDM device inventory


@template("mdm_device_inventory", "aider", "shell", "file")
def mdm_device_inventory(d):
    g, x, r = d.g, d.x, d.rng
    owners = d.people(r.randint(4, 12))
    days = r.choice([30, 45, 60])
    d.user(T(d.L(
        en="Security wants the devices that haven't checked in with the MDM for ⟦n⟧+ days. The export is exports/devices.csv — write a small script and give me the list.",
        it="La security vuole i dispositivi che non si collegano all'MDM da più di ⟦n⟧ giorni. L'export è exports/devices.csv: scrivi uno scriptino e dammi la lista.",
        de="Security will die Geräte, die sich seit ⟦n⟧+ Tagen nicht beim MDM gemeldet haben. Export liegt in exports/devices.csv — schreib ein kleines Skript und gib mir die Liste.",
        fr="La sécu veut les appareils qui ne se sont pas signalés au MDM depuis ⟦n⟧ jours ou plus. L'export est dans exports/devices.csv — écris un petit script et donne-moi la liste.",
        es="Seguridad quiere los dispositivos que no se conectan al MDM desde hace ⟦n⟧ días o más. El export está en exports/devices.csv: escribe un script pequeño y pásame la lista."),
        n=str(days)))
    now = d.clock.t
    devices = []
    for p in owners:
        for _ in range(r.choice([1, 1, 2])):
            kind = r.choice(["laptop", "laptop", "phone"])
            last = now - dt.timedelta(days=r.choice([0, 1, 2, 5, 12, 33, 47, 70, 120]), seconds=r.randint(0, 86000))
            devices.append({"p": p, "kind": kind, "serial": x.id(V.rand_str(r, "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", 10 if kind == "laptop" else 12)),
                            "model": r.choice(["MacBook Pro 14", "ThinkPad T14 Gen 4", "Dell Latitude 7440", "MacBook Air 13"]) if kind == "laptop"
                            else r.choice(["iPhone 14", "iPhone 15", "Pixel 8", "Galaxy S23"]),
                            "os": x.ver(r.choice(["14.6.1", "15.1", "13.7.2", "17.6", "18.1", "14"])),
                            "wifi": g.mac(r.choice([0, 1])), "bt": g.mac(r.choice([0, 1])) if r.random() < 0.6 else None,
                            "last": last, "geo": g.geo(p, sep=",") if r.random() < 0.75 else None,
                            "phone": g.phone(p, intl=True) if kind == "phone" else None})
    r.shuffle(devices)
    head = "serial,model,os_version,assigned_user,user_email,wifi_mac,bt_mac,last_checkin,last_location,phone_number"
    rows = [head]
    for dv in devices:
        rows.append(F(dv["serial"], ",", dv["model"], ",", dv["os"], ",", g.name(dv["p"]), ",", g.email(dv["p"]), ",", dv["wifi"], ",",
                      dv["bt"] or "", ",", x.ts("iso_s", t=dv["last"]), ",", F('"', dv["geo"], '"') if dv["geo"] else "", ",",
                      dv["phone"] or ""))
    shown = rows[: 1 + min(len(devices), r.choice([6, 10, 40]))]
    d.tool("sh", f"head -n {len(shown)} exports/devices.csv && wc -l exports/devices.csv",
           F(lines(*shown), f"{len(devices) + 1} exports/devices.csv\n"))
    script = lines(
        "#!/usr/bin/env python3",
        '"""List MDM devices whose last check-in is older than N days."""',
        "import csv, sys",
        "from datetime import datetime, timedelta, timezone",
        "",
        "def main(path: str, days: int) -> None:",
        "    cutoff = datetime.now(timezone.utc) - timedelta(days=days)",
        "    with open(path, newline=\"\", encoding=\"utf-8\") as f:",
        "        stale = [row for row in csv.DictReader(f)",
        "                 if datetime.fromisoformat(row[\"last_checkin\"].replace(\"Z\", \"+00:00\")) < cutoff]",
        "    stale.sort(key=lambda row: row[\"last_checkin\"])",
        "    w = csv.writer(sys.stdout)",
        "    w.writerow([\"serial\", \"model\", \"assigned_user\", \"user_email\", \"last_checkin\"])",
        "    for row in stale:",
        "        w.writerow([row[k] for k in (\"serial\", \"model\", \"assigned_user\", \"user_email\", \"last_checkin\")])",
        "",
        "if __name__ == \"__main__\":",
        "    main(sys.argv[1], int(sys.argv[2]))",
    )
    d.tool("write", "scripts/stale_devices.py", script)
    stale = sorted([dv for dv in devices if (now - dv["last"]).days >= days], key=lambda dv: dv["last"])
    out = [F("serial,model,assigned_user,user_email,last_checkin")]
    for dv in stale:
        out.append(F(dv["serial"], ",", dv["model"], ",", g.name(dv["p"]), ",", g.email(dv["p"]), ",", x.ts("iso_s", t=dv["last"])))
    d.tool("sh", f"python3 scripts/stale_devices.py exports/devices.csv {days}", lines(*out))
    d.agent(T(d.L(en="⟦n⟧ devices are over the threshold.", it="⟦n⟧ dispositivi superano la soglia.",
                  de="⟦n⟧ Geräte liegen über der Schwelle.", fr="⟦n⟧ appareils dépassent le seuil.",
                  es="⟦n⟧ dispositivos superan el umbral."), n=str(len(stale))),
            " ",
            d.L(en="The script only outputs serial, model, owner and last check-in — the export also carries Wi-Fi/Bluetooth MACs and last known locations, which security doesn't need for this.",
                it="Lo script restituisce solo seriale, modello, assegnatario e ultimo check-in: l'export contiene anche MAC Wi-Fi/Bluetooth e ultime posizioni, che alla security qui non servono.",
                de="Das Skript gibt nur Seriennummer, Modell, Besitzer und letzten Check-in aus — der Export enthält auch WLAN-/Bluetooth-MACs und letzte Standorte, die Security dafür nicht braucht.",
                fr="Le script ne sort que numéro de série, modèle, attributaire et dernier check-in — l'export contient aussi les MAC Wi-Fi/Bluetooth et les dernières positions, inutiles pour la sécu ici.",
                es="El script solo saca número de serie, modelo, usuario y último check-in; el export también lleva MAC de Wi-Fi/Bluetooth y últimas ubicaciones, que seguridad no necesita para esto."))
    if stale and r.random() < 0.5:
        d.user(d.L(en="Can you draft the reminder mail to the owners?", it="Mi prepari la bozza della mail di promemoria ai proprietari?",
                   de="Kannst du die Erinnerungsmail an die Besitzer entwerfen?", fr="Tu peux rédiger le mail de relance aux propriétaires ?",
                   es="¿Me redactas el correo de recordatorio para los propietarios?"))
        to = J(", ", [g.email(dv["p"]) for dv in stale[:6]])
        d.agent(F("To: ", to, "\n", d.L(
            en=f"Subject: Please connect your device to the company network\n\nHi,\n\nour device management hasn't seen your device for more than {days} days. Please turn it on and connect it to the VPN or office Wi-Fi this week so it can receive security updates. If you no longer use it, reply and IT will arrange the return.\n\nThanks,\nIT",
            it=f"Oggetto: Collega il tuo dispositivo alla rete aziendale\n\nCiao,\n\nil sistema di gestione dispositivi non vede il tuo dispositivo da più di {days} giorni. Accendilo e collegalo alla VPN o al Wi-Fi dell'ufficio entro questa settimana per ricevere gli aggiornamenti di sicurezza. Se non lo usi più, rispondi e l'IT organizzerà la restituzione.\n\nGrazie,\nIT",
            de=f"Betreff: Bitte Gerät mit dem Firmennetz verbinden\n\nHallo,\n\nunser Gerätemanagement hat dein Gerät seit mehr als {days} Tagen nicht gesehen. Bitte schalte es diese Woche ein und verbinde es mit VPN oder Büro-WLAN, damit es Sicherheitsupdates bekommt. Falls du es nicht mehr nutzt, antworte kurz, dann organisiert die IT die Rückgabe.\n\nDanke,\nIT",
            fr=f"Objet : Merci de connecter votre appareil au réseau de l'entreprise\n\nBonjour,\n\nnotre gestion des appareils n'a pas vu votre appareil depuis plus de {days} jours. Merci de l'allumer et de le connecter au VPN ou au Wi-Fi du bureau cette semaine pour recevoir les mises à jour de sécurité. Si vous ne l'utilisez plus, répondez et l'IT organisera le retour.\n\nMerci,\nIT",
            es=f"Asunto: Conecta tu dispositivo a la red de la empresa\n\nHola:\n\nnuestra gestión de dispositivos no ve tu dispositivo desde hace más de {days} días. Enciéndelo y conéctalo a la VPN o al Wi-Fi de la oficina esta semana para que reciba las actualizaciones de seguridad. Si ya no lo usas, responde y IT organizará la devolución.\n\nGracias,\nIT")))
