# SPDX-License-Identifier: Apache-2.0
"""Shared, localized connective phrases (en/it/de/fr/es) written for this
generator. Slots use the ⟦name⟧ syntax of core.T."""

from __future__ import annotations

from .core import T

PHRASES: dict[str, dict[str, list[str]]] = {
    # ---------------------------------------------------------------- agent
    "look_first": {
        "en": ["I'll start by looking at ⟦x⟧.", "Let me read ⟦x⟧ first.", "First, ⟦x⟧."],
        "it": ["Inizio dando un'occhiata a ⟦x⟧.", "Prima leggo ⟦x⟧.", "Parto da ⟦x⟧."],
        "de": ["Ich schaue mir zuerst ⟦x⟧ an.", "Zuerst lese ich ⟦x⟧.", "Ich fange mit ⟦x⟧ an."],
        "fr": ["Je commence par regarder ⟦x⟧.", "Je lis d'abord ⟦x⟧.", "D'abord, ⟦x⟧."],
        "es": ["Empiezo revisando ⟦x⟧.", "Primero leo ⟦x⟧.", "Voy a mirar ⟦x⟧ primero."],
    },
    "check_next": {
        "en": ["Now let me check ⟦x⟧.", "Next: ⟦x⟧.", "Checking ⟦x⟧ as well."],
        "it": ["Ora controllo ⟦x⟧.", "Adesso guardo ⟦x⟧.", "Controllo anche ⟦x⟧."],
        "de": ["Jetzt prüfe ich ⟦x⟧.", "Als Nächstes: ⟦x⟧.", "Ich prüfe auch ⟦x⟧."],
        "fr": ["Je vérifie maintenant ⟦x⟧.", "Ensuite : ⟦x⟧.", "Je regarde aussi ⟦x⟧."],
        "es": ["Ahora reviso ⟦x⟧.", "Siguiente: ⟦x⟧.", "Reviso también ⟦x⟧."],
    },
    "secret_warning": {
        "en": ["Heads-up: ⟦x⟧ contains what looks like a live credential. It shouldn't be committed, and it should be rotated.",
               "Careful — ⟦x⟧ has a real secret in plain text. I'd rotate it and move it to the secret store."],
        "it": ["Attenzione: ⟦x⟧ contiene quella che sembra una credenziale reale. Non va committata e andrebbe ruotata.",
               "Occhio: in ⟦x⟧ c'è un segreto in chiaro. Lo ruoterei e lo sposterei nel secret manager."],
        "de": ["Achtung: ⟦x⟧ enthält offenbar ein echtes Zugangsdatum. Das darf nicht committet werden und sollte rotiert werden.",
               "Vorsicht — in ⟦x⟧ steht ein Secret im Klartext. Ich würde es rotieren und in den Secret Store verschieben."],
        "fr": ["Attention : ⟦x⟧ contient ce qui ressemble à un identifiant réel. Il ne faut pas le committer, et il faudrait le renouveler.",
               "Prudence — ⟦x⟧ contient un secret en clair. Je le renouvellerais et le déplacerais dans le coffre à secrets."],
        "es": ["Ojo: ⟦x⟧ contiene lo que parece una credencial real. No debería subirse al repositorio y habría que rotarla.",
               "Cuidado: en ⟦x⟧ hay un secreto en texto plano. Yo lo rotaría y lo movería al gestor de secretos."],
    },
    "pii_warning": {
        "en": ["Note: this output contains personal data, so I won't copy it into the issue or the commit.",
               "This contains real customer details; I'll keep them out of logs and test fixtures."],
        "it": ["Nota: questo output contiene dati personali, quindi non li copierò nell'issue né nel commit.",
               "Qui ci sono dati reali di clienti; li terrò fuori da log e fixture di test."],
        "de": ["Hinweis: Die Ausgabe enthält personenbezogene Daten, die kopiere ich weder ins Ticket noch in den Commit.",
               "Das sind echte Kundendaten; die halte ich aus Logs und Test-Fixtures heraus."],
        "fr": ["Remarque : cette sortie contient des données personnelles, je ne les recopierai ni dans le ticket ni dans le commit.",
               "Ce sont de vraies données clients ; je les garde hors des logs et des fixtures de test."],
        "es": ["Nota: esta salida contiene datos personales, así que no los copiaré en la incidencia ni en el commit.",
               "Hay datos reales de clientes; los mantendré fuera de los logs y de los fixtures de test."],
    },
    "run_tests": {
        "en": ["Running the tests again to confirm.", "Let me re-run the test suite.", "Re-running the failing tests."],
        "it": ["Rilancio i test per conferma.", "Rieseguo la suite di test.", "Rilancio i test che fallivano."],
        "de": ["Ich lasse die Tests zur Bestätigung noch einmal laufen.", "Ich starte die Testsuite neu.",
               "Ich führe die fehlschlagenden Tests erneut aus."],
        "fr": ["Je relance les tests pour confirmer.", "Je relance la suite de tests.", "Je relance les tests en échec."],
        "es": ["Vuelvo a lanzar los tests para confirmar.", "Ejecuto de nuevo la batería de tests.",
               "Relanzo los tests que fallaban."],
    },
    "tests_pass": {
        "en": ["All green now.", "Tests pass.", "Everything passes now."],
        "it": ["Ora è tutto verde.", "I test passano.", "Adesso passa tutto."],
        "de": ["Jetzt ist alles grün.", "Die Tests laufen durch.", "Jetzt läuft alles durch."],
        "fr": ["Tout est vert maintenant.", "Les tests passent.", "Tout passe maintenant."],
        "es": ["Ahora está todo en verde.", "Los tests pasan.", "Ya pasa todo."],
    },
    "done": {
        "en": ["Done. Summary:", "That's fixed. What changed:", "All set. Here's what I did:"],
        "it": ["Fatto. Riepilogo:", "Sistemato. Cosa è cambiato:", "Ecco fatto. Cosa ho modificato:"],
        "de": ["Erledigt. Zusammenfassung:", "Behoben. Was sich geändert hat:", "Fertig. Das habe ich gemacht:"],
        "fr": ["C'est fait. Résumé :", "Corrigé. Ce qui a changé :", "Terminé. Voici ce que j'ai fait :"],
        "es": ["Hecho. Resumen:", "Arreglado. Qué ha cambiado:", "Listo. Esto es lo que hice:"],
    },
    "applying": {
        "en": ["Applying the fix.", "Making the change now.", "Editing the file."],
        "it": ["Applico la correzione.", "Faccio la modifica.", "Modifico il file."],
        "de": ["Ich setze den Fix um.", "Ich nehme die Änderung vor.", "Ich passe die Datei an."],
        "fr": ["J'applique le correctif.", "Je fais la modification.", "Je modifie le fichier."],
        "es": ["Aplico la corrección.", "Hago el cambio.", "Edito el fichero."],
    },
    "searching": {
        "en": ["Searching the codebase for ⟦x⟧.", "Let me find where ⟦x⟧ is used."],
        "it": ["Cerco ⟦x⟧ nel codice.", "Vediamo dove viene usato ⟦x⟧."],
        "de": ["Ich suche im Code nach ⟦x⟧.", "Mal sehen, wo ⟦x⟧ verwendet wird."],
        "fr": ["Je cherche ⟦x⟧ dans le code.", "Voyons où ⟦x⟧ est utilisé."],
        "es": ["Busco ⟦x⟧ en el código.", "Veamos dónde se usa ⟦x⟧."],
    },
    "explain": {
        "en": ["Here's what's happening:", "What I found:", "The problem:"],
        "it": ["Ecco cosa succede:", "Cosa ho trovato:", "Il problema:"],
        "de": ["Folgendes passiert:", "Was ich gefunden habe:", "Das Problem:"],
        "fr": ["Voici ce qui se passe :", "Ce que j'ai trouvé :", "Le problème :"],
        "es": ["Esto es lo que pasa:", "Lo que he encontrado:", "El problema:"],
    },
    "not_committed": {
        "en": ["I haven't committed anything; the diff is ready for your review.",
               "Nothing is committed yet — review the diff when you have a minute."],
        "it": ["Non ho committato nulla; il diff è pronto per la tua revisione.",
               "Ancora nessun commit: dai un'occhiata al diff quando puoi."],
        "de": ["Ich habe nichts committet; der Diff ist bereit für dein Review.",
               "Noch nichts committet — schau dir den Diff an, wenn du Zeit hast."],
        "fr": ["Je n'ai rien committé ; le diff est prêt pour ta relecture.",
               "Rien n'est committé — relis le diff quand tu as une minute."],
        "es": ["No he hecho commit de nada; el diff está listo para que lo revises.",
               "Aún no hay commit: revisa el diff cuando puedas."],
    },
    "logs_window": {
        "en": ["Let me look at the logs around that time.", "Pulling the logs for that window."],
        "it": ["Guardo i log intorno a quell'orario.", "Recupero i log di quella finestra temporale."],
        "de": ["Ich schaue mir die Logs um diese Uhrzeit an.", "Ich hole die Logs für dieses Zeitfenster."],
        "fr": ["Je regarde les logs autour de cette heure-là.", "Je récupère les logs de cette période."],
        "es": ["Miro los logs alrededor de esa hora.", "Saco los logs de esa franja."],
    },
    # ---------------------------------------------------------------- user
    "thanks": {
        "en": ["Thanks!", "Great, thanks.", "perfect, thank you", "ok thanks"],
        "it": ["Grazie!", "Perfetto, grazie.", "ok grazie", "Ottimo, grazie mille."],
        "de": ["Danke!", "Super, danke.", "ok danke", "Perfekt, vielen Dank."],
        "fr": ["Merci !", "Super, merci.", "ok merci", "Parfait, merci beaucoup."],
        "es": ["¡Gracias!", "Genial, gracias.", "ok gracias", "Perfecto, muchas gracias."],
    },
    "go_ahead": {
        "en": ["Go ahead.", "yes please", "Sounds good, do it.", "ok, go"],
        "it": ["Vai pure.", "sì, procedi", "Mi sembra giusto, fallo.", "ok vai"],
        "de": ["Mach ruhig.", "ja bitte", "Klingt gut, mach das.", "ok, los"],
        "fr": ["Vas-y.", "oui stp", "Ça me va, fais-le.", "ok go"],
        "es": ["Adelante.", "sí, por favor", "Me parece bien, hazlo.", "vale, dale"],
    },
    "dont_commit": {
        "en": ["Don't commit yet, I want to look at it first.", "Leave it uncommitted please."],
        "it": ["Non committare ancora, voglio vederlo prima.", "Lascialo senza commit per ora."],
        "de": ["Noch nicht committen, ich will es mir erst ansehen.", "Bitte noch nicht committen."],
        "fr": ["Ne committe pas encore, je veux d'abord regarder.", "Laisse ça sans commit pour l'instant."],
        "es": ["No hagas commit todavía, quiero revisarlo antes.", "Déjalo sin commit de momento."],
    },
    "anything_else": {
        "en": ["Anything else that looks off?", "Do you see anything else wrong in there?"],
        "it": ["C'è altro che non ti convince?", "Vedi altro di strano lì dentro?"],
        "de": ["Fällt dir sonst noch etwas auf?", "Siehst du da noch etwas, das nicht stimmt?"],
        "fr": ["Tu vois autre chose de bizarre ?", "Il y a autre chose qui cloche là-dedans ?"],
        "es": ["¿Ves algo más raro?", "¿Hay algo más que no cuadre ahí?"],
    },
    "rotate_later": {
        "en": ["I'll rotate it later, just fix the code for now.", "Rotation is on me, focus on the bug."],
        "it": ["Lo ruoto io dopo, per ora sistema solo il codice.", "Alla rotazione ci penso io, concentrati sul bug."],
        "de": ["Rotieren mache ich später, kümmere dich erst um den Code.", "Die Rotation übernehme ich, konzentrier dich auf den Bug."],
        "fr": ["Je le renouvellerai plus tard, corrige juste le code pour l'instant.", "Je m'occupe de la rotation, concentre-toi sur le bug."],
        "es": ["Lo roto yo luego, de momento arregla el código.", "La rotación la hago yo, céntrate en el bug."],
    },
}


def say(d, key: str, **kw) -> list:
    """Localized phrase for the document's conversation language."""
    table = PHRASES[key]
    if d.lang in table:
        options = table[d.lang]
    else:
        d.text_langs.add("en")
        options = table["en"]
    return T(d.rng.choice(options), **kw)
