# SPDX-License-Identifier: Apache-2.0
"""Template user prompts and pasted tickets in en / it / de / fr / es.

Every language has its own families, so the template half of the prompt and ticket kinds is the
same size in English as in the other four languages (the carrier half comes from the carriers of
that language: openhands-feedback for English, WildChat-1M and GitHub issues for it/de/fr/es)."""
from __future__ import annotations

import keepvals as K
import values as VV
from doc import AM, KP, MM, P, V, Doc
from slots import Ctx
from tplutil import add_hook, frag, home_path, render_query_line

APPS = ["gestionale", "shop", "crm", "fatturazione", "booking", "api", "portal", "backoffice"]

# ------------------------------------------------------------------ fixed vocabulary per language

LBL = {
    "from": {"en": "From", "it": "Da", "de": "Von", "fr": "De", "es": "De"},
    "to": {"en": "To", "it": "A", "de": "An", "fr": "À", "es": "Para"},
    "date": {"en": "Date", "it": "Data", "de": "Datum", "fr": "Date", "es": "Fecha"},
    "subject": {"en": "Subject", "it": "Oggetto", "de": "Betreff", "fr": "Objet", "es": "Asunto"},
    "phone": {"en": "Phone", "it": "Telefono", "de": "Telefon", "fr": "Téléphone", "es": "Teléfono"},
    "address": {"en": "Address", "it": "Indirizzo", "de": "Adresse", "fr": "Adresse", "es": "Dirección"},
    "customer": {"en": "Customer", "it": "Cliente", "de": "Kunde", "fr": "Client", "es": "Cliente"},
    "order": {"en": "Order", "it": "Ordine", "de": "Bestellung", "fr": "Commande", "es": "Pedido"},
    "priority": {"en": "Priority: High", "it": "Priorità: Alta", "de": "Priorität: Hoch", "fr": "Priorité : Haute", "es": "Prioridad: Alta"},
    "reporter": {"en": "Reported by", "it": "Segnalato da", "de": "Gemeldet von", "fr": "Signalé par", "es": "Reportado por"},
    "assignee": {"en": "Assigned to", "it": "Assegnato a", "de": "Zugewiesen an", "fr": "Assigné à", "es": "Asignado a"},
    "env": {"en": "Environment", "it": "Ambiente", "de": "Umgebung", "fr": "Environnement", "es": "Entorno"},
    "steps": {"en": "Steps to reproduce", "it": "Passi per riprodurre", "de": "Schritte zum Reproduzieren", "fr": "Étapes pour reproduire", "es": "Pasos para reproducir"},
    "expected": {"en": "Expected result", "it": "Risultato atteso", "de": "Erwartetes Verhalten", "fr": "Résultat attendu", "es": "Resultado esperado"},
    "actual": {"en": "Actual result", "it": "Risultato ottenuto", "de": "Tatsächliches Verhalten", "fr": "Résultat obtenu", "es": "Resultado obtenido"},
    "fwd": {"en": "---------- Forwarded message ----------", "it": "---------- Messaggio inoltrato ----------",
            "de": "---------- Weitergeleitete Nachricht ----------",
            "fr": "---------- Message transféré ----------", "es": "---------- Mensaje reenviado ----------"},
    "birth": {"en": "Date of birth", "it": "Data di nascita", "de": "Geburtsdatum", "fr": "Date de naissance", "es": "Fecha de nacimiento"},
    "natid": {"en": "Tax ID", "it": "Codice fiscale", "de": "Steuer-ID", "fr": "N° de sécurité sociale", "es": "DNI/NIE"},
    "passport": {"en": "Passport", "it": "Passaporto", "de": "Reisepass", "fr": "Passeport", "es": "Pasaporte"},
    "dl": {"en": "Driving licence", "it": "Patente", "de": "Führerschein", "fr": "Permis de conduire", "es": "Carné de conducir"},
    "account": {"en": "Customer number", "it": "Codice cliente", "de": "Kundennummer", "fr": "N° client", "es": "N.º de cliente"},
}


def L(key: str, lang: str) -> str:
    return LBL[key][lang]


# ------------------------------------------------------------------ prompt families

PROMPTS: dict[str, dict[str, list[str]]] = {
    "debug_db": {
        "en": ["Hi, since this morning the app can't reach the database any more. This is my .env:\n\n«env»\n\nThe error is:\n«err»\nCan you work out what's wrong? Please don't touch the production config.",
               "docker compose won't start the api container any more. Here's the .env I use locally:\n«env»\ncan you fix the compose file so it picks these variables up?"],
        "it": ["Ciao, da stamattina l'app non si connette più al database. Questo è il mio .env:\n\n«env»\n\nL'errore è:\n«err»\nRiesci a capire cosa non va? Non toccare la configurazione di produzione.",
               "ho un problema con docker compose, il container api va in crash all'avvio. ti incollo il file .env che uso in locale:\n«env»\nmi sistemi il compose in modo che legga queste variabili?"],
        "de": ["Hi, seit heute früh kommt die App nicht mehr an die Datenbank. Hier ist meine .env:\n\n«env»\n\nFehlermeldung:\n«err»\nKannst du rausfinden, woran es liegt? Bitte nichts an der Prod-Konfiguration ändern.",
               "docker compose startet den api-Container nicht mehr. Das ist meine lokale .env:\n«env»\nKannst du die compose-Datei so anpassen, dass sie diese Variablen übernimmt?"],
        "fr": ["Salut, depuis ce matin l'appli n'arrive plus à se connecter à la base. Voici mon .env :\n\n«env»\n\nL'erreur :\n«err»\nTu peux regarder ce qui cloche ? Ne touche pas à la config de prod.",
               "le conteneur api plante au démarrage avec docker compose. je te colle le .env que j'utilise en local :\n«env»\ntu peux corriger le compose pour qu'il lise ces variables ?"],
        "es": ["Hola, desde esta mañana la app no conecta con la base de datos. Este es mi .env:\n\n«env»\n\nEl error es:\n«err»\n¿Puedes ver qué pasa? No toques la configuración de producción.",
               "el contenedor api se cae al arrancar con docker compose. te pego el .env que uso en local:\n«env»\n¿me arreglas el compose para que lea estas variables?"],
    },
    "add_customer_test": {
        "en": ["Add a test for the invoice generation using this real customer who reported the bug:\nName: «name»\nEmail: «email»\nPhone: «phone»\nAddress: «address»\nIBAN: «iban»\nThe test belongs in «path».",
               "write me a pytest fixture with «hon» «name» («email», tel. «phone») and their tax id «natid», I need it to reproduce ticket «ticket»"],
        "it": ["Aggiungi un test per la generazione fattura usando questo cliente reale che ci ha segnalato il bug:\nNome: «name»\nEmail: «email»\nTelefono: «phone»\nIndirizzo: «address»\nIBAN: «iban»\nIl test deve stare in «path».",
               "scrivimi una fixture pytest con il cliente «hon» «name» («email», tel. «phone») e il suo codice fiscale «natid», mi serve per riprodurre il problema del ticket «ticket»"],
        "de": ["Füg bitte einen Test für die Rechnungserstellung hinzu, mit dem echten Kunden, der den Bug gemeldet hat:\nName: «name»\nE-Mail: «email»\nTelefon: «phone»\nAdresse: «address»\nIBAN: «iban»\nDer Test gehört nach «path».",
               "schreib mir eine pytest-Fixture mit «hon» «name» («email», Tel. «phone») und seiner Steuer-ID «natid», brauche ich um «ticket» zu reproduzieren"],
        "fr": ["Ajoute un test pour la génération de facture avec le vrai client qui nous a remonté le bug :\nNom : «name»\nEmail : «email»\nTéléphone : «phone»\nAdresse : «address»\nIBAN : «iban»\nLe test doit aller dans «path».",
               "écris-moi une fixture pytest avec «hon» «name» («email», tél. «phone») et son numéro de sécu «natid», j'en ai besoin pour reproduire le ticket «ticket»"],
        "es": ["Añade un test para la generación de facturas con el cliente real que nos reportó el fallo:\nNombre: «name»\nEmail: «email»\nTeléfono: «phone»\nDirección: «address»\nIBAN: «iban»\nEl test va en «path».",
               "escríbeme una fixture de pytest con «hon» «name» («email», tel. «phone») y su DNI «natid», la necesito para reproducir el ticket «ticket»"],
    },
    "report_mail": {
        "en": ["Write a function that every Monday mails the sales report to «hon» «name» («title» at «company») at «email», cc «email2». Use the template in «path».",
               "I need to send the order summary out automatically to «hon» «name», «title», email «email», mobile «phone». Build me the script with smtplib, the account password is «password»"],
        "it": ["Scrivi una funzione che ogni lunedì manda il report vendite a «hon» «name» («title» di «company») all'indirizzo «email», in copia «email2». Usa il template in «path».",
               "devo mandare in automatico il riepilogo ordini a «hon» «name», «title», email «email», cell «phone». Fammi lo script con smtplib, la password dell'account è «password»"],
        "de": ["Schreib eine Funktion, die jeden Montag den Verkaufsbericht an «hon» «name» («title» bei «company») unter «email» schickt, in CC «email2». Nimm das Template aus «path».",
               "ich muss die Bestellübersicht automatisch an «hon» «name» schicken, «title», E-Mail «email», Handy «phone». Bau mir das Skript mit smtplib, das Passwort vom Konto ist «password»"],
        "fr": ["Écris une fonction qui envoie chaque lundi le rapport des ventes à «hon» «name» («title» chez «company») à l'adresse «email», en copie «email2». Utilise le template dans «path».",
               "je dois envoyer automatiquement le récap des commandes à «hon» «name», «title», email «email», portable «phone». Fais-moi le script avec smtplib, le mot de passe du compte est «password»"],
        "es": ["Escribe una función que cada lunes envíe el informe de ventas a «hon» «name» («title» en «company») a «email», con copia a «email2». Usa la plantilla de «path».",
               "tengo que mandar automáticamente el resumen de pedidos a «hon» «name», «title», email «email», móvil «phone». Hazme el script con smtplib, la contraseña de la cuenta es «password»"],
    },
    "git_author": {
        "en": ["The last commits have the wrong author. Rewrite the history of the last 3 commits with «name» <«email»> as the author. My profile is «purl».\n\n«name» – «title», «company»",
               "configure git in this repo with user.name «name» and user.email «email» and then push to origin, the token is «secret»"],
        "it": ["Gli ultimi commit risultano con l'autore sbagliato. Riscrivi la history degli ultimi 3 commit mettendo come autore «name» <«email»>. Il mio profilo è «purl».\n\n«name» – «title», «company»",
               "configura git in questo repo con user.name «name» e user.email «email» e poi fai il push su origin, il token è «secret»"],
        "de": ["Die letzten Commits haben den falschen Autor. Schreib die History der letzten 3 Commits um, Autor soll «name» <«email»> sein. Mein Profil: «purl».\n\n«name» – «title», «company»",
               "richte git in diesem Repo mit user.name «name» und user.email «email» ein und push dann auf origin, der Token ist «secret»"],
        "fr": ["Les derniers commits ont le mauvais auteur. Réécris l'historique des 3 derniers commits avec comme auteur «name» <«email»>. Mon profil : «purl».\n\n«name» – «title», «company»",
               "configure git dans ce repo avec user.name «name» et user.email «email» puis pousse sur origin, le token c'est «secret»"],
        "es": ["Los últimos commits salen con el autor equivocado. Reescribe el historial de los 3 últimos commits con autor «name» <«email»>. Mi perfil es «purl».\n\n«name» – «title», «company»",
               "configura git en este repo con user.name «name» y user.email «email» y luego haz push a origin, el token es «secret»"],
    },
    "deploy_server": {
        "en": ["Deploy to the new server: IP «ip», user «user», password «password». The code lives in «home». Then restart the service and check the logs. «name2» («title») gives the go-ahead.",
               "the vps «ip» isn't answering on port «port», ssh in as «user» (the key is in «keypath») and see what's going on with nginx"],
        "it": ["Fai il deploy sul server nuovo: IP «ip», utente «user», password «password». Il codice sta in «home». Dopo riavvia il servizio e controlla i log. Se serve un via libera, chiedi a «name2» («title»).",
               "il vps «ip» non risponde sulla porta «port», entra in ssh come «user» (la chiave è in «keypath») e guarda cosa succede con nginx"],
        "de": ["Deploy bitte auf den neuen Server: IP «ip», User «user», Passwort «password». Der Code liegt in «home». Danach den Dienst neu starten und die Logs prüfen. Freigabe gibt «name2» («title»).",
               "der VPS «ip» antwortet nicht auf Port «port», log dich per ssh als «user» ein (Key liegt in «keypath») und schau, was mit nginx los ist"],
        "fr": ["Déploie sur le nouveau serveur : IP «ip», utilisateur «user», mot de passe «password». Le code est dans «home». Ensuite redémarre le service et regarde les logs. Le feu vert vient de «name2» («title»).",
               "le vps «ip» ne répond plus sur le port «port», connecte-toi en ssh avec «user» (la clé est dans «keypath») et regarde ce qui se passe avec nginx"],
        "es": ["Haz el deploy en el servidor nuevo: IP «ip», usuario «user», contraseña «password». El código está en «home». Después reinicia el servicio y revisa los logs. El visto bueno lo da «name2» («title»).",
               "el vps «ip» no responde en el puerto «port», entra por ssh como «user» (la clave está en «keypath») y mira qué pasa con nginx"],
    },
    "paste_key": {
        "en": ["This is my «provider» key: «secret»\nconfigure the client in «path» and make a test call",
               "I've got the new key from «provider», replace it everywhere in the project:\n«secret»\n(the old one was «secret2»)"],
        "it": ["Questa è la mia chiave «provider»: «secret»\nconfigura il client in «path» e fai una chiamata di prova",
               "mi è arrivata la nuova chiave da «provider», sostituiscila ovunque nel progetto:\n«secret»\n(quella vecchia era «secret2»)"],
        "de": ["Das ist mein «provider»-Key: «secret»\nkonfigurier den Client in «path» und mach einen Testaufruf",
               "ich hab den neuen Key von «provider» bekommen, ersetz ihn überall im Projekt:\n«secret»\n(der alte war «secret2»)"],
        "fr": ["Voici ma clé «provider» : «secret»\nconfigure le client dans «path» et fais un appel de test",
               "j'ai reçu la nouvelle clé de «provider», remplace-la partout dans le projet :\n«secret»\n(l'ancienne c'était «secret2»)"],
        "es": ["Esta es mi clave de «provider»: «secret»\nconfigura el cliente en «path» y haz una llamada de prueba",
               "me ha llegado la clave nueva de «provider», sustitúyela en todo el proyecto:\n«secret»\n(la antigua era «secret2»)"],
    },
    "csv_import": {
        "en": ["Import these customers into the customers table, the separator is a semicolon:\n\n«rows»\nWatch out for duplicate emails."],
        "it": ["Importa questi clienti nella tabella customers, il separatore è il punto e virgola:\n\n«rows»\nAttenzione ai duplicati sull'email."],
        "de": ["Importier diese Kunden in die Tabelle customers, Trennzeichen ist Semikolon:\n\n«rows»\nAchte auf Duplikate bei der E-Mail."],
        "fr": ["Importe ces clients dans la table customers, le séparateur est le point-virgule :\n\n«rows»\nAttention aux doublons sur l'email."],
        "es": ["Importa estos clientes en la tabla customers, el separador es punto y coma:\n\n«rows»\nOjo con los duplicados por email."],
    },
    "gdpr_delete": {
        "en": ["A customer has asked for their data to be erased (GDPR art. 17): «hon» «name», born «birth», tax id «natid», email «email». Write a script that finds all their rows in the db and anonymises them."],
        "it": ["Un cliente ha chiesto la cancellazione dei dati (GDPR art. 17): «hon» «name», nato il «birth», codice fiscale «natid», email «email». Scrivi uno script che trovi tutte le sue righe nel db e le anonimizzi."],
        "de": ["Ein Kunde hat die Löschung seiner Daten verlangt (DSGVO Art. 17): «hon» «name», geboren am «birth», Steuer-ID «natid», E-Mail «email». Schreib ein Skript, das alle seine Zeilen in der DB findet und anonymisiert."],
        "fr": ["Un client a demandé l'effacement de ses données (RGPD art. 17) : «hon» «name», né le «birth», n° de sécu «natid», email «email». Écris un script qui retrouve toutes ses lignes en base et les anonymise."],
        "es": ["Un cliente ha pedido la supresión de sus datos (RGPD art. 17): «hon» «name», nacido el «birth», DNI «natid», email «email». Escribe un script que encuentre todas sus filas en la base de datos y las anonimice."],
    },
    "network": {
        "en": ["The device with MAC «mac» no longer takes an IP from DHCP. Our public IP is «ip», the gateway «priv». Check the dnsmasq config in «path». If you touch the firewall, tell «name2» («title»)."],
        "it": ["Il dispositivo con MAC «mac» non prende più l'IP dal DHCP. Il nostro IP pubblico è «ip», il gateway «priv». Controlla la config di dnsmasq in «path». Se tocchi il firewall avvisa «name2» («title»)."],
        "de": ["Das Gerät mit der MAC «mac» bekommt keine IP mehr per DHCP. Unsere öffentliche IP ist «ip», das Gateway «priv». Prüf die dnsmasq-Konfiguration in «path». Wenn du an die Firewall gehst, sag «name2» («title») Bescheid."],
        "fr": ["L'appareil avec la MAC «mac» ne récupère plus d'IP via DHCP. Notre IP publique est «ip», la passerelle «priv». Vérifie la config dnsmasq dans «path». Si tu touches au pare-feu, préviens «name2» («title»)."],
        "es": ["El dispositivo con MAC «mac» ya no recibe IP por DHCP. Nuestra IP pública es «ip», la puerta de enlace «priv». Revisa la configuración de dnsmasq en «path». Si tocas el firewall, avisa a «name2» («title»)."],
    },
    "invoice_bug": {
        "en": ["«company»'s invoice shows the wrong IBAN («iban») instead of the one of customer «account». The card payment «card» went through on «date». Fix the PDF template. Finance contact: «name2», «title»."],
        "it": ["La fattura di «company» mostra l'IBAN sbagliato («iban») invece di quello del cliente «account». Il pagamento con la carta «card» è andato a buon fine il «date». Correggi il template PDF. Referente amministrativo: «name2», «title»."],
        "de": ["Die Rechnung für «company» zeigt die falsche IBAN («iban») statt der von Kunde «account». Die Zahlung mit der Karte «card» ist am «date» durchgegangen. Korrigier bitte das PDF-Template. Ansprechpartnerin Buchhaltung: «name2», «title»."],
        "fr": ["La facture de «company» affiche le mauvais IBAN («iban») au lieu de celui du client «account». Le paiement par la carte «card» est passé le «date». Corrige le template PDF. Contact compta : «name2», «title»."],
        "es": ["La factura de «company» muestra el IBAN equivocado («iban») en vez del del cliente «account». El pago con la tarjeta «card» se hizo el «date». Corrige la plantilla PDF. Contacto de administración: «name2», «title»."],
    },
    "traceback": {
        "en": ["I get this error when I run the tests, any idea why?\n\n«tb»"],
        "it": ["Lanciando i test mi esce questo errore, sai perché?\n\n«tb»"],
        "de": ["Beim Ausführen der Tests kommt dieser Fehler, weißt du warum?\n\n«tb»"],
        "fr": ["En lançant les tests j'ai cette erreur, tu sais pourquoi ?\n\n«tb»"],
        "es": ["Al lanzar los tests me sale este error, ¿sabes por qué?\n\n«tb»"],
    },
    "refactor_clean": {
        "en": ["Rename «ident» to something clearer and update every reference. While you're at it bump «org» to «version» (see «url») and close «ticket». The key should be read from «envref», not hardcoded.",
               "The login page returns «status» since the upgrade to «version». Check «path» and the changelog at «url». No need to touch «ident»."],
        "it": ["Rinomina «ident» in qualcosa di più chiaro e aggiorna tutti i riferimenti. Già che ci sei aggiorna «org» alla «version» (vedi «url») e chiudi «ticket». La chiave va letta da «envref», non hardcodata.",
               "La pagina di login restituisce «status» dopo l'aggiornamento a «version». Controlla «path» e il changelog su «url». Non serve toccare «ident»."],
        "de": ["Benenn «ident» sinnvoller um und pass alle Referenzen an. Wenn du schon dabei bist: «org» auf «version» hochziehen (siehe «url») und «ticket» schließen. Der Key soll aus «envref» kommen, nicht hartkodiert.",
               "Die Login-Seite liefert nach dem Update auf «version» ein «status». Schau dir «path» und das Changelog unter «url» an. «ident» bitte nicht anfassen."],
        "fr": ["Renomme «ident» en quelque chose de plus clair et mets à jour toutes les références. Au passage, monte «org» en «version» (voir «url») et ferme «ticket». La clé doit venir de «envref», pas en dur.",
               "La page de login renvoie «status» depuis la mise à jour en «version». Regarde «path» et le changelog sur «url». Pas besoin de toucher à «ident»."],
        "es": ["Renombra «ident» a algo más claro y actualiza todas las referencias. De paso, sube «org» a la «version» (mira «url») y cierra «ticket». La clave tiene que leerse de «envref», no estar hardcodeada.",
               "La página de login devuelve «status» desde la actualización a «version». Revisa «path» y el changelog en «url». No hace falta tocar «ident»."],
    },
}

# ------------------------------------------------------------------ ticket families

TICKETS: dict[str, dict[str, list[str]]] = {
    "support": {
        "en": ["Ticket «tno» | «prio»\n«from_l»: «name» <«email»>\n«subj_l»: Order not received\n\nHello,\nI placed order «order» on «date» and nothing has arrived yet. The delivery address is «address». Could you call me back on «phone»?\n\nThanks,\n«given»\n\n[Internal note] Call «hon» «family» back before 6 pm – «agent»"],
        "it": ["Ticket «tno» | «prio»\n«from_l»: «name» <«email»>\n«subj_l»: Ordine non ricevuto\n\nBuongiorno,\nho effettuato l'ordine «order» il «date» ma non mi è ancora arrivato nulla. L'indirizzo di spedizione è «address». Potete richiamarmi al «phone»?\n\nGrazie,\n«given»\n\n[Nota interna] Richiamare «hon» «family» entro le 18 – «agent»"],
        "de": ["Ticket «tno» | «prio»\n«from_l»: «name» <«email»>\n«subj_l»: Bestellung nicht angekommen\n\nGuten Tag,\nich habe am «date» die Bestellung «order» aufgegeben, aber bisher ist nichts angekommen. Lieferadresse: «address». Können Sie mich unter «phone» zurückrufen?\n\nViele Grüße\n«given»\n\n[Interne Notiz] «hon» «family» bis 18 Uhr zurückrufen – «agent»"],
        "fr": ["Ticket «tno» | «prio»\n«from_l» : «name» <«email»>\n«subj_l» : Commande non reçue\n\nBonjour,\nj'ai passé la commande «order» le «date» mais je n'ai toujours rien reçu. L'adresse de livraison est «address». Pouvez-vous me rappeler au «phone» ?\n\nMerci,\n«given»\n\n[Note interne] Rappeler «hon» «family» avant 18h – «agent»"],
        "es": ["Ticket «tno» | «prio»\n«from_l»: «name» <«email»>\n«subj_l»: Pedido no recibido\n\nBuenos días,\nhice el pedido «order» el «date» y todavía no me ha llegado nada. La dirección de envío es «address». ¿Me pueden llamar al «phone»?\n\nGracias,\n«given»\n\n[Nota interna] Llamar a «hon» «family» antes de las 18:00 – «agent»"],
    },
    "jira_bug": {
        "en": ["«tno»: 500 error on CSV export\n«rep_l»: «name» («title»)\n«asg_l»: «name2»\n«env_l»: production, version «version», «org»\n\n«steps_l»:\n1. Log in as «email»\n2. Customers → Export\n\n«exp_l»: CSV file\n«act_l»: 500 error, in the logs:\n«logline»"],
        "it": ["«tno»: Errore 500 all'export CSV\n«rep_l»: «name» («title»)\n«asg_l»: «name2»\n«env_l»: produzione, versione «version», «org»\n\n«steps_l»:\n1. Login come «email»\n2. Clienti → Esporta\n\n«exp_l»: file CSV\n«act_l»: errore 500, nei log:\n«logline»"],
        "de": ["«tno»: Fehler 500 beim CSV-Export\n«rep_l»: «name» («title»)\n«asg_l»: «name2»\n«env_l»: Produktion, Version «version», «org»\n\n«steps_l»:\n1. Login als «email»\n2. Kunden → Exportieren\n\n«exp_l»: CSV-Datei\n«act_l»: Fehler 500, im Log:\n«logline»"],
        "fr": ["«tno» : Erreur 500 à l'export CSV\n«rep_l» : «name» («title»)\n«asg_l» : «name2»\n«env_l» : production, version «version», «org»\n\n«steps_l» :\n1. Connexion avec «email»\n2. Clients → Exporter\n\n«exp_l» : fichier CSV\n«act_l» : erreur 500, dans les logs :\n«logline»"],
        "es": ["«tno»: Error 500 al exportar CSV\n«rep_l»: «name» («title»)\n«asg_l»: «name2»\n«env_l»: producción, versión «version», «org»\n\n«steps_l»:\n1. Login como «email»\n2. Clientes → Exportar\n\n«exp_l»: archivo CSV\n«act_l»: error 500, en los logs:\n«logline»"],
    },
    "forwarded": {
        "en": ["«fwd»\n«from_l»: «name» <«email»>\n«date_l»: «date»\n«to_l»: «role»\n«subj_l»: New IBAN for refunds\n\nHello, please pay refunds into my new account «iban» from now on. My customer number is «account». For anything else: «phone».\n«name»\n«title», «company»\n«address»"],
        "it": ["«fwd»\n«from_l»: «name» <«email»>\n«date_l»: «date»\n«to_l»: «role»\n«subj_l»: Cambio IBAN per i rimborsi\n\nSalve, vi chiedo di accreditare i rimborsi sul nuovo conto «iban» intestato a me. Il mio codice cliente è «account». Per qualsiasi cosa: «phone».\n«name»\n«title», «company»\n«address»"],
        "de": ["«fwd»\n«from_l»: «name» <«email»>\n«date_l»: «date»\n«to_l»: «role»\n«subj_l»: Neue IBAN für Erstattungen\n\nHallo, bitte überweisen Sie Erstattungen künftig auf mein neues Konto «iban». Meine Kundennummer ist «account». Bei Fragen: «phone».\n«name»\n«title», «company»\n«address»"],
        "fr": ["«fwd»\n«from_l» : «name» <«email»>\n«date_l» : «date»\n«to_l» : «role»\n«subj_l» : Changement d'IBAN pour les remboursements\n\nBonjour, merci de verser les remboursements sur mon nouveau compte «iban». Mon numéro client est «account». Pour toute question : «phone».\n«name»\n«title», «company»\n«address»"],
        "es": ["«fwd»\n«from_l»: «name» <«email»>\n«date_l»: «date»\n«to_l»: «role»\n«subj_l»: Cambio de IBAN para reembolsos\n\nHola, por favor ingresen los reembolsos en mi nueva cuenta «iban». Mi número de cliente es «account». Para cualquier cosa: «phone».\n«name»\n«title», «company»\n«address»"],
    },
    "kyc": {
        "en": ["Identity check failed for customer «hon» «name» («account»).\n«birth_l»: «birth»\n«pass_l»: «passport»\n«dl_l»: «dl»\n«natid_l»: «natid»\nThe provider («org») answers «status». We need to work out whether the problem is the document format."],
        "it": ["Verifica identità fallita per il cliente «hon» «name» («account»).\n«birth_l»: «birth»\n«pass_l»: «passport»\n«dl_l»: «dl»\n«natid_l»: «natid»\nIl provider («org») risponde «status». Dobbiamo capire se il problema è nel formato del documento."],
        "de": ["Identitätsprüfung für Kunde «hon» «name» («account») fehlgeschlagen.\n«birth_l»: «birth»\n«pass_l»: «passport»\n«dl_l»: «dl»\n«natid_l»: «natid»\nDer Anbieter («org») antwortet mit «status». Wir müssen klären, ob das Dokumentformat das Problem ist."],
        "fr": ["Échec de la vérification d'identité pour le client «hon» «name» («account»).\n«birth_l» : «birth»\n«pass_l» : «passport»\n«dl_l» : «dl»\n«natid_l» : «natid»\nLe prestataire («org») répond «status». Il faut voir si le problème vient du format du document."],
        "es": ["Falló la verificación de identidad del cliente «hon» «name» («account»).\n«birth_l»: «birth»\n«pass_l»: «passport»\n«dl_l»: «dl»\n«natid_l»: «natid»\nEl proveedor («org») responde «status». Hay que ver si el problema es el formato del documento."],
    },
    "payment_dispute": {
        "en": ["Chargeback – order «order»\n«cust_l»: «hon» «name», «email»\nCard: «card»\nAmount: $«amount»\nThe customer says they did not authorise the payment on «date». They are asking for the refund to «iban»."],
        "it": ["Contestazione addebito – ordine «order»\n«cust_l»: «hon» «name», «email»\nCarta: «card»\nImporto: «amount» €\nIl cliente dice di non aver autorizzato il pagamento del «date». Chiede il rimborso su «iban»."],
        "de": ["Rückbuchung – Bestellung «order»\n«cust_l»: «hon» «name», «email»\nKarte: «card»\nBetrag: «amount» €\nDer Kunde sagt, er habe die Zahlung vom «date» nicht autorisiert. Erstattung bitte auf «iban»."],
        "fr": ["Contestation de paiement – commande «order»\n«cust_l» : «hon» «name», «email»\nCarte : «card»\nMontant : «amount} €\nLe client affirme ne pas avoir autorisé le paiement du «date». Il demande le remboursement sur «iban».".replace("«amount}", "«amount»")],
        "es": ["Disputa de cargo – pedido «order»\n«cust_l»: «hon» «name», «email»\nTarjeta: «card»\nImporte: «amount} €\nEl cliente dice que no autorizó el pago del «date». Pide el reembolso en «iban».".replace("«amount}", "«amount»")],
    },
    "access_issue": {
        "en": ["The user «email» (account «account») has not been able to log in since yesterday. Last successful login from «ip» on «date», then failed attempts from «ip2». 2FA is enabled on the number «phone». Can you check whether it is an automatic lock? Billing address on file: «address»."],
        "it": ["L'utente «email» (account «account») non riesce più ad accedere da ieri. Ultimo login riuscito da «ip» il «date», poi tentativi falliti da «ip2». Ha 2FA attiva sul numero «phone». Potete verificare se è un blocco automatico? Indirizzo di fatturazione registrato: «address»."],
        "de": ["Der Nutzer «email» (Konto «account») kommt seit gestern nicht mehr rein. Letzter erfolgreicher Login von «ip» am «date», danach Fehlversuche von «ip2». 2FA ist auf die Nummer «phone» eingerichtet. Könnt ihr prüfen, ob das eine automatische Sperre ist? Hinterlegte Rechnungsadresse: «address»."],
        "fr": ["L'utilisateur «email» (compte «account») n'arrive plus à se connecter depuis hier. Dernière connexion réussie depuis «ip» le «date», puis des échecs depuis «ip2». La 2FA est sur le numéro «phone». Vous pouvez vérifier si c'est un blocage automatique ? Adresse de facturation enregistrée : «address»."],
        "es": ["El usuario «email» (cuenta «account») no puede entrar desde ayer. Último login correcto desde «ip» el «date», luego intentos fallidos desde «ip2». Tiene 2FA en el número «phone». ¿Podéis ver si es un bloqueo automático? Dirección de facturación registrada: «address»."],
    },
    "address_change": {
        "en": ["Request from «hon» «name»: change the delivery address from «address» to «address2». Tel. «phone». Order reference «order»."],
        "it": ["Richiesta di «hon» «name»: cambiare l'indirizzo di spedizione da «address» a «address2». Tel. «phone». Riferimento ordine «order»."],
        "de": ["Anfrage von «hon» «name»: Lieferadresse von «address» auf «address2» ändern. Tel. «phone». Bestellreferenz «order»."],
        "fr": ["Demande de «hon» «name» : changer l'adresse de livraison de «address» à «address2». Tél. «phone». Référence commande «order»."],
        "es": ["Solicitud de «hon» «name»: cambiar la dirección de envío de «address» a «address2». Tel. «phone». Referencia del pedido «order»."],
    },
    "security_report": {
        "en": ["Security report: in commit «sha» by «name» a key ended up in plaintext in «path»:\n«secret»\nIt has to be revoked straight away. The author's GitHub profile is «ghurl»."],
        "it": ["Segnalazione sicurezza: nel commit «sha» di «name» è finita una chiave in chiaro nel file «path»:\n«secret»\nVa revocata subito. Il profilo GitHub dell'autore è «ghurl»."],
        "de": ["Security-Meldung: Im Commit «sha» von «name» ist ein Schlüssel im Klartext in «path» gelandet:\n«secret»\nMuss sofort widerrufen werden. GitHub-Profil des Autors: «ghurl»."],
        "fr": ["Signalement sécurité : dans le commit «sha» de «name», une clé en clair s'est retrouvée dans «path» :\n«secret»\nIl faut la révoquer tout de suite. Profil GitHub de l'auteur : «ghurl»."],
        "es": ["Aviso de seguridad: en el commit «sha» de «name» se coló una clave en claro en «path»:\n«secret»\nHay que revocarla ya. Perfil de GitHub del autor: «ghurl»."],
    },
    "feature_clean": {
        "en": ["«tno»: Support export in «org» format\nAs «title» I would like to export orders over the API as well. Proposal: a new endpoint «path» from version «version», authentication with «envref». Due: «date». References: «url», «ticket»."],
        "it": ["«tno»: Supporto per l'export in formato «org»\nCome «title» vorrei poter esportare gli ordini anche via API. Proposta: nuovo endpoint «path» dalla versione «version», autenticazione con «envref». Scadenza: «date». Riferimenti: «url», «ticket»."],
        "de": ["«tno»: Export im «org»-Format unterstützen\nAls «title» möchte ich Bestellungen auch per API exportieren. Vorschlag: neuer Endpunkt «path» ab Version «version», Authentifizierung über «envref». Fällig: «date». Referenzen: «url», «ticket»."],
        "fr": ["«tno» : Prise en charge de l'export au format «org»\nEn tant que «title», je voudrais exporter les commandes via l'API. Proposition : nouvel endpoint «path» à partir de la version «version», authentification via «envref». Échéance : «date». Références : «url», «ticket»."],
        "es": ["«tno»: Soporte de exportación en formato «org»\nComo «title» quiero exportar los pedidos también por API. Propuesta: nuevo endpoint «path» desde la versión «version», autenticación con «envref». Fecha límite: «date». Referencias: «url», «ticket»."],
    },
}

PROMPT_CLEAN_OK = {"refactor_clean", "paste_key", "report_mail", "debug_db", "traceback", "network"}
TICKET_CLEAN_OK = {"feature_clean", "jira_bug", "security_report", "access_issue"}
PROVIDERS = ["Stripe", "OpenAI", "SendGrid", "Twilio", "Mailgun", "GitHub", "Google Maps", "Anthropic", "Slack", "HubSpot"]


# ------------------------------------------------------------------ slot builders

def _env_block(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    d.add("DATABASE_URL=postgres://app:", ctx.password(), "@", ctx.amb("internal_host"), ":", KP("5432", "port"), "/app\n")
    for s in [ctx.secret() for _ in range(r.randint(1, 3))]:
        d.extend(ctx.secret_line(s, "env"))
        d.add("\n")
    if r.random() < 0.5:
        d.add("ADMIN_EMAIL=", ctx.email(ctx.person()), "\n")
    return d


def _err_line(ctx: Ctx) -> Doc:
    r = ctx.rng
    return frag("psycopg2.OperationalError: connection to server at \"", ctx.amb("internal_host"), "\" (", ctx.private_ip(), "), port ", KP("5432", "port"),
                " failed: FATAL:  password authentication failed for user \"app\"")


def _traceback(ctx: Ctx, p) -> Doc:
    r = ctx.rng
    proj = r.choice(APPS)
    d = Doc()
    d.add("Traceback (most recent call last):\n  File \"")
    d.extend(home_path(ctx, p, f"{r.choice(['progetti', 'Projekte', 'projets', 'proyectos', 'dev'])}/{proj}/tests/test_api.py"))
    d.add("\", line ", KP(str(r.randint(10, 300)), "line_number"), ", in ", KP("test_create_customer", "code_identifier"), "\n    resp = client.post(\"/customers\", json=payload)\n  File \"")
    d.extend(home_path(ctx, p, f"{r.choice(['progetti', 'Projekte', 'projets', 'proyectos', 'dev'])}/{proj}/app/api.py"))
    c = ctx.person()
    d.add("\", line ", KP(str(r.randint(10, 300)), "line_number"), ", in ", KP("create_customer", "code_identifier"), "\n    validate_vat(payload[\"vat\"])\nValueError: invalid tax id '",
          ctx.national_id(c), "' for ", ctx.email(c))
    return d


def _csv_rows(ctx: Ctx) -> Doc:
    r = ctx.rng
    d = Doc()
    d.add("nome;email;telefono;indirizzo\n" if ctx.lang == "it" else ("name;email;phone;address\n"))
    for _ in range(r.randint(2, 5)):
        p = ctx.person()
        d.add(ctx.name(p), ";", ctx.email(p), ";", ctx.phone(), ";", ctx.address(), "\n")
    return d


def _logline(ctx: Ctx) -> Doc:
    r = ctx.rng
    return frag(ctx.kp("log_ts"), " ERROR export failed for user=", ctx.email(ctx.person()), " ip=", ctx.ip(), " request_id=", ctx.kp("uuid"))


PROVIDER_NAMES = {"github": "GitHub", "gitlab": "GitLab", "openai": "OpenAI", "aws": "AWS", "gcp": "Google Cloud", "npm": "npm",
                  "pypi": "PyPI", "huggingface": "Hugging Face", "sendgrid": "SendGrid", "digitalocean": "DigitalOcean", "jwt": "Auth0",
                  "private": "SSH", "generic": "API", "curl": "API", "kubernetes": "Kubernetes", "hashicorp": "HashiCorp", "1password": "1Password",
                  "new": "New Relic", "linkedin": "LinkedIn", "facebook": "Facebook", "planetscale": "PlanetScale", "launchdarkly": "LaunchDarkly",
                  "mailchimp": "Mailchimp", "mailgun": "Mailgun", "hubspot": "HubSpot", "nuget": "NuGet", "rubygems": "RubyGems", "flyio": "Fly.io"}


def provider_of(rule: str) -> str:
    head = rule.split("-")[0]
    return PROVIDER_NAMES.get(head, head.capitalize())


def _secret_v(ctx: Ctx, holder: dict | None = None) -> V | Doc:
    s = ctx.secret()
    if holder is not None and "provider" not in holder:
        holder["provider"] = s.rule
    if s.is_pem:
        return ctx.pem_doc(s)
    return ctx.secret_value(s)


def _birth(ctx: Ctx) -> V:
    y, m, d = VV.birth_date(ctx.rng)
    return AM(K.birth_date_str(ctx.lang, y, m, d, ctx.rng), "birth_date")


FAMILY_PATHS = {
    "add_customer_test": ["tests/test_invoice.py", "tests/billing/test_pdf.py", "tests/fixtures/customers.py"],
    "report_mail": ["templates/report.html", "templates/email/weekly_report.html", "app/reports/mail.py"],
    "paste_key": ["src/config.ts", "app/settings.py", ".env.local", "config/services.yml", "src/lib/client.js"],
    "network": ["/etc/dnsmasq.conf", "/etc/dnsmasq.d/lan.conf", "/opt/router/dhcp.conf"],
    "refactor_clean": ["src/auth/login.ts", "app/views/login.py", "web/src/pages/Login.vue"],
    "security_report": ["config/settings.py", ".env.production", "deploy/values.yaml", "src/config/index.ts"],
    "feature_clean": ["/api/v2/exports", "/api/v1/orders/export", "/v2/reports/orders.csv"],
}


def build_slots(ctx: Ctx, needed: set[str], family: str = "") -> dict:
    r = ctx.rng
    lang = ctx.lang
    p = ctx.person()
    s: dict = {}
    info: dict = {}
    lazy = {
        "name": lambda: ctx.name(p), "given": lambda: ctx.given(p), "family": lambda: ctx.name(p, "family_name"),
        "agent": lambda: ctx.given(ctx.person()), "email": lambda: ctx.email(p), "email2": lambda: ctx.email(ctx.person()),
        "phone": lambda: ctx.phone(), "address": lambda: ctx.address(), "address2": lambda: ctx.address(), "iban": lambda: ctx.iban(),
        "card": lambda: ctx.card(), "natid": lambda: ctx.national_id(p), "passport": lambda: ctx.passport(), "dl": lambda: ctx.driver_license(p),
        "account": lambda: ctx.account(), "ip": lambda: ctx.ip(), "ip2": lambda: ctx.ip(), "priv": lambda: ctx.private_ip(), "mac": lambda: ctx.mac(),
        "purl": lambda: ctx.purl(p), "password": lambda: ctx.password(p), "secret": lambda: _secret_v(ctx, info), "secret2": lambda: _secret_v(ctx),
        "user": lambda: ctx.user(p), "home": lambda: home_path(ctx, p, f"apps/{r.choice(APPS)}"), "keypath": lambda: KP("~/.ssh/id_ed25519", "path"),
        "port": lambda: ctx.kp("port"), "env": lambda: _env_block(ctx), "err": lambda: _err_line(ctx), "tb": lambda: _traceback(ctx, p),
        "rows": lambda: _csv_rows(ctx), "logline": lambda: _logline(ctx), "birth": lambda: _birth(ctx),
        "hon": lambda: ctx.honorific(p.gender), "title": lambda: ctx.kp("job_title"), "company": lambda: ctx.company(),
        "org": lambda: ctx.kp("org"), "name2": lambda: ctx.name(ctx.person()), "path": lambda: KP(r.choice(FAMILY_PATHS.get(family, ["src/config.ts", "app/settings.py"])), "path"),
        "ticket": lambda: ctx.kp("ticket_number"), "envref": lambda: ctx.kp("env_ref"),
        "ghurl": lambda: (KP(K.public_url(r), "public_url") if ctx.clean else MM("https://github.com/" + VV.handle(r, p), "url", "personal_url")), "tno": lambda: KP(r.choice([f"#{r.randint(10000, 99999)}", f"SUP-{r.randint(100, 9999)}", f"PROJ-{r.randint(10, 999)}"]), "ticket_number"),
        "order": lambda: ctx.amb("order_number"), "date": lambda: ctx.kp("date"), "version": lambda: ctx.kp("version"), "url": lambda: ctx.kp("public_url"),
        "status": lambda: ctx.kp("http_status"), "ident": lambda: ctx.kp("code_identifier"), "role": lambda: ctx.amb("role_address"),
        "sha": lambda: ctx.kp("short_sha", value=K.short_sha(r, 7)), "provider": lambda: KP(provider_of(info["provider"]) if "provider" in info else r.choice(PROVIDERS), "org"),
        "amount": lambda: P(f"{r.uniform(9, 1900):.2f}".replace(".", "," if lang != "en" else ".")),
        "prio": lambda: P(L("priority", lang)),
    }
    for key, lab in [("from_l", "from"), ("to_l", "to"), ("date_l", "date"), ("subj_l", "subject"), ("rep_l", "reporter"), ("asg_l", "assignee"), ("env_l", "env"),
                     ("steps_l", "steps"), ("exp_l", "expected"), ("act_l", "actual"), ("fwd", "fwd"), ("birth_l", "birth"), ("natid_l", "natid"),
                     ("pass_l", "passport"), ("dl_l", "dl"), ("cust_l", "customer")]:
        lazy[key] = (lambda lab=lab: P(L(lab, lang)))
    for k in sorted(needed, key=lambda k: (k != "secret", k)):
        s[k] = lazy[k]()
    return s


def _needed(t: str) -> set[str]:
    import re
    return set(re.findall(r"«(\w+)»", t))


def _render(ctx: Ctx, table: dict, clean_ok: set[str]) -> tuple[Doc, str]:
    r = ctx.rng
    fams = sorted(table)
    if ctx.clean:
        fams = sorted(clean_ok)
    fam = r.choice(fams)
    t = r.choice(table[fam][ctx.lang])
    slots = build_slots(ctx, _needed(t), fam)
    d = Doc()
    d.fmt(t, **slots)
    em = slots.get("email")
    if isinstance(em, V) and em.cls == "MUST_MASK":
        reset = {"en": "Reset password link: ", "it": "Link reset password: ", "de": "Link zum Zurücksetzen: ",
                 "fr": "Lien de réinitialisation : ", "es": "Enlace para restablecer: "}[ctx.lang]
        add_hook(d, em, render_query_line("\n" + reset, "https://accounts.shopfront.io/reset", "email", "\n"), "lang_reset_link")
    return d, fam


def generate_prompt(ctx: Ctx) -> tuple[Doc, str]:
    d, fam = _render(ctx, PROMPTS, PROMPT_CLEAN_OK)
    ctx.finish(d)
    return d, fam


def generate_ticket(ctx: Ctx) -> tuple[Doc, str]:
    d, fam = _render(ctx, TICKETS, TICKET_CLEAN_OK)
    ctx.finish(d)
    return d, fam
