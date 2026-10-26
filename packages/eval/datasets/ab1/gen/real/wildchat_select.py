# SPDX-License-Identifier: Apache-2.0
"""Phase A, AB-1: candidate real non-English prompts from WildChat-1M.

Source: allenai/WildChat-1M (ODC-BY), revision 7d6490e462285cf85d91eabea0f9a954fbddcd1f,
`cache/wildchat-1m/data/train-*.parquet` (14 files, 837,989 conversations).

    python gen/real/wildchat_select.py [--data GLOB] [--out DIR] [--keep N] [--files N]

A conversation qualifies when
  1. its `language` (the conversation-level field) is Italian, German, French or Spanish;
  2. it is not flagged toxic (`toxic` false, and the first user turn's own `toxic` false);
  3. its first user turn (the first message with role `user`; skipped when empty) is about
     programming, by the rule below;
  4. the first user turn passes the stop-word language check for that language (the builder's
     `is_english` idea: at least 8% of the prose words are stop words of that language, and
     function words of English and of the other three are counted against it, a word of the
     language under test never counting as foreign) and has no non-Latin script;
  5. after normalisation (the builder's carrier rule: leading newlines and trailing whitespace
     stripped, otherwise verbatim) it is EXCERPT_MIN..EXCERPT_MAX = 300..6,000 characters;
  6. its normalised text (lowercased, whitespace collapsed) is not equal to one already kept.

The candidate text is that first user turn, verbatim. Candidates are ranked by the builder's
seeded priority `derive_seed("pool", "<conversation_hash>|<turn_index>")` and the best `--keep`
(300) per language are written to cache/real/wildchat_<lang>.jsonl as
`{"conversation_hash", "turn_index", "language", "text"}`, in priority order, one JSON object per
line. `turn_index` is the 0-based index of the turn inside the conversation list, `language` the
two-letter code.

Programming-prompt rule. The first user turn is about programming when at least one of:
  P1 fenced code block: the turn holds a ``` or ~~~ fence line;
  P2 code-like lines: at least 2 lines match CODE_LINE_RE, a statement-shaped line (a
     definition/import/declaration keyword, a call or assignment ending in `)`/`;`/`{`, a brace,
     an XML/HTML tag, a SQL keyword, a shell prompt);
  P3 stack trace or error output: STACK_RE matches (Python traceback, `at pkg.Class.method(File:12)`,
     `XxxError:`/`XxxException:`, `panic:`, `SyntaxError`, `NullPointerException`, `Segmentation
     fault`, `undefined reference`, or a line opening with an error word of the turn's language,
     `error:`/`errore:`/`erreur:`/`Fehler:`);
  P4 programming vocabulary: at least one *core* programming term (CORE_UNIVERSAL, or CORE[lang]
     for the turn's language) occurs as a word, or at least two terms in total from CORE and EXTRA
     (`function`/`Funktion`/`funzione`/`fonction`/`función`, `compile`/`compilare`, `database`,
     `debug`, `algorithm`, `python`, `sql`, `json`, `api`, `regex`, `docker`, `git`, …).
Ambiguous words are deliberately absent from the vocabulary: Italian `codice` (also `codice
fiscale`, `codice sconto`), Spanish `código`, German `Code`, French `code` — so a turn that only
talks about a tax code, a discount code or a dialling code does not qualify. The two-term branch
keeps a single generic word (`file`, `server`, `browser`, `excel`) from qualifying a turn on its
own.

Prints counts only: conversations read and, per language, the survivors after each filter.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carriers import EN_STOP, NON_LATIN, normalise, prose_of  # noqa: E402
from common import EXCERPT_MAX, EXCERPT_MIN, ROOT, derive_seed  # noqa: E402

LANGS = ("it", "de", "fr", "es")
LANG_OF_NAME = {"Italian": "it", "German": "de", "French": "fr", "Spanish": "es"}

DEFAULT_DATA = str(ROOT / "cache" / "wildchat-1m" / "data" / "train-*.parquet")
DEFAULT_OUT = ROOT / "cache" / "real"
KEEP_PER_LANG = 300

FENCE_RE = re.compile(r"^\s*(?:```|~~~)", re.M)
STACK_RE = re.compile(
    r"Traceback \(most recent call last\)"
    r"|^\s+at [\w$.<>]+ ?\(.*:\d+(?::\d+)?\)$"
    r"|^\s*(?:panic|fatal|FATAL):"
    r"|\b\w+(?:Error|Exception|Throwable)\b\s*[:)]"
    r"|Segmentation fault|core dumped|undefined reference|No such file or directory"
    r"|SyntaxError|NullPointerException|IndexError|TypeError|ValueError|ImportError"
    r"|^\s*(?:error|errore|erreur|fehler|erro)\b\s*[:\-]",
    re.M | re.I)
CODE_LINE_RE = re.compile(
    r"^\s*(?:"
    r"def |class |import |from \w[\w.]* import |#include|#define|using namespace|package [\w.]+;"
    r"|(?:public|private|protected|static|final|void|func|fn|let|const|var|async|await)\s+\w"
    r"|return\b|if \(|elif |else:|for \(|while \(|switch |case |try:|catch |except |finally:"
    r"|SELECT |INSERT |UPDATE |DELETE |CREATE (?:TABLE|INDEX)|<\?php|</?[a-zA-Z][\w:-]*[ >/]"
    r"|[\w.\[\]'\"]+\s*=\s*\S|[\w.]+\s*\(.*\)\s*[;:{]?\s*$|\}\s*;?|\)\s*;|\{|\}|\[[^\]]*\]\s*=\s*"
    r"|\$\s+\w|>\s+\w+\.(?:py|js|ts|sh|json|yaml|yml|java|go|rb|php|c|cpp|h)\b"
    r")")
# P4 vocabulary: a term of CORE counts on its own, a term of EXTRA needs a second term behind it.
CORE_UNIVERSAL = {
    "python", "python3", "javascript", "typescript", "java", "kotlin", "swift", "rust", "golang",
    "php", "ruby", "perl", "html", "css", "scss", "sql", "mysql", "postgres", "postgresql",
    "sqlite", "mongodb", "json", "yaml", "xml", "api", "rest", "regex", "docker", "kubernetes",
    "git", "github", "gitlab", "npm", "node", "nodejs", "react", "vue", "angular", "django",
    "flask", "spring", "laravel", "vba", "bash", "shell", "compiler", "database", "backend",
    "frontend", "framework", "script", "webscraping", "scraping", "cron", "crontab", "dockerfile",
    "selenium", "pandas", "numpy", "matplotlib", "tensorflow", "pytorch", "opencv", "ffmpeg",
    "sqlalchemy", "bootstrap", "jquery", "ajax", "webhook", "nginx", "apache", "redis", "kafka",
    "rabbitmq", "graphql", "pytest", "jest", "webpack", "vite", "unittest", "unit test",
    "localhost", "ssh", "ftp", "smtp", "parse", "parser", "endpoint", "payload", "exception",
    "refactor", "commit", "pull request", "merge request", "assembly",
    "command line", "wordpress",
    "quellcode", "code source", "código fuente", "codice sorgente", "base de datos",
    "base de données", "datenbank", "datenbanken", "linea di comando", "ligne de commande",
    "línea de comandos", "befehlszeile", "kommandozeile",
}
EXTRA_UNIVERSAL = {
    "excel", "server", "browser", "function", "variable", "array", "string", "boolean", "integer",
    "float", "loop", "runtime", "library", "request", "response", "cookie", "token", "encryption",
    "hash", "null", "undefined", "ip", "tcp", "bot", "telegram", "discord", "automation",
    "front-end", "back-end", "matlab", "linux", "ubuntu", "debian", "windows", "csv", "url",
    "http", "https", "web", "app", "software", "hardware", "install", "download", "upload",
    "cloud", "hosting", "domain", "dns", "plugin", "extension", "bug", "debug",
}
CORE = {
    "it": {"funzione", "funzioni", "variabile", "variabili", "programmare", "programmazione",
           "compilare", "compilatore", "libreria", "librerie", "algoritmo", "parametro",
           "parametri", "array", "stringa", "stringhe", "debug", "debuggare", "sorgente",
           "installare", "eseguire", "database"},
    "de": {"funktion", "funktionen", "variable", "variablen", "programmieren", "programmierung",
           "kompilieren", "compiler", "bibliothek", "bibliotheken", "algorithmus", "parameter",
           "zeichenkette", "debuggen", "skript", "fehlermeldung", "installieren", "ausführen",
           "datenbank", "datenbanken"},
    "fr": {"fonction", "fonctions", "variable", "variables", "programmer", "programmation",
           "compiler", "compilateur", "bibliothèque", "bibliothèques", "algorithme", "paramètre",
           "paramètres", "chaîne", "chaînes", "déboguer", "installer", "exécuter"},
    "es": {"función", "funciones", "variable", "variables", "programar", "programación",
           "compilar", "compilador", "biblioteca", "bibliotecas", "algoritmo", "parámetro",
           "parámetros", "cadena", "cadenas", "depurar", "arreglo", "bucle", "instalar",
           "ejecutar"},
}
EXTRA = {
    "it": {"programma", "programmi", "classe", "classi", "errore", "errori", "metodo", "metodi",
           "modulo", "moduli", "server", "browser", "richiesta", "risposta", "codifica",
           "installazione", "esecuzione", "output", "input", "grafico", "ordinare", "ciclo",
           "vettore", "interfaccia", "linguaggio", "funzionante", "terminale", "cartella",
           "percorso", "comando", "sistema", "applicazione", "sito", "pagina", "rete",
           "connessione", "configurazione", "impostazioni", "utente", "password", "dati",
           "file", "riga"},
    "de": {"programm", "programme", "klasse", "klassen", "fehler", "methode", "methoden", "modul",
           "module", "server", "browser", "anfrage", "antwort", "verschlüsselung", "sortieren",
           "datei", "dateien", "ordner", "pfad", "terminal", "installation", "ausgabe", "eingabe",
           "diagramm", "schnittstelle", "sprache", "befehl", "system", "anwendung", "webseite",
           "seite", "netzwerk", "verbindung", "konfiguration", "einstellungen", "benutzer",
           "passwort", "daten", "schleife"},
    "fr": {"programme", "programmes", "classe", "classes", "erreur", "erreurs", "méthode",
           "méthodes", "module", "modules", "serveur", "navigateur", "requête", "réponse",
           "chiffrement", "trier", "fichier", "fichiers", "dossier", "chemin", "terminal",
           "installation", "sortie", "entrée", "graphique", "interface", "langage", "tableau",
           "boucle", "commande", "système", "application", "site", "page", "réseau", "connexion",
           "configuration", "paramètres", "utilisateur", "données"},
    "es": {"programa", "programas", "clase", "clases", "error", "errores", "método", "métodos",
           "módulo", "módulos", "servidor", "navegador", "petición", "respuesta", "cifrado",
           "ordenar", "archivo", "archivos", "carpeta", "ruta", "terminal", "instalación",
           "ejecución", "salida", "entrada", "gráfico", "interfaz", "lenguaje", "comando",
           "sistema", "aplicación", "sitio", "página", "red", "conexión", "configuración",
           "usuario", "contraseña", "datos"},
}
# The builder's is_english check, per language: a stop-word ratio over the prose lines. A word
# that belongs to the language being tested is never counted as foreign, so the shared short words
# (it/es `a`, it/de `in`, de `was`, fr/es `si`) do not cancel each other out.
STOP = {
    "it": {"il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "del", "della", "dei",
           "delle", "che", "e", "è", "per", "con", "non", "sono", "come", "questo", "questa",
           "ma", "se", "mi", "ti", "si", "ci", "ho", "hai", "ha", "abbiamo", "devo", "vorrei",
           "posso", "puoi", "cosa", "quale", "quando", "dove", "perché", "anche", "più", "molto",
           "nel", "nella", "al", "alla", "da", "in", "su", "tra", "fra", "essere", "fare", "mio",
           "mia", "tuo", "tua", "suo", "sua", "noi", "voi", "loro", "quindi", "solo", "bene",
           "grazie", "ciao", "ho", "voglio", "deve", "può", "sulla", "dal", "dalla", "agli",
           "alle", "una", "tutti", "tutte", "ogni", "stato", "stata", "già", "ancora", "senza",
           "dopo", "prima", "adesso", "qui", "ecco", "poi", "vero", "stessa", "stesso", "a", "ad",
           "ed", "o", "ai", "dai", "sul", "sui", "sullo", "dello", "degli", "questi", "queste",
           "quello", "quella", "quelli", "quelle", "io", "lui", "lei", "cui", "ne", "si", "vi"},
    "de": {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "eines",
           "und", "ist", "sind", "war", "für", "mit", "nicht", "auch", "wie", "ich", "du", "er",
           "sie", "es", "wir", "ihr", "mich", "dich", "sich", "uns", "habe", "hast", "hat",
           "haben", "kann", "können", "muss", "will", "soll", "werden", "wird", "wurde", "aber",
           "oder", "wenn", "dass", "weil", "noch", "nur", "schon", "sehr", "mehr", "bei", "aus",
           "nach", "von", "zu", "im", "am", "um", "auf", "über", "unter", "mein", "meine", "dein",
           "bitte", "danke", "was", "wer", "wo", "wann", "warum", "welche", "welcher", "dieser",
           "diese", "dieses", "möchte", "brauche", "möchte", "etwas", "alle", "immer", "dann",
           "jetzt", "hier", "dort", "ohne", "gegen", "zwischen", "durch", "könnte", "sollte",
           "in", "an", "als", "man", "so", "zum", "zur", "vom", "beim", "damit", "dabei", "dafür",
           "dazu", "davon", "da", "denn", "doch", "mal", "eben", "halt", "wohl", "zwar"},
    "fr": {"le", "la", "les", "un", "une", "des", "du", "de", "et", "est", "sont", "été", "pour",
           "avec", "pas", "ne", "dans", "sur", "sous", "que", "qui", "quoi", "je", "tu", "il",
           "elle", "nous", "vous", "ils", "elles", "me", "te", "se", "mon", "ma", "mes", "ton",
           "ta", "tes", "son", "sa", "ses", "notre", "votre", "leur", "ce", "cette", "ces", "mais",
           "ou", "si", "quand", "comment", "pourquoi", "parce", "plus", "très", "aussi", "bien",
           "merci", "bonjour", "au", "aux", "en", "faut", "peux", "peut", "veux", "veut", "dois",
           "doit", "faire", "avoir", "être", "je", "j'ai", "c'est", "d'un", "d'une", "qui", "tout",
           "tous", "toute", "toutes", "même", "encore", "déjà", "alors", "donc", "ici", "là",
           "après", "avant", "sans", "chez", "cela", "ça", "moi", "toi", "lui", "par", "vers",
           "dont", "où", "ni", "car", "ainsi", "toujours", "jamais", "rien", "à", "dès", "lors",
           "afin", "selon", "malgré", "pendant", "depuis", "voici", "voilà", "celui", "celle"},
    "es": {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "y", "es", "son",
           "fue", "para", "con", "no", "en", "por", "que", "qué", "quien", "quién", "como", "cómo",
           "cuando", "cuándo", "donde", "dónde", "porque", "yo", "tú", "él", "ella", "nosotros",
           "ustedes", "ellos", "me", "te", "se", "mi", "mis", "tu", "tus", "su", "sus", "nuestro",
           "este", "esta", "estos", "estas", "pero", "o", "si", "sí", "más", "muy", "también",
           "bien", "gracias", "hola", "hay", "tiene", "tengo", "quiero", "puedes", "puede",
           "hacer", "ser", "estar", "está", "estoy", "todos", "todas", "cada", "algo", "algunos",
           "desde", "hasta", "sin", "sobre", "entre", "cuando", "ahora", "aquí", "allí", "después",
           "antes", "necesito", "debo", "debería", "podría", "favor", "a", "ante", "bajo",
           "contra", "durante", "mediante", "según", "tras", "hacia", "lo", "le", "les", "nos",
           "os", "uno", "una", "eso", "esto", "esa", "ese", "esos", "esas", "mismo", "misma"},
}
# Words that give away English text in a it/de/fr/es turn: the builder's EN_STOP plus the rest of
# the English function words. A word of the language under test is subtracted before counting.
EN_BASE = EN_STOP | {
    "a", "an", "as", "at", "by", "do", "does", "did", "done", "had", "has", "have", "having",
    "been", "being", "was", "were", "will", "would", "shall", "there", "their", "they", "them",
    "we", "he", "she", "his", "her", "my", "your", "our", "what", "which", "who", "whom", "how",
    "why", "where", "than", "then", "into", "out", "about", "after", "before", "while", "because",
    "also", "just", "very", "more", "most", "some", "any", "all", "one", "two", "only", "even",
    "much", "many", "such", "other", "same", "get", "got", "make", "made", "see", "know", "think",
    "want", "need", "like", "used", "using", "could", "should", "may", "might", "must", "these",
    "those", "here", "now", "still", "well", "way", "thing", "things", "something", "nothing",
}
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_PROSE_WORDS = 25  # the builder's is_english threshold


def dedupe_key(text: str) -> str:
    """Normalised text for the near-duplicate check (lowercased, whitespace collapsed)."""
    return " ".join(text.lower().split())


def has_code_line(text: str) -> bool:
    n = 0
    fence = False
    for line in text.splitlines():
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            fence = not fence
            continue
        if fence or not line.strip():
            continue
        if CODE_LINE_RE.match(line):
            n += 1
            if n >= 2:
                return True
    return False


def vocab_hits(text: str, terms) -> set[str]:
    low = " " + " ".join(text.lower().split()) + " "
    words = set(WORD_RE.findall(text.lower()))
    hits = set()
    for term in terms:
        if " " in term:
            if " " + term + " " in low:
                hits.add(term)
        elif term in words:
            hits.add(term)
    return hits


def is_programming(text: str, lang: str) -> bool:
    if FENCE_RE.search(text):
        return True
    if STACK_RE.search(text):
        return True
    if has_code_line(text):
        return True
    core = vocab_hits(text, CORE_UNIVERSAL | CORE[lang])
    extra = vocab_hits(text, EXTRA_UNIVERSAL | EXTRA[lang])
    return bool(core) or len(core) + len(extra) >= 2


def is_language(text: str, lang: str) -> bool:
    """The builder's is_english idea for it/de/fr/es: stop-word ratio over the non-code lines."""
    if len(NON_LATIN.findall(text)) > 2:
        return False
    prose = prose_of(text)
    words = [w for w in WORD_RE.findall(prose.lower())]
    if len(words) < MIN_PROSE_WORDS:
        return False
    own = STOP[lang]
    foreign = (set().union(*(STOP[o] for o in STOP if o != lang)) | EN_BASE) - own
    mine = sum(w in own for w in words)
    other = sum(w in foreign for w in words)
    return mine >= 0.08 * len(words) and other < max(2, mine / 6)


def select(files: list[str], keep: int) -> dict[str, list[dict]]:
    counts = {lang: collections.Counter() for lang in LANGS}
    found: dict[str, list[tuple[str, dict]]] = {lang: [] for lang in LANGS}  # lang -> [(cid, row)]
    read = 0
    for path in files:
        table = pq.read_table(path, columns=["conversation_hash", "language", "toxic", "conversation"])
        for chash, name, toxic, conv in zip(table.column("conversation_hash").to_pylist(),
                                            table.column("language").to_pylist(),
                                            table.column("toxic").to_pylist(),
                                            table.column("conversation").to_pylist()):
            read += 1
            lang = LANG_OF_NAME.get(name)
            if lang is None:
                continue
            c = counts[lang]
            c["language"] += 1
            if toxic:
                continue
            c["not_toxic"] += 1
            first = None
            for i, msg in enumerate(conv):
                if msg["role"] == "user":
                    first = (i, msg)
                    break
            if first is None or not (first[1]["content"] or "").strip():
                continue
            c["first_user_turn"] += 1
            if first[1]["toxic"]:
                continue
            c["turn_not_toxic"] += 1
            text = normalise(first[1]["content"])
            if not is_programming(text, lang):
                continue
            c["programming"] += 1
            if not is_language(text, lang):
                continue
            c["language_check"] += 1
            if not (EXCERPT_MIN <= len(text) <= EXCERPT_MAX):
                continue
            c["length"] += 1
            cid = f"{chash}|{first[0]}"
            found[lang].append((cid, {"conversation_hash": chash, "turn_index": first[0],
                                      "language": lang, "text": text}))
        print(f"  read {read} conversations", flush=True)
    out = {}
    for lang in LANGS:
        # one copy per normalised text, the best by seeded priority, as in the carrier pool
        best: dict[str, tuple[str, dict]] = {}
        for cid, row in found[lang]:
            key = dedupe_key(row["text"])
            if key not in best or derive_seed("pool", cid) < derive_seed("pool", best[key][0]):
                best[key] = (cid, row)
        counts[lang]["duplicates"] = len(found[lang]) - len(best)
        ranked = sorted(best.items(), key=lambda kv: (derive_seed("pool", kv[1][0]), kv[0]))
        out[lang] = [row for _, (_, row) in ranked[:keep]]
        counts[lang]["kept"] = len(out[lang])
        counts[lang]["candidates"] = len(ranked)
    return {"counts": counts, "rows": out, "read": read}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--keep", type=int, default=KEEP_PER_LANG)
    ap.add_argument("--files", type=int, default=0, help="use only the first N input files (testing)")
    args = ap.parse_args()
    files = sorted(glob.glob(args.data))
    if not files:
        raise SystemExit(f"no input files for {args.data}")
    if args.files:
        files = files[:args.files]
    res = select(files, args.keep)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        rows = res["rows"][lang]
        path = outdir / f"wildchat_{lang}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"files {len(files)}; conversations read {res['read']}")
    steps = ["language", "not_toxic", "first_user_turn", "turn_not_toxic", "programming",
             "language_check", "length", "dups_dropped", "candidates", "kept"]
    print("lang " + " ".join(f"{s:>15}" for s in steps))
    for lang in LANGS:
        c = res["counts"][lang]
        print(f"{lang:>4} " + " ".join(f"{(c['duplicates'] if s == 'dups_dropped' else c[s]):>15}"
                                       for s in steps))
    for lang in LANGS:
        lens = sorted(len(r["text"]) for r in res["rows"][lang])
        if lens:
            print(f"{lang}: kept lengths min {lens[0]} median {lens[len(lens) // 2]} max {lens[-1]}")


if __name__ == "__main__":
    main()
