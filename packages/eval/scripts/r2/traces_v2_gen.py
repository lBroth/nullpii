#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""traces-v2 generator: synthetic coding-agent tool output with planted PII.

What this builds
----------------
A JSON Lines corpus of 600 documents ("tv2:0" ... "tv2:599") that imitate
the tool output an LLM coding agent reads inside a developer's repository:
source files, configuration files, logs, stack traces, shell sessions, data
exports, markdown documents and pasted e-mails / chat transcripts, in five
languages (en, de, fr, it, es). Personal data and credentials are planted at
known code-point offsets and labelled with one of 14 labels. Many unlabelled
look-alike values (UUIDs, hashes, versions, machine timestamps, public URLs,
request ids, placeholders such as <YOUR_API_KEY> or ${DB_PASSWORD}, ...) are
planted as distractors. About 10% of the documents are long (20k-60k
characters, concatenated sections) and about 10% contain no labelled span
(every planted value replaced by a placeholder). SPEC.md next to this file is
the specification this generator implements.

Isolation rules it was written under
------------------------------------
* Written from SPEC.md only. No other file of this repository (detector
  sources, tests, other datasets or dataset generators, benchmark scripts,
  results, logs, protocols) was opened or searched while writing it, so the
  corpus is not shaped by any masking tool's design.
* No fake-data library (no Faker or similar). Every value pool below was
  written by hand for this generator and every value is invented; no real
  person's data is used. Where a real-looking value could collide with a
  real entity, reserved or test forms are used: phone numbers from fiction
  ranges where one is known (US 555-0100..0199, UK Ofcom drama ranges,
  FR ARCEP fiction ranges), payment cards on test BINs (Luhn-valid), IBANs
  for fictional banks (valid ISO 13616 check digits, plus the national
  check digits for FR/IT/ES), IPv4/IPv6 addresses from private, CGNAT and
  documentation ranges, invented company and mailbox domains, US tax
  numbers in ITIN form, UK NHS numbers in the 999 test range. For German,
  Italian and Spanish phone numbers no reserved fiction range is known to
  the author; those digits are random.
* Python 3 standard library only, no network access, deterministic for a
  given --seed (default 20261018); generation takes a few seconds of CPU.

Labelling conventions chosen here (where the spec leaves room)
--------------------------------------------------------------
* A credential embedded in a URL (DB URLs, git remotes, package index URLs)
  is labelled as `secret` alone; the URL around it is left unlabelled so
  that labelled values never nest. URLs without embedded credentials that
  point at internal hosts, private repositories or user-specific resources
  are labelled `private_url` as one span.
* Handles are labelled without a leading "@" mention marker.
* Multi-line postal addresses are one span including the newline(s).
* Base64 encodings of a password (Kubernetes Secret data, HTTP Basic auth)
  are labelled `secret`.
* Network blocks (10.0.0.0/8, 172.28.0.0/16) and the broadcast MAC are
  unlabelled distractors; they do not identify a host.
* Connection strings and DB URLs (postgres://, jdbc:, amqp://, ...) are
  never labelled `private_url`; only an embedded password (`secret`) or a
  literal host IP (`private_ip`) inside them is labelled.
* E-mail Message-IDs (<hex@mail.example-domain>) are message identifiers,
  not addresses, and stay unlabelled; every real address, including role
  mailboxes and bot noreply addresses, is labelled `private_email`.
* Public homepages (https://www.<company>), public health endpoints and
  pull-request links of a company's open-source repositories are public
  URLs (unlabelled); links into "<company>-internal" repositories, internal
  hosts and per-user resources are `private_url`.
* Dates that are business or machine events (release dates, payment
  execution dates, log/commit/file timestamps) are unlabelled; only dates of
  a person's life or schedule are `private_date`.

Output record: {"id","kind","template","lang","text","spans":[{"start","end","label"}]}.
Offsets are Python code-point indices, end exclusive. All self-checks run
before anything is written; any failure aborts with a non-zero exit status.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import math
import random
import re
import string
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Tuple, Union

# ----------------------------------------------------------------- constants

DEFAULT_SEED = 20261018
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "results" / "r2" / "traces-v2.jsonl"

N_DOCS = 600
N_LONG = 60
N_CLEAN = 60
LANG_COUNTS = {"en": 300, "de": 75, "fr": 75, "it": 75, "es": 75}
SHORT_MIN, SHORT_MAX = 300, 6000
LONG_MIN, LONG_MAX = 20000, 60000
SHORT_TARGET_LO, SHORT_TARGET_HI = 420, 4800
LONG_TARGET_LO, LONG_TARGET_HI = 21000, 50000
LONG_SECTION_LO, LONG_SECTION_HI = 1500, 5200
MIN_SKELETONS = 40
MIN_USES_PER_SKELETON = 3
DENSITY_LO, DENSITY_HI = 300, 600
NO_SPAN_SHARE_LO, NO_SPAN_SHARE_HI = 0.07, 0.13
LONG_SHARE_LO, LONG_SHARE_HI = 0.08, 0.12
EN_SHARE_LO, EN_SHARE_HI = 0.45, 0.55
OTHER_LANG_SHARE_LO, OTHER_LANG_SHARE_HI = 0.09, 0.16
MAX_ATTEMPTS = 60
MIN_REPEAT_CHECK_LEN = 4

LABELS = (
    "private_person", "private_email", "private_phone", "private_address",
    "private_date", "private_url", "private_ip", "private_mac",
    "account_number", "secret", "private_passport", "private_driver_license",
    "private_vehicle_id", "private_geolocation",
)
LABEL_SET = frozenset(LABELS)
KINDS = ("source_code", "config", "log", "stack_trace", "shell_session",
         "data_export", "markdown", "message")
LANGS = ("en", "de", "fr", "it", "es")
COUNTRY_OF_LANG = {"de": "DE", "fr": "FR", "it": "IT", "es": "ES"}
ALL_COUNTRIES = ("US", "GB", "DE", "FR", "IT", "ES")

# ------------------------------------------------------------ hand-made pools

GIVEN = {  # (female, male)
    "en": (["Olivia", "Harriet", "Imogen", "Rosalind", "Nadia", "Beatrice", "Margot", "Saoirse",
            "Priya", "Felicity", "Tamsin", "Georgina", "Mary-Kate", "Anne-Marie", "Keisha", "Yasmin"],
           ["Marcus", "Declan", "Tobias", "Calvin", "Desmond", "Quentin", "Rhys", "Elliot",
            "Jasper", "Rupert", "Callum", "Damian", "Obinna", "Kwame", "Ravi", "Lachlan"]),
    "de": (["Johanna", "Friederike", "Annika", "Sabine", "Kerstin", "Ulrike", "Mareike", "Svenja",
            "Leonie", "Heike", "Wiebke", "Anna-Lena", "Marie-Luise", "Gesine", "Dörte", "Elif"],
           ["Lukas", "Matthias", "Wolfgang", "Henrik", "Jörg", "Till", "Benedikt", "Konstantin",
            "Dietmar", "Volker", "Jannik", "Hans-Peter", "Karl-Heinz", "Ömer", "Florian", "Niklas"]),
    "fr": (["Mathilde", "Élodie", "Solène", "Clémence", "Inès", "Margaux", "Apolline", "Héloïse",
            "Ophélie", "Anaïs", "Gwenaëlle", "Marie-Hélène", "Anne-Sophie", "Nadège", "Yasmine", "Maëlys"],
           ["Thibault", "Gaspard", "Baptiste", "Aurélien", "Grégoire", "Lucien", "Bastien", "Corentin",
            "Rémi", "Yannick", "Jean-Baptiste", "Pierre-Yves", "Karim", "Loïc", "Mathis", "Hugo"]),
    "it": (["Giulia", "Chiara", "Beatrice", "Ilaria", "Serena", "Martina", "Francesca", "Ludovica",
            "Viola", "Arianna", "Benedetta", "Maria Grazia", "Anna Maria", "Rosaria", "Noemi", "Gaia"],
           ["Lorenzo", "Matteo", "Federico", "Tommaso", "Alessandro", "Gianluca", "Riccardo", "Edoardo",
            "Stefano", "Pierluigi", "Vittorio", "Gian Marco", "Pier Paolo", "Salvatore", "Davide", "Ettore"]),
    "es": (["Lucía", "Carmen", "Marta", "Nerea", "Rocío", "Ainhoa", "Pilar", "Irene",
            "Elena", "Inmaculada", "Begoña", "María José", "Ana Belén", "Itziar", "Valeria", "Noelia"],
           ["Javier", "Alejandro", "Íñigo", "Gonzalo", "Álvaro", "Sergio", "Rubén", "Joaquín",
            "Borja", "Mateo", "Unai", "José Luis", "Juan Carlos", "Ignacio", "Rodrigo", "Andrés"]),
}

FAMILY = {
    "en": ["Ashworth", "Pemberton", "Okafor", "Halloway", "Brennan", "Thackeray", "Whitlock", "Fairbairn",
           "Kingsley", "Prescott", "Radcliffe", "Underhill", "Marlowe", "Dunmore", "Fenwick", "Galloway",
           "Hargreave", "Kershaw", "Northcott", "Penhallow", "Rowntree", "Treharne", "Winterbourne",
           "Yardley", "O'Donnell-Price", "St. Clair", "Abernathy", "Adeyemi", "Chaudhry", "Nakamura-Reid"],
    "de": ["Brandstätter", "Kühnel", "Oberholzer", "Wendlandt", "Hagedorn", "Lindemann", "Pfannenstiel",
           "Rautenberg", "Vogelsang", "Achterberg", "Dornbusch", "Falkenrath", "Grünewald", "Habermann",
           "Jungblut", "Kesselring", "Niederhaus", "Ostermeier", "Quast", "Schulze-Wehninck",
           "von Ostrowski", "Meyer-Abendroth", "Yılmaz", "Kowalczyk", "Weißgerber", "Tiedemann"],
    "fr": ["Desjardins", "Fauconnier", "Garnier", "Hébrard", "Lacombe", "Montagnac", "Rouvière",
           "Sauveterre", "Tissandier", "Vasseur", "Aubertin", "Bellanger", "Courtois", "Delahaye",
           "Fontanel", "Guilloux", "Jacquemin", "Labrousse", "Le Guellec", "Delacroix-Morel",
           "de La Tour-Varenne", "Benali", "Nguyen-Thibaud", "Perrichon"],
    "it": ["Bellandi", "Cattaneo", "D'Ambrosio", "Ferraresi", "Galimberti", "Iacovelli", "Lombardini",
           "Marchetti", "Nardini", "Orlandini", "Pellegrino", "Quaranta", "Rinaldi", "Santoro",
           "Tagliaferri", "Vitale", "Zanella", "De Santis", "Lo Presti", "Dalla Valle", "Di Gregorio",
           "Brambilla", "Scognamiglio", "Mancuso"],
    "es": ["García", "Fernández", "Ortega", "Villanueva", "Echeverría", "Montoya", "Navarrete", "Quiroga",
           "Salcedo", "Barrientos", "Cifuentes", "del Pino", "Larrañaga", "Ibarra", "Peñalver",
           "Torrealba", "Arriaga", "Benavides", "Carrasco", "Zubiaurre", "Medina", "Olmedo", "Sanz",
           "Valdivieso"],
}
PARTICLES = {"von", "van", "de", "del", "della", "di", "da", "la", "le", "du", "dalla", "lo", "st."}

COMPANIES = {
    "en": [("Lumenvale Analytics", "lumenvale.com"), ("Northbeam Labs", "northbeam-labs.io"),
           ("Quillfern Software", "quillfern.io"), ("Ashgrove Dental Group", "ashgrove-dental.co.uk"),
           ("Bluewharf Freight", "bluewharf-freight.co.uk"), ("Mapleforge Systems", "mapleforge.io")],
    "de": [("Korvalis Logistics GmbH", "korvalis-logistics.de"), ("Elbsicht Versicherung AG", "elbsicht-versicherung.de"),
           ("Quellwerk Energie GmbH", "quellwerk.de"), ("Steinfeld Kliniken", "steinfeld-kliniken.de"),
           ("Brauwerk Nord", "brauwerk-nord.de")],
    "fr": [("Brindemar SA", "brindemar.fr"), ("Veloria Énergie", "veloria-energie.fr"),
           ("Transports Garonne", "transports-garonne.fr"), ("Atelier des Sorbiers", "atelier-sorbiers.fr"),
           ("Pharmacie des Tilleuls", "pharmacie-tilleuls.fr")],
    "it": [("Valtessa Group S.p.A.", "valtessa-group.it"), ("Cantieri Adriatici", "cantieri-adriatici.it"),
           ("Farmalpi S.r.l.", "farmalpi.it"), ("Logistica Brenta", "logistica-brenta.it"),
           ("Assicurazioni Torre Alta", "torrealta-assicura.it")],
    "es": [("Orenzo Salud", "orenzo-salud.es"), ("Viajes Alcotán", "viajes-alcotan.es"),
           ("Grupo Ribera Sur", "riberasur.es"), ("Clínica El Almendro", "clinica-almendro.es"),
           ("Tecnored Levante", "tecnored-levante.es")],
}
PERSONAL_DOMAINS = ["postfuchs.de", "courrielle.fr", "mailvento.it", "correo-nube.es", "inboxlark.com",
                    "fastmole.net", "brieftaube-mail.de", "posta-gufo.it", "buzonazul.es", "ptitmel.fr"]
ROLE_MAILBOXES = ["billing", "support", "hr", "it-ops", "noreply", "alerts", "security", "payroll",
                  "accounts", "helpdesk", "dpo", "oncall"]
PRODUCTS = ["Ledgerline", "Parcelbird", "Mintspring", "Torchlake", "Graniteflow", "Cobaltpath",
            "Harborlight", "Quietmeadow", "Saltmarsh", "Emberlane"]
TEAMS = ["payments", "platform", "crm", "data", "hr-tools", "checkout", "identity", "ops"]
REPOS = ["ledger-api", "payroll-export", "customer-portal", "infra-live", "billing-core", "kyc-service",
         "notification-hub", "backoffice"]
CFG_PATHS = ["config/prod.yml", "deploy/values-prod.yaml", "secrets/README.md", "terraform/prod/main.tf",
             "ops/runbooks/db-failover.md", "src/settings/production.py"]
SERVICES = ["api", "worker", "scheduler", "gateway", "billing", "auth", "notifier", "exporter"]

US_AREAS = ["503", "614", "520", "919", "608", "208", "509", "518", "412", "303", "716", "505"]
DE_MOBILE = ["0151", "0152", "0157", "0160", "0162", "0170", "0171", "0176", "0179"]
DE_AREAS = ["030", "040", "089", "0221", "0341", "0761", "0421", "0351", "0251"]
IT_MOBILE = ["320", "328", "333", "338", "340", "347", "349", "366", "380", "393"]
IT_LAND = ["02", "06", "011", "051", "055", "081", "045", "080", "049"]
ES_LAND = ["91", "93", "96", "95", "94", "976", "952", "958"]

# (city, region code, postcode prefix, lat, lon)
CITIES = {
    "US": [("Portland", "OR", "972", 45.5152, -122.6784), ("Columbus", "OH", "432", 39.9612, -82.9988),
           ("Tucson", "AZ", "857", 32.2226, -110.9747), ("Raleigh", "NC", "276", 35.7796, -78.6382),
           ("Madison", "WI", "537", 43.0731, -89.4012), ("Boise", "ID", "837", 43.6150, -116.2023),
           ("Spokane", "WA", "992", 47.6588, -117.4260), ("Albany", "NY", "122", 42.6526, -73.7562)],
    "GB": [("Leeds", "", "LS", 53.8008, -1.5491), ("Bristol", "", "BS", 51.4545, -2.5879),
           ("Norwich", "", "NR", 52.6309, 1.2974), ("York", "", "YO", 53.9600, -1.0873),
           ("Bath", "", "BA", 51.3811, -2.3590), ("Exeter", "", "EX", 50.7184, -3.5339),
           ("Derby", "", "DE", 52.9225, -1.4746), ("Cardiff", "", "CF", 51.4816, -3.1791)],
    "DE": [("Berlin", "", "10", 52.5200, 13.4050), ("Hamburg", "", "22", 53.5511, 9.9937),
           ("München", "", "80", 48.1374, 11.5755), ("Köln", "", "50", 50.9375, 6.9603),
           ("Leipzig", "", "04", 51.3397, 12.3731), ("Freiburg im Breisgau", "", "79", 47.9990, 7.8421),
           ("Bremen", "", "28", 53.0793, 8.8017), ("Dresden", "", "01", 51.0504, 13.7373),
           ("Münster", "", "48", 51.9607, 7.6261)],
    "FR": [("Lyon", "", "690", 45.7640, 4.8357), ("Nantes", "", "440", 47.2184, -1.5536),
           ("Toulouse", "", "310", 43.6047, 1.4442), ("Lille", "", "590", 50.6292, 3.0573),
           ("Bordeaux", "", "330", 44.8378, -0.5792), ("Rennes", "", "350", 48.1173, -1.6778),
           ("Montpellier", "", "340", 43.6108, 3.8767), ("Grenoble", "", "380", 45.1885, 5.7245),
           ("Dijon", "", "210", 47.3220, 5.0415)],
    "IT": [("Milano", "MI", "201", 45.4642, 9.1900), ("Torino", "TO", "101", 45.0703, 7.6869),
           ("Bologna", "BO", "401", 44.4949, 11.3426), ("Firenze", "FI", "501", 43.7696, 11.2558),
           ("Napoli", "NA", "801", 40.8518, 14.2681), ("Verona", "VR", "371", 45.4384, 10.9916),
           ("Bari", "BA", "701", 41.1171, 16.8719), ("Padova", "PD", "351", 45.4064, 11.8768)],
    "ES": [("Madrid", "", "280", 40.4168, -3.7038), ("Barcelona", "", "080", 41.3874, 2.1686),
           ("Valencia", "", "460", 39.4699, -0.3763), ("Sevilla", "", "410", 37.3891, -5.9845),
           ("Bilbao", "", "480", 43.2630, -2.9350), ("Zaragoza", "", "500", 41.6488, -0.8891),
           ("Málaga", "", "290", 36.7213, -4.4214), ("Granada", "", "180", 37.1773, -3.5986)],
}
STREETS = {
    "US": ["Larkspur Ave", "Quillon St", "Maple Hollow Rd", "Birchwood Dr", "Ferncliff Ln",
           "Harbor View Blvd", "Juniper Ct", "Old Mill Rd", "Cedar Bluff Way", "Wren Hollow Pl"],
    "GB": ["Wexcombe Road", "Pelham Close", "Rowan Crescent", "Mill Lane", "Orchard Gardens",
           "Station Approach", "Hawthorn Way", "Saxon Street", "Kestrel Mews", "Abbots Walk"],
    "DE": ["Lindenstraße", "Am Kesselgrund", "Birkenweg", "Hafenstraße", "Mühlenkamp", "Grüner Winkel",
           "Kastanienallee", "Rosenhag", "Uferpromenade", "Ziegeleiweg", "Auf dem Hövel", "Fasanenring"],
    "FR": ["rue des Tanneurs", "avenue des Glycines", "boulevard de la Fonderie", "impasse du Moulin-Vert",
           "chemin des Vignes Basses", "allée des Peupliers", "place du Marché-aux-Herbes",
           "quai des Bateliers", "rue de la Croix-Blanche"],
    "IT": ["Via delle Orsoline", "Via del Gelsomino", "Viale dei Mille", "Piazza San Rocco",
           "Corso Garibaldi", "Vicolo Stretto", "Via Brennero", "Via dei Fabbri", "Largo dei Tigli",
           "Via Montebello"],
    "ES": ["Calle de la Almendra", "Avenida del Puerto", "Calle Mayor", "Paseo de las Acacias",
           "Plaza del Olivo", "Calle Sierra Nevada", "Ronda de la Muralla", "Travesía del Pozo",
           "Calle del Laurel", "Camino de Ronda"],
}
COUNTRY_NAME = {"US": "USA", "GB": "United Kingdom", "DE": "Deutschland", "FR": "France",
                "IT": "Italia", "ES": "España"}

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
           "Oktober", "November", "Dezember"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
           "octobre", "novembre", "décembre"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
           "settembre", "ottobre", "novembre", "dicembre"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
}
MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DATE_RANGES = {"dob": (1952, 2006), "hire": (2009, 2026), "leave": (2026, 2027),
               "appt": (2026, 2027), "event": (2025, 2027)}
DATE_FORMATS = {
    "US": ["us_slash", "long_en_us", "abbr_en_us", "iso"],
    "GB": ["eu_slash", "long_en_gb", "iso"],
    "DE": ["dot", "long_de", "dot_nopad", "iso"],
    "FR": ["eu_slash", "long_fr", "iso"],
    "IT": ["eu_slash", "long_it", "dash_eu"],
    "ES": ["eu_slash", "long_es", "dash_eu", "iso"],
}

LOCALES = ["en-US", "en-GB", "de-DE", "de-AT", "fr-FR", "fr-BE", "it-IT", "es-ES", "es-MX", "pt-BR"]
TZS = ["Europe/Berlin", "Europe/Paris", "Europe/Rome", "Europe/Madrid", "Europe/London",
       "America/New_York", "America/Los_Angeles", "UTC", "Europe/Zurich"]
REGIONS = ["eu-central-1", "eu-west-1", "eu-south-1", "us-east-1", "us-west-2", "europe-west3",
           "westeurope", "fr-par", "eu-north-1"]
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
    "curl/8.9.1", "python-requests/2.32.3", "Go-http-client/2.0", "kube-probe/1.30", "okhttp/4.12.0",
]
PUB_URLS = {
    "python": ["https://docs.python.org/3/library/datetime.html", "https://docs.pytest.org/en/stable/how-to/fixtures.html",
               "https://pypi.org/project/requests/", "https://peps.python.org/pep-0008/"],
    "js": ["https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API", "https://nodejs.org/api/errors.html",
           "https://registry.npmjs.org/", "https://www.typescriptlang.org/tsconfig"],
    "go": ["https://pkg.go.dev/time", "https://go.dev/doc/effective_go"],
    "java": ["https://junit.org/junit5/docs/current/user-guide/", "https://docs.spring.io/spring-boot/reference/",
             "https://repo.maven.apache.org/maven2/"],
    "ruby": ["https://guides.rubyonrails.org/active_record_basics.html", "https://rubygems.org/gems/rails"],
    "php": ["https://www.php.net/manual/en/book.pdo.php", "https://packagist.org/"],
    "ops": ["https://kubernetes.io/docs/concepts/configuration/secret/", "https://docs.docker.com/compose/",
            "https://nginx.org/en/docs/", "https://www.postgresql.org/docs/16/libpq-connect.html",
            "https://docs.github.com/en/actions", "https://prometheus.io/docs/introduction/overview/"],
    "general": ["https://semver.org/", "https://keepachangelog.com/en/1.1.0/", "https://www.rfc-editor.org/rfc/rfc9110",
                "https://www.apache.org/licenses/LICENSE-2.0", "https://json-schema.org/draft/2020-12/schema",
                "https://github.com/psf/requests", "https://www.conventionalcommits.org/en/v1.0.0/"],
}

TOKEN_PREFIXES = ["qfk_live_", "qfk_test_", "nbx_sk_", "lmv_pat_", "zrt1.", "brd-api-", "tsk_prod_",
                  "orz_svc_", "vlt_ak_", "mpf_", "cxr_live_", "hlx_tok_", "kvs-", "plm_sec_"]
PW_WORDS = {
    "en": ["Sunflower", "Marmalade", "Lighthouse", "Juniper", "Velvet", "Thunder", "Pebble", "Kestrel"],
    "de": ["Sonnenblume", "Kaffeetasse", "Leuchtturm", "Wanderweg", "Gartenzaun", "Apfelbaum", "Schneemann"],
    "fr": ["Tournesol", "Papillon", "Chouquette", "Lavande", "Marmotte", "Citronnade"],
    "it": ["Girasole", "Farfalla", "Cappuccino", "Lanterna", "Mandorla", "Pinguino"],
    "es": ["Girasol", "Mariposa", "Churros", "Almendra", "Tortuga", "Abanico"],
}
PASSPHRASE_WORDS = ["lantern", "quiver", "mosaic", "orbit", "tundra", "falcon", "pepper", "harbor",
                    "violet", "cobalt", "meadow", "anchor", "ripple", "saffron", "gravel", "comet"]
SYM_GENERAL = "!#%^&*-_=+.?@"
SYM_URL = "-_.~"
B62 = string.ascii_letters + string.digits
HEX = "0123456789abcdef"

CARD_BINS = [("411111", 16), ("400000", 16), ("424242", 16), ("401288", 16), ("555555", 16),
             ("510510", 16), ("222300", 16), ("378282", 15), ("371449", 15), ("601111", 16),
             ("353011", 16), ("305693", 14)]
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
VIN_TR = dict({str(i): i for i in range(10)}, A=1, B=2, C=3, D=4, E=5, F=6, G=7, H=8, J=1, K=2, L=3,
              M=4, N=5, P=7, R=9, S=2, T=3, U=4, V=5, W=6, X=7, Y=8, Z=9)
VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
VIN_WMIS = ["WK0", "VF8", "ZX9", "VSX", "SAX", "1Z4", "5YZ", "WK7", "ZD3"]
DE_DOC_ALPH = "0123456789CFGHJKLMNPRTVWXYZ"
CF_ODD = {"0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
          "A": 1, "B": 0, "C": 5, "D": 7, "E": 9, "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
          "K": 2, "L": 4, "M": 18, "N": 20, "O": 11, "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
          "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23}
DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
GB_BANKS = ["KRVL", "QFNB", "LMVB", "NBXB", "ASHB", "WHRF"]
PEM_KINDS = [  # (label, DER-ish prefix, random bytes, line width, weight)
    ("EC PRIVATE KEY", b"\x30\x77\x02\x01\x01\x04\x20", 112, 64, 4),
    ("PRIVATE KEY", b"\x30\x2e\x02\x01\x00\x30\x05\x06\x03\x2b\x65\x70\x04\x22\x04\x20", 32, 64, 3),
    ("OPENSSH PRIVATE KEY", b"openssh-key-v1\x00", 360, 70, 3),
    ("RSA PRIVATE KEY", b"\x30\x82\x04\xa4\x02\x01\x00\x02\x82\x01\x01\x00", 1180, 64, 1),
]

PLACEHOLDERS = {
    "private_person": ["<NAME>", "[REDACTED]", "{{ customer.name }}", "${AUTHOR_NAME}", "<redacted-name>", "XXXX"],
    "private_email": ["<EMAIL>", "${ALERT_EMAIL}", "{{ user.email }}", "[email removed]", "<redacted-email>"],
    "private_phone": ["<PHONE>", "+XX XXX XXXXXXX", "[phone removed]", "${SUPPORT_PHONE}"],
    "private_address": ["<ADDRESS>", "[address removed]", "{{ customer.address }}"],
    "private_date": ["<DATE>", "YYYY-MM-DD", "[date removed]", "DD.MM.YYYY"],
    "private_url": ["<INTERNAL_URL>", "${INTERNAL_API_URL}", "https://<internal-host>/<path>", "[link removed]"],
    "private_ip": ["<IP>", "x.x.x.x", "${DB_HOST}", "<redacted-ip>"],
    "private_mac": ["XX:XX:XX:XX:XX:XX", "<MAC>", "[mac removed]"],
    "account_number": ["<IBAN>", "<ACCOUNT_NUMBER>", "[REDACTED]", "XXXX-XXXX-XXXX-XXXX", "${PAYOUT_ACCOUNT}"],
    "secret": ["<YOUR_API_KEY>", "${DB_PASSWORD}", "********", "[REDACTED]", "{{ .Values.secret }}",
               "${{ secrets.DEPLOY_TOKEN }}", "REPLACE_ME", "<redacted>"],
    "private_passport": ["<PASSPORT_NO>", "[REDACTED]"],
    "private_driver_license": ["<LICENSE_NO>", "[REDACTED]"],
    "private_vehicle_id": ["<PLATE>", "<VIN>", "[REDACTED]"],
    "private_geolocation": ["<LAT>, <LON>", "[location removed]"],
}

PII_FIELD_WEIGHTS = [
    ("email", 10), ("phone", 8), ("address", 7), ("birth_date", 6), ("iban", 5), ("card_number", 3),
    ("national_id", 3), ("tax_id", 3), ("health_insurance_no", 2), ("passport_no", 2),
    ("driver_license", 2), ("license_plate", 2), ("vin", 1), ("last_location", 2),
    ("last_login_ip", 4), ("device_mac", 2), ("hire_date", 3), ("wallet", 1), ("username", 4),
]
NEUTRAL_FIELDS = ["status", "plan", "locale", "timezone", "created_at", "score", "newsletter",
                  "country", "currency", "tier", "version", "segment", "source", "external_ref",
                  "updated_at", "order_count", "loyalty_points", "risk_score", "marketing_opt_in"]
FIELD_LABELS = {
    "de": {"id": "id", "full_name": "name", "first_name": "vorname", "last_name": "nachname", "email": "email",
           "phone": "telefon", "address": "anschrift", "birth_date": "geburtsdatum", "iban": "iban",
           "bank_account": "konto", "card_number": "kartennummer", "national_id": "ausweis_nr",
           "tax_id": "steuer_id", "health_insurance_no": "kv_nummer", "passport_no": "pass_nr",
           "driver_license": "fuehrerschein_nr", "license_plate": "kennzeichen", "vin": "fin",
           "last_location": "letzter_standort", "last_login_ip": "letzte_ip", "device_mac": "geraete_mac",
           "hire_date": "eintrittsdatum", "wallet": "wallet", "username": "benutzer", "status": "status",
           "plan": "tarif", "locale": "sprache", "timezone": "zeitzone", "created_at": "angelegt_am",
           "score": "score", "newsletter": "newsletter", "country": "land", "currency": "waehrung",
           "tier": "stufe", "version": "version"},
    "fr": {"id": "id", "full_name": "nom_complet", "first_name": "prénom", "last_name": "nom", "email": "courriel",
           "phone": "téléphone", "address": "adresse", "birth_date": "date_naissance", "iban": "iban",
           "bank_account": "compte", "card_number": "num_carte", "national_id": "num_secu",
           "tax_id": "num_fiscal", "health_insurance_no": "num_assure", "passport_no": "passeport",
           "driver_license": "permis", "license_plate": "immatriculation", "vin": "vin",
           "last_location": "derniere_position", "last_login_ip": "derniere_ip", "device_mac": "mac_appareil",
           "hire_date": "date_embauche", "wallet": "portefeuille", "username": "identifiant",
           "status": "statut", "plan": "formule", "locale": "langue", "timezone": "fuseau",
           "created_at": "cree_le", "score": "score", "newsletter": "newsletter", "country": "pays",
           "currency": "devise", "tier": "niveau", "version": "version"},
    "it": {"id": "id", "full_name": "nome_completo", "first_name": "nome", "last_name": "cognome", "email": "email",
           "phone": "telefono", "address": "indirizzo", "birth_date": "data_nascita", "iban": "iban",
           "bank_account": "conto", "card_number": "numero_carta", "national_id": "codice_fiscale",
           "tax_id": "cod_fiscale_piva", "health_insurance_no": "tessera_sanitaria", "passport_no": "passaporto",
           "driver_license": "patente", "license_plate": "targa", "vin": "telaio",
           "last_location": "ultima_posizione", "last_login_ip": "ultimo_ip", "device_mac": "mac_dispositivo",
           "hire_date": "data_assunzione", "wallet": "wallet", "username": "utente", "status": "stato",
           "plan": "piano", "locale": "lingua", "timezone": "fuso_orario", "created_at": "creato_il",
           "score": "punteggio", "newsletter": "newsletter", "country": "paese", "currency": "valuta",
           "tier": "livello", "version": "versione"},
    "es": {"id": "id", "full_name": "nombre_completo", "first_name": "nombre", "last_name": "apellidos",
           "email": "correo", "phone": "telefono", "address": "direccion", "birth_date": "fecha_nacimiento",
           "iban": "iban", "bank_account": "cuenta", "card_number": "num_tarjeta", "national_id": "dni_nie",
           "tax_id": "nif", "health_insurance_no": "num_seg_social", "passport_no": "pasaporte",
           "driver_license": "permiso_conducir", "license_plate": "matricula", "vin": "bastidor",
           "last_location": "ultima_ubicacion", "last_login_ip": "ultima_ip", "device_mac": "mac_dispositivo",
           "hire_date": "fecha_alta", "wallet": "monedero", "username": "usuario", "status": "estado",
           "plan": "plan", "locale": "idioma", "timezone": "zona_horaria", "created_at": "creado_en",
           "score": "puntuacion", "newsletter": "boletin", "country": "pais", "currency": "moneda",
           "tier": "nivel", "version": "version"},
}

# ------------------------------------------------------- localized sentences

NEUTRAL_SENT = {
    "en": ["The retry logic now backs off exponentially after the third failure.",
           "We agreed to keep the cache TTL at five minutes until the migration is finished.",
           "Most of the latency comes from the synchronous call to the pricing service.",
           "The nightly export has been stable since the connection pool was resized.",
           "Nobody could reproduce the issue on staging, only in production.",
           "The dashboard shows a clear drop in error rate after the rollback.",
           "We still need a decision on whether to drop support for the old API version.",
           "The test suite takes eleven minutes on CI, which is too slow for every push.",
           "Disk usage on the log volume is at 78 percent and growing slowly.",
           "The vendor confirmed that the outage on their side is resolved.",
           "Please keep comments in the ticket rather than in private messages.",
           "The new queue consumer processes about 900 messages per second.",
           "We will revisit the alert thresholds after two weeks of data.",
           "Documentation for the endpoint is still missing the error codes.",
           "The migration script is idempotent, so it is safe to run it twice.",
           "We moved the cron schedule to 02:00 UTC to avoid the backup window.",
           "Memory usage stays flat after the fix, even under peak load.",
           "The feature flag stays off for enterprise tenants until the audit is done.",
           "Logs older than fourteen days are rotated to cold storage automatically.",
           "The rate limiter now returns a Retry-After header with every 429 response.",
           "We should pin the base image digest instead of using the latest tag.",
           "Half of the flaky tests were caused by a shared temporary directory."],
    "de": ["Die Wiederholungslogik wartet nach dem dritten Fehler jetzt exponentiell länger.",
           "Wir lassen die Cache-Laufzeit bei fünf Minuten, bis die Migration abgeschlossen ist.",
           "Der Großteil der Latenz entsteht durch den synchronen Aufruf des Preisdienstes.",
           "Der nächtliche Export läuft stabil, seit der Connection-Pool vergrößert wurde.",
           "Auf Staging ließ sich der Fehler nicht reproduzieren, nur in Produktion.",
           "Das Dashboard zeigt nach dem Rollback einen deutlichen Rückgang der Fehlerrate.",
           "Wir müssen noch entscheiden, ob die alte API-Version weiter unterstützt wird.",
           "Die Testsuite braucht in der CI elf Minuten, das ist für jeden Push zu langsam.",
           "Das Log-Volume ist zu 78 Prozent belegt und wächst langsam weiter.",
           "Der Dienstleister hat bestätigt, dass die Störung auf seiner Seite behoben ist.",
           "Bitte Kommentare im Ticket hinterlassen und nicht per Direktnachricht.",
           "Der neue Queue-Consumer verarbeitet etwa 900 Nachrichten pro Sekunde.",
           "Die Alarmschwellen schauen wir uns nach zwei Wochen Daten noch einmal an.",
           "In der Doku zum Endpunkt fehlen noch die Fehlercodes.",
           "Das Migrationsskript ist idempotent, ein zweiter Lauf ist also unkritisch.",
           "Den Cron-Zeitplan haben wir auf 02:00 UTC verschoben, um das Backup-Fenster zu meiden.",
           "Der Speicherverbrauch bleibt nach dem Fix auch unter Last konstant.",
           "Das Feature-Flag bleibt für Enterprise-Mandanten aus, bis das Audit abgeschlossen ist.",
           "Logs, die älter als vierzehn Tage sind, wandern automatisch in den Cold Storage.",
           "Der Rate Limiter liefert jetzt bei jeder 429-Antwort einen Retry-After-Header.",
           "Wir sollten den Digest des Basis-Images festschreiben, statt das latest-Tag zu nutzen.",
           "Die Hälfte der instabilen Tests lag an einem gemeinsam genutzten Temp-Verzeichnis."],
    "fr": ["La logique de relance attend désormais de façon exponentielle après le troisième échec.",
           "Nous gardons la durée du cache à cinq minutes jusqu'à la fin de la migration.",
           "L'essentiel de la latence vient de l'appel synchrone au service de tarification.",
           "L'export nocturne est stable depuis que le pool de connexions a été agrandi.",
           "Personne n'a pu reproduire le problème en préproduction, seulement en production.",
           "Le tableau de bord montre une nette baisse du taux d'erreur après le retour arrière.",
           "Il faut encore décider si l'on abandonne l'ancienne version de l'API.",
           "La suite de tests prend onze minutes en CI, c'est trop lent pour chaque push.",
           "Le volume des journaux est rempli à 78 % et continue de grossir lentement.",
           "Le prestataire a confirmé que l'incident de son côté est résolu.",
           "Merci de commenter dans le ticket plutôt qu'en message privé.",
           "Le nouveau consommateur de file traite environ 900 messages par seconde.",
           "Nous reverrons les seuils d'alerte après deux semaines de données.",
           "La documentation de l'endpoint ne liste pas encore les codes d'erreur.",
           "Le script de migration est idempotent, on peut donc le relancer sans risque.",
           "Nous avons déplacé la tâche cron à 02:00 UTC pour éviter la fenêtre de sauvegarde.",
           "La consommation mémoire reste stable après le correctif, même en pic de charge.",
           "Le flag reste désactivé pour les clients entreprise jusqu'à la fin de l'audit.",
           "Les journaux de plus de quatorze jours partent automatiquement en stockage froid.",
           "Le limiteur de débit renvoie désormais un en-tête Retry-After avec chaque réponse 429.",
           "Il faudrait figer le digest de l'image de base au lieu d'utiliser le tag latest.",
           "La moitié des tests instables venaient d'un répertoire temporaire partagé."],
    "it": ["La logica di retry ora attende in modo esponenziale dopo il terzo errore.",
           "Teniamo il TTL della cache a cinque minuti finché la migrazione non è conclusa.",
           "Gran parte della latenza deriva dalla chiamata sincrona al servizio prezzi.",
           "L'export notturno è stabile da quando abbiamo ingrandito il pool di connessioni.",
           "Nessuno è riuscito a riprodurre il problema in staging, solo in produzione.",
           "La dashboard mostra un netto calo del tasso di errore dopo il rollback.",
           "Dobbiamo ancora decidere se abbandonare la vecchia versione dell'API.",
           "La suite di test impiega undici minuti in CI, troppo per ogni push.",
           "Il volume dei log è occupato al 78 per cento e cresce lentamente.",
           "Il fornitore ha confermato che il disservizio da parte loro è risolto.",
           "Per favore commentate nel ticket e non in chat privata.",
           "Il nuovo consumer della coda elabora circa 900 messaggi al secondo.",
           "Rivedremo le soglie degli alert dopo due settimane di dati.",
           "Nella documentazione dell'endpoint mancano ancora i codici di errore.",
           "Lo script di migrazione è idempotente, quindi rilanciarlo non crea problemi.",
           "Abbiamo spostato il cron alle 02:00 UTC per evitare la finestra di backup.",
           "Dopo la correzione l'uso di memoria resta stabile anche nei picchi di carico.",
           "Il flag resta spento per i tenant enterprise finché l'audit non è concluso.",
           "I log più vecchi di quattordici giorni passano automaticamente nello storage freddo.",
           "Il rate limiter ora restituisce un header Retry-After con ogni risposta 429.",
           "Dovremmo fissare il digest dell'immagine base invece di usare il tag latest.",
           "Metà dei test instabili dipendeva da una directory temporanea condivisa."],
    "es": ["La lógica de reintentos ahora espera de forma exponencial tras el tercer fallo.",
           "Mantenemos el TTL de la caché en cinco minutos hasta terminar la migración.",
           "Casi toda la latencia viene de la llamada síncrona al servicio de precios.",
           "La exportación nocturna es estable desde que ampliamos el pool de conexiones.",
           "Nadie pudo reproducir el problema en preproducción, solo en producción.",
           "El panel muestra una clara bajada de la tasa de errores tras el rollback.",
           "Aún hay que decidir si dejamos de dar soporte a la versión antigua de la API.",
           "La batería de pruebas tarda once minutos en CI, demasiado para cada push.",
           "El volumen de logs está al 78 por ciento y sigue creciendo despacio.",
           "El proveedor confirmó que la incidencia por su parte está resuelta.",
           "Por favor, comentad en el ticket y no por mensaje privado.",
           "El nuevo consumidor de la cola procesa unos 900 mensajes por segundo.",
           "Revisaremos los umbrales de alerta tras dos semanas de datos.",
           "A la documentación del endpoint todavía le faltan los códigos de error.",
           "El script de migración es idempotente, así que se puede lanzar dos veces sin problema.",
           "Hemos movido el cron a las 02:00 UTC para evitar la ventana de copias de seguridad.",
           "El consumo de memoria se mantiene estable tras el arreglo, incluso en los picos de carga.",
           "El flag sigue desactivado para los clientes enterprise hasta que termine la auditoría.",
           "Los logs de más de catorce días pasan automáticamente al almacenamiento en frío.",
           "El limitador de peticiones devuelve ahora una cabecera Retry-After con cada respuesta 429.",
           "Deberíamos fijar el digest de la imagen base en lugar de usar la etiqueta latest.",
           "La mitad de los tests inestables se debían a un directorio temporal compartido."],
}

PII_SENT = {
    "en": ["Please call ⟦name⟧ back on ⟦phone⟧, the callback was promised for today.",
           "⟦name⟧ has moved, the new address is ⟦address⟧.",
           "The refund of 84.20 EUR goes to ⟦iban⟧, account holder ⟦name⟧.",
           "⟦given⟧ is on leave from ⟦d1⟧ until ⟦d2⟧.",
           "We saw repeated login failures for ⟦handle⟧ coming from ⟦ip⟧.",
           "Send the signed contract to ⟦email⟧ and keep a copy in the shared folder.",
           "The last GPS fix from the courier app for ⟦name⟧ was ⟦geo⟧.",
           "Company car ⟦plate⟧ is assigned to ⟦name⟧.",
           "I gave ⟦given⟧ the temporary password ⟦pw⟧, it must be changed at first login.",
           "Customer ⟦name⟧, born ⟦dob⟧, asked for a copy of all stored data.",
           "For the travel booking we need passport number ⟦passport⟧ of ⟦name⟧.",
           "Card ⟦card⟧ was charged twice for the order of ⟦name⟧.",
           "The staging key ⟦token⟧ was pasted into the channel and has to be rotated.",
           "The laptop of ⟦name⟧ (MAC ⟦mac⟧) keeps dropping off the Wi-Fi.",
           "ID number on file for ⟦name⟧: ⟦natid⟧.",
           "Please check the driving licence ⟦dl⟧ of ⟦name⟧ before handing over the van.",
           "The appointment with ⟦name⟧ was moved to ⟦appt⟧.",
           "The shared report for ⟦given⟧ is at ⟦url⟧.",
           "The leased vehicle with VIN ⟦vin⟧ goes back to the dealer next month."],
    "de": ["Bitte ⟦name⟧ unter ⟦phone⟧ zurückrufen, der Rückruf war für heute zugesagt.",
           "⟦name⟧ ist umgezogen, die neue Anschrift lautet ⟦address⟧.",
           "Die Erstattung über 84,20 EUR geht an ⟦iban⟧, Kontoinhaber ⟦name⟧.",
           "⟦given⟧ ist vom ⟦d1⟧ bis zum ⟦d2⟧ im Urlaub.",
           "Für ⟦handle⟧ gab es wiederholt fehlgeschlagene Logins von ⟦ip⟧.",
           "Den unterschriebenen Vertrag bitte an ⟦email⟧ schicken und eine Kopie ablegen.",
           "Der letzte GPS-Punkt aus der Kurier-App für ⟦name⟧ war ⟦geo⟧.",
           "Der Dienstwagen ⟦plate⟧ ist ⟦name⟧ zugeordnet.",
           "Ich habe ⟦given⟧ das Initialpasswort ⟦pw⟧ gegeben, es muss beim ersten Login geändert werden.",
           "Kundin ⟦name⟧, geboren am ⟦dob⟧, hat eine Kopie aller gespeicherten Daten angefordert.",
           "Für die Reisebuchung brauchen wir die Passnummer ⟦passport⟧ von ⟦name⟧.",
           "Die Karte ⟦card⟧ wurde für die Bestellung von ⟦name⟧ doppelt belastet.",
           "Der Staging-Key ⟦token⟧ wurde in den Channel gepostet und muss rotiert werden.",
           "Der Laptop von ⟦name⟧ (MAC ⟦mac⟧) verliert ständig das WLAN.",
           "Hinterlegte Ausweis- bzw. Steuernummer für ⟦name⟧: ⟦natid⟧.",
           "Bitte den Führerschein ⟦dl⟧ von ⟦name⟧ prüfen, bevor der Transporter übergeben wird.",
           "Der Termin mit ⟦name⟧ wurde auf den ⟦appt⟧ verschoben.",
           "Der freigegebene Bericht für ⟦given⟧ liegt unter ⟦url⟧.",
           "Das Leasingfahrzeug mit der FIN ⟦vin⟧ geht nächsten Monat an den Händler zurück."],
    "fr": ["Merci de rappeler ⟦name⟧ au ⟦phone⟧, le rappel était promis pour aujourd'hui.",
           "⟦name⟧ a déménagé, la nouvelle adresse est ⟦address⟧.",
           "Le remboursement de 84,20 EUR part sur ⟦iban⟧, titulaire ⟦name⟧.",
           "⟦given⟧ est en congé du ⟦d1⟧ au ⟦d2⟧.",
           "Plusieurs échecs de connexion pour ⟦handle⟧ depuis ⟦ip⟧.",
           "Envoyez le contrat signé à ⟦email⟧ et gardez une copie dans le dossier partagé.",
           "La dernière position GPS de l'application coursier pour ⟦name⟧ était ⟦geo⟧.",
           "Le véhicule de service ⟦plate⟧ est attribué à ⟦name⟧.",
           "J'ai donné à ⟦given⟧ le mot de passe provisoire ⟦pw⟧, à changer à la première connexion.",
           "Le client ⟦name⟧, né le ⟦dob⟧, demande une copie de toutes ses données.",
           "Pour la réservation du voyage il nous faut le numéro de passeport ⟦passport⟧ de ⟦name⟧.",
           "La carte ⟦card⟧ a été débitée deux fois pour la commande de ⟦name⟧.",
           "La clé de préprod ⟦token⟧ a été collée dans le canal, il faut la révoquer.",
           "L'ordinateur de ⟦name⟧ (MAC ⟦mac⟧) perd sans cesse le Wi-Fi.",
           "Numéro d'identification enregistré pour ⟦name⟧ : ⟦natid⟧.",
           "Vérifiez le permis de conduire ⟦dl⟧ de ⟦name⟧ avant de remettre la camionnette.",
           "Le rendez-vous avec ⟦name⟧ est déplacé au ⟦appt⟧.",
           "Le rapport partagé pour ⟦given⟧ se trouve sur ⟦url⟧.",
           "Le véhicule en leasing (VIN ⟦vin⟧) retourne chez le concessionnaire le mois prochain."],
    "it": ["Per favore richiamare ⟦name⟧ al ⟦phone⟧, la richiamata era promessa per oggi.",
           "⟦name⟧ ha traslocato, il nuovo indirizzo è ⟦address⟧.",
           "Il rimborso di 84,20 EUR va su ⟦iban⟧, intestatario ⟦name⟧.",
           "⟦given⟧ è in ferie dal ⟦d1⟧ al ⟦d2⟧.",
           "Ripetuti accessi falliti per ⟦handle⟧ provenienti da ⟦ip⟧.",
           "Inviate il contratto firmato a ⟦email⟧ e conservatene una copia nella cartella condivisa.",
           "L'ultima posizione GPS dell'app corrieri per ⟦name⟧ era ⟦geo⟧.",
           "L'auto aziendale ⟦plate⟧ è assegnata a ⟦name⟧.",
           "Ho dato a ⟦given⟧ la password temporanea ⟦pw⟧, va cambiata al primo accesso.",
           "Il cliente ⟦name⟧, nato il ⟦dob⟧, ha chiesto una copia di tutti i dati conservati.",
           "Per la prenotazione del viaggio serve il numero di passaporto ⟦passport⟧ di ⟦name⟧.",
           "La carta ⟦card⟧ è stata addebitata due volte per l'ordine di ⟦name⟧.",
           "La chiave di staging ⟦token⟧ è stata incollata nel canale e va ruotata.",
           "Il portatile di ⟦name⟧ (MAC ⟦mac⟧) perde continuamente il Wi-Fi.",
           "Codice identificativo registrato per ⟦name⟧: ⟦natid⟧.",
           "Controllate la patente ⟦dl⟧ di ⟦name⟧ prima di consegnare il furgone.",
           "L'appuntamento con ⟦name⟧ è stato spostato al ⟦appt⟧.",
           "Il report condiviso per ⟦given⟧ si trova su ⟦url⟧.",
           "Il veicolo in leasing con telaio ⟦vin⟧ torna al concessionario il mese prossimo."],
    "es": ["Por favor, llamad a ⟦name⟧ al ⟦phone⟧, la llamada estaba prometida para hoy.",
           "⟦name⟧ se ha mudado, la nueva dirección es ⟦address⟧.",
           "El reembolso de 84,20 EUR va a ⟦iban⟧, titular ⟦name⟧.",
           "⟦given⟧ está de vacaciones del ⟦d1⟧ al ⟦d2⟧.",
           "Varios intentos de acceso fallidos para ⟦handle⟧ desde ⟦ip⟧.",
           "Enviad el contrato firmado a ⟦email⟧ y guardad una copia en la carpeta compartida.",
           "La última posición GPS de la app de reparto para ⟦name⟧ fue ⟦geo⟧.",
           "El coche de empresa ⟦plate⟧ está asignado a ⟦name⟧.",
           "Le di a ⟦given⟧ la contraseña temporal ⟦pw⟧, debe cambiarla en el primer acceso.",
           "El cliente ⟦name⟧, nacido el ⟦dob⟧, ha pedido una copia de todos sus datos.",
           "Para la reserva del viaje necesitamos el número de pasaporte ⟦passport⟧ de ⟦name⟧.",
           "La tarjeta ⟦card⟧ se cobró dos veces en el pedido de ⟦name⟧.",
           "La clave de preproducción ⟦token⟧ se pegó en el canal y hay que rotarla.",
           "El portátil de ⟦name⟧ (MAC ⟦mac⟧) pierde la wifi constantemente.",
           "Número de identificación registrado para ⟦name⟧: ⟦natid⟧.",
           "Comprobad el permiso de conducir ⟦dl⟧ de ⟦name⟧ antes de entregar la furgoneta.",
           "La cita con ⟦name⟧ se ha movido al ⟦appt⟧.",
           "El informe compartido para ⟦given⟧ está en ⟦url⟧.",
           "El vehículo de renting con bastidor ⟦vin⟧ vuelve al concesionario el mes que viene."],
}

CODE_COMMENTS = {
    "en": ["TODO: remove once the migration is finished", "keep in sync with the billing schema",
           "values copied from the staging ticket", "FIXME: this should come from the vault",
           "do not change without telling the payments team", "used by the nightly export",
           "temporary workaround, see incident review", "default timeout is too low for the EU region",
           "only for local development", "legacy field, kept for the mobile app"],
    "de": ["TODO: entfernen, sobald die Migration durch ist", "synchron halten mit dem Abrechnungsschema",
           "Werte aus dem Staging-Ticket übernommen", "FIXME: sollte aus dem Vault kommen",
           "nicht ändern, ohne das Payments-Team zu informieren", "wird vom nächtlichen Export genutzt",
           "vorübergehender Workaround, siehe Incident-Review", "Standard-Timeout ist für die EU-Region zu knapp",
           "nur für die lokale Entwicklung", "Altfeld, bleibt für die Mobile-App erhalten"],
    "fr": ["TODO : à supprimer une fois la migration terminée", "à garder synchronisé avec le schéma de facturation",
           "valeurs reprises du ticket de préprod", "FIXME : devrait venir du coffre-fort",
           "ne pas modifier sans prévenir l'équipe paiements", "utilisé par l'export nocturne",
           "contournement temporaire, voir la revue d'incident", "le délai par défaut est trop court pour la région UE",
           "uniquement pour le développement local", "champ hérité, conservé pour l'appli mobile"],
    "it": ["TODO: rimuovere a migrazione conclusa", "tenere allineato con lo schema di fatturazione",
           "valori copiati dal ticket di staging", "FIXME: dovrebbe arrivare dal vault",
           "non modificare senza avvisare il team pagamenti", "usato dall'export notturno",
           "workaround temporaneo, vedi la review dell'incidente", "il timeout di default è troppo basso per la regione UE",
           "solo per lo sviluppo locale", "campo legacy, mantenuto per l'app mobile"],
    "es": ["TODO: eliminar cuando termine la migración", "mantener sincronizado con el esquema de facturación",
           "valores copiados del ticket de preproducción", "FIXME: debería venir del vault",
           "no cambiar sin avisar al equipo de pagos", "lo usa la exportación nocturna",
           "solución temporal, ver la revisión del incidente", "el timeout por defecto es demasiado bajo para la región UE",
           "solo para desarrollo local", "campo heredado, se mantiene por la app móvil"],
}

LOG_PII = {
    "en": ["Invoice INV-⟦n⟧ sent to ⟦email⟧", "Login failed for user ⟦handle⟧ from ⟦ip⟧",
           "Address updated for customer ⟦cid⟧: ⟦address⟧", "Payment declined for card ⟦card⟧ (code 51)",
           "Password reset requested by ⟦email⟧", "SMS verification code sent to ⟦phone⟧",
           "Payout of ⟦amt⟧ EUR scheduled to ⟦iban⟧", "New device ⟦mac⟧ registered for ⟦handle⟧",
           "KYC check passed for ⟦name⟧ (document ⟦passport⟧)", "Profile of ⟦name⟧ exported on request"],
    "de": ["Rechnung INV-⟦n⟧ an ⟦email⟧ versendet", "Anmeldung fehlgeschlagen für Benutzer ⟦handle⟧ von ⟦ip⟧",
           "Adresse für Kunde ⟦cid⟧ aktualisiert: ⟦address⟧", "Zahlung abgelehnt für Karte ⟦card⟧ (Code 51)",
           "Passwort-Reset angefordert von ⟦email⟧", "SMS-Bestätigungscode an ⟦phone⟧ gesendet",
           "Auszahlung von ⟦amt⟧ EUR an ⟦iban⟧ geplant", "Neues Gerät ⟦mac⟧ für ⟦handle⟧ registriert",
           "KYC-Prüfung bestanden für ⟦name⟧ (Dokument ⟦passport⟧)", "Profil von ⟦name⟧ auf Anfrage exportiert"],
    "fr": ["Facture INV-⟦n⟧ envoyée à ⟦email⟧", "Échec de connexion pour l'utilisateur ⟦handle⟧ depuis ⟦ip⟧",
           "Adresse mise à jour pour le client ⟦cid⟧ : ⟦address⟧", "Paiement refusé pour la carte ⟦card⟧ (code 51)",
           "Réinitialisation du mot de passe demandée par ⟦email⟧", "Code de vérification SMS envoyé au ⟦phone⟧",
           "Virement de ⟦amt⟧ EUR programmé vers ⟦iban⟧", "Nouvel appareil ⟦mac⟧ enregistré pour ⟦handle⟧",
           "Contrôle KYC validé pour ⟦name⟧ (document ⟦passport⟧)", "Profil de ⟦name⟧ exporté sur demande"],
    "it": ["Fattura INV-⟦n⟧ inviata a ⟦email⟧", "Accesso fallito per l'utente ⟦handle⟧ da ⟦ip⟧",
           "Indirizzo aggiornato per il cliente ⟦cid⟧: ⟦address⟧", "Pagamento rifiutato per la carta ⟦card⟧ (codice 51)",
           "Reset della password richiesto da ⟦email⟧", "Codice di verifica SMS inviato al ⟦phone⟧",
           "Bonifico di ⟦amt⟧ EUR pianificato verso ⟦iban⟧", "Nuovo dispositivo ⟦mac⟧ registrato per ⟦handle⟧",
           "Verifica KYC superata per ⟦name⟧ (documento ⟦passport⟧)", "Profilo di ⟦name⟧ esportato su richiesta"],
    "es": ["Factura INV-⟦n⟧ enviada a ⟦email⟧", "Inicio de sesión fallido para el usuario ⟦handle⟧ desde ⟦ip⟧",
           "Dirección actualizada para el cliente ⟦cid⟧: ⟦address⟧", "Pago rechazado para la tarjeta ⟦card⟧ (código 51)",
           "Restablecimiento de contraseña solicitado por ⟦email⟧", "Código de verificación SMS enviado al ⟦phone⟧",
           "Transferencia de ⟦amt⟧ EUR programada a ⟦iban⟧", "Nuevo dispositivo ⟦mac⟧ registrado para ⟦handle⟧",
           "Verificación KYC superada para ⟦name⟧ (documento ⟦passport⟧)", "Perfil de ⟦name⟧ exportado a petición"],
}
LOG_NEUTRAL = {
    "en": ["Cache warmed in ⟦ms⟧ms (⟦n⟧ keys)", "Retrying request ⟦rid⟧ (attempt 2/5)", "Health check OK",
           "Scheduled job finished, ⟦n⟧ rows processed", "Connection pool resized to 32", "GC pause ⟦ms⟧ms",
           "Request ⟦rid⟧ completed with status 200 in ⟦ms⟧ms", "Feature flag new-checkout evaluated to false"],
    "de": ["Cache in ⟦ms⟧ms aufgewärmt (⟦n⟧ Schlüssel)", "Wiederhole Anfrage ⟦rid⟧ (Versuch 2/5)", "Health-Check OK",
           "Geplanter Job beendet, ⟦n⟧ Zeilen verarbeitet", "Connection-Pool auf 32 vergrößert", "GC-Pause ⟦ms⟧ms",
           "Anfrage ⟦rid⟧ mit Status 200 in ⟦ms⟧ms abgeschlossen", "Feature-Flag new-checkout ergibt false"],
    "fr": ["Cache préchauffé en ⟦ms⟧ ms (⟦n⟧ clés)", "Nouvelle tentative pour la requête ⟦rid⟧ (essai 2/5)",
           "Contrôle de santé OK", "Tâche planifiée terminée, ⟦n⟧ lignes traitées", "Pool de connexions porté à 32",
           "Pause GC ⟦ms⟧ ms", "Requête ⟦rid⟧ terminée avec le statut 200 en ⟦ms⟧ ms", "Le flag new-checkout vaut false"],
    "it": ["Cache riscaldata in ⟦ms⟧ms (⟦n⟧ chiavi)", "Nuovo tentativo per la richiesta ⟦rid⟧ (tentativo 2/5)",
           "Health check OK", "Job pianificato terminato, ⟦n⟧ righe elaborate", "Pool di connessioni portato a 32",
           "Pausa GC ⟦ms⟧ms", "Richiesta ⟦rid⟧ completata con stato 200 in ⟦ms⟧ms", "Il flag new-checkout vale false"],
    "es": ["Caché precalentada en ⟦ms⟧ ms (⟦n⟧ claves)", "Reintentando la petición ⟦rid⟧ (intento 2/5)",
           "Health check OK", "Tarea programada terminada, ⟦n⟧ filas procesadas", "Pool de conexiones ampliado a 32",
           "Pausa de GC ⟦ms⟧ ms", "Petición ⟦rid⟧ completada con estado 200 en ⟦ms⟧ ms", "El flag new-checkout vale false"],
}
CHANGELOG_ITEMS = {
    "en": ["Fix rounding of VAT amounts on credit notes", "Retry webhook delivery with exponential backoff",
           "Add CSV export for the customer list", "Drop support for Node 18",
           "Validate IBAN check digits before saving", "Speed up the invoice search by 40 percent",
           "Show the correct time zone in reminder e-mails", "Update the PostgreSQL driver to the latest patch release"],
    "de": ["Rundung der USt.-Beträge auf Gutschriften korrigiert", "Webhook-Zustellung mit exponentiellem Backoff wiederholen",
           "CSV-Export für die Kundenliste hinzugefügt", "Unterstützung für Node 18 entfernt",
           "IBAN-Prüfziffern vor dem Speichern validieren", "Rechnungssuche um 40 Prozent beschleunigt",
           "Korrekte Zeitzone in Erinnerungs-E-Mails anzeigen", "PostgreSQL-Treiber auf das neueste Patch-Release aktualisiert"],
    "fr": ["Correction de l'arrondi de la TVA sur les avoirs", "Relance des webhooks avec un délai exponentiel",
           "Ajout d'un export CSV de la liste des clients", "Fin du support de Node 18",
           "Vérification de la clé IBAN avant l'enregistrement", "Recherche de factures 40 % plus rapide",
           "Affichage du bon fuseau horaire dans les e-mails de relance", "Mise à jour du pilote PostgreSQL vers le dernier correctif"],
    "it": ["Corretto l'arrotondamento dell'IVA sulle note di credito", "Nuovi tentativi dei webhook con backoff esponenziale",
           "Aggiunto export CSV dell'elenco clienti", "Rimosso il supporto per Node 18",
           "Verifica delle cifre di controllo IBAN prima del salvataggio", "Ricerca fatture più veloce del 40 per cento",
           "Fuso orario corretto nelle email di promemoria", "Aggiornato il driver PostgreSQL all'ultima patch"],
    "es": ["Corregido el redondeo del IVA en las facturas rectificativas", "Reintento de webhooks con espera exponencial",
           "Añadida exportación CSV del listado de clientes", "Eliminado el soporte para Node 18",
           "Validación de los dígitos de control del IBAN antes de guardar", "Búsqueda de facturas un 40 por ciento más rápida",
           "Zona horaria correcta en los correos de recordatorio", "Actualizado el driver de PostgreSQL al último parche"],
}
CHAT_SHORT = {
    "en": ["ok", "thanks!", "on it", "give me 5 min", "done", "can you check?", "same here", "+1", "looking now"],
    "de": ["ok", "danke!", "bin dran", "gib mir 5 Min", "erledigt", "kannst du mal schauen?", "bei mir auch", "+1", "schaue gerade"],
    "fr": ["ok", "merci !", "je m'en occupe", "donne-moi 5 min", "fait", "tu peux vérifier ?", "pareil ici", "+1", "je regarde"],
    "it": ["ok", "grazie!", "ci sono", "dammi 5 min", "fatto", "puoi controllare?", "anche qui", "+1", "sto guardando"],
    "es": ["ok", "¡gracias!", "me pongo", "dame 5 min", "hecho", "¿puedes revisarlo?", "aquí igual", "+1", "mirando ahora"],
}

# ------------------------------------------------------------ check digits


def iban_check_digits(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return "%02d" % (98 - int(numeric) % 97)


def iban_valid(iban: str) -> bool:
    s = iban.replace(" ", "")
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def luhn_digit(partial: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(partial)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - total % 10) % 10)


def luhn_valid(number: str) -> bool:
    digits = re.sub(r"\D", "", number)
    return luhn_digit(digits[:-1]) == digits[-1]


def it_check_char(s: str) -> str:
    total = 0
    for i, c in enumerate(s):
        total += CF_ODD[c] if i % 2 == 0 else (int(c) if c.isdigit() else ord(c) - 65)
    return chr(65 + total % 26)


def es_dc(ten: str) -> str:
    weights = [1, 2, 4, 8, 5, 10, 9, 7, 3, 6]
    dc = 11 - sum(int(c) * w for c, w in zip(ten, weights)) % 11
    return str({10: 1, 11: 0}.get(dc, dc))


def de_mod11_10(digits: str) -> str:
    product = 10
    for ch in digits:
        s = (int(ch) + product) % 10
        if s == 0:
            s = 10
        product = (s * 2) % 11
    check = 11 - product
    return "0" if check == 10 else str(check)


def icao_check(s: str) -> str:
    weights = [7, 3, 1]
    vals = [int(c) if c.isdigit() else ord(c) - 55 for c in s]
    return str(sum(v * weights[i % 3] for i, v in enumerate(vals)) % 10)


def bech32_polymod(values: List[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= gen[i]
    return chk


def bech32_address(hrp: str, witver: int, program: bytes) -> str:
    acc, bits, data = 0, 0, [witver]
    for value in program:
        acc = (acc << 8) | value
        bits += 8
        while bits >= 5:
            bits -= 5
            data.append((acc >> bits) & 31)
    if bits:
        data.append((acc << (5 - bits)) & 31)
    expanded = [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]
    polymod = bech32_polymod(expanded + data + [0] * 6) ^ 1
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(BECH32_CHARSET[d] for d in data + checksum)


def base58check(payload: bytes) -> str:
    full = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n = int.from_bytes(full, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = B58[rem] + out
    pad = len(full) - len(full.lstrip(b"\0"))
    return "1" * pad + out


UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", "ı": "i"})


def ascii_fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.translate(UMLAUT))
    return "".join(c for c in s if not unicodedata.combining(c)).encode("ascii", "ignore").decode("ascii")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", ascii_fold(s).lower())


def camel(k: str) -> str:
    parts = k.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def pascal(k: str) -> str:
    return "ID" if k == "id" else "".join(p.capitalize() for p in k.split("_"))


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


# ------------------------------------------------------------- core types


class PII(NamedTuple):
    label: str
    value: str


Value = Union[str, PII, int, float, list, tuple]
SLOT_RE = re.compile("⟦(\\w+)⟧")


def vt(x) -> str:
    """Text a value will occupy in the document."""
    if isinstance(x, PII):
        return x.value
    if isinstance(x, (list, tuple)):
        return "".join(vt(y) for y in x)
    return str(x)


class Doc:
    """Append-only text builder that records the offsets of planted values."""

    def __init__(self) -> None:
        self._parts: List[str] = []
        self.spans: List[Tuple[int, int, str, str]] = []
        self.n = 0

    def __len__(self) -> int:
        return self.n

    def t(self, s: str) -> "Doc":
        if not isinstance(s, str):
            raise TypeError("Doc.t expects str, got %r" % type(s))
        self._parts.append(s)
        self.n += len(s)
        return self

    def v(self, x) -> "Doc":
        if isinstance(x, PII):
            if x.label not in LABEL_SET:
                raise ValueError("unknown label %r" % x.label)
            self.spans.append((self.n, self.n + len(x.value), x.label, x.value))
            return self.t(x.value)
        if isinstance(x, (list, tuple)):
            for y in x:
                self.v(y)
            return self
        if isinstance(x, bool):
            raise TypeError("render booleans explicitly")
        return self.t(str(x))

    def f(self, tpl: str, **kw) -> "Doc":
        used = set()
        pos = 0
        for m in SLOT_RE.finditer(tpl):
            self.t(tpl[pos:m.start()])
            key = m.group(1)
            if key not in kw:
                raise KeyError("template slot %r has no value" % key)
            self.v(kw[key])
            used.add(key)
            pos = m.end()
        self.t(tpl[pos:])
        unused = set(kw) - used
        if unused:
            raise KeyError("values given for unknown slots: %s" % sorted(unused))
        return self

    def extend(self, other: "Doc") -> "Doc":
        for s, e, lab, val in other.spans:
            self.spans.append((s + self.n, e + self.n, lab, val))
        return self.t(other.text())

    def text(self) -> str:
        return "".join(self._parts)


def lit(d: Doc, v, q: str = '"', t: str = "true", f: str = "false", null: str = "null") -> None:
    """Render a scalar as a literal in code/config syntaxes."""
    if v is None:
        d.t(null)
    elif isinstance(v, bool):
        d.t(t if v else f)
    elif isinstance(v, (int, float)):
        d.t(str(v))
    else:
        if q and q in vt(v):
            raise ValueError("quote character inside literal: %r" % vt(v))
        d.t(q)
        d.v(v)
        d.t(q)


class Person(NamedTuple):
    given: str
    family: str
    gender: str
    plang: str
    middle: str
    handle: str
    gslug: str
    fslug: str


# ------------------------------------------------------------- generator


class Gen:
    """Per-document value factory. Planted values are returned as PII; in
    clean documents every planted value is replaced by a placeholder string."""

    def __init__(self, rng: random.Random, lang: str, clean: bool) -> None:
        self.r = rng
        self.lang = lang
        self.clean = clean
        self.country = COUNTRY_OF_LANG.get(lang) or rng.choice(("US", "GB"))
        self.co_name, self.co_domain = rng.choice(COMPANIES[lang])
        self.slug = self.co_domain.split(".")[0]
        self.clock = dt.datetime(2026, rng.randint(1, 10), rng.randint(1, 28), rng.randint(0, 23),
                                 rng.randint(0, 59), rng.randint(0, 59), rng.randint(0, 999) * 1000)
        self.tzo = {"US": "-0500", "GB": "+0100"}.get(self.country, "+0200")

    # ---- randomness helpers
    def chance(self, p: float) -> bool:
        return self.r.random() < p

    def pick(self, seq):
        return self.r.choice(seq)

    def rint(self, a: int, b: int) -> int:
        return self.r.randint(a, b)

    def weighted(self, pairs):
        total = sum(w for _, w in pairs)
        x = self.r.uniform(0, total)
        for item, w in pairs:
            x -= w
            if x <= 0:
                return item
        return pairs[-1][0]

    def weighted_sample(self, pairs, k: int):
        pool = list(pairs)
        out = []
        for _ in range(min(k, len(pool))):
            item = self.weighted(pool)
            out.append(item)
            pool = [p for p in pool if p[0] != item]
        return out

    def tx(self, en: str, de: str, fr: str, it: str, es: str) -> str:
        return {"en": en, "de": de, "fr": fr, "it": it, "es": es}[self.lang]

    def loop(self, d: Doc, target: int, min_iter: int = 1, max_iter: int = 400):
        i = 0
        while i < min_iter or (len(d) < target and i < max_iter):
            yield i
            i += 1

    def b62(self, n: int) -> str:
        return "".join(self.r.choice(B62) for _ in range(n))

    def hexs(self, n: int) -> str:
        return "".join(self.r.choice(HEX) for _ in range(n))

    def digits(self, n: int, first_nonzero: bool = False) -> str:
        s = "".join(str(self.r.randint(0, 9)) for _ in range(n))
        if first_nonzero and s[0] == "0":
            s = str(self.r.randint(1, 9)) + s[1:]
        return s

    def letters(self, n: int, alphabet: str = string.ascii_uppercase) -> str:
        return "".join(self.r.choice(alphabet) for _ in range(n))

    def rbytes(self, n: int) -> bytes:
        return bytes(self.r.getrandbits(8) for _ in range(n))

    def other_country(self, p: float) -> str:
        return self.pick(ALL_COUNTRIES) if self.chance(p) else self.country

    def _pii(self, label: str, value: str):
        if label not in LABEL_SET:
            raise ValueError("unknown label %r" % label)
        if not value or value != value.strip():
            raise ValueError("bad planted value for %s: %r" % (label, value))
        if self.clean:
            return self.pick(PLACEHOLDERS[label])
        return PII(label, value)

    # ---- distractors (never labelled)
    def uuid(self) -> str:
        h = self.hexs(32)
        return "%s-%s-4%s-%s%s-%s" % (h[:8], h[8:12], h[13:16], self.pick("89ab"), h[17:20], h[20:])

    def sha(self) -> str:
        return self.hexs(40)

    def sha256(self) -> str:
        return self.hexs(64)

    def ver(self) -> str:
        a, b, c = self.rint(0, 9), self.rint(0, 30), self.rint(0, 40)
        return self.pick(["%d.%d.%d" % (a, b, c), "v%d.%d.%d" % (a, b, c), "%d.%d.%d-rc.%d" % (a, b, c, self.rint(1, 5)),
                          "%d.%d" % (a + 1, b)])

    def port(self) -> int:
        return self.pick([80, 443, 3000, 5432, 6379, 8000, 8080, 8443, 9090, 9200, 5672, 3306])

    def req_id(self) -> str:
        return self.pick(["req_" + self.b62(16), self.uuid(), self.hexs(16), "r-" + self.hexs(12)])

    def trace_id(self) -> str:
        return self.hexs(32)

    def amount(self) -> str:
        return "%d.%02d" % (self.rint(3, 4999), self.rint(0, 99))

    def locale(self) -> str:
        return self.pick(LOCALES)

    def tz(self) -> str:
        return self.pick(TZS)

    def region(self) -> str:
        return self.pick(REGIONS)

    def product(self) -> str:
        return self.pick(PRODUCTS)

    def pub_url(self, topic: str = "general") -> str:
        return self.pick(PUB_URLS[topic] + PUB_URLS["general"])

    def co_homepage(self) -> str:
        return "https://www." + self.co_domain

    def int_host(self, role: str) -> str:
        return self.pick(["%s-primary.%s.internal" % (role, self.slug), "%s01.prod.%s.lan" % (role, self.slug),
                          "%s-replica.%s.internal" % (role, self.slug), "%s.svc.cluster.local" % role])

    def pymod(self) -> str:
        return self.slug.replace("-", "_")

    def code_comment(self) -> str:
        return self.pick(CODE_COMMENTS[self.lang])

    def neutral(self) -> str:
        return self.pick(NEUTRAL_SENT[self.lang])

    def placeholder_secret(self) -> str:
        return self.pick(PLACEHOLDERS["secret"][:2] + ["${API_TOKEN}", "<token>", "xxxxxxxx"])

    # ---- clock (machine timestamps, never labelled)
    def tick(self, lo: int = 1, hi: int = 30) -> None:
        self.clock += dt.timedelta(seconds=self.rint(lo, hi), milliseconds=self.rint(0, 999))

    def ts_iso(self) -> str:
        c = self.clock
        return c.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (c.microsecond // 1000)

    def ts_space(self, sep: str = ",") -> str:
        c = self.clock
        return c.strftime("%Y-%m-%d %H:%M:%S") + sep + "%03d" % (c.microsecond // 1000)

    def ts_sec(self) -> str:
        return self.clock.strftime("%Y-%m-%d %H:%M:%S")

    def ts_nginx(self) -> str:
        c = self.clock
        return "%02d/%s/%d:%s %s" % (c.day, MON_ABBR[c.month - 1], c.year, c.strftime("%H:%M:%S"), self.tzo)

    def ts_syslog(self) -> str:
        c = self.clock
        return "%s %2d %s" % (MON_ABBR[c.month - 1], c.day, c.strftime("%H:%M:%S"))

    def ts_git(self) -> str:
        c = self.clock
        return "%s %s %d %s %d %s" % (DAY_ABBR[c.weekday()], MON_ABBR[c.month - 1], c.day, c.strftime("%H:%M:%S"),
                                      c.year, self.tzo)

    def ts_rfc2822(self) -> str:
        c = self.clock
        return "%s, %d %s %d %s %s" % (DAY_ABBR[c.weekday()], c.day, MON_ABBR[c.month - 1], c.year,
                                       c.strftime("%H:%M:%S"), self.tzo)

    def hhmm(self) -> str:
        return self.clock.strftime("%H:%M")

    def epoch(self) -> int:
        return int(self.clock.replace(tzinfo=dt.timezone.utc).timestamp())

    # ---- persons
    def person(self, plang: str = None, safe: bool = False) -> Person:
        while True:
            pl = plang or (self.lang if self.chance(0.8) else self.pick(LANGS))
            gender = self.pick("FM")
            given = self.pick(GIVEN[pl][0 if gender == "F" else 1])
            family = self._family(pl)
            if safe and ("'" in given or "'" in family):
                continue
            break
        middle = (self.pick("ABCDEFGHJKLMNPRSTW") + ".") if pl == "en" and self.chance(0.15) else ""
        tokens = [t for t in family.replace("-", " ").split() if t.lower() not in PARTICLES]
        main = tokens[0] if pl == "es" else tokens[-1]
        gs = slug(given.replace("-", " ").split()[0])
        fs = slug(main)
        y2 = "%02d" % self.rint(70, 99)
        handle = self.pick([gs[0] + fs, gs + "." + fs, gs + fs[0], gs + "_" + fs, fs + gs[0],
                            gs + fs[:2] + y2, gs[0] + "." + fs, fs + "." + gs])
        return Person(given, family, gender, pl, middle, handle, gs, fs)

    def _family(self, pl: str) -> str:
        if pl != "es":
            return self.pick(FAMILY[pl])
        a, b = self.r.sample(FAMILY["es"], 2)
        r = self.r.random()
        if r < 0.15:
            return a
        if r < 0.28:
            return a + "-" + b
        return a + " " + b

    def name(self, p: Person, form: str = "full"):
        if form == "any":
            form = self.weighted([("full", 7), ("initial", 1), ("rev", 1), ("upper_family", 1)])
        if form == "full":
            s = " ".join(x for x in (p.given, p.middle, p.family) if x)
        elif form == "given":
            s = p.given
        elif form == "family":
            s = p.family
        elif form == "initial":
            s = "%s. %s" % (p.given[0], p.family)
        elif form == "rev":
            s = "%s, %s" % (p.family, p.given)
        elif form == "upper_family":
            s = "%s %s" % (p.family.upper(), p.given)
        else:
            raise ValueError(form)
        return self._pii("private_person", s)

    def handle(self, p: Person):
        return self._pii("private_person", p.handle)

    def email(self, p: Person, kind: str = None):
        kind = kind or self.weighted([("work", 6), ("personal", 3), ("partner", 1)])
        g, f = p.gslug, p.fslug
        if kind == "work":
            local = self.pick(["%s.%s" % (g, f), "%s.%s" % (g[0], f), "%s%s" % (g[0], f), "%s%s" % (g, f[0]),
                               "%s.%s" % (f, g)])
            dom = self.co_domain
        elif kind == "personal":
            local = self.pick(["%s.%s%s" % (g, f, self.digits(2)), "%s_%s" % (g, f), "%s%s%d" % (g, f[0], self.rint(1, 999)),
                               "%s.%s" % (g, f)])
            dom = self.pick(PERSONAL_DOMAINS)
        else:
            local = "%s.%s" % (g, f)
            dom = self.pick(COMPANIES[self.pick(LANGS)])[1]
        if self.chance(0.05):
            local += "+" + self.pick(["invoices", "test", "jira", "newsletter"])
        return self._pii("private_email", "%s@%s" % (local, dom))

    def mailbox(self):
        return self._pii("private_email", "%s@%s" % (self.pick(ROLE_MAILBOXES), self.co_domain))

    # ---- contact data
    def phone(self, country: str = None):
        c = country or self.other_country(0.1)
        r = self.r
        if c == "US":
            a, x = r.choice(US_AREAS), "%02d" % r.randint(0, 99)
            s = r.choice(["(%s) 555-01%s" % (a, x), "+1 %s-555-01%s" % (a, x), "%s.555.01%s" % (a, x),
                          "+1%s55501%s" % (a, x), "%s-555-01%s" % (a, x), "+1 (%s) 555-01%s" % (a, x)])
        elif c == "GB":
            k = "%03d" % r.randint(0, 999)
            s = r.choice(["07700 900" + k, "+44 7700 900" + k, "+447700900" + k, "020 7946 0" + k,
                          "+44 20 7946 0" + k, "0113 496 0" + k, "0117 496 0" + k, "0161 496 0" + k])
        elif c == "FR":
            a, b = "%02d" % r.randint(0, 99), "%02d" % r.randint(0, 99)
            s = r.choice(["06 39 98 %s %s" % (a, b), "+33 6 39 98 %s %s" % (a, b), "063998%s%s" % (a, b),
                          "01 99 00 %s %s" % (a, b), "+33 1 99 00 %s %s" % (a, b), "06.39.98.%s.%s" % (a, b)])
        elif c == "DE":
            if self.chance(0.55):
                pre, n = r.choice(DE_MOBILE), self.digits(7)
                s = r.choice(["%s %s" % (pre, n), "+49 %s %s" % (pre[1:], n), "+49%s%s" % (pre[1:], n),
                              "%s/%s" % (pre, n), "%s-%s %s" % (pre, n[:3], n[3:])])
            else:
                area, n = r.choice(DE_AREAS), self.digits(r.randint(6, 8), True)
                s = r.choice(["%s %s %s" % (area, n[:4], n[4:]), "%s/%s" % (area, n), "+49 %s %s" % (area[1:], n),
                              "+49 (0)%s %s" % (area[1:], n), "+49-%s-%s" % (area[1:], n)])
        elif c == "IT":
            if self.chance(0.6):
                pre, n = r.choice(IT_MOBILE), self.digits(7)
                s = r.choice(["%s %s %s" % (pre, n[:3], n[3:]), "+39 %s %s" % (pre, n), "+39%s%s" % (pre, n),
                              "%s/%s" % (pre, n)])
            else:
                area, n = r.choice(IT_LAND), self.digits(r.randint(6, 8), True)
                s = r.choice(["%s %s %s" % (area, n[:4], n[4:]), "+39 %s %s" % (area, n), "%s-%s" % (area, n)])
        else:
            if self.chance(0.6):
                m = "6" + self.digits(8)
                s = r.choice(["%s %s %s %s" % (m[:3], m[3:5], m[5:7], m[7:]), "+34 %s %s %s" % (m[:3], m[3:6], m[6:]),
                              "+34%s" % m, "%s %s %s" % (m[:3], m[3:6], m[6:])])
            else:
                area = r.choice(ES_LAND)
                n = self.digits(9 - len(area))
                full = area + n
                s = r.choice(["%s %s %s %s" % (full[:2], full[2:5], full[5:7], full[7:]),
                              "+34 %s %s %s" % (full[:3], full[3:6], full[6:]), full])
        return self._pii("private_phone", s)

    def address(self, multiline: bool = False, country: str = None, sep: str = None):
        c = country or self.other_country(0.1)
        r = self.r
        city, reg, pc, _, _ = r.choice(CITIES[c])
        street = r.choice(STREETS[c])
        with_country = self.chance(0.25)
        nl = "\n" if multiline else ", "
        if c == "US":
            zip5 = pc + self.digits(2)
            unit = (", Apt %d%s" % (r.randint(1, 30), r.choice(["", "A", "B"]))) if self.chance(0.3) else ""
            s = "%d %s%s%s%s, %s %s" % (r.randint(10, 9999), street, unit, nl, city, reg, zip5)
        elif c == "GB":
            letters = "ABDEFGHJLNPQRSTUWXYZ"
            post = "%s%d %d%s" % (pc, r.randint(1, 28), r.randint(1, 9), self.letters(2, letters))
            s = "%d %s%s%s%s%s" % (r.randint(1, 240), street, nl, city, "\n" if multiline else " ", post)
        elif c == "DE":
            num = "%d%s" % (r.randint(1, 180), r.choice(["", "", "", "a", "b"]))
            s = "%s %s%s%s%s %s" % (street, num, nl, pc, self.digits(3), city)
        elif c == "FR":
            num = "%d%s" % (r.randint(1, 140), r.choice(["", "", "", " bis"]))
            s = "%s %s%s%s%s %s" % (num, street, nl, pc, self.digits(2), city)
        elif c == "IT":
            s = "%s %d%s%s%s %s (%s)" % (street, r.randint(1, 220), nl, pc, self.digits(2), city, reg)
        else:
            floor = "%dº %s" % (r.randint(1, 9), r.choice("ABCDI"))
            s = "%s, %d, %s%s%s%s %s" % (street, r.randint(1, 160), floor, nl, pc, self.digits(2), city)
        if with_country:
            s += nl + COUNTRY_NAME[c]
        if sep is not None:
            s = s.replace(", ", sep).replace("\n", sep)
        return self._pii("private_address", s)

    def _date(self, kind: str) -> dt.date:
        lo, hi = DATE_RANGES[kind]
        return dt.date(self.rint(lo, hi), self.rint(1, 12), self.rint(1, 28))

    def _date_fmt(self, style: str) -> str:
        if style == "iso":
            return "iso"
        fmts = DATE_FORMATS[self.country]
        if style == "prose":
            fmts = [f for f in fmts if f != "iso"]
        return self.pick(fmts)

    def render_date(self, d: dt.date, fmt: str) -> str:
        y, m, day = d.year, d.month, d.day
        if fmt == "iso":
            return d.isoformat()
        if fmt == "us_slash":
            return "%02d/%02d/%d" % (m, day, y)
        if fmt == "eu_slash":
            return "%02d/%02d/%d" % (day, m, y)
        if fmt == "dot":
            return "%02d.%02d.%d" % (day, m, y)
        if fmt == "dot_nopad":
            return "%d.%d.%d" % (day, m, y)
        if fmt == "dash_eu":
            return "%02d-%02d-%d" % (day, m, y)
        if fmt == "long_en_us":
            return "%s %d, %d" % (MONTHS["en"][m - 1], day, y)
        if fmt == "abbr_en_us":
            return "%s %d, %d" % (MON_ABBR[m - 1], day, y)
        if fmt == "long_en_gb":
            return "%d %s %d" % (day, MONTHS["en"][m - 1], y)
        if fmt == "long_de":
            return "%d. %s %d" % (day, MONTHS["de"][m - 1], y)
        if fmt == "long_fr":
            return "%s %s %d" % ("1er" if day == 1 else str(day), MONTHS["fr"][m - 1], y)
        if fmt == "long_it":
            return "%d %s %d" % (day, MONTHS["it"][m - 1], y)
        if fmt == "long_es":
            return "%d de %s de %d" % (day, MONTHS["es"][m - 1], y)
        raise ValueError(fmt)

    def pdate(self, kind: str = "dob", style: str = "any"):
        return self._pii("private_date", self.render_date(self._date(kind), self._date_fmt(style)))

    def pdate_pair(self, kind: str = "leave", style: str = "prose"):
        d1 = self._date(kind)
        d2 = d1 + dt.timedelta(days=self.rint(3, 21))
        fmt = self._date_fmt(style)
        return self._pii("private_date", self.render_date(d1, fmt)), self._pii("private_date", self.render_date(d2, fmt))

    # ---- account numbers
    def iban(self, country: str = None, spaced: bool = None):
        c = country or self.other_country(0.15)
        if c == "US":
            return self._pii("account_number", self.digits(self.rint(9, 12), True))
        if c == "DE":
            bban = str(self.rint(1, 8)) + self.digits(7) + self.digits(10)
        elif c == "FR":
            bank, branch, acct = "%05d" % self.rint(10000, 49999), self.digits(5), self.digits(11)
            key = 97 - ((89 * int(bank) + 15 * int(branch) + 3 * int(acct)) % 97)
            bban = bank + branch + acct + "%02d" % key
        elif c == "IT":
            abi, cab, acct = self.digits(5), self.digits(5), self.digits(12)
            bban = it_check_char(abi + cab + acct) + abi + cab + acct
        elif c == "ES":
            bank, branch, acct = self.digits(4), self.digits(4), self.digits(10)
            bban = bank + branch + es_dc("00" + bank + branch) + es_dc(acct) + acct
        else:
            bban = self.pick(GB_BANKS) + self.digits(6) + self.digits(8)
        s = c + iban_check_digits(c, bban) + bban
        if not iban_valid(s):
            raise AssertionError("generated invalid IBAN")
        if spaced is None:
            spaced = self.chance(0.5)
        if spaced:
            s = " ".join(s[i:i + 4] for i in range(0, len(s), 4))
        return self._pii("account_number", s)

    def card(self):
        bin_, length = self.pick(CARD_BINS)
        body = bin_ + self.digits(length - len(bin_) - 1)
        num = body + luhn_digit(body)
        if not luhn_valid(num):
            raise AssertionError("generated invalid card number")
        groups = {15: [4, 6, 5], 14: [4, 6, 4]}.get(length, [4, 4, 4, 4])
        sep = self.pick([" ", "-", ""])
        out, i = [], 0
        for gsz in groups:
            out.append(num[i:i + gsz])
            i += gsz
        return self._pii("account_number", sep.join(out))

    def _itin(self) -> str:
        if self.chance(0.15):
            return "987-65-432%d" % self.rint(0, 9)
        return "9%s-%d-%s" % (self.digits(2), self.rint(70, 88), self.digits(4))

    def _nino(self) -> str:
        first, second = "ABCEGHJKLMNOPRSTWXYZ", "ABCEGHJKLMNPRSTWXYZ"
        while True:
            pre = self.pick(first) + self.pick(second)
            if pre not in ("BG", "GB", "NK", "KN", "TN", "NT", "ZZ"):
                break
        d = self.digits(6)
        suf = self.pick("ABCD")
        return self.pick(["%s %s %s %s %s" % (pre, d[:2], d[2:4], d[4:], suf), pre + d + suf])

    def _de_idcard(self) -> str:
        s = self.pick("LMNPRTVWXYZ") + self.letters(8, DE_DOC_ALPH)
        return s + icao_check(s)

    def _de_sv(self) -> str:
        area = "%02d" % self.rint(10, 89)
        b = self._date("dob")
        letter = self.pick("ABDEFGHKLMNOPRSTWZ")
        serial = "%02d" % self.rint(0, 99)
        digits = area + b.strftime("%d%m%y") + "%02d" % (ord(letter) - 64) + serial
        weights = [2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1]
        total = sum(sum(divmod(int(c) * w, 10)) for c, w in zip(digits, weights))
        core = area + b.strftime("%d%m%y") + letter + serial + str(total % 10)
        return self.pick([core, "%s %s %s %s" % (core[:2], core[2:8], core[8], core[9:])])

    def _de_steuer_id(self) -> str:
        while True:
            ds = self.r.sample(range(10), 9)
            ds.append(self.pick(ds))
            self.r.shuffle(ds)
            if ds[0] != 0:
                break
        s = "".join(map(str, ds))
        s += de_mod11_10(s)
        return self.pick([s, "%s %s %s %s" % (s[:2], s[2:5], s[5:8], s[8:])])

    def _de_kvnr(self) -> str:
        letter = self.pick(string.ascii_uppercase)
        body = self.digits(8)
        digits = "%02d" % (ord(letter) - 64) + body
        total = 0
        for i, c in enumerate(digits):
            prod = int(c) * (1 if i % 2 == 0 else 2)
            total += prod if prod < 10 else prod - 9
        return letter + body + str(total % 10)

    def _nir(self) -> str:
        sex = self.pick("12")
        yy, mm = "%02d" % self.rint(50, 99), "%02d" % self.rint(1, 12)
        dept = "%02d" % self.pick([n for n in range(1, 96) if n != 20])
        commune, order = "%03d" % self.rint(1, 999), "%03d" % self.rint(1, 999)
        n13 = sex + yy + mm + dept + commune + order
        key = "%02d" % (97 - int(n13) % 97)
        return self.pick(["%s %s %s %s %s %s %s" % (sex, yy, mm, dept, commune, order, key), n13 + key])

    def _cf(self, p: Person = None) -> str:
        if p is None or p.plang != "it":
            p = self.person(plang="it")

        def code(name: str, is_given: bool) -> str:
            letters = [c for c in ascii_fold(name).upper() if c.isalpha()]
            cons = [c for c in letters if c not in "AEIOU"]
            vows = [c for c in letters if c in "AEIOU"]
            if is_given and len(cons) >= 4:
                return cons[0] + cons[2] + cons[3]
            return ("".join(cons) + "".join(vows) + "XXX")[:3]

        b = self._date("dob")
        day = b.day + (40 if p.gender == "F" else 0)
        s15 = (code(p.family, False) + code(p.given, True) + "%02d" % (b.year % 100) + "ABCDEHLMPRST"[b.month - 1]
               + "%02d" % day + self.pick("ABCDEFGHILM") + self.digits(3))
        return s15 + it_check_char(s15)

    def _dni(self) -> str:
        n = self.rint(10000000, 99999999)
        s = "%08d%s" % (n, DNI_LETTERS[n % 23])
        return self.pick([s, "%s.%s.%s-%s" % (s[:2], s[2:5], s[5:8], s[8])])

    def _nie(self) -> str:
        i = self.rint(0, 2)
        n = self.digits(7)
        return "XYZ"[i] + n + DNI_LETTERS[int(str(i) + n) % 23]

    def _nss(self) -> str:
        prov, num = "%02d" % self.rint(1, 52), self.digits(8)
        check = "%02d" % (int(prov + num) % 97)
        return self.pick(["%s/%s/%s" % (prov, num, check), "%s %s%s" % (prov, num, check)])

    def _nhs(self) -> str:
        while True:
            body = "999" + self.digits(6)
            rem = sum(int(c) * w for c, w in zip(body, range(10, 1, -1))) % 11
            check = 11 - rem
            if check == 10:
                continue
            s = body + str(0 if check == 11 else check)
            return "%s %s %s" % (s[:3], s[3:6], s[6:])

    def _mbi(self) -> str:
        let = "ACDEFGHJKMNPQRTUVWXY"
        an = let + "0123456789"
        s = (str(self.rint(1, 9)) + self.pick(let) + self.pick(an) + str(self.rint(0, 9)) + self.pick(let)
             + self.pick(an) + str(self.rint(0, 9)) + self.pick(let) + self.pick(let) + self.digits(2))
        return self.pick([s, "%s-%s-%s" % (s[:4], s[4:7], s[7:])])

    def _piva(self) -> str:
        base = self.digits(7, True) + "%03d" % self.rint(1, 100)
        x = sum(int(base[i]) for i in range(0, 10, 2))
        y = 0
        for i in range(1, 10, 2):
            v = int(base[i]) * 2
            y += v - 9 if v > 9 else v
        return base + str((10 - (x + y) % 10) % 10)

    def natid(self, p: Person = None):
        c = self.other_country(0.1)
        if c == "US":
            v = self._itin()
        elif c == "GB":
            v = self._nino()
        elif c == "DE":
            v = self._de_idcard() if self.chance(0.5) else self._de_sv()
        elif c == "FR":
            v = self._nir()
        elif c == "IT":
            v = self._cf(p)
        else:
            v = self._dni() if self.chance(0.75) else self._nie()
        return self._pii("account_number", v)

    def taxid(self, p: Person = None):
        c = self.other_country(0.1)
        if c == "US":
            v = self.pick(["%s-%s" % (self.pick(["12", "20", "27", "45", "46", "81", "82", "84", "87", "88"]), self.digits(7)),
                           self._itin()])
        elif c == "GB":
            u = self.digits(10, True)
            v = self.pick([u, "%s %s" % (u[:5], u[5:])])
        elif c == "DE":
            if self.chance(0.6):
                v = self._de_steuer_id()
            else:
                b = self.digits(8, True)
                v = "DE" + b + de_mod11_10(b)
        elif c == "FR":
            s = str(self.rint(0, 3)) + self.digits(12)
            v = self.pick([s, "%s %s %s %s %s" % (s[:2], s[2:4], s[4:7], s[7:10], s[10:])])
        elif c == "IT":
            v = self._cf(p) if self.chance(0.5) else self.pick(["IT", ""]) + self._piva()
        else:
            v = self._dni() if self.chance(0.7) else self._nie()
        return self._pii("account_number", v)

    def healthid(self, p: Person = None):
        c = self.other_country(0.1)
        v = {"US": self._mbi, "GB": self._nhs, "DE": self._de_kvnr, "FR": self._nir,
             "IT": lambda: self._cf(p), "ES": self._nss}[c]()
        return self._pii("account_number", v)

    def crypto(self):
        kind = self.pick(["bech32", "b58", "eth"])
        if kind == "bech32":
            v = bech32_address("bc", 0, self.rbytes(20))
        elif kind == "b58":
            v = base58check(b"\x00" + self.rbytes(20))
        else:
            v = "0x" + self.hexs(40)
        return self._pii("account_number", v)

    def account(self, p: Person = None):
        return self.pick([self.iban, self.card, lambda: self.natid(p), lambda: self.taxid(p),
                          lambda: self.healthid(p), self.crypto])()

    # ---- documents and vehicles
    def passport(self):
        c = self.other_country(0.1)
        if c in ("US", "GB"):
            v = self.pick([self.digits(9, True), self.pick("ACEFGH") + self.digits(8)]) if c == "US" else self.digits(9, True)
        elif c == "DE":
            v = "C" + self.letters(8, DE_DOC_ALPH)
        elif c == "FR":
            v = self.digits(2) + self.letters(2) + self.digits(5)
        elif c == "IT":
            v = self.letters(2) + self.digits(7)
        else:
            v = self.pick(["PA", "XD", "AA"]) + self.letters(1) + self.digits(6)
        return self._pii("private_passport", v)

    def dl(self, p: Person = None):
        c = self.other_country(0.1)
        if c == "US":
            v = self.pick([self.letters(1) + self.digits(7), "%s %s %s" % (self.digits(3), self.digits(3), self.digits(3)),
                           self.digits(8), "%s%s-%s-%s-%s-%s" % (self.letters(1), self.digits(3), self.digits(3),
                                                                 self.digits(2), self.digits(3), self.digits(1))])
        elif c == "GB":
            q = p or self.person(plang="en")
            b = self._date("dob")
            sur = (slug(q.family).upper() + "99999")[:5]
            month = b.month + (50 if q.gender == "F" else 0)
            ini = (q.gslug[:1].upper() + (q.middle[:1] or "9"))
            v = "%s%d%02d%02d%d%s9%s" % (sur, (b.year // 10) % 10, month, b.day, b.year % 10, ini, self.letters(2))
        elif c == "DE":
            v = self.letters(1) + self.digits(3) + self.letters(5, string.ascii_uppercase + string.digits) + self.digits(2)
        elif c == "FR":
            v = self.digits(12)
        elif c == "IT":
            v = self.pick(["MI", "RM", "TO", "NA", "BO", "FI", "VR", "U1"]) + self.digits(7) + self.letters(1)
        else:
            v = self._dni()
        return self._pii("private_driver_license", v)

    def plate(self):
        c = self.other_country(0.1)
        if c == "DE":
            city = self.pick(["B", "HH", "M", "K", "L", "FR", "HB", "DD", "MS"])
            v = "%s%s%s %d%s" % (city, self.pick(["-", " "]), self.letters(self.rint(1, 2)), self.rint(1, 9999),
                                 "E" if self.chance(0.1) else "")
        elif c == "FR":
            a = "ABCDEFGHJKLMNPQRSTVWXYZ"
            v = "%s-%s-%s" % (self.letters(2, a), self.digits(3), self.letters(2, a))
        elif c == "IT":
            a = "ABCDEFGHJKLMNPRSTVWXYZ"
            v = self.pick(["%s %s%s", "%s%s%s"]) % (self.letters(2, a), self.digits(3), self.letters(2, a))
        elif c == "ES":
            v = "%s %s" % (self.digits(4), self.letters(3, "BCDFGHJKLMNPRSTVWXYZ"))
        elif c == "GB":
            a = "ABCDEFGHJKLMNOPRSTUVWXY"
            v = "%s%s %s" % (self.letters(2, a), self.pick(["21", "71", "22", "72", "23", "73", "24", "74"]),
                             self.letters(3, a))
        else:
            v = self.pick(["%d%s%s" % (self.rint(1, 9), self.letters(3), self.digits(3)),
                           "%s-%s" % (self.letters(3), self.digits(4))])
        return self._pii("private_vehicle_id", v)

    def vin(self):
        raw = (self.pick(VIN_WMIS) + self.letters(5, VIN_CHARS) + "0" + self.pick("LMNPRSTV")
               + self.pick(VIN_CHARS) + self.digits(6))
        s = sum(VIN_TR[c] * w for c, w in zip(raw, VIN_WEIGHTS)) % 11
        return self._pii("private_vehicle_id", raw[:8] + ("X" if s == 10 else str(s)) + raw[9:])

    def geo(self, prose: bool = False):
        c = self.other_country(0.1)
        _, _, _, lat0, lon0 = self.pick(CITIES[c])
        lat, lon = lat0 + self.r.uniform(-0.06, 0.06), lon0 + self.r.uniform(-0.06, 0.06)
        fmts = ["pair", "pair_tight", "geo_uri"] + (["dms", "deg_words"] if prose else [])
        f = self.pick(fmts)
        if f == "pair":
            v = "%.5f, %.5f" % (lat, lon)
        elif f == "pair_tight":
            v = "%.6f,%.6f" % (lat, lon)
        elif f == "geo_uri":
            v = "geo:%.5f,%.5f" % (lat, lon)
        elif f == "dms":
            v = "%s %s" % (self._dms(lat, "NS"), self._dms(lon, "EW"))
        else:
            v = "%.4f° %s, %.4f° %s" % (abs(lat), "N" if lat >= 0 else "S", abs(lon), "E" if lon >= 0 else "W")
        return self._pii("private_geolocation", v)

    @staticmethod
    def _dms(v: float, hemis: str) -> str:
        a = abs(v)
        deg = int(a)
        mins = int((a - deg) * 60)
        secs = ((a - deg) * 60 - mins) * 60
        return "%d°%02d'%04.1f\"%s" % (deg, mins, secs, hemis[0] if v >= 0 else hemis[1])

    # ---- network
    def ip(self, v6: bool = None):
        if v6 is None:
            v6 = self.chance(0.12)
        r = self.r
        if v6:
            kind = r.choice(["doc", "doc", "ula", "ll"])
            groups = ["%x" % r.randint(1, 0xFFFF) for _ in range(4)]
            if kind == "doc":
                v = r.choice(["2001:db8:%s:%s::%s" % (groups[0], groups[1], groups[2]),
                              "2001:db8:%s:%s:%s:%s:%x:%x" % (groups[0], groups[1], groups[2], groups[3],
                                                              r.randint(1, 0xFFFF), r.randint(1, 0xFFFF))])
            elif kind == "ula":
                v = "fd%02x:%s:%s::%x" % (r.randint(0, 255), groups[0], groups[1], r.randint(2, 0xFFF))
            else:
                v = "fe80::%s:%s:%s:%s" % tuple(groups)
            return self._pii("private_ip", v)
        x = r.random()
        if x < 0.30:
            v = "10.%d.%d.%d" % (r.randint(0, 255), r.randint(0, 255), r.randint(2, 254))
        elif x < 0.45:
            v = "172.%d.%d.%d" % (r.randint(16, 31), r.randint(0, 255), r.randint(2, 254))
        elif x < 0.62:
            v = "192.168.%d.%d" % (r.randint(0, 255), r.randint(2, 254))
        elif x < 0.90:
            v = "%s.%d" % (r.choice(["192.0.2", "198.51.100", "203.0.113"]), r.randint(2, 254))
        else:
            v = "100.%d.%d.%d" % (r.randint(64, 127), r.randint(0, 255), r.randint(2, 254))
        return self._pii("private_ip", v)

    def mac(self):
        b = [self.rint(0, 255) for _ in range(6)]
        b[0] &= 0xFE
        f = self.pick(["colon", "colon", "colon_upper", "dash", "cisco"])
        if f == "colon":
            v = ":".join("%02x" % x for x in b)
        elif f == "colon_upper":
            v = ":".join("%02X" % x for x in b)
        elif f == "dash":
            v = "-".join("%02X" % x for x in b)
        else:
            h = "".join("%02x" % x for x in b)
            v = "%s.%s.%s" % (h[:4], h[4:8], h[8:])
        return self._pii("private_mac", v)

    def purl(self):
        dom, sl, r = self.co_domain, self.slug, self.r
        n = r.randint(1000, 99999)
        opts = [
            "https://grafana.int.%s/d/%s/payments-overview?orgId=%d&var-env=prod" % (dom, self.b62(9), r.randint(1, 9)),
            "https://gitlab.%s/%s/%s/-/blob/main/%s" % (dom, r.choice(TEAMS), r.choice(REPOS), r.choice(CFG_PATHS)),
            "https://jira.%s/browse/%s-%d" % (dom, r.choice(["OPS", "PAY", "CRM", "HR", "SEC"]), r.randint(100, 9999)),
            "https://app.%s/account/users/%d/billing" % (dom, n),
            "https://files.%s/share/%s?dl=1&token=%s" % (dom, self.b62(12), self.b62(24)),
            "https://hooks.chat.%s/services/T%s/B%s/%s" % (dom, self.letters(8, string.ascii_uppercase + string.digits),
                                                           self.letters(8, string.ascii_uppercase + string.digits), self.b62(24)),
            "http://admin.%s.internal:8080/users/%d/edit" % (sl, n),
            "https://crm.%s/contacts/%d?view=full" % (dom, n),
            "https://github.com/%s-internal/%s/blob/main/%s" % (sl, r.choice(REPOS), r.choice(CFG_PATHS)),
            "https://kibana.int.%s/app/discover#/?_a=(query:(language:kuery,query:'user.id:%d'))" % (dom, n),
            "https://objects.%s/%s-private-exports/2026/customers_%d.csv?X-Sig=%s&X-Expires=%d" % (
                dom, sl, n, self.hexs(40), r.randint(1780000000, 1800000000)),
            "https://calendar.%s/booking/%s?attendee=%d" % (dom, self.b62(10), n),
            "https://wiki.intra.%s/display/HR/Employee+File+%d" % (dom, n),
        ]
        return self._pii("private_url", r.choice(opts))

    def api_user_url(self):
        n = self.rint(1000, 999999)
        path = self.pick(["customers", "users", "accounts", "employees", "patients"])
        return self._pii("private_url", "https://api.%s/v%d/%s/%d" % (self.co_domain, self.rint(1, 3), path, n))

    def repo_url(self):
        return self._pii("private_url", "https://gitlab.%s/%s/%s.git" % (self.co_domain, self.pick(TEAMS), self.pick(REPOS)))

    # ---- secrets
    def token(self):
        return self._pii("secret", self.pick(TOKEN_PREFIXES) + self.b62(self.rint(24, 40)))

    def jwt(self):
        alg = self.pick(["HS256", "RS256", "ES256"])
        hdr = {"alg": alg, "typ": "JWT"}
        if alg != "HS256":
            hdr["kid"] = self.hexs(16)
        iat = self.epoch()
        payload = {"sub": str(self.rint(10000, 9999999)), "iss": "https://auth.%s/" % self.co_domain,
                   "aud": self.slug + "-api", "iat": iat, "exp": iat + self.pick([900, 3600, 86400]),
                   "scope": self.pick(["read:orders", "admin", "billing:write read:customers", "openid profile"])}
        sig = self.rbytes({"HS256": 32, "ES256": 64, "RS256": 256}[alg])
        return self._pii("secret", ".".join([b64url(json.dumps(hdr, separators=(",", ":")).encode()),
                                             b64url(json.dumps(payload, separators=(",", ":")).encode()),
                                             b64url(sig)]))

    def pem(self, indent: str = "", joiner: str = "\n", small: bool = False):
        kinds = PEM_KINDS[:3] if small else PEM_KINDS
        label, prefix, n, width = self.weighted([((k[0], k[1], k[2], k[3]), k[4]) for k in kinds])
        body = base64.b64encode(prefix + self.rbytes(n)).decode("ascii")
        lines = ["-----BEGIN %s-----" % label] + [body[i:i + width] for i in range(0, len(body), width)]
        lines.append("-----END %s-----" % label)
        return self._pii("secret", (joiner + indent).join(lines))

    def hexkey(self, n: int = None):
        return self._pii("secret", self.hexs(n or self.pick([32, 40, 64])))

    def b64key(self, nbytes: int = None):
        return self._pii("secret", base64.b64encode(self.rbytes(nbytes or self.pick([24, 32, 48]))).decode("ascii"))

    def password(self, style: str = None, urlsafe: bool = False):
        style = style or self.weighted([("word_year", 3), ("random", 3), ("passphrase", 1), ("simple", 2), ("long", 1)])
        syms = SYM_URL if urlsafe else SYM_GENERAL
        if style == "word_year":
            v = self.pick(PW_WORDS[self.lang]) + self.pick([str(self.rint(1960, 2026)), self.digits(2), self.digits(3)]) + self.pick(syms)
        elif style == "random":
            n = self.rint(10, 18)
            pool = string.ascii_letters + string.digits + syms
            v = self.pick(string.ascii_letters) + "".join(self.pick(pool) for _ in range(n - 3)) + self.pick(syms) + self.pick(string.digits)
        elif style == "passphrase":
            v = self.pick(["-", ".", "_"]).join(self.r.sample(PASSPHRASE_WORDS, self.rint(3, 4))) + self.digits(2)
        elif style == "simple":
            v = self.pick(PW_WORDS[self.lang]).lower() + self.digits(self.rint(2, 4))
        else:
            v = self.b62(self.rint(24, 32))
        return self._pii("secret", v)

    def cookie(self):
        v = self.pick([self.hexs(32), b64url(self.rbytes(32)), "s%3A" + self.b62(24) + "." + b64url(self.rbytes(32))])
        return self._pii("secret", v)

    def b64_of(self, user: str, pw):
        if not isinstance(pw, PII):
            return pw
        return self._pii("secret", base64.b64encode((user + ":" + pw.value).encode()).decode("ascii"))

    def b64_secret_of(self, pw):
        if not isinstance(pw, PII):
            return pw
        return self._pii("secret", base64.b64encode(pw.value.encode()).decode("ascii"))

    def secret_any(self):
        return self.weighted([(self.token, 4), (self.jwt, 1), (self.hexkey, 2), (self.b64key, 2), (self.password, 3)])()

    # ---- records
    def field_value(self, f: str, p: Person, style: str = "code"):
        ds = "iso" if style == "code" else "any"
        table = {
            "email": lambda: self.email(p), "phone": self.phone, "address": self.address,
            "birth_date": lambda: self.pdate("dob", ds), "iban": self.iban, "card_number": self.card,
            "national_id": lambda: self.natid(p), "tax_id": lambda: self.taxid(p),
            "health_insurance_no": lambda: self.healthid(p), "passport_no": self.passport,
            "driver_license": lambda: self.dl(p), "license_plate": self.plate, "vin": self.vin,
            "last_location": self.geo, "last_login_ip": self.ip, "device_mac": self.mac,
            "hire_date": lambda: self.pdate("hire", ds), "wallet": self.crypto, "username": lambda: self.handle(p),
        }
        return table[f]()

    def field_key(self, f: str) -> str:
        return "bank_account" if f == "iban" and self.country == "US" else f

    def neutral_value(self, f: str):
        table = {
            "status": lambda: self.pick(["active", "suspended", "pending", "closed"]),
            "plan": lambda: self.pick(["free", "pro", "business", "enterprise"]),
            "locale": self.locale, "timezone": self.tz, "created_at": self.ts_iso,
            "score": lambda: round(self.r.uniform(0, 1), 3), "newsletter": lambda: self.chance(0.5),
            "country": lambda: self.pick(ALL_COUNTRIES), "currency": lambda: self.pick(["EUR", "USD", "GBP", "CHF"]),
            "tier": lambda: self.rint(1, 4), "version": lambda: self.rint(1, 40),
            "segment": lambda: self.pick(["smb", "mid-market", "consumer", "public-sector"]),
            "source": lambda: self.pick(["web", "ios", "android", "import", "partner-api"]),
            "external_ref": self.uuid, "updated_at": self.ts_iso, "order_count": lambda: self.rint(0, 240),
            "loyalty_points": lambda: self.rint(0, 9000), "risk_score": lambda: round(self.r.uniform(0, 100), 1),
            "marketing_opt_in": lambda: self.chance(0.4),
        }
        return table[f]()

    def pii_fields(self, k: int = None, exclude=()):
        pool = [x for x in PII_FIELD_WEIGHTS if x[0] not in exclude]
        return self.weighted_sample(pool, k if k is not None else self.rint(1, 2))

    def record(self, p: Person, k: int = None, include_id: bool = True, include_name: bool = True,
               exclude=(), n_neutral: int = None, style: str = "code"):
        rec = []
        if include_id:
            rec.append(("id", self.uuid() if self.chance(0.5) else self.rint(1000, 999999)))
        if include_name:
            if self.chance(0.6):
                rec.append(("full_name", self.name(p, "full")))
            else:
                rec.append(("first_name", self.name(p, "given")))
                rec.append(("last_name", self.name(p, "family")))
        rest = [(self.field_key(f), self.field_value(f, p, style)) for f in self.pii_fields(k, exclude)]
        nn = n_neutral if n_neutral is not None else self.rint(2, 4)
        rest += [(f, self.neutral_value(f)) for f in self.r.sample(NEUTRAL_FIELDS, nn)]
        self.r.shuffle(rest)
        return rec + rest

    def flabel(self, key: str) -> str:
        return FIELD_LABELS.get(self.lang, {}).get(key, key)

    # ---- localized text with slots
    def fill(self, tpl: str, p: Person = None) -> list:
        p = p or self.person()
        cache: Dict[str, object] = {}
        parts: list = []
        pos = 0
        for m in SLOT_RE.finditer(tpl):
            parts.append(tpl[pos:m.start()])
            parts.append(self._slot(m.group(1), p, cache))
            pos = m.end()
        parts.append(tpl[pos:])
        return parts

    def _slot(self, name: str, p: Person, cache: dict):
        if name in cache:
            return cache[name]
        if name in ("d1", "d2"):
            if "pair" not in cache:
                cache["pair"] = self.pdate_pair("leave", "prose")
            val = cache["pair"][0 if name == "d1" else 1]
        else:
            table = {
                "name": lambda: self.name(p, "full"), "given": lambda: self.name(p, "given"),
                "family": lambda: self.name(p, "family"), "handle": lambda: self.handle(p),
                "email": lambda: self.email(p), "mailbox": self.mailbox, "phone": self.phone,
                "address": self.address, "dob": lambda: self.pdate("dob", "prose"),
                "appt": lambda: self.pdate("appt", "prose"), "hire": lambda: self.pdate("hire", "prose"),
                "iban": self.iban, "card": self.card, "pw": self.password, "token": self.token,
                "secret": self.secret_any, "ip": self.ip, "mac": self.mac, "geo": lambda: self.geo(prose=True),
                "plate": self.plate, "vin": self.vin, "passport": self.passport, "dl": lambda: self.dl(p),
                "natid": lambda: self.natid(p), "taxid": lambda: self.taxid(p), "url": self.purl,
                "n": lambda: str(self.rint(1000, 99999)), "cid": lambda: str(self.rint(10000, 999999)),
                "amt": self.amount, "ms": lambda: str(self.rint(3, 900)), "rid": self.req_id,
            }
            val = table[name]()
        cache[name] = val
        return val

    def pii_sentence(self, p: Person = None) -> list:
        return self.fill(self.pick(PII_SENT[self.lang]), p)

    def prose(self, n: int, pii_ratio: float = 0.45) -> list:
        parts: list = []
        for i in range(n):
            if i:
                parts.append(" ")
            if self.chance(pii_ratio):
                parts.extend(self.pii_sentence())
            else:
                parts.append(self.neutral())
        return parts

    def log_msg(self, pii_prob: float = 0.45) -> list:
        pool = LOG_PII if self.chance(pii_prob) else LOG_NEUTRAL
        return self.fill(self.pick(pool[self.lang]))


# ----------------------------------------------------------- template registry

Template = Callable[[Gen, Doc, int], None]
REGISTRY: Dict[str, List[Tuple[str, str, Template]]] = {k: [] for k in KINDS}


def template(tid: str, kind: str, fname: str):
    def deco(fn: Template) -> Template:
        REGISTRY[kind].append((tid, fname, fn))
        return fn
    return deco


def json_obj(d: Doc, rec, indent: str, step: str = "  ") -> None:
    d.t("{\n")
    for i, (k, v) in enumerate(rec):
        d.t('%s%s"%s": ' % (indent, step, k))
        lit(d, v)
        d.t(",\n" if i < len(rec) - 1 else "\n")
    d.t(indent + "}")


def csv_cell(d: Doc, v, sep: str) -> None:
    if isinstance(v, bool):
        d.t("true" if v else "false")
        return
    text = vt(v)
    if sep in text or '"' in text or "\n" in text:
        if '"' in text:
            raise ValueError("double quote inside CSV cell")
        d.t('"')
        d.v(v)
        d.t('"')
    else:
        d.v(v)


def table_row(d: Doc, cells, widths, sep: str = " | ", lead: str = " ", tail: str = "") -> None:
    for i, (c, w) in enumerate(zip(cells, widths)):
        d.t(lead if i == 0 else sep)
        d.v(c)
        d.t(" " * (w - len(vt(c))))
    d.t(tail + "\n")


# ============================================================ neutral filler
# Blocks without any labelled value. They carry distractors (versions, hashes,
# ports, regions, placeholders, ...) and keep the span density realistic.


def _nslot(g: Gen, base: str) -> str:
    table = {
        "c": g.code_comment, "n": lambda: str(g.rint(100, 9999)), "q": lambda: str(g.rint(2, 9)),
        "a": g.amount, "rid": g.req_id, "ms": lambda: str(g.rint(3, 900)), "m": lambda: str(g.rint(1, 12)),
        "d": lambda: str(g.rint(1, 28)), "uuid": g.uuid, "sha": g.sha, "shortsha": lambda: g.sha()[:7],
        "ver": g.ver, "semver": lambda: "%d.%d.%d" % (g.rint(0, 9), g.rint(0, 30), g.rint(0, 20)),
        "port": lambda: str(g.port()), "tz": g.tz, "reg": g.region, "pub": g.pub_url, "loc": g.locale,
        "hexa": lambda: g.hexs(8), "b": lambda: g.pick(["true", "false"]), "bpy": lambda: g.pick(["True", "False"]),
        "prod": g.product, "sl": lambda: g.slug, "dom": lambda: g.co_domain, "ts": g.ts_iso,
        "pct": lambda: str(g.rint(5, 95)), "svc": lambda: g.pick(SERVICES), "team": lambda: g.pick(TEAMS),
        "s": lambda: "%.3f" % g.r.uniform(1.5, 25), "hhmm": g.hhmm, "sent": g.neutral,
        "plan": lambda: g.pick(["basic", "pro", "team", "enterprise"]),
    }
    return table[base]()


def nfill(g: Gen, tpl: str) -> str:
    """Fill a neutral template; slot names ending in digits are distinct draws."""
    cache: Dict[str, str] = {}

    def rep(m) -> str:
        name = m.group(1)
        if name not in cache:
            cache[name] = _nslot(g, name.rstrip("0123456789"))
        return cache[name]
    return SLOT_RE.sub(rep, tpl)


def neutral(g: Gen, d: Doc, key: str) -> None:
    d.t(nfill(g, g.pick(NEUTRAL[key])))


NEUTRAL = {
    "py": [
        '\n\ndef _round_money(value: Decimal) -> Decimal:\n    # ⟦c⟧\n    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)\n',
        '\n\n@pytest.fixture\ndef invoice_lines() -> list:\n    return [\n        {"sku": "SKU-⟦n1⟧", "qty": ⟦q1⟧, "unit_price": Decimal("⟦a1⟧"), "vat_rate": Decimal("0.19")},\n'
        '        {"sku": "SKU-⟦n2⟧", "qty": ⟦q2⟧, "unit_price": Decimal("⟦a2⟧"), "vat_rate": Decimal("0.07")},\n    ]\n',
        '\n\n@pytest.mark.parametrize(\n    ("currency", "expected"),\n    [("EUR", "€"), ("GBP", "£"), ("USD", "$"), ("CHF", "CHF")],\n)\n'
        'def test_currency_symbol(currency: str, expected: str) -> None:\n    assert symbol_for(currency) == expected\n',
        '\n\nclass FakeGateway:\n    """⟦c⟧"""\n\n    def __init__(self) -> None:\n        self.calls: list = []\n\n'
        '    def charge(self, **kwargs) -> dict:\n        self.calls.append(kwargs)\n        return {"status": "succeeded", "id": "⟦rid⟧", "latency_ms": ⟦ms⟧}\n',
        '\n\ndef test_retry_backoff_is_capped() -> None:\n    delays = [backoff(attempt, base=0.5, cap=30.0) for attempt in range(⟦q⟧)]\n'
        '    assert delays[:3] == [0.5, 1.0, 2.0]\n    assert max(delays) <= 30.0\n',
        '\n\n@pytest.fixture\ndef frozen_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:\n    now = datetime(2026, ⟦m⟧, ⟦d⟧, 9, 30, tzinfo=timezone.utc)\n'
        '    monkeypatch.setattr("billing.clock.utcnow", lambda: now)\n    return now\n',
        '\n\ndef test_invoice_number_format() -> None:\n    number = next_invoice_number(prefix="INV", year=2026, sequence=⟦n⟧)\n'
        '    assert re.fullmatch(r"INV-2026-\\d{6}", number), number\n',
        '\n\n@pytest.fixture(scope="session")\ndef api_settings() -> dict:\n    # ⟦c⟧\n'
        '    return {"region": "⟦reg⟧", "timeout_s": ⟦q⟧, "tz": "⟦tz⟧", "build": "⟦shortsha⟧"}\n',
    ],
    "ts": [
        '\n/** ⟦c⟧ */\nexport function formatMoney(cents: number, currency = "EUR", locale = "⟦loc⟧"): string {\n'
        '  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(cents / 100);\n}\n',
        '\nexport const RETRY_POLICY = {\n  maxAttempts: ⟦q⟧,\n  baseDelayMs: 250,\n  maxDelayMs: 30_000,\n  retryOn: [408, 429, 502, 503, 504],\n} as const;\n',
        '\nexport async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {\n'
        '  const res = await fetch(config.apiBaseUrl + path, { ...init, headers: { "X-Request-Id": crypto.randomUUID() } });\n'
        '  if (!res.ok) throw new HttpError(res.status, await res.text());\n  return (await res.json()) as T;\n}\n',
        '\n// ⟦c⟧\nexport const FEATURE_FLAGS: Record<string, boolean> = {\n  newCheckout: ⟦b1⟧,\n  darkMode: true,\n  sepaInstant: ⟦b2⟧,\n};\n',
        '\nexport const BUILD_INFO = {\n  version: "⟦semver⟧",\n  commit: "⟦sha⟧",\n  builtAt: "⟦ts⟧",\n  region: "⟦reg⟧",\n} as const;\n',
        '\nexport const PLANS = [\n  { code: "basic", monthlyCents: ⟦n1⟧, seats: 1 },\n  { code: "team", monthlyCents: ⟦n2⟧, seats: ⟦q⟧ },\n'
        '  { code: "enterprise", monthlyCents: null, seats: null },\n];\n',
    ],
    "go": [
        '\n// ⟦c⟧\nfunc roundCents(v float64) int64 {\n\treturn int64(math.Round(v * 100))\n}\n',
        '\nvar retryableStatus = map[int]bool{\n\thttp.StatusTooManyRequests:    true,\n\thttp.StatusBadGateway:         true,\n'
        '\thttp.StatusServiceUnavailable: true,\n}\n',
        '\n// Products used by the integration tests.\nvar Products = []model.Product{\n'
        '\t{SKU: "SKU-⟦n1⟧", Name: "⟦prod⟧ Basic", PriceCents: ⟦n2⟧, Currency: "EUR"},\n'
        '\t{SKU: "SKU-⟦n3⟧", Name: "⟦prod⟧ Pro", PriceCents: ⟦n4⟧, Currency: "EUR"},\n}\n',
        '\nfunc init() {\n\t// ⟦c⟧\n\tif os.Getenv("SEED_REGION") == "" {\n\t\t_ = os.Setenv("SEED_REGION", "⟦reg⟧")\n\t}\n}\n',
        '\n// BuildInfo is injected at link time.\nvar BuildInfo = struct {\n\tVersion string\n\tCommit  string\n}{Version: "⟦semver⟧", Commit: "⟦sha⟧"}\n',
    ],
    "java": [
        '\n    @Test\n    void rejectsNegativeAmounts() {\n        // ⟦c⟧\n'
        '        assertThrows(IllegalArgumentException.class, () -> service.charge(new BigDecimal("-⟦a⟧"), "EUR"));\n    }\n',
        '\n    @Test\n    void retriesOnServiceUnavailable() {\n        gateway.failNext(503, ⟦q⟧);\n        service.syncAll();\n'
        '        assertEquals(⟦q⟧ + 1, gateway.callCount());\n    }\n',
        '\n    @Test\n    void exposesBuildVersion() {\n        assertEquals("⟦semver⟧", service.buildInfo().version());\n    }\n',
        '\n    @Test\n    void computesGrossAmount() {\n        BigDecimal gross = VatCalculator.gross(new BigDecimal("⟦a⟧"), new BigDecimal("0.19"));\n'
        '        assertTrue(gross.compareTo(BigDecimal.ZERO) > 0);\n    }\n',
        '\n    @Test\n    void pagesThroughResults() {\n        // ⟦c⟧\n        Page<Customer> page = service.list(PageRequest.of(⟦q⟧, 50));\n'
        '        assertTrue(page.getSize() <= 50);\n    }\n',
    ],
    "rb": [
        '\n# ⟦c⟧\nPlan.find_or_create_by!(code: "⟦plan⟧") do |plan|\n  plan.monthly_price_cents = ⟦n⟧\n  plan.currency = "EUR"\nend\n',
        '\nSetting.find_or_create_by!(key: "retry.max_attempts") { |s| s.value = "⟦q⟧" }\n'
        'Setting.find_or_create_by!(key: "export.timezone") { |s| s.value = "⟦tz⟧" }\n',
        '\n%w[eu-central-1 eu-west-1 us-east-1].each do |region|\n  Region.find_or_create_by!(code: region)\nend\n',
        '\nFeatureFlag.upsert_all([\n  { key: "new_checkout", enabled: ⟦b1⟧ },\n  { key: "sepa_instant", enabled: ⟦b2⟧ },\n], unique_by: :key)\n',
    ],
    "php": [
        "    'cache' => [\n        'driver' => 'redis',\n        'ttl' => ⟦n⟧,\n        'prefix' => '⟦sl⟧_cache_',\n    ],\n",
        "    'features' => [\n        'sepa_instant' => ⟦b1⟧,\n        'new_checkout' => ⟦b2⟧,\n    ],\n",
        "    'logging' => [\n        // ⟦c⟧\n        'channel' => 'stack',\n        'path' => '/var/log/shop/app.log',\n        'level' => 'warning',\n    ],\n",
        "    'queue' => [\n        'connection' => 'redis',\n        'retry_after' => ⟦n⟧,\n        'block_for' => ⟦q⟧,\n    ],\n",
    ],
    "sh": [
        '\n# ⟦c⟧\nif ! docker image inspect "${REGISTRY}/api:${RELEASE}" >/dev/null 2>&1; then\n  echo "image ${RELEASE} not found" >&2\n  exit 1\nfi\n',
        '\nretry() {\n  local n=0\n  until "$@"; do\n    n=$((n + 1))\n    [ "$n" -ge ⟦q⟧ ] && return 1\n    sleep $((n * 2))\n  done\n}\n',
        '\necho "release=${RELEASE} sha=⟦sha⟧ built=$(date -u +%FT%TZ)" >> /var/log/deploy/history.log\n',
        '\nfor i in $(seq 1 30); do\n  curl -fsS http://127.0.0.1:8080/healthz && break\n  sleep 2\ndone\n',
        '\nfind /var/log/app -name "*.log" -mtime +14 -delete\nlogger -t deploy "release ${RELEASE} finished"\n',
        '\nfor host in "${HOSTS[@]}"; do\n  echo ">> deploying ${RELEASE} to ${host}"\n'
        '  ssh -o StrictHostKeyChecking=accept-new deploy@"${host}" \\\n'
        '    "docker pull ${REGISTRY}/api:${RELEASE} && docker compose up -d --remove-orphans"\ndone\n',
    ],
    "env": [
        '\n# --- Cache ---\nCACHE_DRIVER=redis\nCACHE_TTL=⟦n⟧\nCACHE_PREFIX=⟦sl⟧\n',
        '\n# --- HTTP ---\nHTTP_TIMEOUT_MS=⟦n⟧\nHTTP_MAX_RETRIES=⟦q⟧\nCORS_ORIGINS=*\nTRUST_PROXY=true\n',
        '\n# --- Workers ---\nWORKER_CONCURRENCY=⟦q⟧\nQUEUE_NAME=⟦svc⟧-jobs\nJOB_TIMEOUT_SECONDS=⟦n⟧\n',
        '\n# --- Locale ---\nDEFAULT_LOCALE=⟦loc⟧\nDEFAULT_TIMEZONE=⟦tz⟧\nCURRENCY=EUR\n',
        '\n# --- Metrics ---\nMETRICS_PORT=9090\nOTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_ENDPOINT}\nOTEL_SERVICE_NAME=⟦svc⟧\nOTEL_TRACES_SAMPLER_ARG=0.⟦q⟧\n',
        '\n# --- Feature flags ---\nFEATURE_NEW_CHECKOUT=⟦b1⟧\nFEATURE_DARK_MODE=⟦b2⟧\nRATE_LIMIT_PER_MIN=⟦n⟧\n',
        '\n# --- Third party ---\nMAPS_API_KEY=<YOUR_API_KEY>\nSENTRY_DSN=${SENTRY_DSN}\nCDN_URL=https://cdn.⟦dom⟧\n',
        '\n# --- Build ---\n# ⟦c⟧\nBUILD_SHA=⟦sha⟧\nBUILD_NUMBER=⟦n⟧\nRELEASE=⟦semver⟧\n',
    ],
    "yaml": [
        'resilience4j:\n  circuitbreaker:\n    instances:\n      pricing:\n        sliding-window-size: ⟦q⟧0\n        failure-rate-threshold: 50\n'
        '        wait-duration-in-open-state: ⟦q2⟧s\n',
        'spring.jpa:\n  open-in-view: false\n  properties:\n    hibernate.jdbc.batch_size: 50\n    hibernate.order_inserts: true\n',
        'server.tomcat:\n  threads:\n    max: 200\n    min-spare: ⟦q⟧\n  connection-timeout: ⟦n⟧ms\n',
        'management.metrics:\n  tags:\n    region: ⟦reg⟧\n    service: ⟦svc⟧\n  distribution.percentiles-histogram.http.server.requests: true\n',
        '# ⟦c⟧\napp.export:\n  cron: "0 0 2 * * *"\n  zone: ⟦tz⟧\n  batch-size: ⟦n⟧\n  output-dir: /var/lib/⟦svc⟧/exports\n',
        'app.cache:\n  ttl: ⟦n⟧s\n  max-entries: ⟦n2⟧\n  key-prefix: ⟦sl⟧\n',
    ],
    "toml": [
        '\n[cache]\nbackend = "redis"\nttl_seconds = ⟦n⟧\nmax_entries = ⟦n2⟧\n',
        '\n[metrics]\nenabled = true\nlisten = "0.0.0.0:9090"\nhistogram_buckets = [0.005, 0.01, 0.05, 0.1, 0.5, 1.0]\n',
        '\n[[routes]]\npath = "/v1/⟦svc⟧"\nupstream = "⟦svc⟧:⟦port⟧"\ntimeout_ms = ⟦n⟧\nretries = ⟦q⟧\n',
        '\n# ⟦c⟧\n[features]\nnew_checkout = ⟦b1⟧\nsepa_instant = ⟦b2⟧\nrollout_percent = ⟦pct⟧\n',
        '\n[limits]\nrequests_per_minute = ⟦n⟧\nburst = ⟦q⟧0\nmax_body_bytes = 1048576\n',
    ],
    "ini": [
        '\n[cache]\nenabled = yes\nttl = ⟦n⟧\ndirectory = /var/cache/reporting\n',
        '\n[report.⟦n⟧]\nschedule = 0 ⟦q⟧ * * 1-5\nformat = xlsx\ncolumns = order_id,amount,currency,status,created_at\ntimezone = ⟦tz⟧\n',
        '\n; ⟦c⟧\n[paths]\ntemplates = /opt/reporting/templates\noutput = /srv/reports/out\narchive = /srv/reports/archive\n',
        '\n[smtp_relay]\nhost = smtp.⟦dom⟧\nport = 587\nstarttls = yes\ntimeout = ⟦q⟧0\n',
    ],
    "json": [
        '"RateLimits": {\n    "PermitLimit": ⟦n⟧,\n    "WindowSeconds": 60,\n    "QueueLimit": ⟦q⟧\n  }',
        '"Features": {\n    "NewCheckout": ⟦b1⟧,\n    "SepaInstant": ⟦b2⟧\n  }',
        '"Cors": {\n    "AllowedOrigins": [ "https://www.⟦dom⟧" ],\n    "MaxAgeSeconds": 600\n  }',
        '"HealthChecks": {\n    "Path": "/healthz",\n    "TimeoutSeconds": ⟦q⟧\n  }',
        '"Telemetry": {\n    "ServiceName": "⟦svc⟧",\n    "SamplingRatio": 0.⟦q⟧,\n    "Region": "⟦reg⟧"\n  }',
        '"Retry": {\n    "MaxAttempts": ⟦q⟧,\n    "BackoffMs": [ 250, 1000, 5000 ]\n  }',
    ],
    "compose": [
        '\n  redis-⟦q⟧:\n    image: redis:7.4-alpine\n    command: ["redis-server", "--save", "", "--appendonly", "no"]\n    healthcheck:\n'
        '      test: ["CMD", "redis-cli", "ping"]\n      interval: 10s\n',
        '\n  nginx-⟦q⟧:\n    image: nginx:1.27-alpine\n    ports:\n      - "⟦port⟧:80"\n    volumes:\n      - ./nginx.conf:/etc/nginx/nginx.conf:ro\n',
        '\n  prometheus-⟦q⟧:\n    image: prom/prometheus:v2.54.1\n    volumes:\n      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro\n'
        '    ports:\n      - "9090:9090"\n',
        '\n  ⟦svc⟧-cron-⟦q⟧:\n    image: registry.⟦dom⟧/⟦svc⟧:⟦semver⟧\n    command: ["python", "-m", "jobs.nightly"]\n    environment:\n'
        '      TZ: ⟦tz⟧\n      LOG_LEVEL: info\n',
    ],
    "k8s": [
        '---\napiVersion: v1\nkind: Service\nmetadata:\n  name: ⟦svc⟧\n  namespace: ⟦team⟧\nspec:\n  selector:\n'
        '    app.kubernetes.io/name: ⟦svc⟧\n  ports:\n    - port: 80\n      targetPort: ⟦port⟧\n',
        '---\napiVersion: autoscaling/v2\nkind: HorizontalPodAutoscaler\nmetadata:\n  name: ⟦svc⟧\n  namespace: ⟦team⟧\nspec:\n'
        '  scaleTargetRef:\n    apiVersion: apps/v1\n    kind: Deployment\n    name: ⟦svc⟧\n  minReplicas: 2\n  maxReplicas: ⟦q⟧0\n'
        '  metrics:\n    - type: Resource\n      resource:\n        name: cpu\n        target:\n          type: Utilization\n'
        '          averageUtilization: ⟦pct⟧\n',
        '---\napiVersion: policy/v1\nkind: PodDisruptionBudget\nmetadata:\n  name: ⟦svc⟧-pdb\n  namespace: ⟦team⟧\nspec:\n'
        '  minAvailable: 1\n  selector:\n    matchLabels:\n      app.kubernetes.io/name: ⟦svc⟧\n',
        '---\napiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: ⟦svc⟧-ingress\n  namespace: ⟦team⟧\nspec:\n'
        '  podSelector:\n    matchLabels:\n      app.kubernetes.io/name: ⟦svc⟧\n  ingress:\n    - from:\n        - ipBlock:\n'
        '            cidr: 10.0.0.0/8\n      ports:\n        - port: ⟦port⟧\n',
        '---\n# ⟦c⟧\napiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: ⟦svc⟧-cleanup\n  namespace: ⟦team⟧\nspec:\n'
        '  schedule: "⟦q⟧ 3 * * *"\n  jobTemplate:\n    spec:\n      template:\n        spec:\n          restartPolicy: OnFailure\n'
        '          containers:\n            - name: cleanup\n              image: registry.⟦dom⟧/⟦svc⟧:⟦semver⟧\n'
        '              args: ["cleanup", "--older-than=30d"]\n',
    ],
    "ci": [
        '  build-⟦n⟧:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@v4\n      - uses: docker/setup-buildx-action@v3\n'
        '      - run: docker build --build-arg VERSION=⟦semver⟧ -t ${{ env.REGISTRY }}/⟦svc⟧:${{ github.sha }} .\n',
        '  matrix-⟦n⟧:\n    runs-on: ${{ matrix.os }}\n    strategy:\n      matrix:\n        os: [ubuntu-24.04, macos-14]\n'
        '        node: [18, 20, 22]\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v4\n'
        '        with:\n          node-version: ${{ matrix.node }}\n      - run: npm ci && npm test\n',
        "  cache-⟦n⟧:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/cache@v4\n        with:\n          path: ~/.npm\n"
        "          key: npm-${{ hashFiles('package-lock.json') }}-⟦hexa⟧\n",
        '  lint-⟦n⟧:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@v4\n      - run: npx biome ci . && npx tsc --noEmit\n',
    ],
    "docker": [
        '\nRUN apt-get update && apt-get install -y --no-install-recommends \\\n      curl ca-certificates tzdata && \\\n    rm -rf /var/lib/apt/lists/*\n',
        '\n# ⟦c⟧\nRUN useradd --uid 10001 --create-home app && mkdir -p /srv/app/var && chown -R app /srv/app\n',
        '\nCOPY --from=build /srv/app/.venv /srv/app/.venv\nENV PATH="/srv/app/.venv/bin:${PATH}" \\\n    PYTHONUNBUFFERED=1\n',
        '\nRUN python -m pip install --no-cache-dir "gunicorn==⟦semver⟧" "uvicorn[standard]" && \\\n'
        '    python -c "import app; print(app.__version__)"\n',
        '\nCOPY --chown=10001:10001 . .\nRUN python -m compileall -q app/ && \\\n    echo "build ⟦n⟧ (⟦shortsha⟧)" > BUILD_INFO\n',
    ],
    "shell": [
        "$ git status --short --branch\n## main...origin/main [ahead ⟦q⟧]\n M src/⟦svc⟧/handler.go\n M go.sum\n?? docs/adr/00⟦q2⟧-retry-policy.md\n",
        "$ ls src/\napi  billing  cmd  config  internal  migrations  web\n",
        "$ npm test -- --reporter=dot\n\n  ⟦n⟧ passing (⟦s⟧s)\n  ⟦q⟧ pending\n\n",
        "$ df -h /var/lib/docker\nFilesystem      Size  Used Avail Use% Mounted on\n/dev/nvme0n1p1  200G  ⟦q⟧9G  ⟦q2⟧1G  ⟦pct⟧% /\n",
        "$ uptime\n ⟦hhmm⟧:12 up ⟦q⟧ days,  3:41,  2 users,  load average: 0.⟦q2⟧2, 0.48, 0.51\n",
        "$ docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | head -3\nregistry.⟦dom⟧/⟦svc⟧:⟦semver⟧ 182MB\n"
        "postgres:16.4-alpine 243MB\nredis:7.4-alpine 41.2MB\n",
        "$ pytest -q tests/unit\n........................................ [ 72%]\n...............                          [100%]\n"
        "⟦n⟧ passed, ⟦q⟧ warnings in ⟦s⟧s\n",
        "$ make lint\nbiome check .\nChecked ⟦n⟧ files in ⟦ms⟧ms. No fixes applied.\n",
        "$ terraform plan -out=tfplan\nRefreshing state... [id=⟦uuid⟧]\nPlan: ⟦q⟧ to add, 1 to change, 0 to destroy.\n",
        "$ go test ./...\nok  \t⟦sl⟧.dev/ledger/internal/payout\t0.⟦q⟧12s\nok  \t⟦sl⟧.dev/ledger/internal/store\t1.⟦q2⟧04s\n"
        "?   \t⟦sl⟧.dev/ledger/cmd/ledger\t[no test files]\n",
        "$ free -m\n               total        used        free      shared  buff/cache   available\n"
        "Mem:           ⟦n⟧        ⟦n2⟧        ⟦n3⟧          12        ⟦n4⟧        ⟦n5⟧\n",
        '$ cat package.json | jq .scripts\n{\n  "build": "tsc -p .",\n  "test": "vitest run",\n  "lint": "biome check ."\n}\n',
        "$ openssl x509 -in tls.crt -noout -subject -enddate\nsubject=CN = *.⟦dom⟧\nnotAfter=Mar ⟦d⟧ 12:00:00 2027 GMT\n",
        "$ kubectl -n ⟦team⟧ rollout status deploy/⟦svc⟧\ndeployment \"⟦svc⟧\" successfully rolled out\n",
        "$ kubectl -n ⟦team⟧ top pods\nNAME                     CPU(cores)   MEMORY(bytes)\n⟦svc⟧-⟦hexa⟧-x2k4p       ⟦q⟧3m         ⟦n⟧Mi\n",
    ],
    "framework_log": [
        "HikariPool-1 - Start completed.", "Tomcat started on port 8080 (http) with context path '/'",
        "Started Application in ⟦s⟧ seconds (process running for ⟦s2⟧)",
        "Initializing Spring DispatcherServlet 'dispatcherServlet'", "Completed initialization in ⟦ms⟧ ms",
        "Flushing ⟦n⟧ metrics to collector", "Evicted ⟦n⟧ expired sessions",
        "Kafka consumer group ⟦svc⟧-group rebalanced, assigned partitions [0, 1, 2]",
        "Slow query detected (⟦ms⟧ms): SELECT id, status FROM orders WHERE updated_at > $1",
        "Circuit breaker 'pricing' changed state from CLOSED to OPEN",
        "Loaded ⟦n⟧ feature flags from cache (etag ⟦hexa⟧)",
        "Scheduled task 'cleanupExpiredTokens' completed in ⟦ms⟧ms",
        "GET /v1/orders?page=⟦q⟧ -> 200 (⟦ms⟧ms, request_id=⟦rid⟧)",
    ],
    "bot": [
        "✅ ⟦svc⟧ ⟦semver⟧ deployed to production (commit ⟦shortsha⟧, ⟦q⟧m⟦d⟧s)",
        "[FIRING:1] HighErrorRate ⟦svc⟧ (severity=warning, region=⟦reg⟧) error_rate=0.0⟦q⟧",
        "[RESOLVED] HighLatency ⟦svc⟧ p95=⟦ms⟧ms",
        "PR #⟦n⟧ merged into main: chore(deps): bump ⟦prod⟧ to ⟦semver⟧",
        "Pipeline #⟦n⟧ passed on main in ⟦q⟧m (⟦n2⟧ tests, coverage ⟦pct⟧%)",
    ],
}
BOTS = ["deploy-bot", "alertmanager", "github", "ci-runner", "pagerduty"]


def neutral_md(g: Gen, d: Doc) -> None:
    k = g.rint(0, 4)
    if k == 0:
        d.t("\n## %s\n\n" % g.tx("Architecture", "Architektur", "Architecture", "Architettura", "Arquitectura"))
        d.t(" ".join(g.neutral() for _ in range(g.rint(2, 3))))
        d.t(nfill(g, "\n\n```mermaid\nflowchart LR\n  client --> gateway --> ⟦svc⟧\n  ⟦svc⟧ --> db[(PostgreSQL)]\n  ⟦svc⟧ --> queue[[RabbitMQ]]\n```\n"))
    elif k == 1:
        d.t("\n## %s\n\n" % g.tx("Metrics", "Kennzahlen", "Indicateurs", "Metriche", "Métricas"))
        d.t(nfill(g, "| Metric | p50 | p95 | p99 |\n|---|---|---|---|\n| latency_ms | ⟦ms1⟧ | ⟦ms2⟧ | ⟦ms3⟧ |\n"
                     "| error_rate | 0.0⟦q1⟧ | 0.0⟦q2⟧ | 0.⟦q3⟧ |\n| throughput_rps | ⟦n1⟧ | ⟦n2⟧ | ⟦n3⟧ |\n"))
    elif k == 2:
        d.t("\n## %s\n\n" % g.tx("Commands", "Befehle", "Commandes", "Comandi", "Comandos"))
        d.t(nfill(g, "```bash\nmake test\nmake migrate ENV=staging\ndocker compose up -d ⟦svc⟧\ncurl -s http://localhost:⟦port⟧/healthz\n```\n"))
    elif k == 3:
        d.t("\n## %s\n\n" % g.pick([g.tx("Background", "Hintergrund", "Contexte", "Contesto", "Contexto"),
                                    g.tx("Open questions", "Offene Fragen", "Questions ouvertes", "Domande aperte", "Preguntas abiertas")]))
        d.t(" ".join(g.neutral() for _ in range(g.rint(2, 4))) + "\n")
    else:
        d.t("\n## %s\n\n" % g.tx("Next steps", "Nächste Schritte", "Prochaines étapes", "Prossimi passi", "Próximos pasos"))
        for _ in range(g.rint(2, 4)):
            d.t("- " + g.neutral() + "\n")


# ================================================================ source_code

FIXTURE_NAMES = ["vip_customer", "customer_with_iban", "blocked_customer", "new_signup", "customer_eu",
                 "legacy_customer", "customer_with_card", "b2b_contact", "customer_moved", "dormant_account",
                 "customer_minor", "reseller_contact"]
JAVA_TESTS = ["registersCustomerWithIban", "rejectsDuplicateEmail", "normalizesPhoneNumber", "exportsGdprReport",
              "masksCardInToString", "updatesPostalAddress", "keepsLegacyTaxId", "findsCustomerByEmail",
              "mergesDuplicateProfiles", "anonymizesClosedAccount"]


@template("code.py.pytest_fixtures", "source_code", "tests/conftest.py")
def tpl_py_fixtures(g: Gen, d: Doc, target: int) -> None:
    d.f('"""⟦a⟧\n\n⟦b⟧\n"""\n\nfrom __future__ import annotations\n\nimport os\nimport re\nfrom datetime import datetime, timezone\n'
        'from decimal import ROUND_HALF_UP, Decimal\n\nimport pytest\n\n'
        'from ⟦m⟧.billing.models import Customer, Invoice\n\n# ⟦u⟧\nAPI_VERSION = "⟦v⟧"\n'
        'BILLING_URL = os.environ.get("BILLING_URL", "⟦url⟧")\nBILLING_TOKEN = os.environ.get("BILLING_TOKEN", "⟦tok⟧")\n',
        a=g.tx("Shared fixtures for the billing test-suite.", "Gemeinsame Fixtures für die Abrechnungs-Tests.",
               "Fixtures partagées pour les tests de facturation.", "Fixture condivise per i test di fatturazione.",
               "Fixtures compartidas para las pruebas de facturación."),
        b=g.code_comment(), m=g.pymod(), u=g.pub_url("python"), v=g.ver(), url=g.purl(),
        tok=g.pick([g.token(), g.placeholder_secret()]))
    n_fx = 0
    for i in g.loop(d, target):
        if i and not g.chance(0.18):
            neutral(g, d, "py")
            continue
        p = g.person()
        fn = FIXTURE_NAMES[n_fx % len(FIXTURE_NAMES)] + ("" if n_fx < len(FIXTURE_NAMES) else "_%d" % n_fx)
        n_fx += 1
        d.f("\n\n@pytest.fixture\ndef ⟦fn⟧() -> Customer:\n    # ⟦c⟧\n    return Customer(\n", fn=fn, c=g.code_comment())
        for k, v in g.record(p):
            d.t("        %s=" % k)
            lit(d, v, t="True", f="False")
            d.t(",\n")
        d.t("    )\n")
        if g.chance(0.2):
            d.f('\n\ndef test_⟦fn⟧_recipient(⟦fn⟧):\n    invoice = Invoice.for_customer(⟦fn⟧, amount=Decimal("⟦amt⟧"))\n'
                '    assert invoice.recipient == "⟦name⟧"\n', fn=fn, amt=g.amount(), name=g.name(p, "full"))


@template("code.ts.config_module", "source_code", "src/config/index.ts")
def tpl_ts_config(g: Gen, d: Doc, target: int) -> None:
    d.f('// ⟦c⟧\n// ⟦u⟧\nimport type { AppConfig, SeedUser } from "./types";\n\nexport const config: AppConfig = {\n'
        '  env: "production",\n  region: "⟦reg⟧",\n  release: "⟦ver⟧",\n  buildSha: "⟦sha⟧",\n  apiBaseUrl: "⟦purl⟧",\n'
        '  docsUrl: "⟦pub⟧",\n  paymentsKey: "⟦tok⟧",\n  webhookSecret: process.env.WEBHOOK_SECRET ?? "⟦hk⟧",\n'
        '  supportMailbox: "⟦mb⟧",\n  timeouts: { connectMs: ⟦t1⟧, readMs: ⟦t2⟧ },\n  defaultLocale: "⟦loc⟧",\n};\n',
        c=g.code_comment(), u=g.pub_url("js"), reg=g.region(), ver=g.ver(), sha=g.sha(), purl=g.purl(),
        pub=g.pub_url("js"), tok=g.token(), hk=g.pick([g.hexkey(), "${WEBHOOK_SECRET}"]), mb=g.mailbox(),
        t1=g.pick(["1500", "2500", "5000"]), t2=g.pick(["10000", "15000", "30000"]), loc=g.locale())
    d.f("\n/** ⟦c⟧ */\nexport const SEED_USERS: SeedUser[] = [\n", c=g.code_comment())
    for _ in range(1):
        d.t("  {\n")
        for k, v in g.record(g.person()):
            d.t("    %s: " % camel(k))
            lit(d, v)
            d.t(",\n")
        d.t("  },\n")
    d.t("];\n")
    for _ in g.loop(d, target, min_iter=0):
        neutral(g, d, "ts")
    if g.chance(0.3):
        d.f('\nexport const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? "⟦pw⟧";\n', pw=g.password())


@template("code.go.seed_data", "source_code", "internal/seed/users.go")
def tpl_go_seed(g: Gen, d: Doc, target: int) -> None:
    d.f('// Package seed ⟦c⟧\npackage seed\n\nimport (\n\t"math"\n\t"net/http"\n\t"os"\n\t"time"\n\n\t"⟦mod⟧/internal/model"\n)\n\n// ⟦c2⟧\n'
        'const seedDSN = "postgres://seed:⟦pw⟧@db-seed.⟦sl⟧.internal:5432/platform?sslmode=disable"\n\n'
        '// SeedVersion is bumped whenever the fixtures change.\nconst SeedVersion = "⟦ver⟧"\n\n'
        'var seededAt = time.Date(2026, time.⟦mon⟧, ⟦day⟧, 10, 0, 0, 0, time.UTC)\n\n// Users ⟦c3⟧\nvar Users = []model.User{\n',
        c=g.code_comment(), mod="%s.dev/platform" % g.slug, c2=g.code_comment(), pw=g.password(urlsafe=True),
        sl=g.slug, ver=g.ver(), mon=MONTHS["en"][g.rint(0, 11)], day=str(g.rint(1, 28)), c3=g.code_comment())
    for _ in range(g.rint(1, 2)):
        d.t("\t{\n")
        for k, v in g.record(g.person()):
            d.t("\t\t%s: " % pascal(k))
            lit(d, v)
            d.t(",\n")
        d.t("\t},\n")
    d.t("}\n")
    for _ in g.loop(d, target, min_iter=0):
        neutral(g, d, "go")


@template("code.java.junit_test", "source_code", "src/test/java/CustomerServiceTest.java")
def tpl_java_test(g: Gen, d: Doc, target: int) -> None:
    d.f('package com.⟦pkg⟧.crm.customer;\n\nimport static org.junit.jupiter.api.Assertions.assertEquals;\n'
        'import static org.junit.jupiter.api.Assertions.assertThrows;\nimport static org.junit.jupiter.api.Assertions.assertTrue;\n\n'
        'import java.math.BigDecimal;\nimport org.junit.jupiter.api.BeforeEach;\nimport org.junit.jupiter.api.Test;\n\n/**\n * ⟦c⟧\n *\n'
        ' * @see <a href="⟦pub⟧">JUnit 5 User Guide</a>\n */\nclass CustomerServiceTest {\n\n'
        '    private static final String API_KEY = "⟦tok⟧";\n    private static final String CRM_URL = "⟦url⟧";\n\n'
        '    private CustomerService service;\n\n    @BeforeEach\n    void setUp() {\n'
        '        service = new CustomerService(new InMemoryCustomerRepository(), CRM_URL, API_KEY);\n    }\n',
        pkg=g.slug.replace("-", ""), c=g.code_comment(), pub=PUB_URLS["java"][0], tok=g.token(), url=g.purl())
    n_t = 0
    for i in g.loop(d, target - 10):
        if i and not g.chance(0.12):
            neutral(g, d, "java")
            continue
        p = g.person()
        name, email = g.name(p, "full"), g.email(p)
        d.f('\n    @Test\n    void ⟦m⟧() {\n        // ⟦c⟧\n        Customer customer = Customer.builder()\n'
            '            .fullName("⟦name⟧")\n            .email("⟦email⟧")\n',
            m=JAVA_TESTS[n_t % len(JAVA_TESTS)] + ("" if n_t < len(JAVA_TESTS) else str(n_t)), c=g.code_comment(),
            name=name, email=email)
        n_t += 1
        for k, v in g.record(p, k=g.rint(0, 2), include_id=False, include_name=False, exclude=("email",)):
            d.t("            .%s(" % camel(k))
            lit(d, v)
            d.t(")\n")
        d.f('            .build();\n        service.register(customer);\n'
            '        assertEquals("⟦name⟧", service.findByEmail("⟦email⟧").getFullName());\n    }\n', name=name, email=email)
    d.t("}\n")


@template("code.rb.rails_seeds", "source_code", "db/seeds.rb")
def tpl_rb_seeds(g: Gen, d: Doc, target: int) -> None:
    d.f('# frozen_string_literal: true\n\n# ⟦c⟧\n# bin/rails db:seed -- ⟦u⟧\n\n'
        'ADMIN_PASSWORD = ENV.fetch("SEED_ADMIN_PASSWORD", "⟦pw⟧")\n\nusers = [\n',
        c=g.code_comment(), u=g.pub_url("ruby"), pw=g.password())
    for _ in range(1):
        d.t("  {\n")
        for k, v in g.record(g.person()):
            d.t("    %s: " % k)
            lit(d, v, null="nil")
            d.t(",\n")
        d.t("  },\n")
    d.t('].freeze\n\nusers.each do |attrs|\n  User.find_or_create_by!(id: attrs[:id]) do |user|\n'
        '    user.assign_attributes(attrs.except(:id).merge(password: ADMIN_PASSWORD))\n  end\nend\n')
    for _ in g.loop(d, target - 200, min_iter=0):
        neutral(g, d, "rb")
    if g.chance(0.35):
        p = g.person()
        d.f('\nOrganization.find_or_create_by!(name: "⟦co⟧") do |org|\n  org.billing_contact = "⟦email⟧"\n'
            '  org.vat_id = "⟦tax⟧"\n  org.owner_name = "⟦name⟧"\nend\n',
            co=g.co_name, email=g.email(p), tax=g.taxid(p), name=g.name(p))


@template("code.php.settings", "source_code", "config/settings.php")
def tpl_php_settings(g: Gen, d: Doc, target: int) -> None:
    d.f("<?php\n/**\n * ⟦c⟧\n *\n * @see ⟦pub⟧\n */\n\ndeclare(strict_types=1);\n\nreturn [\n    'app' => [\n"
        "        'name' => '⟦prod⟧',\n        'env' => 'production',\n        'url' => '⟦home⟧',\n        'key' => '⟦key⟧',\n"
        "        'timezone' => '⟦tz⟧',\n    ],\n    'database' => [\n        'driver' => 'mysql',\n        'host' => '⟦dbh⟧',\n"
        "        'port' => 3306,\n        'database' => 'shop',\n        'username' => 'shop_app',\n        'password' => '⟦pw⟧',\n"
        "    ],\n    'mail' => [\n        'host' => 'smtp.⟦dom⟧',\n        'username' => '⟦mb⟧',\n        'password' => env('MAIL_PASSWORD'),\n"
        "        'from' => ['address' => '⟦mb⟧', 'name' => '⟦prod⟧'],\n    ],\n",
        c=g.code_comment(), pub=g.pub_url("php"), prod=g.product(), home=g.co_homepage(), key=g.b64key(32), tz=g.tz(),
        dbh=g.pick([g.ip(v6=False), g.int_host("mysql")]), pw=g.password(), dom=g.co_domain, mb=g.mailbox())
    n_c = 0
    for i in g.loop(d, target - 20):
        if i and not g.chance(0.15):
            neutral(g, d, "php")
            continue
        n_c += 1
        d.t("    '%s' => [\n" % g.pick(["support_contact", "dpo_contact", "billing_contact", "escalation_contact"]))
        for k, v in g.record(g.person(safe=True), k=1, include_id=False):
            d.t("        '%s' => " % k)
            lit(d, v, q="'")
            d.t(",\n")
        d.t("    ],\n")
    d.t("];\n")


@template("code.sh.deploy_script", "source_code", "scripts/deploy.sh")
def tpl_sh_deploy(g: Gen, d: Doc, target: int) -> None:
    ips = [g.ip(v6=False) for _ in range(g.rint(1, 3))]
    d.f('#!/usr/bin/env bash\n# ⟦c⟧\n# Usage: ./deploy.sh <release-tag>\nset -euo pipefail\n\nRELEASE="${1:-⟦ver⟧}"\n'
        'export DEPLOY_TOKEN="${DEPLOY_TOKEN:-⟦tok⟧}"\nREGISTRY="registry.⟦dom⟧"\nNOTIFY_TO="⟦email⟧"\nHOSTS=(',
        c=g.code_comment(), ver=g.ver(), tok=g.pick([g.token(), g.placeholder_secret()]), dom=g.co_domain, email=g.mailbox())
    for j, ip in enumerate(ips):
        d.v(ip)
        d.t(" " if j < len(ips) - 1 else ")\n")
    for i in g.loop(d, target):
        if not g.chance(0.15):
            neutral(g, d, "sh")
            continue
        b = g.pick(["migrate", "backup", "notify", "mail", "purge"])
        if b == "migrate":
            d.f("\n# ⟦c⟧\nPGPASSWORD='⟦pw⟧' psql -h ⟦h⟧ -U migrator -d app -v ON_ERROR_STOP=1 \\\n"
                "  -f migrations/⟦n⟧_add_customer_consent.sql\n", c=g.code_comment(), pw=g.password(),
                h=g.pick([g.int_host("db"), g.ip(v6=False)]), n="%04d" % g.rint(1, 400))
        elif b == "backup":
            d.f("\nrsync -az --delete /srv/app/uploads/ ⟦u⟧@⟦ip⟧:/backups/⟦sl⟧/uploads/\n",
                u=g.handle(g.person()), ip=g.ip(v6=False), sl=g.slug)
        elif b == "notify":
            d.f("\ncurl -fsS -X POST -H 'Content-Type: application/json' \\\n"
                "  -d \"{\\\"text\\\":\\\"${RELEASE} deployed by ${USER}\\\"}\" \\\n  ⟦hook⟧\n", hook=g.purl())
        elif b == "mail":
            p = g.person()
            d.f('\n# on-call: ⟦name⟧, ⟦ph⟧\nprintf \'Release %s deployed\\n\' "$RELEASE" | mail -s "deploy ⟦app⟧" "$NOTIFY_TO"\n',
                name=g.name(p), ph=g.phone(), app=g.product().lower())
        else:
            d.f('\ncdnctl purge --tag "release-${RELEASE}" --api-key "⟦k⟧"\n', k=g.token())


# ===================================================================== config


def _env_pii_sections(g: Gen):
    p = g.person()
    dbpw, rpw = g.password(urlsafe=True), g.password(urlsafe=True)
    host = g.int_host("db")
    return [
        ("App", [("APP_ENV", "production"), ("APP_URL", g.co_homepage()), ("APP_SECRET", g.hexkey(64)),
                 ("LOG_LEVEL", g.pick(["info", "warn", "debug"])), ("TZ", g.tz()), ("PORT", str(g.port()))]),
        ("Database", [("DB_HOST", g.pick([host, g.ip(v6=False)])), ("DB_PORT", "5432"), ("DB_USER", "app"),
                      ("DB_PASSWORD", dbpw), ("DATABASE_URL", ["postgres://app:", dbpw, "@", host, ":5432/app"]),
                      ("DB_POOL_SIZE", str(g.rint(5, 40)))]),
        ("Redis", [("REDIS_URL", ["redis://:", rpw, "@", g.int_host("redis"), ":6379/0"]),
                   ("CACHE_TTL", str(g.pick([60, 300, 900])))]),
        ("Mail", [("SMTP_HOST", "smtp." + g.co_domain), ("SMTP_PORT", "587"), ("SMTP_USER", g.mailbox()),
                  ("SMTP_PASSWORD", g.password()), ("MAIL_FROM_NAME", '"%s"' % g.co_name)]),
        ("Payments", [("PAYMENTS_API_KEY", g.token()), ("PAYMENTS_WEBHOOK_SECRET", g.hexkey(g.pick([32, 64]))),
                      ("PAYOUT_ACCOUNT", g.iban(spaced=False)), ("PAYMENTS_MODE", "live")]),
        ("Auth", [("JWT_SECRET", g.b64key()), ("OAUTH_CLIENT_ID", g.uuid()), ("OAUTH_CLIENT_SECRET", g.token()),
                  ("SESSION_COOKIE_NAME", "sid"), ("SESSION_TTL_SECONDS", str(g.rint(900, 86400)))]),
        ("Storage", [("S3_BUCKET", g.slug + "-prod-assets"), ("S3_REGION", g.region()),
                     ("S3_SECRET_ACCESS_KEY", g.b64key(30))]),
        ("Monitoring", [("GRAFANA_URL", g.purl()), ("SENTRY_DSN", "${SENTRY_DSN}"), ("ALERT_SMS_TO", g.phone())]),
        ("Support", [("ESCALATION_CONTACT", ['"', g.name(p), " <", g.email(p), '>"']), ("SUPPORT_HOURS", '"Mo-Fr 08-18"')]),
        ("Admin", [("ADMIN_EMAIL", g.email(g.person())), ("ADMIN_INITIAL_PASSWORD", g.password())]),
        ("Backups", [("BACKUP_SFTP_HOST", g.ip(v6=False)), ("BACKUP_SFTP_USER", g.handle(g.person())),
                     ("BACKUP_SSH_KEY_PATH", "/run/secrets/backup_ed25519"), ("BACKUP_CRON", '"0 3 * * *"')]),
    ]


@template("cfg.dotenv", "config", ".env.production")
def tpl_dotenv(g: Gen, d: Doc, target: int) -> None:
    prod = g.product()
    d.t("# " + g.tx("Production environment for %s", "Produktionsumgebung für %s", "Environnement de production pour %s",
                    "Ambiente di produzione per %s", "Entorno de producción para %s") % prod + "\n")
    d.t("# " + g.tx("Do not commit this file.", "Diese Datei nicht einchecken.", "Ne pas committer ce fichier.",
                    "Non committare questo file.", "No subir este archivo al repositorio.") + "\n")
    for i in g.loop(d, target):
        if i and not g.chance(0.2):
            neutral(g, d, "env")
            continue
        title, lines = g.pick(_env_pii_sections(g))
        d.t("\n# --- %s ---\n" % title)
        if g.chance(0.3):
            d.t("# " + g.code_comment() + "\n")
        for k, v in lines:
            d.t(k + "=")
            d.v(v)
            d.t("\n")


@template("cfg.yaml.spring_app", "config", "src/main/resources/application-prod.yml")
def tpl_spring_yaml(g: Gen, d: Doc, target: int) -> None:
    app = g.pick(SERVICES) + "-service"
    d.f("# ⟦c⟧\nserver:\n  port: 8080\n  shutdown: graceful\nspring:\n  application:\n    name: ⟦app⟧\n  datasource:\n"
        "    url: jdbc:postgresql://⟦host⟧:5432/⟦db⟧\n    username: ⟦db⟧_rw\n    password: \"⟦pw⟧\"\n    hikari:\n"
        "      maximum-pool-size: 20\n  mail:\n    host: smtp.⟦dom⟧\n    port: 587\n    username: ⟦mb⟧\n    password: ${MAIL_PASSWORD}\n"
        "  security:\n    oauth2:\n      client:\n        registration:\n          keycloak:\n            client-id: ⟦app⟧\n"
        "            client-secret: ⟦tok⟧\nmanagement:\n  endpoints.web.exposure.include: health,info,prometheus\n"
        "app:\n  release: ⟦ver⟧\n  docs: ⟦pub⟧\n  notifications:\n    recipients:\n",
        c=g.code_comment(), app=app, host=g.pick([g.int_host("db"), g.ip(v6=False)]), db=g.pick(["orders", "crm", "billing"]),
        pw=g.password(), dom=g.co_domain, mb=g.mailbox(), tok=g.token(), ver=g.ver(), pub=g.pub_url("java"))
    for _ in range(1):
        p = g.person()
        d.f('      - name: "⟦name⟧"\n        email: ⟦email⟧\n        on-call: ⟦oc⟧\n',
            name=g.name(p), email=g.email(p), oc=g.pick(["true", "false"]))
    for _ in g.loop(d, target - 150, min_iter=0):
        neutral(g, d, "yaml")
    d.t("logging:\n  level:\n    root: INFO\n    org.hibernate.SQL: WARN\n  file:\n    name: /var/log/%s/app.log\n" % app)


@template("cfg.toml.service", "config", "config/service.toml")
def tpl_toml(g: Gen, d: Doc, target: int) -> None:
    app = g.pick(SERVICES)
    d.f('# ⟦c⟧\ntitle = "⟦app⟧"\nversion = "⟦ver⟧"\n\n[server]\nbind = "0.0.0.0:⟦port⟧"\nworkers = 4\npublic_url = "⟦home⟧"\n'
        'region = "⟦reg⟧"\n\n[database]\nurl = "mysql://svc_⟦app⟧:⟦pw⟧@⟦host⟧:3306/⟦app⟧"\npool_size = 16\n\n[smtp]\n'
        'host = "smtp.⟦dom⟧"\nuser = "⟦mb⟧"\npassword_file = "/run/secrets/smtp_password"\n',
        c=g.code_comment(), app=app, ver=g.ver(), port=str(g.port()), home=g.co_homepage(), reg=g.region(),
        pw=g.password(urlsafe=True), host=g.int_host("mysql"), dom=g.co_domain, mb=g.mailbox())
    for i in g.loop(d, target):
        if not g.chance(0.15):
            neutral(g, d, "toml")
            continue
        d.t("\n[[contacts]]\n")
        for k, v in g.record(g.person(), include_id=False):
            d.t("%s = " % k)
            lit(d, v)
            d.t("\n")


@template("cfg.ini.legacy", "config", "conf/reporting.ini")
def tpl_ini(g: Gen, d: Doc, target: int) -> None:
    dc = g.slug.split("-")[0]
    d.f("; ⟦c⟧\n[general]\napp_name = reporting\nlog_file = /var/log/reporting/app.log\nlocale = ⟦loc⟧\ntimezone = ⟦tz⟧\n\n"
        "[database]\nhost = ⟦ip⟧\nport = 1433\nuser = sa_report\npassword = ⟦pw⟧\n",
        c=g.code_comment(), loc=g.locale(), tz=g.tz(), ip=g.pick([g.ip(v6=False), g.int_host("mssql")]), pw=g.password())
    if g.chance(0.5):
        d.f("\n[ldap]\nuri = ⟦ldap⟧\nbind_dn = cn=svc-reporting,ou=services,dc=⟦dc⟧,dc=local\nbind_password = ⟦pw⟧\n",
            ldap=g._pii("private_url", "ldaps://ldap.int.%s:636" % g.co_domain), dc=dc, pw=g.password())
    n_op = 0
    for i in g.loop(d, target):
        if not g.chance(0.15):
            neutral(g, d, "ini")
            continue
        n_op += 1
        p = g.person()
        d.f("\n[operator.⟦n⟧]\nname = ⟦name⟧\nemail = ⟦email⟧\nshift = ⟦sh⟧\n", n=str(n_op), name=g.name(p),
            email=g.email(p), sh=g.pick(["early", "late", "weekend"]))


@template("cfg.json.appsettings", "config", "appsettings.Production.json")
def tpl_appsettings(g: Gen, d: Doc, target: int) -> None:
    d.f('{\n  "Logging": {\n    "LogLevel": {\n      "Default": "Information",\n      "Microsoft.AspNetCore": "Warning"\n    }\n  },\n'
        '  "AllowedHosts": "*",\n  "ConnectionStrings": {\n'
        '    "Default": "Server=⟦host⟧;Database=⟦db⟧;User Id=app_⟦db⟧;Password=⟦pw⟧;TrustServerCertificate=True"\n  },\n'
        '  "Jwt": {\n    "Issuer": "https://login.⟦dom⟧/realms/main",\n    "Key": "⟦key⟧",\n    "ExpiresMinutes": 60\n  },\n'
        '  "Smtp": {\n    "Host": "smtp.⟦dom⟧",\n    "Port": 587,\n    "User": "⟦mb⟧",\n    "Password": "${SMTP_PASSWORD}"\n  },\n'
        '  "Release": "⟦ver⟧",\n  "AdminUsers": [\n',
        host=g.int_host("sql"), db=g.pick(["Orders", "Crm", "Billing"]), pw=g.password(), dom=g.co_domain,
        key=g.b64key(), mb=g.mailbox(), ver=g.ver())
    d.t("    ")
    json_obj(d, g.record(g.person()), "    ")
    d.t("\n  ]")
    used = Counter()
    for _ in g.loop(d, target - 200, min_iter=0):
        block = nfill(g, g.pick(NEUTRAL["json"]))
        key = block.split('"')[1]
        used[key] += 1
        if used[key] > 1:
            block = block.replace('"%s"' % key, '"%s%d"' % (key, used[key]), 1)
        d.t(",\n  " + block)
    if g.chance(0.4):
        d.f(',\n  "ServiceAccount": {\n    "type": "service_account",\n    "private_key_id": "⟦kid⟧",\n'
            '    "private_key": "⟦pem⟧",\n    "client_email": "⟦em⟧"\n  }',
            kid=g.sha(), pem=g.pem(joiner="\\n", small=True),
            em=g._pii("private_email", "svc-reporting@%s-prod.iam.%s" % (g.slug, g.co_domain)))
    d.t("\n}\n")


@template("cfg.compose", "config", "docker-compose.prod.yml")
def tpl_compose(g: Gen, d: Doc, target: int) -> None:
    pw = g.password(urlsafe=True)
    d.f("# ⟦c⟧\nservices:\n  db:\n    image: postgres:16.4-alpine\n    restart: unless-stopped\n    environment:\n"
        "      POSTGRES_USER: app\n      POSTGRES_PASSWORD: ⟦pw⟧\n    volumes:\n      - pgdata:/var/lib/postgresql/data\n"
        "    networks:\n      backend:\n        ipv4_address: ⟦ip⟧\n\n  api:\n    image: registry.⟦dom⟧/api:⟦ver⟧\n"
        "    depends_on: [db]\n    environment:\n      DATABASE_URL: postgres://app:⟦pw⟧@db:5432/app\n      PAYMENTS_API_KEY: ⟦tok⟧\n"
        "      TZ: ⟦tz⟧\n    ports:\n      - \"8080:8080\"\n",
        c=g.code_comment(), pw=pw, ip=g.ip(v6=False), dom=g.co_domain, ver=g.ver(), tok=g.token(), tz=g.tz())
    if g.chance(0.25):
        p = g.person()
        d.f("    labels:\n      com.⟦sl⟧.owner: \"⟦name⟧ <⟦email⟧>\"\n", sl=g.slug, name=g.name(p), email=g.email(p))
    for i in g.loop(d, target - 150, min_iter=0):
        if not g.chance(0.15):
            neutral(g, d, "compose")
            continue
        svc = g.pick(SERVICES) + "-%d" % (i + 1)
        d.f("\n  ⟦svc⟧:\n    image: registry.⟦dom⟧/⟦base⟧:⟦ver⟧\n    environment:\n      QUEUE_URL: amqp://⟦base⟧:⟦pw⟧@rabbitmq:5672/prod\n"
            "      REPORT_RECIPIENT: ⟦mail⟧\n      LOG_LEVEL: info\n",
            svc=svc, dom=g.co_domain, base=svc.split("-")[0], ver=g.ver(), pw=g.password(urlsafe=True), mail=g.mailbox())
    d.t("\nnetworks:\n  backend:\n    ipam:\n      config:\n        - subnet: 172.28.0.0/16\n\nvolumes:\n  pgdata: {}\n")


@template("cfg.k8s_manifest", "config", "deploy/k8s/payments.yaml")
def tpl_k8s(g: Gen, d: Doc, target: int) -> None:
    ns = g.pick(TEAMS)
    for i in g.loop(d, target):
        if i and not g.chance(0.2):
            neutral(g, d, "k8s")
            continue
        app = g.pick(SERVICES)
        pw = g.password()
        d.f("---\napiVersion: v1\nkind: Secret\nmetadata:\n  name: ⟦app⟧-credentials\n  namespace: ⟦ns⟧\n"
            "  annotations:\n    owner: ⟦mb⟧\ntype: Opaque\ndata:\n  username: ⟦u64⟧\n  password: ⟦p64⟧\nstringData:\n"
            "  API_TOKEN: \"⟦tok⟧\"\n",
            app=app, ns=ns, mb=g.mailbox(), u64=base64.b64encode(b"app").decode(), p64=g.b64_secret_of(pw), tok=g.token())
        if g.chance(0.3):
            d.f("  tls.key: |\n    ⟦pem⟧\n", pem=g.pem(indent="    ", small=True))
        d.f("---\napiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: ⟦app⟧\n  namespace: ⟦ns⟧\n  labels:\n"
            "    app.kubernetes.io/name: ⟦app⟧\n    app.kubernetes.io/version: \"⟦ver⟧\"\nspec:\n  replicas: ⟦rep⟧\n"
            "  template:\n    spec:\n      containers:\n        - name: ⟦app⟧\n          image: registry.⟦dom⟧/⟦app⟧@sha256:⟦dig⟧\n"
            "          envFrom:\n            - secretRef:\n                name: ⟦app⟧-credentials\n"
            "          env:\n            - name: DB_HOST\n              value: \"⟦dbh⟧\"\n            - name: DB_PASSWORD\n"
            "              valueFrom:\n                secretKeyRef: {name: ⟦app⟧-credentials, key: password}\n",
            app=app, ns=ns, ver=g.ver(), rep=str(g.rint(1, 6)), dom=g.co_domain, dig=g.sha256(),
            dbh=g.pick([g.ip(v6=False), g.int_host("db")]))


@template("cfg.ci_pipeline", "config", ".github/workflows/deploy.yml")
def tpl_ci(g: Gen, d: Doc, target: int) -> None:
    p = g.person()
    d.f("# ⟦c⟧\n# owner: ⟦handle⟧\nname: deploy\non:\n  push:\n    branches: [main]\n  workflow_dispatch: {}\n"
        "env:\n  REGISTRY: registry.⟦dom⟧\n  NODE_VERSION: \"20.17.0\"\n  NPM_TOKEN: ${{ secrets.NPM_TOKEN }}\njobs:\n"
        "  test:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v4\n"
        "        with:\n          node-version: ${{ env.NODE_VERSION }}\n      - run: npm ci && npm test -- --reporter=dot\n",
        c=g.code_comment(), handle=g.handle(p), dom=g.co_domain)
    for i in g.loop(d, target):
        if not g.chance(0.2):
            neutral(g, d, "ci")
            continue
        j = g.pick(["deploy", "e2e", "backup", "notify"])
        sfx = "-%d" % i
        if j == "deploy":
            d.f("  deploy⟦s⟧:\n    needs: test\n    runs-on: ubuntu-24.04\n    environment: production\n    steps:\n      - run: |\n"
                "          echo \"⟦tok⟧\" | docker login registry.⟦dom⟧ -u ci-bot --password-stdin\n"
                "          ssh deploy@⟦ip⟧ \"cd /srv/app && ./deploy.sh ${GITHUB_SHA::7}\"\n",
                s=sfx, tok=g.token(), dom=g.co_domain, ip=g.ip(v6=False))
        elif j == "e2e":
            q = g.person()
            d.f("  e2e⟦s⟧:\n    needs: test\n    runs-on: ubuntu-24.04\n    env:\n      BASE_URL: ⟦purl⟧\n"
                "      TEST_USER_EMAIL: ⟦email⟧\n      TEST_USER_PASSWORD: ⟦pw⟧\n      CI_SECRET: ${{ secrets.E2E_SECRET }}\n"
                "    steps:\n      - uses: actions/checkout@v4\n      - run: npx playwright test --project=chromium\n",
                s=sfx, purl=g.purl(), email=g.email(q), pw=g.password())
        elif j == "backup":
            d.f("  backup⟦s⟧:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: |\n"
                "          PGPASSWORD=⟦pw⟧ pg_dump -h ⟦h⟧ -U backup app | gzip > app-$(date +%F).sql.gz\n"
                "          rclone copy app-*.sql.gz backup:⟦sl⟧-backups/ --s3-region ⟦reg⟧\n",
                s=sfx, pw=g.password(urlsafe=True), h=g.int_host("db"), sl=g.slug, reg=g.region())
        else:
            d.f("  notify⟦s⟧:\n    needs: [test]\n    if: failure()\n    runs-on: ubuntu-24.04\n    steps:\n"
                "      - run: curl -fsS -X POST -d '{\"text\":\"build failed\"}' ⟦hook⟧\n", s=sfx, hook=g.purl())


@template("cfg.dockerfile", "config", "Dockerfile")
def tpl_dockerfile(g: Gen, d: Doc, target: int) -> None:
    p = g.person()
    d.f("# syntax=docker/dockerfile:1.7\n# ⟦c⟧\nFROM python:3.12-slim@sha256:⟦dig⟧ AS build\n"
        "LABEL maintainer=\"⟦name⟧ <⟦email⟧>\" \\\n      org.opencontainers.image.version=\"⟦ver⟧\"\n"
        "ARG PIP_INDEX_URL=https://ci-bot:⟦tok⟧@pypi.int.⟦dom⟧/simple\nENV PYTHONDONTWRITEBYTECODE=1 \\\n"
        "    APP_HOME=/srv/app \\\n    TZ=⟦tz⟧\nWORKDIR /srv/app\nCOPY requirements.lock .\n"
        "RUN pip install --no-cache-dir -r requirements.lock\n",
        c=g.code_comment(), dig=g.sha256(), name=g.name(p), email=g.email(p), ver=g.ver(), tok=g.token(),
        dom=g.co_domain, tz=g.tz())
    for i in g.loop(d, target - 250, min_iter=0):
        if not g.chance(0.2):
            neutral(g, d, "docker")
            continue
        if g.chance(0.5):
            d.f("\n# ⟦c⟧\nENV SENTRY_DSN=${SENTRY_DSN} \\\n    DB_PASSWORD=⟦pw⟧\n", c=g.code_comment(), pw=g.password())
        else:
            d.f("\nRUN echo \"⟦ip⟧ legacy-erp.internal\" >> /etc/hosts\n", ip=g.ip(v6=False))
    d.t("\nEXPOSE 8000\nUSER 10001\nHEALTHCHECK CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1\n"
        "CMD [\"gunicorn\", \"app.wsgi:application\", \"--bind\", \"0.0.0.0:8000\", \"--workers\", \"4\"]\n")


# ======================================================================== log


def app_msg(g: Gen, pii_prob: float) -> list:
    if g.chance(0.35):
        return [nfill(g, g.pick(NEUTRAL["framework_log"]))]
    return g.log_msg(pii_prob)


@template("log.nginx_access", "log", "access.log")
def tpl_nginx(g: Gen, d: Doc, target: int) -> None:
    ups = ["app-%d:8080" % i for i in range(1, 4)]
    for _ in g.loop(d, target):
        g.tick(0, 15)
        r = g.r.random()
        if r < 0.6:
            path = g.pick(["/healthz", "/metrics", "/readyz"])
            d.t('%s - - [%s] "GET %s HTTP/1.1" 200 %d "-" "%s" rt=0.00%d upstream=%s req_id=%s\n'
                % (g.pick(["127.0.0.1", "127.0.0.1", "::1"]), g.ts_nginx(), path, g.rint(2, 9000),
                   g.pick(["kube-probe/1.30", "Prometheus/2.54.1"]), g.rint(1, 9), g.pick(ups), g.hexs(32)))
            continue
        status = 200
        if r < 0.63:
            method, path = "GET", ["/api/v2/customers/export?email=", g.email(g.person()), "&format=csv"]
        elif r < 0.65:
            method, path, status = "GET", ["/account/reset?token=", g.token()], 302
        elif r < 0.75:
            method, path, status = "POST", "/api/v2/orders", g.pick([201, 201, 400, 422])
        elif r < 0.85:
            method, path = "GET", "/static/js/app.%s.js" % g.hexs(8)
        elif r < 0.94:
            method, path, status = "GET", "/api/v2/orders?page=%d&per_page=50" % g.rint(1, 40), g.pick([200, 200, 304])
        else:
            method, path, status = g.pick(["POST", "GET"]), "/login", g.pick([200, 302, 401, 429])
        user = g.handle(g.person()) if g.chance(0.05) else "-"
        ref = g.pick(["-", "-", "-", g.co_homepage() + "/", g.purl()])
        d.v(g.ip())
        d.t(" - ")
        d.v(user)
        d.t(' [%s] "%s ' % (g.ts_nginx(), method))
        d.v(path)
        d.t(' HTTP/1.1" %d %d "' % (status, g.rint(120, 90000)))
        d.v(ref)
        d.t('" "%s" rt=%.3f upstream=%s req_id=%s\n' % (g.pick(USER_AGENTS), g.r.uniform(0.001, 2.5), g.pick(ups), g.hexs(32)))


@template("log.app_levels", "log", "app.log")
def tpl_app_log(g: Gen, d: Doc, target: int) -> None:
    pre = g.slug[0]
    loggers = ["%s.b.billing.InvoiceService" % pre, "%s.a.auth.LoginController" % pre, "%s.c.crm.CustomerSync" % pre,
               "o.h.engine.jdbc.spi.SqlExceptionHelper", "%s.p.payout.PayoutJob" % pre, "%s.n.notify.MailSender" % pre,
               "com.zaxxer.hikari.HikariDataSource", "o.s.b.w.embedded.tomcat.TomcatWebServer"]
    for _ in g.loop(d, target):
        g.tick(0, 40)
        lvl = g.weighted([("INFO", 6), ("DEBUG", 2), ("WARN", 2), ("ERROR", 1)])
        thread = g.pick(["http-nio-8080-exec-%d" % g.rint(1, 12), "scheduling-1", "task-%d" % g.rint(1, 8), "main"])
        d.t("%s %5s 1 --- [%15s] %-40s : " % (g.ts_space("."), lvl, thread[-15:], g.pick(loggers)[:40]))
        d.v(app_msg(g, 0.2))
        d.t("\n")


@template("log.audit_jsonl", "log", "audit.jsonl")
def tpl_audit(g: Gen, d: Doc, target: int) -> None:
    actions = ["user.login", "user.update", "user.export", "role.grant", "apikey.create", "invoice.view", "mfa.reset",
               "job.run", "config.reload", "cache.flush"]
    for _ in g.loop(d, target):
        g.tick(1, 300)
        human = g.chance(0.2)
        a = g.pick(actions[:7] if human else actions[5:])
        d.t('{"ts":"%s","actor":"' % g.ts_iso())
        if human:
            p = g.person()
            d.v(g.handle(p))
            if g.chance(0.5):
                d.t('","actor_email":"')
                d.v(g.email(p))
            d.t('","source_ip":"')
            d.v(g.ip())
        else:
            d.t('%s","source_ip":"127.0.0.1' % g.pick(["svc-billing", "system", "scheduler", "svc-crm-sync"]))
        d.t('","action":"%s","target":"%s"' % (a, g.uuid()))
        if a == "user.update" and g.chance(0.5):
            field = g.pick(["phone", "address", "email"])
            q = g.person()
            maker = {"phone": g.phone, "address": g.address, "email": lambda: g.email(q)}[field]
            d.t(',"changes":{"%s":["' % field)
            d.v(maker())
            d.t('","')
            d.v(maker())
            d.t('"]}')
        elif a == "role.grant":
            d.t(',"role":"%s"' % g.pick(["admin", "billing-viewer", "support-agent"]))
        d.t(',"request_id":"%s","outcome":"%s","latency_ms":%d}\n' % (g.req_id(), g.pick(["success", "success", "denied"]),
                                                                    g.rint(1, 900)))


CRON_JOBS = ["payroll-export", "gdpr-purge", "invoice-reminders", "backup-db", "sync-crm", "cert-renew"]


@template("log.cron_jobs", "log", "cron.log")
def tpl_cron(g: Gen, d: Doc, target: int) -> None:
    for _ in g.loop(d, target):
        job = g.pick(CRON_JOBS)
        g.tick(600, 7200)

        def line(body, **kw):
            g.tick(0, 9)
            d.t("[%s] [%s] " % (g.ts_sec(), job))
            d.f(body + "\n", **kw)

        def progress():
            for _k in range(g.rint(1, 4)):
                line("batch ⟦b⟧/⟦t⟧ done (⟦n⟧ rows, ⟦r⟧ rows/s, rss=⟦m⟧MB)", b=str(_k + 1), t=str(g.rint(4, 12)),
                     n=str(g.rint(100, 5000)), r=str(g.rint(80, 4000)), m=str(g.rint(80, 900)))

        line("run ⟦r⟧ started (host=batch-0⟦h⟧, pid=⟦pid⟧)", r=str(g.rint(1000, 99999)), h=str(g.rint(1, 4)),
             pid=str(g.rint(300, 65000)))
        line("lock acquired: /var/lock/%s.lock" % job)
        if job == "payroll-export":
            line(g.tx("loaded ⟦n⟧ employees", "⟦n⟧ Mitarbeitende geladen", "⟦n⟧ salariés chargés", "⟦n⟧ dipendenti caricati",
                      "⟦n⟧ empleados cargados"), n=str(g.rint(40, 4000)))
            progress()
            if g.chance(0.4):
                line(g.tx("WARN employee ⟦name⟧ has no tax id on file", "WARN Mitarbeiter ⟦name⟧ ohne hinterlegte Steuer-ID",
                          "WARN le salarié ⟦name⟧ n'a pas de numéro fiscal", "WARN il dipendente ⟦name⟧ non ha codice fiscale",
                          "WARN el empleado ⟦name⟧ no tiene NIF registrado"), name=g.name(g.person()))
            line("wrote /data/exports/payroll_2026-%02d.csv (sha256=%s)" % (g.rint(1, 12), g.sha256()))
            if g.chance(0.4):
                line(g.tx("uploaded to ⟦u⟧@⟦ip⟧:/inbound/", "hochgeladen nach ⟦u⟧@⟦ip⟧:/inbound/", "envoyé vers ⟦u⟧@⟦ip⟧:/inbound/",
                          "caricato su ⟦u⟧@⟦ip⟧:/inbound/", "subido a ⟦u⟧@⟦ip⟧:/inbound/"), u=g.handle(g.person()), ip=g.ip(v6=False))
        elif job == "gdpr-purge":
            line(g.tx("deleted ⟦n⟧ accounts inactive for 3 years", "⟦n⟧ seit 3 Jahren inaktive Konten gelöscht",
                      "⟦n⟧ comptes inactifs depuis 3 ans supprimés", "eliminati ⟦n⟧ account inattivi da 3 anni",
                      "eliminadas ⟦n⟧ cuentas inactivas desde hace 3 años"), n=str(g.rint(0, 900)))
            if g.chance(0.4):
                p = g.person()
                line(g.tx("skipped ⟦name⟧ (⟦email⟧): legal hold", "übersprungen: ⟦name⟧ (⟦email⟧), Aufbewahrungspflicht",
                          "ignoré : ⟦name⟧ (⟦email⟧), conservation légale", "saltato ⟦name⟧ (⟦email⟧): conservazione legale",
                          "omitido ⟦name⟧ (⟦email⟧): retención legal"), name=g.name(p), email=g.email(p))
        elif job == "invoice-reminders":
            progress()
            for _k in range(g.rint(0, 2)):
                line(g.tx("reminder for INV-⟦n⟧ sent to ⟦email⟧", "Erinnerung zu INV-⟦n⟧ an ⟦email⟧ gesendet",
                          "relance INV-⟦n⟧ envoyée à ⟦email⟧", "sollecito INV-⟦n⟧ inviato a ⟦email⟧",
                          "recordatorio INV-⟦n⟧ enviado a ⟦email⟧"), n=str(g.rint(10000, 99999)), email=g.email(g.person()))
        elif job == "backup-db":
            line("pg_dump app | zstd > /backups/app-%s.sql.zst (%d MB)" % (g.clock.strftime("%Y%m%d"), g.rint(80, 9000)))
            line("uploaded to bucket %s-backups region=%s etag=%s" % (g.slug, g.region(), g.hexs(32)))
        elif job == "sync-crm":
            progress()
            if g.chance(0.5):
                line(g.tx("updated contact ⟦name⟧ (⟦phone⟧)", "Kontakt ⟦name⟧ aktualisiert (⟦phone⟧)", "contact ⟦name⟧ mis à jour (⟦phone⟧)",
                          "contatto ⟦name⟧ aggiornato (⟦phone⟧)", "contacto ⟦name⟧ actualizado (⟦phone⟧)"),
                     name=g.name(g.person()), phone=g.phone())
        else:
            line("certificate for *.%s renewed, expires in 90 days (serial %s)" % (g.co_domain, g.hexs(16)))
        if g.chance(0.2):
            line(g.tx("report mailed to ⟦m⟧", "Bericht an ⟦m⟧ gesendet", "rapport envoyé à ⟦m⟧", "report inviato a ⟦m⟧",
                      "informe enviado a ⟦m⟧"), m=g.mailbox())
        line("finished in %.1fs, exit=%d" % (g.r.uniform(0.4, 300), g.pick([0, 0, 0, 1])))


@template("log.auth_syslog", "log", "auth.log")
def tpl_authlog(g: Gen, d: Doc, target: int) -> None:
    host = g.pick(["bastion-01", "app-03", "gw-01", "db-02"])
    users = [g.person() for _ in range(3)]
    for _ in g.loop(d, target):
        g.tick(1, 90)
        pid = g.rint(1000, 60000)
        r = g.r.random()
        p = g.pick(users)
        d.t("%s %s " % (g.ts_syslog(), host))
        if r < 0.06:
            d.f("sshd[⟦pid⟧]: Accepted publickey for ⟦u⟧ from ⟦ip⟧ port ⟦port⟧ ssh2: ED25519 SHA256:⟦fp⟧\n",
                pid=str(pid), u=g.handle(p), ip=g.ip(), port=str(g.rint(30000, 65000)), fp=b64url(g.rbytes(32)))
        elif r < 0.14:
            d.f("sshd[⟦pid⟧]: Failed password for invalid user ⟦bad⟧ from ⟦ip⟧ port ⟦port⟧ ssh2\n", pid=str(pid),
                bad=g.pick(["admin", "oracle", "test", "ubuntu", "git", "postgres"]), ip=g.ip(v6=False),
                port=str(g.rint(30000, 65000)))
        elif r < 0.18:
            d.f("sudo:   ⟦u⟧ : TTY=pts/⟦t⟧ ; PWD=/srv/app ; USER=root ; COMMAND=/usr/bin/systemctl restart ⟦svc⟧\n",
                u=g.handle(p), t=str(g.rint(0, 4)), svc=g.pick(["nginx", "postgresql", "app", "docker"]))
        elif r < 0.21:
            d.f("dhcpd[⟦pid⟧]: DHCPACK on ⟦ip⟧ to ⟦mac⟧ (⟦hn⟧) via eth1\n", pid=str(pid), ip=g.ip(v6=False), mac=g.mac(),
                hn=g.pick(["android-%s" % g.hexs(6), "DESKTOP-%s" % g.letters(7, string.ascii_uppercase + string.digits),
                           "printer-3f", "iPhone"]))
        elif r < 0.23:
            d.f("systemd-logind[⟦pid⟧]: New session ⟦s⟧ of user ⟦u⟧.\n", pid=str(pid), s=str(g.rint(10, 999)), u=g.handle(p))
        elif r < 0.62:
            d.t("CRON[%d]: (root) CMD (%s)\n" % (pid, g.pick(["/usr/local/bin/backup.sh >/dev/null 2>&1",
                                                             "test -x /usr/sbin/anacron || run-parts --report /etc/cron.daily",
                                                             "/usr/lib/php/sessionclean"])))
        elif r < 0.75:
            d.t("CRON[%d]: pam_unix(cron:session): session %s for user root\n" % (pid, g.pick(["opened", "closed"])))
        elif r < 0.9:
            d.t("systemd[1]: %s\n" % g.pick(["Starting Daily apt download activities...", "Finished Daily apt upgrade and clean activities.",
                                            "Started Session Cleanup.", "logrotate.service: Deactivated successfully.",
                                            "Started Hourly backup of /etc."]))
        else:
            d.t("kernel: [%d.%06d] TCP: request_sock_TCP: Possible SYN flooding on port %d. Sending cookies.\n"
                % (g.rint(1000, 999999), g.rint(0, 999999), g.port()))


@template("log.k8s_logfmt", "log", "pod.log")
def tpl_logfmt(g: Gen, d: Doc, target: int) -> None:
    for _ in g.loop(d, target):
        g.tick(0, 20)
        lvl = g.weighted([("info", 6), ("debug", 2), ("warn", 2), ("error", 1)])
        d.t('ts=%s level=%s caller=%s.go:%d msg="' % (g.ts_iso(), lvl, g.pick(["handler", "store", "worker", "auth"]),
                                                      g.rint(20, 400)))
        d.v(app_msg(g, 0.15))
        d.t('" method=%s path=/v1/%s status=%d duration_ms=%d trace_id=%s'
            % (g.pick(["GET", "POST", "PATCH"]), g.pick(["orders", "customers", "payouts", "sessions"]),
               g.pick([200, 200, 201, 404, 500]), g.rint(1, 900), g.trace_id()))
        if g.chance(0.08):
            d.t(" client_ip=")
            d.v(g.ip())
        d.t("\n")


@template("log.postfix", "log", "mail.log")
def tpl_postfix(g: Gen, d: Doc, target: int) -> None:
    for _ in g.loop(d, target):
        g.tick(5, 300)
        qid = g.letters(10, "0123456789ABCDEF")
        pid = g.rint(1000, 60000)
        if g.chance(0.6):
            d.t("%s mx1 postfix/pickup[%d]: %s: uid=1001 from=<app>\n" % (g.ts_syslog(), pid, qid))
        else:
            peer = "mail-out.%s" % g.pick(COMPANIES[g.pick(LANGS)])[1]
            d.t("%s mx1 postfix/smtpd[%d]: connect from %s[" % (g.ts_syslog(), pid, peer))
            d.v(g.ip(v6=False))
            d.t("]\n")
        d.t("%s mx1 postfix/cleanup[%d]: %s: message-id=<%s@%s>\n" % (g.ts_syslog(), pid + 3, qid, g.hexs(20), g.co_domain))
        d.t("%s mx1 postfix/qmgr[811]: %s: from=<" % (g.ts_syslog(), qid))
        d.v(g.pick([g.mailbox(), g.mailbox(), g.email(g.person())]))
        d.t(">, size=%d, nrcpt=1 (queue active)\n" % g.rint(800, 90000))
        g.tick(0, 3)
        rcpt = g.email(g.person())
        d.t("%s mx1 postfix/smtp[%d]: %s: to=<" % (g.ts_syslog(), pid + 9, qid))
        d.v(rcpt)
        if g.chance(0.85):
            d.t(">, relay=mx.%s[" % g.pick(COMPANIES[g.pick(LANGS)])[1])
            d.v(g.ip(v6=False))
            d.t("]:25, delay=%.2f, delays=0.1/0/0.2/0.1, dsn=2.0.0, status=sent (250 2.0.0 Ok: queued as %s)\n"
                % (g.r.uniform(0.1, 3), g.letters(10, "0123456789ABCDEF")))
        else:
            d.t(">, relay=none, delay=%.1f, dsn=5.1.1, status=bounced (host said: 550 5.1.1 <" % g.r.uniform(0.1, 3))
            d.v(rcpt)
            d.t(">: Recipient address rejected: User unknown)\n")
        d.t("%s mx1 postfix/qmgr[811]: %s: removed\n" % (g.ts_syslog(), qid))
        for _k in range(g.rint(2, 5)):
            g.tick(1, 60)
            d.t("%s mx1 %s\n" % (g.ts_syslog(), g.pick([
                "postfix/anvil[%d]: statistics: max connection rate 1/60s for (smtp:%s) at %s" % (g.rint(100, 9000), g.hexs(6), g.ts_syslog()),
                "postfix/scache[%d]: statistics: domain lookup hits=%d miss=%d success=%d%%" % (g.rint(100, 9000), g.rint(0, 40), g.rint(0, 9), g.rint(50, 100)),
                "postfix/tlsmgr[%d]: prng_exch cache: updated" % g.rint(100, 9000),
                "postfix/smtp[%d]: Trusted TLS connection established (TLSv1.3 with cipher TLS_AES_256_GCM_SHA384 (256/256 bits))" % g.rint(100, 9000)])))


# ================================================================ stack_trace


def py_frames(g: Gen, n: int) -> str:
    own = ["billing/tasks.py", "billing/gateway.py", "crm/sync.py", "api/views/customers.py", "core/db.py"]
    libs = [".venv/lib/python3.12/site-packages/requests/models.py", ".venv/lib/python3.12/site-packages/psycopg/cursor.py",
            ".venv/lib/python3.12/site-packages/django/core/handlers/base.py",
            ".venv/lib/python3.12/site-packages/celery/app/trace.py"]
    funcs = ["charge_customer", "sync_contact", "handle", "execute", "raise_for_status", "save", "get_response", "__call__"]
    out = []
    for _ in range(n):
        path = "/srv/app/" + g.pick(own + libs)
        out.append('  File "%s", line %d, in %s\n    %s\n' % (path, g.rint(12, 1400), g.pick(funcs),
                                                              g.pick(["result = gateway.charge(card_number=card, amount=amount)",
                                                                      "resp.raise_for_status()", "self._conn.execute(query, params)",
                                                                      "return self.process(request)", "customer.save(update_fields=fields)",
                                                                      "R = retval = fun(*args, **kwargs)"])))
    return "".join(out)


@template("trace.python", "stack_trace", "worker-error.log")
def tpl_trace_py(g: Gen, d: Doc, target: int) -> None:
    for i in g.loop(d, target):
        g.tick(30, 3000)
        p = g.person(safe=True)
        d.t("%s ERROR [worker-%d] %s: " % (g.ts_space(), g.rint(1, 8), g.pick(["billing.tasks", "crm.sync", "api.views"])))
        d.f(g.tx("charge failed for customer ⟦cid⟧", "Belastung für Kunde ⟦cid⟧ fehlgeschlagen", "échec du débit pour le client ⟦cid⟧",
                 "addebito fallito per il cliente ⟦cid⟧", "cargo fallido para el cliente ⟦cid⟧"), cid=str(g.rint(1000, 99999)))
        d.t("\nTraceback (most recent call last):\n" + py_frames(g, g.rint(3, 8)))
        k = g.rint(0, 7) if i else g.rint(0, 4)
        if k == 0:
            d.f("requests.exceptions.HTTPError: 402 Client Error: Payment Required for url: ⟦u⟧\n", u=g.api_user_url())
        elif k == 1:
            d.f("ValueError: invalid IBAN checksum: '⟦iban⟧'\n", iban=g.iban())
        elif k == 2:
            d.f('psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "users_email_key"\n'
                "DETAIL:  Key (email)=(⟦email⟧) already exists.\n", email=g.email(p))
        elif k == 3:
            d.f("smtplib.SMTPRecipientsRefused: {'⟦email⟧': (550, b'5.1.1 User unknown')}\n", email=g.email(p))
        elif k == 4:
            d.f("pydantic_core._pydantic_core.ValidationError: 1 validation error for Customer\nphone\n"
                "  String should match pattern '^\\+?[0-9 ]+$' [type=string_pattern_mismatch, input_value='⟦ph⟧', input_type=str]\n",
                ph=g.phone())
        elif k == 5:
            d.t("TimeoutError: timed out after %d.0 seconds waiting for pricing-service\n" % g.rint(5, 60))
        elif k == 6:
            d.t("KeyError: 'currency'\n")
        else:
            d.t("ConnectionResetError: [Errno 104] Connection reset by peer\n")
        if g.chance(0.2):
            d.f("\nLocals:\n    customer = {'id': ⟦id⟧, 'name': '⟦name⟧', 'email': '⟦email⟧'}\n    card     = '⟦card⟧'\n"
                "    amount   = Decimal('⟦amt⟧')\n", id=str(g.rint(1000, 99999)), name=g.name(p), email=g.email(p),
                card=g.card(), amt=g.amount())
        d.t("\n")


JAVA_LIB_FRAMES = [
    "org.springframework.web.servlet.FrameworkServlet.processRequest(FrameworkServlet.java:1014)",
    "org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1089)",
    "org.springframework.web.method.support.InvocableHandlerMethod.invokeForRequest(InvocableHandlerMethod.java:179)",
    "org.apache.catalina.core.ApplicationFilterChain.doFilter(ApplicationFilterChain.java:138)",
    "org.apache.tomcat.util.threads.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:659)",
    "org.hibernate.engine.jdbc.spi.SqlExceptionHelper.convert(SqlExceptionHelper.java:95)",
    "com.zaxxer.hikari.pool.ProxyPreparedStatement.executeUpdate(ProxyPreparedStatement.java:61)",
    "org.springframework.transaction.interceptor.TransactionInterceptor.invoke(TransactionInterceptor.java:119)",
    "org.springframework.aop.framework.ReflectiveMethodInvocation.proceed(ReflectiveMethodInvocation.java:184)",
    "java.base/java.lang.Thread.run(Thread.java:1583)",
]


@template("trace.java", "stack_trace", "catalina.out")
def tpl_trace_java(g: Gen, d: Doc, target: int) -> None:
    pkg = "com.%s" % g.slug.replace("-", "")
    for i in g.loop(d, target):
        g.tick(30, 3000)
        p = g.person()
        d.t("%s ERROR 1 --- [nio-8080-exec-%d] o.a.c.c.C.[.[.[/].[dispatcherServlet]    : Servlet.service() for servlet "
            "[dispatcherServlet] threw exception\n" % (g.ts_space("."), g.rint(1, 9)))
        k = g.rint(0, 4) if i else g.rint(0, 2)
        if k == 0:
            d.f("⟦pkg⟧.crm.CustomerNotFoundException: ⟦msg⟧ ⟦email⟧\n", pkg=pkg, email=g.email(p),
                msg=g.tx("No customer with email", "Kein Kunde mit E-Mail", "Aucun client avec l'adresse",
                         "Nessun cliente con email", "Ningún cliente con el correo"))
        elif k == 1:
            d.f("⟦pkg⟧.payout.PayoutRejectedException: payout rejected for account ⟦iban⟧ (holder ⟦name⟧)\n",
                pkg=pkg, iban=g.iban(), name=g.name(p))
        elif k == 2:
            d.f("⟦pkg⟧.kyc.DocumentValidationException: passport ⟦pp⟧ expired for applicant ⟦name⟧\n",
                pkg=pkg, pp=g.passport(), name=g.name(p))
        elif k == 3:
            d.t("org.springframework.dao.QueryTimeoutException: PreparedStatementCallback; SQL [select * from orders where status = ?]; "
                "timeout after %dms\n" % g.rint(1000, 30000))
        else:
            d.t("java.lang.IllegalStateException: Circuit breaker 'pricing' is OPEN and does not permit further calls\n")
        for _f in range(g.rint(2, 4)):
            d.t("\tat %s.%s.%s(%s.java:%d)\n" % (pkg, g.pick(["crm", "payout", "kyc", "api"]),
                                                 g.pick(["CustomerService.findByEmail", "PayoutService.execute",
                                                         "KycController.submit", "CustomerController.update"]),
                                                 g.pick(["CustomerService", "PayoutService", "KycController"]), g.rint(20, 400)))
        for fr in g.r.sample(JAVA_LIB_FRAMES, g.rint(4, 8)):
            d.t("\tat %s\n" % fr)
        if k < 3 and g.chance(0.4):
            d.f("Caused by: org.postgresql.util.PSQLException: ERROR: duplicate key value violates unique constraint "
                "\"customers_tax_id_key\"\n  Detail: Key (tax_id)=(⟦tax⟧) already exists.\n", tax=g.taxid(p))
            d.t("\tat org.postgresql.core.v3.QueryExecutorImpl.receiveErrorResponse(QueryExecutorImpl.java:2733)\n"
                "\t... %d more\n" % g.rint(20, 90))
        d.t("\n")


@template("trace.node", "stack_trace", "pm2-error.log")
def tpl_trace_node(g: Gen, d: Doc, target: int) -> None:
    for i in g.loop(d, target):
        g.tick(30, 3000)
        k = g.weighted([(0, 2), (1, 1), (2, 3), (3, 3)]) if i else g.rint(0, 1)
        if k == 0:
            ip = g.ip(v6=False)
            d.f("/srv/app/node_modules/pg/lib/client.js:⟦ln⟧\n        throw err\n        ^\n\nError: connect ECONNREFUSED ⟦ip⟧:5432\n"
                "    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16) {\n  errno: -111,\n  code: 'ECONNREFUSED',\n"
                "  syscall: 'connect',\n  address: '⟦ip⟧',\n  port: 5432\n}\n\nNode.js v⟦nv⟧\n",
                ln=str(g.rint(100, 600)), ip=ip, nv=g.pick(["20.17.0", "22.9.0", "18.20.4"]))
        elif k == 1:
            p = g.person(safe=True)
            d.f("[⟦ts⟧] UnhandledPromiseRejection: TypeError: Cannot read properties of undefined (reading 'postalCode')\n"
                "    at formatAddress (/srv/app/dist/lib/address.js:⟦a⟧:⟦b⟧)\n    at Object.toInvoice (/srv/app/dist/billing/invoice.js:⟦c⟧:9)\n"
                "    at processTicksAndRejections (node:internal/process/task_queues:105:5)\n"
                "  payload: {\n    customer: {\n      name: '⟦name⟧',\n      email: '⟦email⟧',\n      address: '⟦addr⟧'\n    },\n"
                "    requestId: '⟦rid⟧'\n  }\n",
                ts=g.ts_iso(), a=str(g.rint(10, 200)), b=str(g.rint(2, 40)), c=str(g.rint(10, 300)), name=g.name(p),
                email=g.email(p), addr=g.address(), rid=g.uuid())
        elif k == 2:
            d.t("[%s] RangeError: Invalid time value\n    at Date.toISOString (<anonymous>)\n"
                "    at serializeOrder (/srv/app/dist/orders/serialize.js:%d:31)\n    at Array.map (<anonymous>)\n"
                "    at listOrders (/srv/app/dist/orders/handler.js:%d:22)\n    at async /srv/app/dist/server.js:%d:5\n"
                % (g.ts_iso(), g.rint(10, 200), g.rint(10, 200), g.rint(10, 200)))
        else:
            d.t("[%s] FetchError: request to https://api.%s/v1/rates failed, reason: socket hang up\n"
                "    at ClientRequest.<anonymous> (/srv/app/node_modules/node-fetch/lib/index.js:1501:11)\n"
                "    at ClientRequest.emit (node:events:519:28)\n  type: 'system',\n  errno: 'ECONNRESET',\n  code: 'ECONNRESET'\n"
                % (g.ts_iso(), g.pick(["exchangerate-public.org", "fx-feed.net"])))
        d.t("\n")


@template("trace.go_panic", "stack_trace", "panic.txt")
def tpl_trace_go(g: Gen, d: Doc, target: int) -> None:
    mod = "%s.dev/ledger" % g.slug
    for i in g.loop(d, target):
        g.tick(30, 3000)
        if i == 0 or g.chance(0.5):
            p = g.person()
            d.t('time=%s level=ERROR msg="payout failed" iban=' % g.ts_iso())
            d.v(g.iban(spaced=False))
            d.t(' holder="')
            d.v(g.name(p))
            d.t('" trace_id=%s\n' % g.trace_id())
        d.t("panic: runtime error: invalid memory address or nil pointer dereference\n"
            "[signal SIGSEGV: segmentation violation code=0x1 addr=0x18 pc=0x%s]\n\n" % g.hexs(6))
        for gi in range(g.rint(1, 3)):
            d.t("goroutine %d [%s]:\n" % (g.rint(1, 900), "running" if gi == 0 else g.pick(["select", "chan receive", "IO wait"])))
            for _f in range(g.rint(2, 4)):
                d.t("%s/internal/%s.(*%s).%s(0xc000%s, {0x%s, 0xc000%s})\n\t/build/internal/%s/%s.go:%d +0x%s\n"
                    % (mod, g.pick(["payout", "store", "api"]), g.pick(["Service", "Store", "Handler"]),
                       g.pick(["Send", "Commit", "ServeHTTP"]), g.hexs(6), g.hexs(6), g.hexs(6),
                       g.pick(["payout", "store", "api"]), g.pick(["service", "store", "handler"]), g.rint(20, 500), g.hexs(3)))
            d.t("created by net/http.(*Server).Serve in goroutine 1\n\t/usr/local/go/src/net/http/server.go:3285 +0x4b4\n\n")


@template("trace.ruby_rails", "stack_trace", "log/production.log")
def tpl_trace_ruby(g: Gen, d: Doc, target: int) -> None:
    for i in g.loop(d, target):
        g.tick(30, 3000)
        pii = i == 0 or g.chance(0.4)
        d.t('Started POST "/%s" for ' % ("users" if pii else "orders"))
        d.v(g.ip() if pii else "127.0.0.1")
        d.t(" at %s %s\nProcessing by %s#create as HTML\n" % (g.ts_sec(), g.tzo, "UsersController" if pii else "OrdersController"))
        if pii:
            p = g.person()
            d.f('  Parameters: {"authenticity_token"=>"[FILTERED]", "user"=>{"name"=>"⟦name⟧", "email"=>"⟦email⟧", '
                '"birthday"=>"⟦dob⟧", "password"=>"[FILTERED]"}}\n',
                name=g.name(p), email=g.email(p), dob=g.pdate("dob", "iso"))
            err = "ActiveRecord::RecordInvalid (Validation failed: Email has already been taken):"
        else:
            d.t('  Parameters: {"authenticity_token"=>"[FILTERED]", "order"=>{"sku"=>"SKU-%d", "qty"=>"%d", "coupon"=>"%s"}}\n'
                % (g.rint(100, 9999), g.rint(1, 9), g.pick(["", "WELCOME10", "SPRING26"])))
            err = "ActiveRecord::StaleObjectError (Attempted to update a stale object: Order.):"
        d.t("Completed 422 Unprocessable Entity in %dms (ActiveRecord: %.1fms | Allocations: %d)\n\n%s\n\n"
            % (g.rint(5, 900), g.r.uniform(0.5, 90), g.rint(1000, 90000), err))
        for fr in ["app/models/user.rb:%d:in `block in <class:User>'", "app/controllers/users_controller.rb:%d:in `create'",
                   "app/services/signup.rb:%d:in `call'", "activerecord (7.2.1) lib/active_record/validations.rb:%d:in `save!'",
                   "actionpack (7.2.1) lib/action_controller/metal/basic_implicit_render.rb:%d:in `send_action'"][:g.rint(3, 5)]:
            d.t("  " + fr % g.rint(5, 200) + "\n")
        d.t("\n")


@template("trace.php_fatal", "stack_trace", "php-fpm-error.log")
def tpl_trace_php(g: Gen, d: Doc, target: int) -> None:
    for i in g.loop(d, target):
        g.tick(30, 3000)
        ts = g.clock.strftime("%d-%b-%Y %H:%M:%S") + " UTC"
        if i and g.chance(0.5):
            d.t("[%s] PHP Warning:  Undefined array key \"currency\" in /var/www/html/src/Cart.php on line %d\n"
                "[%s] PHP Deprecated:  strftime() is deprecated in /var/www/html/src/Report.php on line %d\n\n"
                % (ts, g.rint(10, 300), ts, g.rint(10, 300)))
            continue
        d.f("[⟦ts⟧] PHP Fatal error:  Uncaught PDOException: SQLSTATE[HY000] [1045] Access denied for user 'shop_app'@'⟦ip⟧' "
            "(using password: YES) in /var/www/html/lib/Db.php:31\nStack trace:\n"
            "#0 /var/www/html/lib/Db.php(31): PDO->__construct('mysql:host=db.i...', 'shop_app', '⟦pw⟧')\n"
            "#1 /var/www/html/lib/Repository.php(18): Db::connect()\n#2 /var/www/html/public/index.php(⟦ln⟧): Repository->__construct()\n"
            "#3 {main}\n  thrown in /var/www/html/lib/Db.php on line 31\n",
            ts=ts, ip=g.ip(v6=False), pw=g.password(), ln=str(g.rint(5, 90)))
        if g.chance(0.3):
            p = g.person(safe=True)
            d.f("[⟦ts⟧] PHP Warning:  Undefined array key \"vat_id\" in /var/www/html/src/Invoice.php on line ⟦ln⟧, "
                "customer='⟦name⟧'\n", ts=ts, ln=str(g.rint(10, 300)), name=g.name(p))
        d.t("\n")


@template("trace.sentry_event", "stack_trace", "sentry-issue.txt")
def tpl_trace_sentry(g: Gen, d: Doc, target: int) -> None:
    for _ in g.loop(d, target):
        g.tick(300, 9000)
        p = g.person()
        d.f("Sentry Issue: ⟦proj⟧-⟦id⟧\nTypeError: Cannot read properties of undefined (reading 'iban')\n"
            "  at PaymentForm.submit (webpack://checkout/src/components/PaymentForm.tsx:⟦l1⟧:31)\n"
            "  at HTMLFormElement.<anonymous> (webpack://checkout/src/hooks/useForm.ts:⟦l2⟧:9)\n"
            "  at commitHookEffectListMount (webpack://checkout/node_modules/react-dom/cjs/react-dom.production.min.js:⟦l3⟧:12)\n\n"
            "Event ID: ⟦eid⟧\nRelease: checkout@⟦ver⟧\nEnvironment: production\nFirst seen: ⟦ts⟧\nEvents: ⟦ev⟧   Users: ⟦us⟧\n\n"
            "User\n  id: ⟦uid⟧\n  ip_address: ⟦ip⟧\n",
            proj=g.pick(["CHECKOUT", "BILLING-API", "PORTAL"]), id=g.letters(3, "0123456789ABCDEF"), l1=str(g.rint(20, 400)),
            l2=str(g.rint(10, 200)), l3=str(g.rint(10, 900)), eid=g.hexs(32), ver=g.ver(), ts=g.ts_iso(), ev=str(g.rint(1, 900)),
            us=str(g.rint(1, 300)), uid=str(g.rint(1000, 999999)), ip=g.ip())
        if g.chance(0.3):
            d.f("  email: ⟦email⟧\n  username: ⟦handle⟧\n", email=g.email(p), handle=g.handle(p))
        d.f("\nTags\n  browser: Firefox 131.0\n  os: Windows 11\n  locale: ⟦loc⟧\n  transaction: /checkout/payment\n\nBreadcrumbs\n",
            loc=g.locale())
        for _b in range(g.rint(2, 5)):
            g.tick(0, 5)
            d.t("  %s %-11s " % (g.clock.strftime("%H:%M:%S"), g.pick(["navigation", "fetch", "ui.input", "console"])))
            d.v(g.pick([["/checkout -> /checkout/payment"], ["POST /api/v1/payment-methods [400]"], ["input#iban"],
                        g.log_msg(0.3)]))
            d.t("\n")
        d.t("\nRequest\n  POST /api/v1/payment-methods\n")
        if g.chance(0.4):
            d.t("  Cookie: session=")
            d.v(g.cookie())
            d.t("; theme=dark; consent=1\n")
        if g.chance(0.3):
            d.f("  Body: {\"holder\":\"⟦name⟧\",\"iban\":\"⟦iban⟧\"}\n", name=g.name(p), iban=g.iban(spaced=False))
        else:
            d.t('  Body: {"method":"sepa_debit","mandate":"%s","amount":%d}\n' % (g.uuid(), g.rint(100, 90000)))
        d.t("\n")


# ============================================================== shell_session


def prompt(g: Gen, d: Doc, cmd: str, user=None) -> None:
    if user is None:
        d.t("$ " + cmd + "\n")
    else:
        d.v(user)
        d.t("@%s:~/src$ %s\n" % (g.pick(["laptop-07", "dev-box", "ws-114"]), cmd))


@template("sh.curl_api", "shell_session", "curl-session.txt")
def tpl_sh_curl(g: Gen, d: Doc, target: int) -> None:
    tok = g.pick([g.token(), g.jwt()])
    for i in g.loop(d, target):
        if i and not g.chance(0.15):
            if g.chance(0.4):
                prompt(g, d, 'curl -s -o /dev/null -w "%{http_code}\\n" https://api.' + g.co_domain + "/healthz")
                d.t(g.pick(["200", "200", "503"]) + "\n")
            else:
                d.t(nfill(g, g.pick(NEUTRAL["shell"])))
            continue
        k = g.rint(0, 2)
        if k == 0:
            d.t('$ curl -s -H "Authorization: Bearer ')
            d.v(tok)
            d.t('" ')
            d.v(g.api_user_url())
            d.t(" | jq .\n")
            json_obj(d, g.record(g.person()), "")
            d.t("\n")
        elif k == 1:
            d.t("$ curl -s -X PATCH ")
            d.v(g.api_user_url())
            d.t(' \\\n    -H "Authorization: Bearer ')
            d.v(tok)
            d.t('" \\\n    -H "Content-Type: application/json" \\\n    -d \'{"phone": "')
            d.v(g.phone())
            d.t('"}\'\n{"status":"ok","updated_at":"%s"}\n' % g.ts_iso())
        else:
            pw = g.password()
            d.t("$ curl -sv -u ci-bot:")
            d.v(pw)
            d.t(" ")
            d.v(g._pii("private_url", "https://artifacts.int.%s/api/storage/releases" % g.co_domain))
            d.t(" 2>&1 | grep -iE '^(> auth|< set-cookie|< HTTP)'\n> Authorization: Basic ")
            d.v(g.b64_of("ci-bot", pw))
            d.t("\n< HTTP/2 200\n< set-cookie: SESSION=")
            d.v(g.cookie())
            d.t("; Path=/; HttpOnly; Secure; SameSite=Lax\n")


SQL_NEUTRAL = [
    ("SELECT status, count(*) FROM orders GROUP BY status ORDER BY 2 DESC;", ["status", "count"],
     lambda g: [[s, str(g.rint(10, 90000))] for s in ["paid", "pending", "refunded", "failed"]]),
    ("SELECT date_trunc('day', created_at) AS day, sum(amount_cents)/100 AS revenue FROM orders GROUP BY 1 ORDER BY 1 DESC LIMIT 3;",
     ["day", "revenue"], lambda g: [["2026-%02d-%02d 00:00:00+00" % (g.rint(1, 9), g.rint(1, 28)), g.amount()] for _ in range(3)]),
    ("SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY 2 DESC LIMIT 4;", ["relname", "n_live_tup"],
     lambda g: [[t, str(g.rint(1000, 9000000))] for t in ["orders", "order_lines", "events", "customers"]]),
]


@template("sh.psql", "shell_session", "psql-session.txt")
def tpl_sh_psql(g: Gen, d: Doc, target: int) -> None:
    d.t('$ psql "postgresql://readonly:')
    d.v(g.password(urlsafe=True))
    d.t('@%s:5432/crm?sslmode=require"\npsql (16.4)\nSSL connection (protocol: TLSv1.3, cipher: TLS_AES_256_GCM_SHA384)\n'
        'Type "help" for help.\n\n' % g.int_host("db"))
    for i in g.loop(d, target):
        if i and not g.chance(0.15):
            q, cols, mk = g.pick(SQL_NEUTRAL)
            rows = mk(g)
            d.t("crm=> %s\n" % q)
        else:
            fields = g.pii_fields(g.rint(1, 2), exclude=("address", "last_location"))
            cols = ["id", "full_name"] + [g.field_key(f) for f in fields] + ["created_at"]
            rows = []
            for _r in range(g.rint(1, 3)):
                p = g.person()
                g.tick(10, 9000)
                rows.append([str(g.rint(1000, 99999)), g.name(p)] + [g.field_value(f, p) for f in fields] + [g.ts_sec()])
            d.t("crm=> SELECT %s FROM customers WHERE created_at > now() - interval '%d days' LIMIT %d;\n"
                % (", ".join(cols), g.rint(1, 30), len(rows)))
        widths = [max(len(c), *(len(vt(r[j])) for r in rows)) for j, c in enumerate(cols)]
        d.t(" " + " | ".join(c.center(w) for c, w in zip(cols, widths)) + "\n")
        d.t("-" + "-+-".join("-" * w for w in widths) + "-\n")
        for r in rows:
            table_row(d, r, widths)
        d.t("(%d rows)\n\n" % len(rows))
    d.t("crm=> \\q\n")


@template("sh.mysql", "shell_session", "mysql-session.txt")
def tpl_sh_mysql(g: Gen, d: Doc, target: int) -> None:
    d.t("$ mysql -h %s -u support -p'" % g.int_host("mysql"))
    d.v(g.password())
    d.t("' shop\nmysql: [Warning] Using a password on the command line interface can be insecure.\n"
        "Welcome to the MySQL monitor.  Commands end with ; or \\g.\nServer version: 8.0.39 MySQL Community Server - GPL\n\n")
    for i in g.loop(d, target):
        if i and not g.chance(0.15):
            q, cols, mk = g.pick(SQL_NEUTRAL[:1] + [
                ("SHOW TABLE STATUS WHERE Name IN ('orders','carts');", ["Name", "Engine", "Rows"],
                 lambda g: [["orders", "InnoDB", str(g.rint(1000, 9000000))], ["carts", "InnoDB", str(g.rint(100, 90000))]])])
            rows = mk(g)
            d.t("mysql> %s\n" % q)
        else:
            fields = g.pii_fields(g.rint(1, 2), exclude=("address",))
            cols = ["id", "name"] + [g.field_key(f) for f in fields]
            rows = []
            for _r in range(g.rint(1, 3)):
                p = g.person()
                rows.append([str(g.rint(1, 9999)), g.name(p)] + [g.field_value(f, p) for f in fields])
            d.t("mysql> SELECT %s FROM customers ORDER BY id DESC LIMIT %d;\n" % (", ".join(cols), len(rows)))
        widths = [max(len(c), *(len(vt(r[j])) for r in rows)) for j, c in enumerate(cols)]
        border = "+" + "+".join("-" * (w + 2) for w in widths) + "+\n"
        d.t(border + "| " + " | ".join(c.ljust(w) for c, w in zip(cols, widths)) + " |\n" + border)
        for r in rows:
            table_row(d, r, widths, sep=" | ", lead="| ", tail=" |")
        d.t(border + "%d rows in set (0.%02d sec)\n\n" % (len(rows), g.rint(0, 99)))
    d.t("mysql> exit\nBye\n")


@template("sh.kubectl", "shell_session", "kubectl-session.txt")
def tpl_sh_kubectl(g: Gen, d: Doc, target: int) -> None:
    ns = g.pick(TEAMS)
    for i in g.loop(d, target):
        if i and not g.chance(0.25):
            d.t(nfill(g, g.pick(NEUTRAL["shell"])) + "\n")
            continue
        k = g.rint(0, 3)
        if k == 0:
            d.t("$ kubectl -n %s get pods -o wide\nNAME                          READY   STATUS    RESTARTS   AGE    IP              NODE\n" % ns)
            for _r in range(g.rint(2, 4)):
                ip = g.ip(v6=False)
                d.t("%-29s 1/1     %-9s %-10d %-6s " % ("%s-%s-%s" % (g.pick(SERVICES), g.hexs(9), g.letters(5, "bcdfghjklmnpqrstvwxz2456789")),
                                                       g.pick(["Running", "Running", "Pending"]), g.rint(0, 4), "%dd%dh" % (g.rint(0, 30), g.rint(0, 23))))
                d.v(ip)
                d.t(" " * max(1, 16 - len(vt(ip))) + "pool-%s-%s\n" % (g.pick("abc"), g.letters(4, "abcdefghjkmnpqrstuvwxyz0123456789")))
            d.t("\n")
        elif k == 1:
            pw = g.password()
            p64 = g.b64_secret_of(pw)
            d.t("$ kubectl -n %s get secret db-credentials -o yaml\napiVersion: v1\ndata:\n  password: " % ns)
            d.v(p64)
            d.t("\n  username: YXBw\nkind: Secret\nmetadata:\n  creationTimestamp: \"%s\"\n  name: db-credentials\n"
                "  namespace: %s\n  resourceVersion: \"%d\"\n  uid: %s\ntype: Opaque\n$ echo " % (g.ts_iso()[:19] + "Z", ns, g.rint(10000, 9999999), g.uuid()))
            d.v(p64)
            d.t(" | base64 -d\n")
            d.v(pw)
            d.t("\n\n")
        elif k == 2:
            d.t("$ kubectl -n %s logs deploy/%s --tail=6\n" % (ns, g.pick(SERVICES)))
            for _r in range(6):
                g.tick(0, 10)
                d.t('ts=%s level=info msg="' % g.ts_iso())
                d.v(app_msg(g, 0.2))
                d.t('"\n')
            d.t("\n")
        else:
            d.t("$ kubectl get nodes -o wide\nNAME            STATUS   ROLES    AGE   VERSION   INTERNAL-IP\n")
            for _r in range(g.rint(2, 4)):
                d.t("pool-%s-%s   Ready    <none>   %dd   v1.30.%d   " % (g.pick("abc"), g.letters(4, "abcdefghjkmnpqrstuvwxyz0123456789"),
                                                                       g.rint(1, 200), g.rint(1, 6)))
                d.v(g.ip(v6=False))
                d.t("\n")
            d.t("\n")


GIT_SUBJECTS = ["fix(billing): handle empty VAT id", "feat(crm): add consent timestamp", "chore(deps): bump pg to 8.13.0",
                "refactor(api): split customer serializer", "fix(export): escape semicolons in CSV", "test: cover payout retries",
                "perf(orders): batch inserts in nightly import", "docs: document retry policy"]
GIT_FILES = ["src/billing/vat.py", "src/crm/consent.ts", "package-lock.json", "internal/payout/service.go",
             "migrations/0142_add_consent.sql", "docs/adr/0007-retry-policy.md", "tests/test_export.py"]


@template("sh.git_log", "shell_session", "git-log.txt")
def tpl_sh_git(g: Gen, d: Doc, target: int) -> None:
    d.t("$ git log -n 8 --stat --no-color\n")
    for i in g.loop(d, target - 300):
        g.tick(600, 90000)
        bot = i and g.chance(0.4)
        p = g.person()
        d.t("commit %s\nAuthor: " % g.sha())
        if bot:
            d.t("renovate[bot] <")
            d.v(g._pii("private_email", "29139614+renovate[bot]@users.noreply.github.com"))
            d.t(">")
        else:
            d.v(g.name(p))
            d.t(" <")
            d.v(g.email(p, "work"))
            d.t(">")
        d.t("\nDate:   %s\n\n    %s\n\n    " % (g.ts_git(), g.pick(GIT_SUBJECTS)))
        d.v(g.prose(g.rint(1, 2), 0.1))
        d.t("\n")
        if not bot and g.chance(0.15):
            q = g.person()
            d.t("\n    Co-authored-by: ")
            d.v(g.name(q))
            d.t(" <")
            d.v(g.email(q))
            d.t(">\n")
        files = g.r.sample(GIT_FILES, g.rint(2, 6))
        d.t("\n")
        ins = dels = 0
        for f in files:
            a, b = g.rint(0, 60), g.rint(0, 30)
            ins, dels = ins + a, dels + b
            d.t(" %-40s | %3d %s\n" % (f, a + b, "+" * min(a, 20) + "-" * min(b, 10)))
        d.t(" %d files changed, %d insertions(+), %d deletions(-)\n\n" % (len(files), ins, dels))
    p = g.person()
    d.t("$ git config user.email\n")
    d.v(g.email(p, "work"))
    d.t("\n$ git remote -v\n")
    if g.chance(0.5):
        tok = g.token()
        for kind in ("fetch", "push"):
            d.t("origin\thttps://oauth2:")
            d.v(tok)
            d.t("@gitlab.%s/%s/%s.git (%s)\n" % (g.co_domain, g.pick(TEAMS), g.pick(REPOS), kind))
    else:
        url = g.repo_url()
        for kind in ("fetch", "push"):
            d.t("origin\t")
            d.v(url)
            d.t(" (%s)\n" % kind)


@template("sh.ssh_admin", "shell_session", "ssh-session.txt")
def tpl_sh_ssh(g: Gen, d: Doc, target: int) -> None:
    p = g.person()
    host = g.pick(["app-01", "db-02", "worker-03"])
    ip = g.ip(v6=False)
    d.t("$ ssh ")
    d.v(g.handle(p))
    d.t("@")
    d.v(ip)
    d.t("\nLast login: %s from " % g.ts_git()[:-6])
    d.v(g.ip())
    d.t("\n")
    rooted = False
    for i in g.loop(d, target):
        k = g.weighted([("ip", 1), ("ls", 1), ("pgpass", 1), ("who", 1), ("tail", 1), ("neutral", 8)])
        if i == 0 and k == "neutral":
            k = "ip"
        if not rooted and i >= 1:
            d.v(g.handle(p))
            d.t("@%s:~$ sudo -i\n" % host)
            rooted = True
        if k == "neutral":
            d.t("root@%s:/srv/app# " % host)
            d.t(nfill(g, g.pick(NEUTRAL["shell"]))[2:])
            continue
        if rooted:
            d.t("root@%s:~# " % host)
        else:
            d.v(g.handle(p))
            d.t("@%s:~$ " % host)
        if k == "ip":
            d.t("ip -br addr && ip link show eth0\nlo               UNKNOWN        127.0.0.1/8 ::1/128\neth0             UP             ")
            d.v(ip)
            d.t("/24 ")
            d.v(g.ip(v6=True))
            d.t("/64\n2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP mode DEFAULT\n    link/ether ")
            d.v(g.mac())
            d.t(" brd ff:ff:ff:ff:ff:ff\n")
        elif k == "ls":
            d.t("ls -la /srv/app\ntotal 64\n")
            for name, perm, size in [(".", "drwxr-x---", 4096), ("..", "drwxr-xr-x", 4096), (".env", "-rw-------", g.rint(400, 3000)),
                                     ("app", "drwxr-xr-x", 4096), ("releases", "drwxr-xr-x", 4096),
                                     ("export_%s.csv" % g.clock.strftime("%Y%m%d"), "-rw-r--r--", g.rint(1000, 9000000))]:
                g.tick(-90000, -100)
                d.t("%s %2d app  app  %8d %s %2d %s %s\n" % (perm, g.rint(1, 5), size, MON_ABBR[g.clock.month - 1], g.clock.day,
                                                             g.clock.strftime("%H:%M"), name))
        elif k == "pgpass":
            d.t("cat ~/.pgpass\n%s:5432:*:app:" % g.int_host("db"))
            d.v(g.password())
            d.t("\n")
        elif k == "who":
            d.t("who\n")
            for _r in range(g.rint(1, 2)):
                q = g.pick([p, g.person()])
                d.v(g.handle(q))
                d.t("  pts/%d        %s (" % (g.rint(0, 5), g.ts_sec()[:16]))
                d.v(g.ip())
                d.t(")\n")
        else:
            d.t("tail -n 4 /var/log/app/app.log\n")
            for _r in range(4):
                g.tick(0, 30)
                d.t("%s INFO " % g.ts_space())
                d.v(app_msg(g, 0.25))
                d.t("\n")
    if rooted:
        d.t("root@%s:~# exit\nlogout\n" % host)
    d.v(g.handle(p))
    d.t("@%s:~$ exit\nlogout\nConnection to " % host)
    d.v(ip)
    d.t(" closed.\n")


@template("sh.docker_inspect", "shell_session", "docker-session.txt")
def tpl_sh_docker(g: Gen, d: Doc, target: int) -> None:
    d.t("$ docker ps --format 'table {{.ID}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}'\nCONTAINER ID   IMAGE                       STATUS          PORTS\n")
    for _r in range(g.rint(2, 4)):
        d.t("%s   %-27s Up %d hours      0.0.0.0:%d->%d/tcp\n" % (g.hexs(12), "registry.%s/%s:%s" % (g.slug, g.pick(SERVICES), g.ver()),
                                                                g.rint(1, 90), g.port(), g.port()))
    for i in g.loop(d, target):
        k = g.weighted([("env", 2), ("net", 1), ("neutral", 4)]) if i else "env"
        if k == "neutral":
            d.t("\n" + nfill(g, g.pick(NEUTRAL["shell"])))
        elif k == "env":
            pw = g.password(urlsafe=True)
            d.t("\n$ docker inspect --format '{{json .Config.Env}}' %s | jq .\n[\n" % g.pick(SERVICES))
            envs = [["DATABASE_URL=postgres://app:", pw, "@db:5432/app"], ["API_KEY=", g.token()],
                    ["TZ=" + g.tz()], ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"], ["NODE_ENV=production"],
                    ["LANG=C.UTF-8"], ["APP_VERSION=" + g.ver()], ["OTEL_SERVICE_NAME=" + g.pick(SERVICES)],
                    ["PORT=%d" % g.port()]]
            g.r.shuffle(envs)
            envs = envs[:g.rint(5, len(envs))]
            for j, e in enumerate(envs):
                d.t('  "')
                d.v(e)
                d.t('"' + ("," if j < len(envs) - 1 else "") + "\n")
            d.t("]\n")
        else:
            d.t("\n$ docker network inspect backend --format '{{json .Containers}}' | jq .\n{\n")
            n = g.rint(1, 2)
            for j in range(n):
                ip = g.ip(v6=False)
                d.t('  "%s": {\n    "Name": "%s-%d",\n    "EndpointID": "%s",\n    "MacAddress": "' % (g.hexs(64), g.pick(SERVICES), j + 1, g.hexs(64)))
                d.v(g.mac())
                d.t('",\n    "IPv4Address": "')
                d.v(ip)
                d.t('/16",\n    "IPv6Address": ""\n  }' + ("," if j < n - 1 else "") + "\n")
            d.t("}\n")


# =============================================================== data_export


@template("data.csv_customers", "data_export", "exports/customers.csv")
def tpl_csv(g: Gen, d: Doc, target: int) -> None:
    fields = g.pii_fields(g.rint(1, 2))
    named = g.chance(0.6)
    neutral_cols = ["external_ref", "created_at"] + g.r.sample([f for f in NEUTRAL_FIELDS if f not in ("external_ref", "created_at")],
                                                               g.rint(3, 6))
    sep = g.pick([",", ";"]) if g.lang != "en" else ","
    header = ["id"] + (["full_name"] if named else []) + [g.field_key(f) for f in fields] + neutral_cols
    d.t(sep.join(g.flabel(h) for h in header) + "\n")
    for _ in g.loop(d, target):
        p = g.person()
        g.tick(60, 90000)
        cells = [str(g.rint(1000, 999999))] + ([g.name(p)] if named else [])
        cells += ["" if g.chance(0.35) else g.field_value(f, p, "export") for f in fields]
        cells += [g.neutral_value(f) for f in neutral_cols]
        for j, c in enumerate(cells):
            if j:
                d.t(sep)
            csv_cell(d, c, sep)
        d.t("\n")


@template("data.csv_orders", "data_export", "exports/orders.csv")
def tpl_csv_orders(g: Gen, d: Doc, target: int) -> None:
    sep = g.pick([",", ";"]) if g.lang != "en" else ","
    d.t(sep.join(["order_id", "customer_email", "sku", "qty", "amount", "currency", "status", "channel", "created_at",
                  "shipped_at"]) + "\n")
    for _ in g.loop(d, target):
        g.tick(30, 3000)
        cells = ["ORD-%d" % g.rint(100000, 999999), g.email(g.person()) if g.chance(0.3) else "",
                 "SKU-%d" % g.rint(100, 9999), str(g.rint(1, 6)), g.amount(), g.pick(["EUR", "EUR", "GBP", "USD"]),
                 g.pick(["paid", "shipped", "refunded", "pending"]), g.pick(["web", "ios", "android", "pos"]), g.ts_iso(), ""]
        for j, c in enumerate(cells):
            if j:
                d.t(sep)
            csv_cell(d, c, sep)
        d.t("\n")


@template("data.sql_dump", "data_export", "dumps/crm.sql")
def tpl_sql(g: Gen, d: Doc, target: int) -> None:
    fields = g.pii_fields(g.rint(1, 3))
    cols = ["id", "full_name"] + [g.field_key(f) for f in fields] + ["created_at"]
    d.t("-- MySQL dump 10.13  Distrib 8.0.39, for Linux (x86_64)\n--\n-- Host: localhost    Database: crm\n"
        "-- ------------------------------------------------------\n-- Server version\t8.0.39\n\n"
        "/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;\n/*!50503 SET NAMES utf8mb4 */;\n\n"
        "DROP TABLE IF EXISTS `customers`;\nCREATE TABLE `customers` (\n")
    d.t("".join("  `%s` %s,\n" % (c, "int NOT NULL AUTO_INCREMENT" if c == "id" else "varchar(255) DEFAULT NULL") for c in cols))
    d.t("  PRIMARY KEY (`id`)\n) ENGINE=InnoDB AUTO_INCREMENT=%d DEFAULT CHARSET=utf8mb4;\n\nLOCK TABLES `customers` WRITE;\n"
        % g.rint(1000, 90000))
    n_rows = g.rint(1, 4)
    for i in range(n_rows):
        p = g.person(safe=True)
        g.tick(60, 90000)
        vals = [g.name(p)] + [g.field_value(f, p) for f in fields] + [g.ts_sec()]
        d.t("INSERT INTO `customers` VALUES (%d," % (i + 1))
        for j, v in enumerate(vals):
            lit(d, v, q="'")
            d.t("," if j < len(vals) - 1 else ");\n")
    d.t("UNLOCK TABLES;\n\nDROP TABLE IF EXISTS `order_lines`;\nCREATE TABLE `order_lines` (\n  `id` bigint NOT NULL AUTO_INCREMENT,\n"
        "  `order_id` bigint NOT NULL,\n  `sku` varchar(32) NOT NULL,\n  `qty` int NOT NULL,\n  `unit_price_cents` int NOT NULL,\n"
        "  PRIMARY KEY (`id`)\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n\nLOCK TABLES `order_lines` WRITE;\nINSERT INTO `order_lines` VALUES ")
    for i in g.loop(d, target - 80):
        d.t("%s(%d,%d,'SKU-%d',%d,%d)" % ("," if i else "", i + 1, g.rint(100000, 999999), g.rint(100, 9999), g.rint(1, 9),
                                        g.rint(100, 99999)))
    d.t(";\nUNLOCK TABLES;\n\n-- Dump completed on %s\n" % g.ts_sec())


@template("data.json_api_page", "data_export", "responses/users-page.json")
def tpl_json_page(g: Gen, d: Doc, target: int) -> None:
    page = g.rint(1, 40)
    d.t('{\n  "data": [\n')
    for i in g.loop(d, target - 220):
        if i:
            d.t(",\n")
        d.t("    ")
        rec = g.record(g.person(), k=g.rint(0, 2), n_neutral=g.rint(3, 6))
        rec.append(("stats", None))
        d.t("{\n")
        for j, (k, v) in enumerate(rec):
            d.t('      "%s": ' % k)
            if k == "stats":
                d.t('{"orders": %d, "returns": %d, "avg_basket": %s, "last_order_id": "%s"}'
                    % (g.rint(0, 90), g.rint(0, 9), g.amount(), g.uuid()))
            else:
                lit(d, v)
            d.t(",\n" if j < len(rec) - 1 else "\n")
        d.t("    }")
    d.t('\n  ],\n  "meta": {\n    "page": %d,\n    "per_page": 25,\n    "total": %d,\n    "request_id": "%s",\n'
        '    "generated_at": "%s"\n  },\n  "links": {\n    "self": "/v2/users?page=%d",\n    "next": "/v2/users?page=%d"\n  }\n}\n'
        % (page, g.rint(100, 9000), g.req_id(), g.ts_iso(), page, page + 1))


@template("data.xml_payments", "data_export", "exports/sepa-batch.xml")
def tpl_xml(g: Gen, d: Doc, target: int) -> None:
    d.f('<?xml version="1.0" encoding="UTF-8"?>\n<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">\n'
        '  <CstmrCdtTrfInitn>\n    <GrpHdr>\n      <MsgId>⟦mid⟧</MsgId>\n      <CreDtTm>⟦ts⟧</CreDtTm>\n'
        '      <InitgPty><Nm>⟦co⟧</Nm></InitgPty>\n    </GrpHdr>\n    <PmtInf>\n      <PmtInfId>⟦pid⟧</PmtInfId>\n'
        '      <PmtMtd>TRF</PmtMtd>\n      <Dbtr><Nm>⟦co⟧</Nm></Dbtr>\n      <DbtrAcct><Id><IBAN>⟦iban⟧</IBAN></Id></DbtrAcct>\n'
        '      <DbtrAgt><FinInstnId><BICFI>⟦bic⟧</BICFI></FinInstnId></DbtrAgt>\n      <ChrgBr>SLEV</ChrgBr>\n',
        mid="MSG-%s" % g.hexs(12).upper(), ts=g.ts_iso()[:19], co=g.co_name, pid="PMT-%d" % g.rint(1000, 99999),
        iban=g.iban(spaced=False), bic=g.letters(4) + g.pick(["DE", "FR", "IT", "ES", "GB"]) + g.letters(2) + "XXX")
    for _ in g.loop(d, target - 80):
        p = g.person()
        d.f("      <CdtTrfTxInf>\n        <PmtId>\n          <InstrId>⟦ins⟧</InstrId>\n          <EndToEndId>⟦e2e⟧</EndToEndId>\n"
            "        </PmtId>\n        <PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl></PmtTpInf>\n"
            "        <Amt><InstdAmt Ccy=\"EUR\">⟦amt⟧</InstdAmt></Amt>\n        <Cdtr>\n          <Nm>⟦name⟧</Nm>\n        </Cdtr>\n"
            "        <CdtrAcct><Id><IBAN>⟦iban⟧</IBAN></Id></CdtrAcct>\n        <Purp><Cd>⟦purp⟧</Cd></Purp>\n"
            "        <RmtInf><Ustrd>⟦rem⟧ ⟦inv⟧</Ustrd></RmtInf>\n      </CdtTrfTxInf>\n",
            ins="INS-%s" % g.hexs(8).upper(), e2e="E2E-%s" % g.hexs(10).upper(), amt=g.amount(), name=g.name(p),
            iban=g.iban(country=g.pick(["DE", "FR", "IT", "ES", "GB"]), spaced=False), purp=g.pick(["SUPP", "SALA", "REFU", "TRAD"]),
            rem=g.tx("Refund", "Erstattung", "Remboursement", "Rimborso", "Reembolso"), inv="INV-%d" % g.rint(10000, 99999))
    d.t("    </PmtInf>\n  </CstmrCdtTrfInitn>\n</Document>\n")


@template("data.ndjson_events", "data_export", "exports/events.ndjson")
def tpl_ndjson(g: Gen, d: Doc, target: int) -> None:
    for _ in g.loop(d, target):
        g.tick(1, 600)
        p = g.person()
        d.t('{"event":"%s","ts":"%s","session":"%s","device":{"model":"%s","os":"%s","screen":"%dx%d","network":"%s"'
            % (g.pick(["app_open", "checkout_started", "location_update", "login", "push_opened", "screen_view"]), g.ts_iso(), g.uuid(),
               g.pick(["Pixel 8", "iPhone 15", "Galaxy S24", "Fairphone 5"]), g.pick(["Android 15", "iOS 18.0", "Android 14"]),
               g.pick([1080, 1170, 1440]), g.pick([2400, 2532, 3120]), g.pick(["wifi", "5g", "4g"])))
        if g.chance(0.2):
            d.t(',"mac":"')
            d.v(g.mac())
            d.t('"')
        d.t("}")
        if g.chance(0.3):
            d.t(',"ip":"')
            d.v(g.ip())
            d.t('"')
        if g.chance(0.2):
            d.t(',"geo":"')
            d.v(g.geo())
            d.t('"')
        d.t(',"user":{"id":%d' % g.rint(1000, 999999))
        if g.chance(0.12):
            d.t(',"email":"')
            d.v(g.email(p))
            d.t('"')
        d.t('},"app_version":"%s","build":%d,"locale":"%s","experiments":["%s"]}\n'
            % (g.ver(), g.rint(1000, 9999), g.locale(), g.pick(["new-onboarding:b", "checkout-v3:a", "none"])))


@template("data.tsv_hr", "data_export", "hr/roster.tsv")
def tpl_tsv(g: Gen, d: Doc, target: int) -> None:
    fields = ([g.pick(["birth_date", "hire_date"])] if g.chance(0.5) else []) + g.weighted_sample(
        [("tax_id", 3), ("national_id", 3), ("iban", 3), ("phone", 2), ("health_insurance_no", 2), ("license_plate", 1),
         ("driver_license", 1)], g.rint(0, 1))
    header = (["employee_no", "full_name"] + [g.field_key(f) for f in fields]
              + ["department", "cost_center", "grade", "fte", "location", "contract", "weekly_hours", "shift", "manager_no",
                 "badge_id", "vacation_days", "review_score"])
    d.t("\t".join(g.flabel(h) for h in header) + "\n")
    for _ in g.loop(d, target):
        p = g.person()
        cells = ["E%05d" % g.rint(1, 99999), g.name(p, g.pick(["full", "rev"]))]
        cells += [g.field_value(f, p, "export") for f in fields]
        cells += [g.pick(TEAMS), "CC-%d" % g.rint(1000, 9999), g.pick(["L2", "L3", "L4", "M1"]), g.pick(["1.0", "0.8", "0.5"]),
                  g.pick(["HQ", "REMOTE", "PLANT-2", "STORE-14"]), g.pick(["permanent", "fixed-term", "apprentice"]),
                  str(g.pick([40, 38, 32, 20])), g.pick(["early", "late", "day", "night"]), "E%05d" % g.rint(1, 99999),
                  "B-%s" % g.hexs(8).upper(), str(g.rint(0, 30)), "%.1f" % g.r.uniform(1, 5)]
        for j, c in enumerate(cells):
            if j:
                d.t("\t")
            d.v(c)
        d.t("\n")


@template("data.ldif", "data_export", "exports/people.ldif")
def tpl_ldif(g: Gen, d: Doc, target: int) -> None:
    dc = g.slug.split("-")[0]
    d.t("version: 1\n\n# %s\n" % g.code_comment())
    for _ in g.loop(d, target):
        if g.chance(0.55):
            grp = g.pick(TEAMS)
            d.t("dn: cn=%s,ou=groups,dc=%s,dc=local\nobjectClass: groupOfNames\ncn: %s\ndescription: %s\n"
                "entryUUID: %s\ncreateTimestamp: %s\n\n" % (grp, dc, grp, g.neutral(), g.uuid(), g.clock.strftime("%Y%m%d%H%M%SZ")))
            continue
        p = g.person()
        h = g.handle(p)
        d.t("dn: uid=")
        d.v(h)
        d.t(",ou=people,dc=%s,dc=local\nobjectClass: inetOrgPerson\nobjectClass: posixAccount\nobjectClass: top\nuid: " % dc)
        d.v(h)
        d.t("\ncn: ")
        d.v(g.name(p))
        d.t("\nmail: ")
        d.v(g.email(p, "work"))
        if g.chance(0.4):
            d.t("\ntelephoneNumber: ")
            d.v(g.phone())
        if g.chance(0.2):
            d.t("\npostalAddress: ")
            d.v(g.address(sep=" $ "))
        d.t("\nuidNumber: %d\ngidNumber: %d\nloginShell: /bin/bash\nmemberOf: cn=%s,ou=groups,dc=%s,dc=local\n"
            "entryUUID: %s\ncreateTimestamp: %s\n\n" % (g.rint(1000, 60000), g.rint(1000, 2000), g.pick(TEAMS), dc, g.uuid(),
                                                        g.clock.strftime("%Y%m%d%H%M%SZ")))


# ================================================================== markdown


@template("md.readme", "markdown", "README.md")
def tpl_readme(g: Gen, d: Doc, target: int) -> None:
    prod = g.product()
    d.t("# %s\n\n" % prod)
    d.v(g.prose(2, 0.1))
    d.f("\n\n## ⟦h⟧\n\n```bash\ngit clone ⟦repo⟧\ncp .env.example .env   # API_KEY=<YOUR_API_KEY>, DB_PASSWORD=${DB_PASSWORD}\nmake dev\n```\n\n",
        h=g.tx("Setup", "Einrichtung", "Installation", "Installazione", "Instalación"), repo=g.repo_url())
    d.f("## ⟦h⟧\n\n| Variable | Default | ⟦desc⟧ |\n|---|---|---|\n| `DATABASE_URL` | `postgres://app:${DB_PASSWORD}@localhost:5432/app` | ⟦d1⟧ |\n"
        "| `API_KEY` | `<YOUR_API_KEY>` | ⟦d2⟧ |\n| `PORT` | `8080` | HTTP |\n| `TZ` | `⟦tz⟧` | ⟦d3⟧ |\n\n",
        h=g.tx("Configuration", "Konfiguration", "Configuration", "Configurazione", "Configuración"),
        desc=g.tx("Description", "Beschreibung", "Description", "Descrizione", "Descripción"),
        d1=g.tx("Primary database", "Hauptdatenbank", "Base principale", "Database principale", "Base de datos principal"),
        d2=g.tx("Partner API key", "API-Schlüssel des Partners", "Clé API du partenaire", "Chiave API del partner", "Clave API del socio"),
        tz=g.tz(), d3=g.tx("Time zone", "Zeitzone", "Fuseau horaire", "Fuso orario", "Zona horaria"))
    if g.chance(0.5):
        d.f("## Staging\n\n⟦s1⟧ ⟦url⟧. ⟦s2⟧ `qa-team` / `⟦pw⟧`.\n\n",
            s1=g.tx("Staging runs at", "Staging läuft unter", "La préprod tourne sur", "Lo staging gira su", "Preproducción está en"),
            url=g.purl(), s2=g.tx("Shared QA login:", "Gemeinsamer QA-Login:", "Compte QA partagé :", "Login QA condiviso:", "Acceso QA compartido:"),
            pw=g.password())
    d.t("## %s\n\n" % g.tx("Maintainers", "Ansprechpersonen", "Mainteneurs", "Manutentori", "Responsables"))
    for _r in range(g.rint(1, 2)):
        p = g.person()
        d.t("- ")
        d.v(g.name(p))
        d.t(" — @")
        d.v(g.handle(p))
        d.t("\n")
    for _ in g.loop(d, target - 200, min_iter=0):
        if g.chance(0.8):
            neutral_md(g, d)
        else:
            d.t("\n## %s\n\n" % g.pick([g.tx("Troubleshooting", "Fehlersuche", "Dépannage", "Risoluzione dei problemi", "Resolución de problemas"),
                                        "FAQ", g.tx("Notes", "Hinweise", "Remarques", "Note", "Notas")]))
            d.v(g.prose(g.rint(2, 4), 0.15))
            d.t("\n")
    d.t("\n## Links\n\n- %s\n- %s\n" % (g.pub_url("ops"), g.pub_url()))


@template("md.incident_report", "markdown", "docs/incidents/postmortem.md")
def tpl_incident(g: Gen, d: Doc, target: int) -> None:
    authors = [g.person() for _ in range(2)]
    d.t("# %s: %s\n\n**%s:** " % (g.tx("Postmortem", "Postmortem", "Post-mortem", "Postmortem", "Postmortem"),
                                 g.tx("payment webhooks delayed", "Verzögerte Zahlungs-Webhooks", "webhooks de paiement retardés",
                                      "webhook di pagamento in ritardo", "webhooks de pago retrasados"),
                                 g.tx("Authors", "Autoren", "Auteurs", "Autori", "Autores")))
    d.v(g.name(authors[0]))
    d.t(", ")
    d.v(g.name(authors[1]))
    d.t("  \n**Status:** %s  \n**Severity:** SEV-%d  \n**Incident ID:** INC-%d\n\n## %s\n\n" % (
        g.tx("Resolved", "Behoben", "Résolu", "Risolto", "Resuelto"), g.rint(1, 3), g.rint(100, 9999),
        g.tx("Summary", "Zusammenfassung", "Résumé", "Sintesi", "Resumen")))
    d.v(g.prose(3, 0.1))
    d.t("\n\n## %s (UTC)\n\n| %s | %s |\n|---|---|\n" % (g.tx("Timeline", "Zeitleiste", "Chronologie", "Cronologia", "Cronología"),
                                                     g.tx("Time", "Zeit", "Heure", "Ora", "Hora"),
                                                     g.tx("Event", "Ereignis", "Événement", "Evento", "Evento")))
    for _r in range(g.rint(3, 7)):
        g.tick(60, 900)
        d.t("| %s | " % g.hhmm())
        d.v(g.pick([[g.neutral()], [g.neutral()], [nfill(g, g.pick(NEUTRAL["framework_log"]))],
                    ["Alert fired on ", g.ip(v6=False), " (p95 > 2s)"]]))
        d.t(" |\n")
    for _ in g.loop(d, target - 250, min_iter=0):
        if g.chance(0.6):
            neutral_md(g, d)
            continue
        d.t("\n## %s\n\n" % g.pick([g.tx("Impact", "Auswirkung", "Impact", "Impatto", "Impacto"),
                                    g.tx("Root cause", "Ursache", "Cause racine", "Causa principale", "Causa raíz"),
                                    g.tx("Customer reports", "Kundenmeldungen", "Signalements clients", "Segnalazioni clienti",
                                         "Avisos de clientes")]))
        d.v(g.prose(g.rint(2, 5), 0.15))
        d.t("\n")
    d.t("\n## %s\n\n" % g.tx("Action items", "Maßnahmen", "Actions", "Azioni", "Acciones"))
    for _r in range(g.rint(1, 3)):
        d.t("- [ ] ")
        d.v(g.neutral())
        d.t(" — @")
        d.v(g.handle(g.pick(authors)))
        d.t(" (Sprint %d)\n" % g.rint(30, 60))


@template("md.meeting_notes", "markdown", "docs/meetings/weekly-sync.md")
def tpl_meeting(g: Gen, d: Doc, target: int) -> None:
    people = [g.person() for _ in range(g.rint(2, 4))]
    d.t("# %s — %s %d\n\n**%s:** " % (g.tx("Weekly sync", "Wöchentlicher Sync", "Point hebdo", "Sync settimanale", "Reunión semanal"),
                                     g.tx("Week", "KW", "Semaine", "Settimana", "Semana"), g.rint(1, 52),
                                     g.tx("Attendees", "Teilnehmende", "Participants", "Partecipanti", "Asistentes")))
    for j, p in enumerate(people):
        d.v(g.name(p))
        d.t(", " if j < len(people) - 1 else "\n")
    d.t("\n## %s\n\n" % g.tx("Updates", "Updates", "Avancement", "Aggiornamenti", "Novedades"))
    for i in g.loop(d, target - 250):
        if i and g.chance(0.5):
            neutral_md(g, d)
            continue
        d.t("- **%s**: " % g.pick(TEAMS))
        d.v(g.pii_sentence() if g.chance(0.12) else [g.neutral() + " " + g.neutral()])
        d.t("\n")
    d.t("\n## %s\n\n" % g.tx("Absences", "Abwesenheiten", "Absences", "Assenze", "Ausencias"))
    p = g.pick(people)
    d1, d2 = g.pdate_pair("leave", "prose")
    d.t("- ")
    d.v(g.name(p, "given"))
    d.t(": ")
    d.v(d1)
    d.t(" – ")
    d.v(d2)
    d.t("\n\n## %s\n\n- [ ] %s\n- [ ] %s\n" % (g.tx("Action items", "Aufgaben", "Actions", "Azioni", "Tareas"), g.neutral(), g.neutral()))


@template("md.support_ticket", "markdown", "support/ticket.md")
def tpl_ticket(g: Gen, d: Doc, target: int) -> None:
    p = g.person()
    rows = [(g.tx("Customer", "Kunde", "Client", "Cliente", "Cliente"), g.name(p)),
            ("E-Mail", g.email(p, "personal")),
            (g.tx("Customer no.", "Kundennr.", "N° client", "N. cliente", "N.º cliente"), "K-%d" % g.rint(10000, 999999)),
            (g.tx("Priority", "Priorität", "Priorité", "Priorità", "Prioridad"), "P%d" % g.rint(1, 4)),
            (g.tx("Product", "Produkt", "Produit", "Prodotto", "Producto"), g.product()),
            ("Plan", g.pick(["basic", "pro", "enterprise"])),
            (g.tx("Created", "Erstellt", "Créé", "Creato", "Creado"), g.ts_sec()),
            ("SLA", "%dh" % g.pick([4, 8, 24, 48]))]
    d.t("## Ticket #%d — %s\n\n| | |\n|---|---|\n" % (g.rint(10000, 99999), g.tx(
        "Refund not received", "Erstattung nicht erhalten", "Remboursement non reçu", "Rimborso non ricevuto", "Reembolso no recibido")))
    for k, v in rows:
        d.t("| %s | " % k)
        d.v(v)
        d.t(" |\n")
    d.t("\n### %s\n\n> " % g.tx("Description", "Beschreibung", "Description", "Descrizione", "Descripción"))
    d.v(g.prose(g.rint(2, 4), 0.15))
    d.t("\n\n### %s\n\n" % g.tx("Internal notes", "Interne Notizen", "Notes internes", "Note interne", "Notas internas"))
    for _ in g.loop(d, target):
        g.tick(300, 20000)
        d.t("- %s **%s**: " % (g.ts_sec()[:16], g.pick(["L1", "L2", "billing", "tech"])))
        d.v(g.pii_sentence() if g.chance(0.12) else [g.neutral() + " " + g.neutral()])
        d.t("\n")


@template("md.changelog", "markdown", "CHANGELOG.md")
def tpl_changelog(g: Gen, d: Doc, target: int) -> None:
    org, repo = g.slug, g.product().lower() + g.pick(["", "-sdk", "-cli", "-js"])
    d.t("# Changelog\n\nAll notable changes to this project are documented in this file. The format is based on "
        "[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to "
        "[Semantic Versioning](https://semver.org/).\n")
    major, minor, patch = g.rint(1, 5), g.rint(0, 20), g.rint(3, 12)
    for i in g.loop(d, target):
        g.tick(-3000000, -86400)
        d.t("\n## [%d.%d.%d] - %s\n" % (major, minor, patch, g.clock.strftime("%Y-%m-%d")))
        for section in g.r.sample(["Added", "Fixed", "Changed", "Security"], g.rint(1, 3)):
            d.t("\n### %s\n\n" % section)
            for _r in range(g.rint(1, 3)):
                pr = g.rint(100, 4000)
                d.t("- %s ([#%d](https://github.com/%s/%s/pull/%d))" % (g.pick(CHANGELOG_ITEMS[g.lang]), pr, org, repo, pr))
                if (i == 0 and _r == 0) or g.chance(0.2):
                    d.t(" — @")
                    d.v(g.handle(g.person()))
                elif g.chance(0.1):
                    d.t(g.tx(", reported by ", ", gemeldet von ", ", signalé par ", ", segnalato da ", ", reportado por "))
                    d.v(g.name(g.person()))
                d.t("\n")
            if section == "Security" and g.chance(0.3):
                d.t(g.tx("- Rotated the staging deploy key that was committed by mistake (`", "- Versehentlich eingecheckten Staging-Deploy-Key rotiert (`",
                         "- Rotation de la clé de déploiement préprod commitée par erreur (`", "- Ruotata la chiave di deploy di staging committata per errore (`",
                         "- Rotada la clave de despliegue de preproducción subida por error (`"))
                d.v(g.token())
                d.t("`)\n")
        patch -= 1
        if patch < 0:
            minor, patch = max(0, minor - 1), g.rint(3, 9)


@template("md.onboarding", "markdown", "docs/onboarding/new-hire.md")
def tpl_onboarding(g: Gen, d: Doc, target: int) -> None:
    p, mgr, buddy = g.person(), g.person(), g.person()
    d.t("# Onboarding: ")
    d.v(g.name(p))
    rows = [(g.tx("Start date", "Startdatum", "Date d'arrivée", "Data di inizio", "Fecha de incorporación"), g.pdate("hire", "prose")),
            ("Team", g.pick(TEAMS)),
            (g.tx("Manager", "Führungskraft", "Manager", "Responsabile", "Responsable"), [g.name(mgr), " (", g.email(mgr, "work"), ")"]),
            ("Buddy", g.name(buddy)),
            (g.tx("Work phone", "Diensthandy", "Téléphone pro", "Telefono aziendale", "Teléfono de empresa"), g.phone())]
    d.t("\n\n")
    for k, v in rows:
        d.t("- **%s:** " % k)
        d.v(v)
        d.t("\n")
    d.t("\n## %s\n\n| System | Login | %s |\n|---|---|---|\n| VPN | " % (g.tx("Accounts", "Zugänge", "Comptes", "Account", "Cuentas"),
                                                                    g.tx("Initial password", "Initialpasswort", "Mot de passe initial",
                                                                         "Password iniziale", "Contraseña inicial")))
    d.v(g.handle(p))
    d.t(" | `")
    d.v(g.password())
    d.t("` |\n| GitLab | SSO | SSO |\n| Jira | SSO | SSO |\n\n## Hardware\n\n- MacBook Pro 14\", serial C02%s, Wi-Fi MAC "
        % g.letters(7, string.ascii_uppercase + string.digits))
    d.v(g.mac())
    d.t("\n")
    if g.chance(0.3):
        d.t("- %s: " % g.tx("Company car", "Dienstwagen", "Véhicule de service", "Auto aziendale", "Coche de empresa"))
        d.v(g.plate())
        d.t("\n")
    d.t("\n## Checklist\n\n")
    for _ in g.loop(d, target):
        if g.chance(0.6):
            neutral_md(g, d)
            continue
        d.t("- [%s] " % g.pick(["x", " "]))
        d.t(g.neutral())
        d.t("\n")


# =================================================================== message

GREET = ("Hi ⟦g⟧,", "Hallo ⟦g⟧,", "Bonjour ⟦g⟧,", "Ciao ⟦g⟧,", "Hola ⟦g⟧,")
SIGNOFF = ("Best regards,", "Viele Grüße", "Cordialement,", "Cordiali saluti,", "Un saludo,")
SUBJECTS = {
    "en": ["Re: invoice correction", "Access to the staging environment", "Contract renewal", "Data export request", "Your refund"],
    "de": ["AW: Rechnungskorrektur", "Zugang zur Staging-Umgebung", "Vertragsverlängerung", "Anfrage Datenauskunft", "Ihre Erstattung"],
    "fr": ["RE: correction de facture", "Accès à la préprod", "Renouvellement du contrat", "Demande d'export de données", "Votre remboursement"],
    "it": ["R: correzione fattura", "Accesso all'ambiente di staging", "Rinnovo del contratto", "Richiesta export dati", "Il suo rimborso"],
    "es": ["RE: corrección de factura", "Acceso al entorno de preproducción", "Renovación del contrato", "Solicitud de exportación de datos", "Su reembolso"],
}


def signature(g: Gen, d: Doc, p: Person) -> None:
    d.t(g.tx(*SIGNOFF) + "\n")
    d.v(g.name(p))
    d.t("\n%s | %s\n" % (g.pick(["Customer Success", "Platform Engineering", "Finance", "Head of Operations", "Backoffice"]), g.co_name))
    if g.chance(0.4):
        d.t(g.pick(["Tel. ", "T: ", "Phone: ", "Mob. "]))
        d.v(g.phone())
        d.t("\n")
    if g.chance(0.3):
        d.v(g.address(multiline=True))
        d.t("\n")
    d.t("%s\n" % g.co_homepage())


def mail_headers(g: Gen, d: Doc, sender: Person, rcpt: Person, subject: str):
    """Write RFC 5322 headers; returns the recipient address that was used."""
    d.t("From: ")
    d.v(g.name(sender))
    d.t(" <")
    d.v(g.email(sender, "work"))
    d.t(">\nTo: ")
    rcpt_email = g.email(rcpt)
    if g.chance(0.5):
        d.v(g.name(rcpt))
        d.t(" <")
        d.v(rcpt_email)
        d.t(">\n")
    else:
        d.v(rcpt_email)
        d.t("\n")
    if g.chance(0.2):
        d.t("Cc: ")
        d.v(g.mailbox())
        d.t("\n")
    d.t("Subject: %s\nDate: %s\nMessage-ID: <%s@mail.%s>\n\n" % (subject, g.ts_rfc2822(), g.hexs(24), g.co_domain))
    return rcpt_email


@template("msg.email_plain", "message", "mail.eml")
def tpl_email(g: Gen, d: Doc, target: int) -> None:
    s, r = g.person(), g.person()
    mail_headers(g, d, s, r, g.pick(SUBJECTS[g.lang]))
    d.f(g.tx(*GREET) + "\n\n", g=g.name(r, "given"))
    for _ in g.loop(d, target - 200):
        d.v(g.prose(g.rint(3, 6), 0.08))
        d.t("\n\n")
    signature(g, d, s)


@template("msg.chat_transcript", "message", "chat-export.txt")
def tpl_chat(g: Gen, d: Doc, target: int) -> None:
    people = [g.person() for _ in range(g.rint(2, 4))]
    d.t("#%s — %s\n" % (g.pick(["ops", "payments-dev", "incident-%d" % g.rint(100, 999), "support-escalations"]),
                         g.clock.strftime("%Y-%m-%d")))
    for _ in g.loop(d, target):
        g.tick(10, 400)
        d.t("[%s] " % g.hhmm())
        r = g.r.random()
        if r < 0.45:
            d.t(g.pick(BOTS) + ": " + nfill(g, g.pick(NEUTRAL["bot"])) + "\n")
            continue
        d.v(g.handle(g.pick(people)))
        d.t(": ")
        if r < 0.53:
            d.v(g.pii_sentence())
        elif r < 0.8:
            d.t(g.neutral() + " " + g.neutral())
        elif r < 0.86:
            d.t(g.pick(CHAT_SHORT[g.lang]))
        elif r < 0.9:
            d.t("```\n" + nfill(g, g.pick(NEUTRAL["shell"])) + "```")
        elif r < 0.95:
            d.t(g.tx("here is the key, delete after use:", "hier der Key, danach löschen:", "voici la clé, à supprimer après :",
                     "ecco la chiave, cancellala dopo:", "aquí la clave, borradla después:") + "\n```\n")
            d.v(g.pick([g.pem(small=True), g.secret_any()]))
            d.t("\n```")
        else:
            d.t(nfill(g, "```\n$ kubectl -n ⟦team⟧ get pods\n⟦svc⟧-⟦hexa⟧-x2k4p   1/1   Running   0   ⟦q⟧h\n```"))
        d.t("\n")


@template("msg.email_reply_quoted", "message", "reply.eml")
def tpl_reply(g: Gen, d: Doc, target: int) -> None:
    s, r = g.person(), g.person()
    s_email = mail_headers(g, d, r, s, "Re: " + g.pick(SUBJECTS[g.lang]))
    d.f(g.tx(*GREET) + "\n\n", g=g.name(s, "given"))
    d.v(g.prose(g.rint(3, 5), 0.08))
    d.t("\n\n")
    signature(g, d, r)
    g.tick(-90000, -600)
    d.t("\n")
    d.f(g.tx("On ⟦dt⟧, ⟦n⟧ <⟦e⟧> wrote:", "Am ⟦dt⟧ schrieb ⟦n⟧ <⟦e⟧>:", "Le ⟦dt⟧, ⟦n⟧ <⟦e⟧> a écrit :",
             "Il ⟦dt⟧ ⟦n⟧ <⟦e⟧> ha scritto:", "El ⟦dt⟧, ⟦n⟧ <⟦e⟧> escribió:") + "\n",
        dt=g.ts_rfc2822()[:-6], n=g.name(s), e=s_email)
    depth = 1
    for _ in g.loop(d, target):
        sent = g.prose(g.rint(3, 5), 0.08)
        d.t("> " * depth)
        d.v(sent)
        d.t("\n" + "> " * depth + "\n")
        if g.chance(0.2) and depth < 3:
            depth += 1


@template("msg.raw_email_headers", "message", "raw-message.eml")
def tpl_raw_email(g: Gen, d: Doc, target: int) -> None:
    s, r = g.person(), g.person()
    other = g.pick(COMPANIES[g.pick(LANGS)])[1]
    d.t("Return-Path: <")
    d.v(g.email(s, "work"))
    d.t(">\nReceived: from mail-out.%s (mail-out.%s [" % (g.co_domain, g.co_domain))
    d.v(g.ip(v6=False))
    d.t("])\n        by mx1.%s (Postfix) with ESMTPS id %s\n        for <" % (other, g.letters(10, "0123456789ABCDEF")))
    d.v(g.email(r))
    d.t(">; %s\nDKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; d=%s; s=sel%d;\n        h=from:to:subject:date:message-id;\n"
        "        bh=%s;\n        b=%s\n" % (g.ts_rfc2822(), g.co_domain, g.rint(1, 3), base64.b64encode(g.rbytes(32)).decode(),
                                          "\n          ".join(base64.b64encode(g.rbytes(128)).decode()[i:i + 60] for i in range(0, 172, 60))))
    d.t("Received: from localhost (localhost [127.0.0.1])\n        by mx1.%s (Postfix) with ESMTP id %s;\n        %s\n"
        % (other, g.letters(10, "0123456789ABCDEF"), g.ts_rfc2822()))
    d.t("ARC-Seal: i=1; a=rsa-sha256; t=%d; cv=none; d=%s; s=arc-2026;\n        b=%s\n"
        % (g.epoch(), other, "\n          ".join(base64.b64encode(g.rbytes(128)).decode()[i:i + 60] for i in range(0, 172, 60))))
    d.t("Authentication-Results: mx1.%s; spf=pass smtp.mailfrom=%s; dkim=pass header.d=%s; dmarc=pass\n"
        "X-Spam-Status: No, score=-%.1f required=5.0 tests=BAYES_00,DKIM_SIGNED,DKIM_VALID\n"
        % (other, g.co_domain, g.co_domain, g.r.uniform(0.1, 3)))
    mail_headers(g, d, s, r, g.pick(SUBJECTS[g.lang]))
    d.t("MIME-Version: 1.0\nContent-Type: text/plain; charset=\"UTF-8\"\nContent-Transfer-Encoding: 8bit\n\n")
    d.f(g.tx(*GREET) + "\n\n", g=g.name(r, "given"))
    for _ in g.loop(d, target - 150):
        d.v(g.prose(g.rint(3, 6), 0.08))
        d.t("\n\n")
    signature(g, d, s)


@template("msg.whatsapp_export", "message", "WhatsApp Chat.txt")
def tpl_whatsapp(g: Gen, d: Doc, target: int) -> None:
    people = [g.person() for _ in range(2)]
    names = [g.name(people[0]), g.name(people[1], g.pick(["given", "full"]))]
    us = g.country == "US"
    d.t(g.tx("Messages and calls are end-to-end encrypted. No one outside of this chat can read or listen to them.",
             "Nachrichten und Anrufe sind Ende-zu-Ende-verschlüsselt. Niemand außerhalb dieses Chats kann sie lesen oder anhören.",
             "Les messages et les appels sont chiffrés de bout en bout. Personne en dehors de cette discussion ne peut les lire ou les écouter.",
             "I messaggi e le chiamate sono crittografati end-to-end. Nessuno al di fuori di questa chat può leggerli o ascoltarli.",
             "Los mensajes y las llamadas están cifrados de extremo a extremo. Nadie fuera de este chat puede leerlos ni escucharlos.") + "\n")
    for _ in g.loop(d, target):
        g.tick(30, 4000)
        c = g.clock
        stamp = ("%d/%d/%02d, %d:%02d %s" % (c.month, c.day, c.year % 100, (c.hour % 12) or 12, c.minute, "AM" if c.hour < 12 else "PM")
                 if us else "%02d/%02d/%d, %s" % (c.day, c.month, c.year, c.strftime("%H:%M")))
        d.t(stamp + " - ")
        d.v(names[g.rint(0, 1)])
        d.t(": ")
        r = g.r.random()
        if r < 0.12:
            d.v(g.pii_sentence())
        elif r < 0.16:
            d.t(g.tx("Location: ", "Standort: ", "Position : ", "Posizione: ", "Ubicación: "))
            d.v(g.geo(prose=True))
        elif r < 0.4:
            d.t(g.pick(CHAT_SHORT[g.lang]))
        elif r < 0.45:
            d.t("<Media omitted>")
        else:
            d.t(" ".join(g.neutral() for _ in range(g.rint(2, 4))))
            for _k in range(g.pick([0, 0, 1, 2])):
                d.t("\n" + g.neutral())
        d.t("\n")


@template("msg.support_livechat", "message", "livechat-transcript.txt")
def tpl_livechat(g: Gen, d: Doc, target: int) -> None:
    cust, agent = g.person(), g.person()
    cust_label = g.tx("Customer", "Kunde", "Client", "Cliente", "Cliente")
    d.t("=== Live chat #%d — %s ===\n" % (g.rint(100000, 999999), g.co_name))
    d.t("[%s] " % g.clock.strftime("%H:%M:%S"))
    d.v(g.name(agent, "given"))
    d.t(" %s\n" % g.tx("joined the chat", "ist dem Chat beigetreten", "a rejoint la discussion", "è entrato nella chat", "se ha unido al chat"))
    turns = [
        (cust_label, ["hi, ", g.tx("I can't log in, my email is ", "ich komme nicht rein, meine E-Mail ist ", "je n'arrive pas à me connecter, mon e-mail est ",
                                     "non riesco ad accedere, la mia email è ", "no puedo entrar, mi correo es "), g.email(cust, "personal")]),
        ("Agent", [g.tx("Sure, can you confirm your date of birth?", "Gern, können Sie Ihr Geburtsdatum bestätigen?",
                        "Bien sûr, pouvez-vous confirmer votre date de naissance ?", "Certo, può confermare la sua data di nascita?",
                        "Claro, ¿puede confirmar su fecha de nacimiento?")]),
        (cust_label, [g.pdate("dob", "any")]),
    ]
    for _ in g.loop(d, target):
        if turns:
            who, body = turns.pop(0)
        else:
            who = g.pick([cust_label, "Agent"])
            r = g.r.random()
            if r < 0.08:
                body = g.pii_sentence(cust)
            elif r < 0.11:
                body = [g.tx("my card is ", "meine Karte ist ", "ma carte est ", "la mia carta è ", "mi tarjeta es "), g.card()]
            elif r < 0.14:
                body = [g.tx("new address: ", "neue Adresse: ", "nouvelle adresse : ", "nuovo indirizzo: ", "nueva dirección: "), g.address()]
            else:
                body = [" ".join(g.neutral() for _ in range(g.rint(1, 3)))]
        g.tick(5, 120)
        d.t("[%s] %s: " % (g.clock.strftime("%H:%M:%S"), who))
        d.v(body)
        d.t("\n")
    d.t("=== %s ===\n" % g.tx("chat closed by agent", "Chat vom Agenten beendet", "chat fermé par l'agent",
                               "chat chiusa dall'operatore", "chat cerrado por el agente"))


# ================================================================ long docs


def long_header(g: Gen, kind: str, fname: str, i: int) -> str:
    lead = "\n\n" if i else ""
    svc = g.pick(SERVICES)
    if kind in ("source_code", "config", "data_export"):
        return lead + "==> %s/%s <==\n" % (svc, fname)
    if kind == "log":
        return lead + "==> /var/log/%s/%s <==\n" % (svc, fname)
    if kind == "stack_trace":
        return lead + "----- crash report #%d (%s-%d, %s) -----\n" % (i + 1, svc, g.rint(1, 9), fname)
    if kind == "shell_session":
        return lead + 'Script started on %s+00:00 [TERM="xterm-256color" TTY="/dev/pts/%d" COLUMNS="%d" LINES="%d"]\n' % (
            g.ts_sec(), g.rint(0, 9), g.pick([120, 160, 211]), g.pick([40, 48, 60]))
    if kind == "markdown":
        return lead + "<!-- page: %s/%s -->\n\n" % (svc, fname)
    return lead + "======== %s (%d) ========\n\n" % (fname, i + 1)


# Relative weight of a template when it is drawn as a section of a long
# document; the densest exports and chat formats are drawn less often so that
# long documents stay within the target density.
LONG_WEIGHTS = {"data.csv_customers": 0.15, "data.tsv_hr": 0.15, "data.ldif": 0.4, "msg.whatsapp_export": 0.4,
                "msg.chat_transcript": 0.4, "sh.ssh_admin": 0.4, "sh.mysql": 0.5, "sh.curl_api": 0.6}


def build_long(g: Gen, d: Doc, target: int, kind: str) -> None:
    i = 0
    choices = [((t, f, fn), LONG_WEIGHTS.get(t, 1.0)) for t, f, fn in REGISTRY[kind]]
    while len(d) < target:
        _tid, fname, fn = g.weighted(choices)
        sub = Doc()
        fn(g, sub, g.rint(LONG_SECTION_LO, LONG_SECTION_HI))
        d.t(long_header(g, kind, fname, i))
        d.extend(sub)
        i += 1


# ================================================================ validation


def unlabelled_repeats(text: str, spans) -> List[str]:
    """Return planted values that also occur in the text outside every span."""
    covered = sorted((s, e) for s, e, _l, _v in spans)
    problems = []
    for value in sorted({v for _s, _e, _l, v in spans if len(v) >= MIN_REPEAT_CHECK_LEN}):
        start = 0
        while True:
            k = text.find(value, start)
            if k < 0:
                break
            end = k + len(value)
            start = k + 1
            before = text[k - 1] if k > 0 else " "
            after = text[end] if end < len(text) else " "
            if (before.isalnum() or before == "_") or (after.isalnum() or after == "_"):
                continue
            if not any(s <= k and end <= e for s, e in covered):
                problems.append("value %r occurs unlabelled at %d" % (value, k))
    return problems


def assert_span_invariants(text: str, spans) -> None:
    """Hard invariants: a violation is a generator bug, so abort instead of retrying."""
    prev_end = -1
    for s, e, lab, val in spans:
        if lab not in LABEL_SET:
            raise AssertionError("unknown label %r" % lab)
        if text[s:e] != val:
            raise AssertionError("span text mismatch at %d: %r != %r" % (s, text[s:e], val))
        if e <= s:
            raise AssertionError("empty span at %d" % s)
        if s < prev_end:
            raise AssertionError("overlapping or unsorted span at %d" % s)
        prev_end = e


def validate_doc(text: str, spans, is_long: bool, clean: bool) -> List[str]:
    """Soft constraints: a violation makes build_doc draw the document again."""
    assert_span_invariants(text, spans)
    problems = []
    n = len(text)
    if is_long and not (LONG_MIN <= n <= LONG_MAX):
        problems.append("long doc length %d outside [%d, %d]" % (n, LONG_MIN, LONG_MAX))
    if not is_long and not (SHORT_MIN <= n <= SHORT_MAX):
        problems.append("short doc length %d outside [%d, %d]" % (n, SHORT_MIN, SHORT_MAX))
    if clean and spans:
        problems.append("clean document has spans")
    if not clean and not spans:
        problems.append("non-clean document has no spans")
    problems.extend(unlabelled_repeats(text, spans))
    return problems


def build_doc(seed: int, idx: int, slot: dict) -> dict:
    last: List[str] = []
    for attempt in range(MAX_ATTEMPTS):
        rng = random.Random("%d:%d:%d" % (seed, idx, attempt))
        g = Gen(rng, slot["lang"], slot["clean"])
        d = Doc()
        if slot["long"]:
            tid = "long." + slot["kind"]
            build_long(g, d, rng.randint(LONG_TARGET_LO, LONG_TARGET_HI), slot["kind"])
        else:
            tid, _fname, fn = REGISTRY[slot["kind"]][slot["tpl"]]
            target = int(math.exp(rng.uniform(math.log(SHORT_TARGET_LO), math.log(SHORT_TARGET_HI))))
            fn(g, d, target)
        text = d.text()
        last = validate_doc(text, d.spans, slot["long"], slot["clean"])
        if not last:
            return {"id": "tv2:%d" % idx, "kind": slot["kind"], "template": tid, "lang": slot["lang"], "text": text,
                    "spans": [{"start": s, "end": e, "label": lab} for s, e, lab, _v in d.spans],
                    "_values": [v for _s, _e, _l, v in d.spans]}
    raise RuntimeError("doc %d (%s): checks still failing after %d attempts: %s" % (idx, slot, MAX_ATTEMPTS, last[:5]))


def plan_slots(rng: random.Random) -> List[dict]:
    per_kind = N_DOCS // len(KINDS)
    if per_kind * len(KINDS) != N_DOCS:
        raise ValueError("N_DOCS must be divisible by the number of kinds")
    long_per_kind = {k: N_LONG // len(KINDS) for k in KINDS}
    for k in rng.sample(KINDS, N_LONG - sum(long_per_kind.values())):
        long_per_kind[k] += 1
    slots = [{"kind": k, "long": j < long_per_kind[k]} for k in KINDS for j in range(per_kind)]
    langs = [lang for lang, c in LANG_COUNTS.items() for _ in range(c)]
    if len(langs) != N_DOCS:
        raise ValueError("LANG_COUNTS must sum to N_DOCS")
    rng.shuffle(langs)
    for s, lang in zip(slots, langs):
        s["lang"] = lang
    short_idx = [i for i, s in enumerate(slots) if not s["long"]]
    clean = set(rng.sample(short_idx, N_CLEAN))
    for i, s in enumerate(slots):
        s["clean"] = i in clean
    for k in KINDS:
        order = list(range(len(REGISTRY[k])))
        rng.shuffle(order)
        for j, s in enumerate(s for s in slots if s["kind"] == k and not s["long"]):
            s["tpl"] = order[j % len(order)]
    rng.shuffle(slots)
    return slots


def corpus_checks(docs: List[dict]) -> List[str]:
    problems = []
    n = len(docs)
    if n != N_DOCS:
        problems.append("document count %d != %d" % (n, N_DOCS))
    if len({d["id"] for d in docs}) != n:
        problems.append("duplicate ids")
    templates = Counter(d["template"] for d in docs)
    if len(templates) < MIN_SKELETONS:
        problems.append("only %d template skeletons (< %d)" % (len(templates), MIN_SKELETONS))
    rare = [t for t, c in templates.items() if c < MIN_USES_PER_SKELETON]
    if rare:
        problems.append("templates used fewer than %d times: %s" % (MIN_USES_PER_SKELETON, rare))
    n_long = sum(1 for d in docs if len(d["text"]) > SHORT_MAX)
    if not (LONG_SHARE_LO <= n_long / n <= LONG_SHARE_HI):
        problems.append("long share %.3f outside [%.2f, %.2f]" % (n_long / n, LONG_SHARE_LO, LONG_SHARE_HI))
    for d in docs:
        ln = len(d["text"])
        if not (SHORT_MIN <= ln <= SHORT_MAX or LONG_MIN <= ln <= LONG_MAX):
            problems.append("%s length %d outside both ranges" % (d["id"], ln))
        for sp in d["spans"]:
            if sp["label"] not in LABEL_SET:
                problems.append("%s unknown label %s" % (d["id"], sp["label"]))
        for sp, val in zip(d["spans"], d["_values"]):
            if d["text"][sp["start"]:sp["end"]] != val:
                problems.append("%s span text mismatch" % d["id"])
        ends = [(sp["start"], sp["end"]) for sp in d["spans"]]
        if ends != sorted(ends) or any(a[1] > b[0] for a, b in zip(ends, ends[1:])):
            problems.append("%s spans unsorted or overlapping" % d["id"])
    langs = Counter(d["lang"] for d in docs)
    if not (EN_SHARE_LO <= langs["en"] / n <= EN_SHARE_HI):
        problems.append("en share %.3f out of range" % (langs["en"] / n))
    for lang in LANGS[1:]:
        if not (OTHER_LANG_SHARE_LO <= langs[lang] / n <= OTHER_LANG_SHARE_HI):
            problems.append("%s share %.3f out of range" % (lang, langs[lang] / n))
    no_span = sum(1 for d in docs if not d["spans"]) / n
    if not (NO_SPAN_SHARE_LO <= no_span <= NO_SPAN_SHARE_HI):
        problems.append("no-span share %.3f out of range" % no_span)
    total_chars = sum(len(d["text"]) for d in docs)
    total_spans = sum(len(d["spans"]) for d in docs)
    density = total_chars / max(1, total_spans)
    if not (DENSITY_LO <= density <= DENSITY_HI):
        problems.append("density %.1f chars/span outside [%d, %d]" % (density, DENSITY_LO, DENSITY_HI))
    kinds = Counter(d["kind"] for d in docs)
    if set(kinds) != set(KINDS) or max(kinds.values()) - min(kinds.values()) > N_DOCS // 20:
        problems.append("kind distribution uneven: %s" % dict(kinds))
    return problems


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="master seed (default %(default)s)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output JSONL path (default %(default)s)")
    ap.add_argument("--stats", action="store_true", help="print per-template statistics")
    args = ap.parse_args(argv)

    t0 = time.time()
    n_tpl = sum(len(v) for v in REGISTRY.values()) + len(KINDS)
    if n_tpl < MIN_SKELETONS:
        raise SystemExit("registry defines only %d skeletons" % n_tpl)
    slots = plan_slots(random.Random("%d:plan" % args.seed))
    docs = [build_doc(args.seed, i, slot) for i, slot in enumerate(slots)]
    problems = corpus_checks(docs)
    if problems:
        report(docs, args.stats, sys.stderr)
        for p in problems[:50]:
            print("CHECK FAILED: " + p, file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        for d in docs:
            rec = {k: d[k] for k in ("id", "kind", "template", "lang", "text", "spans")}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("wrote %s" % args.out)
    print("sha256 %s" % hashlib.sha256(args.out.read_bytes()).hexdigest())
    report(docs, args.stats, sys.stdout)
    print("elapsed %.1fs" % (time.time() - t0))
    return 0


def report(docs: List[dict], per_template: bool, out) -> None:
    labels = Counter(sp["label"] for d in docs for sp in d["spans"])
    total_chars = sum(len(d["text"]) for d in docs)
    total_spans = sum(labels.values())
    lens = sorted(len(d["text"]) for d in docs)
    print("documents %d (long %d, without spans %d)" % (len(docs), sum(1 for x in lens if x > SHORT_MAX),
                                                         sum(1 for d in docs if not d["spans"])), file=out)
    print("templates %d" % len({d["template"] for d in docs}), file=out)
    print("kinds %s" % json.dumps(dict(sorted(Counter(d["kind"] for d in docs).items()))), file=out)
    print("langs %s" % json.dumps(dict(sorted(Counter(d["lang"] for d in docs).items()))), file=out)
    print("spans %d, chars %d, density %.1f chars/span" % (total_spans, total_chars, total_chars / max(1, total_spans)),
          file=out)
    print("length min %d median %d max %d" % (lens[0], lens[len(lens) // 2], lens[-1]), file=out)
    print("labels:", file=out)
    for lab in LABELS:
        print("  %-24s %6d" % (lab, labels[lab]), file=out)
    if not per_template:
        return
    by_t: Dict[str, List[int]] = {}
    for d in docs:
        acc = by_t.setdefault(d["template"], [0, 0, 0])
        acc[0] += 1
        acc[1] += len(d["text"])
        acc[2] += len(d["spans"])
    print("per template (docs, mean chars, chars/span):", file=out)
    for t in sorted(by_t):
        c, ch, sp = by_t[t]
        print("  %-28s %4d %7d %8.1f" % (t, c, ch // c, ch / max(1, sp)), file=out)


if __name__ == "__main__":
    sys.exit(main())
