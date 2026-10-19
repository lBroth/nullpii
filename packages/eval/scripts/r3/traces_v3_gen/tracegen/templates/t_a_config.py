# SPDX-License-Identifier: Apache-2.0
"""Templates centred on infrastructure and application configuration files."""

from __future__ import annotations

import base64

from ..core import F, J, T, Seg, esc_json, grid, lines, numbered, table
from ..phrases import say
from . import template


def _b64_secret(d, seg: Seg) -> Seg:
    """Kubernetes `data:` value: base64 of a secret; the encoded form is the secret."""
    if seg.label == "secret":
        return Seg(base64.b64encode(seg.text.encode()).decode(), label="secret")
    return d.x.ph("api_key", "${BASE64_VALUE}")


@template("k8s_manifests", "xml", "file", "shell")
def k8s_manifests(d):
    g, x, r = d.g, d.x, d.rng
    ns = r.choice(["prod", "staging", "payments", "backend", "apps"])
    app = d.project
    pw = g.password()
    wrong, right = r.choice([("DATABASE_PASSWORD", "DB_PASSWORD"), ("SMTP_PASS", "SMTP_PASSWORD"),
                             ("API_TOKEN", "UPSTREAM_API_TOKEN")])
    d.user(T(d.L(
        en="⟦app⟧ is stuck in CrashLoopBackOff since we moved the config into a Secret. Manifests are in k8s/, can you take a look?",
        it="⟦app⟧ è in CrashLoopBackOff da quando abbiamo spostato la config in un Secret. I manifest sono in k8s/, ci dai un'occhiata?",
        de="⟦app⟧ hängt in CrashLoopBackOff, seit wir die Konfiguration in ein Secret verschoben haben. Die Manifeste liegen in k8s/, schaust du mal?",
        fr="⟦app⟧ est en CrashLoopBackOff depuis qu'on a déplacé la config dans un Secret. Les manifestes sont dans k8s/, tu peux regarder ?",
        es="⟦app⟧ está en CrashLoopBackOff desde que movimos la config a un Secret. Los manifiestos están en k8s/, ¿le echas un vistazo?"), app=app))
    d.tool("glob", "k8s/**/*.yaml", lines("k8s/deployment.yaml", "k8s/service.yaml", "k8s/secret.yaml",
                                          "k8s/ingress.yaml", *(["k8s/hpa.yaml"] if r.random() < 0.5 else [])))
    owner = d.me
    smtp_pw = g.password()
    secret_rows = [
        "apiVersion: v1", "kind: Secret", "metadata:", f"  name: {app}-env", f"  namespace: {ns}",
        "  annotations:", T("    contact: ⟦e⟧", e=g.email(owner)),
        "type: Opaque", "stringData:",
        T("  ⟦k⟧: ⟦v⟧", k=right, v=pw if right != "UPSTREAM_API_TOKEN" else g.secret(r.choice(["bearer_opaque", "github_pat", "openai"]))),
        T("  REDIS_URL: redis://:⟦pw⟧@⟦ip⟧:⟦p⟧/1", pw=g.password(), ip=g.ip("private"), p=x.port(6379)),
        T("  SENTRY_DSN: ⟦s⟧", s=g.secret("sentry_dsn")),
        "data:",
        T("  SMTP_PASSWORD_B64: ⟦v⟧", v=_b64_secret(d, smtp_pw)),
    ]
    d.tool("read", "k8s/secret.yaml", lines(*secret_rows))
    image_ver = x.ver()
    dep = [
        "apiVersion: apps/v1", "kind: Deployment", "metadata:", f"  name: {app}", f"  namespace: {ns}",
        "  labels:", f"    app.kubernetes.io/name: {app}",
        "  annotations:", T("    maintainer: \"⟦n⟧ <⟦e⟧>\"", n=g.name(owner), e=g.email(owner)),
        "spec:", f"  replicas: {r.choice([2, 3, 4])}", "  template:", "    spec:",
    ]
    if r.random() < 0.5:
        dep += ["      hostAliases:", T("        - ip: \"⟦ip⟧\"", ip=g.ip("private")),
                "          hostnames: [\"legacy-erp.local\"]"]
    dep += ["      containers:", f"        - name: {app}",
            T("          image: registry.⟦dom⟧/⟦app⟧:⟦v⟧", dom=d.int_domain, app=app, v=image_ver),
            "          ports:", T("            - containerPort: ⟦p⟧", p=x.port(8080)),
            "          env:", f"            - name: {wrong}", "              valueFrom:", "                secretKeyRef:",
            f"                  name: {app}-env", f"                  key: {wrong}",
            "          envFrom:", "            - secretRef:", f"                name: {app}-env",
            "          readinessProbe:", "            httpGet:", "              path: /healthz",
            T("              port: ⟦p⟧", p=x.port(8080))]
    d.tool("read", "k8s/deployment.yaml", lines(*dep))
    pods = [["NAME", "READY", "STATUS", "RESTARTS", "AGE", "IP", "NODE"]]
    for i in range(r.randint(2, 4)):
        suffix = x.short(10).text[:10] + "-" + x.short(5).text[:5]
        pods.append([f"{app}-{suffix}", "0/1", r.choice(["CrashLoopBackOff", "Error", "CrashLoopBackOff"]),
                     f"{r.randint(3, 40)} ({r.randint(1, 50)}s ago)", f"{r.randint(5, 59)}m", g.ip("private"),
                     f"ip-node-{r.randint(1, 9)}"])
    d.tool("sh", f"kubectl -n {ns} get pods -o wide -l app.kubernetes.io/name={app}", table(pods, gap=3))
    if r.random() < 0.5:
        ev = [["LAST SEEN", "TYPE", "REASON", "OBJECT", "MESSAGE"]]
        for _ in range(r.randint(4, 24)):
            reason, typ, msg = r.choice([
                ("BackOff", "Warning", "Back-off restarting failed container"),
                ("Pulled", "Normal", "Container image already present on machine"),
                ("Started", "Normal", "Started container " + app),
                ("Unhealthy", "Warning", "Readiness probe failed: connection refused"),
                ("Scheduled", "Normal", "Successfully assigned to node"),
                ("Killing", "Normal", "Stopping container " + app)])
            ev.append([f"{r.randint(1, 59)}{r.choice('sm')}", typ, reason, F("pod/", app, "-", x.short(10)), msg])
        d.tool("sh", f"kubectl -n {ns} get events --sort-by=.lastTimestamp | tail -n {len(ev) - 1}", table(ev, gap=3))
    d.tool("sh", f"kubectl -n {ns} logs deploy/{app} --previous --tail=6",
           lines(T("⟦t⟧ INFO  boot: loading configuration (profile=⟦ns⟧)", t=x.ts("iso_z", tick=(1, 3)), ns=ns),
                 T("⟦t⟧ ERROR config: required environment variable ⟦k⟧ is not set", t=x.ts("iso_z", tick=(0, 1)), k=right),
                 T("⟦t⟧ FATAL exiting with status 78", t=x.ts("iso_z", tick=(0, 1)))))
    d.agent(say(d, "explain"), "\n",
            T(d.L(en="the Deployment maps the secret key `⟦w⟧`, but secret.yaml defines `⟦k⟧`. The `secretKeyRef` fails to resolve and the app exits before the readiness probe.",
                  it="il Deployment mappa la chiave `⟦w⟧`, ma secret.yaml definisce `⟦k⟧`. Il `secretKeyRef` non si risolve e l'app esce prima della readiness probe.",
                  de="das Deployment referenziert den Key `⟦w⟧`, secret.yaml definiert aber `⟦k⟧`. Der `secretKeyRef` lässt sich nicht auflösen und die App beendet sich vor der Readiness-Probe.",
                  fr="le Deployment référence la clé `⟦w⟧`, mais secret.yaml définit `⟦k⟧`. Le `secretKeyRef` ne se résout pas et l'appli s'arrête avant la readiness probe.",
                  es="el Deployment referencia la clave `⟦w⟧`, pero secret.yaml define `⟦k⟧`. El `secretKeyRef` no se resuelve y la app termina antes de la readiness probe."), w=wrong, k=right))
    d.tool("edit", "k8s/deployment.yaml",
           lines(f"@@ env:", f"             - name: {right}", "               valueFrom:", "                 secretKeyRef:",
                 f"                   name: {app}-env", f"-                  key: {wrong}", f"+                  key: {right}"))
    d.tool("sh", f"kubectl apply -f k8s/ && kubectl -n {ns} rollout status deploy/{app} --timeout=120s",
           lines(f"deployment.apps/{app} configured", f"service/{app} unchanged", f"secret/{app}-env unchanged",
                 f"ingress.networking.k8s.io/{app} unchanged", f"Waiting for deployment \"{app}\" rollout to finish: 1 of 3 updated replicas are available...",
                 f"deployment \"{app}\" successfully rolled out"))
    if r.random() < 0.7:
        d.agent(say(d, "secret_warning", x="k8s/secret.yaml"), " ",
                T(d.L(en="Consider ⟦a⟧ or ⟦b⟧ so the plaintext never lands in git.",
                      it="Valuta ⟦a⟧ o ⟦b⟧, così il testo in chiaro non finisce in git.",
                      de="Überleg dir ⟦a⟧ oder ⟦b⟧, damit der Klartext nie im Git landet.",
                      fr="Pense à ⟦a⟧ ou ⟦b⟧ pour que le clair ne finisse jamais dans git.",
                      es="Plantéate ⟦a⟧ o ⟦b⟧ para que el texto plano no acabe en git."),
                  a=x.ent("Sealed Secrets"), b=x.ent("External Secrets Operator")),
                "\n", x.url("docs", "https://kubernetes.io/docs/concepts/configuration/secret/"))
    d.user(say(d, "thanks"))


@template("django_settings_admins", "md", "file", "trace")
def django_settings_admins(d):
    g, x, r = d.g, d.x, d.rng
    admins = d.people(r.randint(2, 4))
    mailbox = d.person()
    ver = r.choice(["5.0.6", "5.1.2", "4.2.16"])
    d.user(T(d.L(
        en="Since the upgrade to ⟦dj⟧ ⟦v⟧ nobody gets the 500 error mails anymore. Can you figure out why?",
        it="Dopo l'aggiornamento a ⟦dj⟧ ⟦v⟧ nessuno riceve più le mail degli errori 500. Riesci a capire perché?",
        de="Seit dem Upgrade auf ⟦dj⟧ ⟦v⟧ bekommt niemand mehr die Mails zu 500er-Fehlern. Findest du raus, warum?",
        fr="Depuis la mise à jour vers ⟦dj⟧ ⟦v⟧, plus personne ne reçoit les mails d'erreur 500. Tu peux trouver pourquoi ?",
        es="Desde la actualización a ⟦dj⟧ ⟦v⟧ nadie recibe los correos de errores 500. ¿Puedes averiguar por qué?"),
        dj=x.ent("Django"), v=x.ver(ver)))
    d.agent(say(d, "look_first", x="config/settings/production.py"))
    port = r.choice([465, 587])
    use_ssl = port == 465 and r.random() < 0.5
    admin_rows = J("\n", [T("    (\"⟦n⟧\", \"⟦e⟧\"),", n=g.name(p), e=g.email(p)) for p in admins])
    settings = T('''from .base import *  # noqa

DEBUG = False
SECRET_KEY = "⟦sk⟧"
ALLOWED_HOSTS = ["api.⟦dom⟧", "⟦ip⟧", "localhost"]

ADMINS = [
⟦admins⟧
]
MANAGERS = ADMINS

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "⟦db⟧",
        "USER": "⟦db⟧_rw",
        "PASSWORD": "⟦dbpw⟧",
        "HOST": "⟦dbip⟧",
        "PORT": "⟦dbport⟧",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.⟦dom⟧"
EMAIL_PORT = ⟦port⟧
EMAIL_USE_TLS = ⟦tls⟧
EMAIL_HOST_USER = "⟦mailuser⟧"
EMAIL_HOST_PASSWORD = env("SMTP_PASSWORD", default="⟦mailpw⟧")
''', sk=g.secret("django_secret"), dom=d.domain, ip=g.ip("public"), admins=admin_rows, db=d.project.replace("-", "_"),
        dbpw=g.password(), dbip=g.ip("private"), dbport=x.port(5432), port=x.port(port), tls="True" if not use_ssl else "False",
        mailuser=g.email(mailbox), mailpw=g.password())
    d.tool("read", "config/settings/production.py", numbered(settings))
    d.agent(d.L(en="The settings look plausible; let me send a test mail to the admins and see what the SMTP server says.",
                it="I settings sembrano plausibili; mando una mail di prova agli admin e vediamo cosa risponde il server SMTP.",
                de="Die Settings sehen plausibel aus; ich schicke eine Testmail an die Admins und schaue, was der SMTP-Server sagt.",
                fr="Les settings ont l'air corrects ; j'envoie un mail de test aux admins pour voir ce que répond le serveur SMTP.",
                es="Los settings parecen correctos; envío un correo de prueba a los admins para ver qué responde el servidor SMTP."))
    venv = F(d.home(), "/.virtualenvs/", d.project, "/lib/python3.12/site-packages")
    err = r.choice(["auth", "ssl"]) if not use_ssl else "ssl"
    tb = [
        "Traceback (most recent call last):",
        T('  File "⟦v⟧/django/core/management/base.py", line ⟦n⟧, in run_from_argv', v=venv, n=x.num(lo=380, hi=420)),
        "    self.execute(*args, **cmd_options)",
        T('  File "⟦v⟧/django/core/mail/message.py", line ⟦n⟧, in send', v=venv, n=x.num(lo=290, hi=310)),
        "    return self.get_connection(fail_silently).send_messages([self])",
        T('  File "⟦v⟧/django/core/mail/backends/smtp.py", line ⟦n⟧, in open', v=venv, n=x.num(lo=80, hi=95)),
        "    self.connection.login(self.username, self.password)",
    ]
    if err == "auth":
        tb += ['  File "/usr/lib/python3.12/smtplib.py", line 750, in login',
               "    raise last_exception",
               "smtplib.SMTPAuthenticationError: (535, b'5.7.8 Username and Password not accepted. Credentials rejected')"]
    else:
        tb += ['  File "/usr/lib/python3.12/smtplib.py", line 398, in getreply',
               "    raise SMTPServerDisconnected(\"Connection unexpectedly closed\")",
               "smtplib.SMTPServerDisconnected: Connection unexpectedly closed"]
    d.tool("sh", "python manage.py sendtestemail --admins --settings=config.settings.production", lines(*tb))
    if err == "auth":
        d.agent(say(d, "explain"), "\n\n",
                d.L(en="`SMTP_PASSWORD` is not set in the new container image, so the hard-coded default in the settings file is used — and that one was revoked. The fallback should go away entirely.",
                    it="`SMTP_PASSWORD` non è impostata nella nuova immagine, quindi viene usato il default scritto nel file di settings, che è stato revocato. Il fallback va eliminato del tutto.",
                    de="`SMTP_PASSWORD` ist im neuen Image nicht gesetzt, deshalb greift der hartkodierte Default aus den Settings — und der wurde widerrufen. Der Fallback sollte ganz weg.",
                    fr="`SMTP_PASSWORD` n'est pas définie dans la nouvelle image, donc c'est la valeur par défaut codée en dur qui est utilisée — et elle a été révoquée. Il faut supprimer ce fallback.",
                    es="`SMTP_PASSWORD` no está definida en la nueva imagen, así que se usa el valor por defecto escrito en settings, que fue revocado. Hay que quitar ese fallback."))
        d.tool("edit", "config/settings/production.py",
               lines("-EMAIL_HOST_PASSWORD = env(\"SMTP_PASSWORD\", default=\"…\")", "+EMAIL_HOST_PASSWORD = env(\"SMTP_PASSWORD\")"))
    else:
        d.agent(say(d, "explain"), "\n\n",
                T(d.L(en="port ⟦p⟧ expects implicit TLS, but the settings enable STARTTLS. With ⟦dj⟧ ⟦v⟧ that combination closes the connection right away; use `EMAIL_USE_SSL = True` and drop `EMAIL_USE_TLS`.",
                      it="la porta ⟦p⟧ richiede TLS implicito, ma i settings attivano STARTTLS. Con ⟦dj⟧ ⟦v⟧ la connessione viene chiusa subito; serve `EMAIL_USE_SSL = True` senza `EMAIL_USE_TLS`.",
                      de="Port ⟦p⟧ erwartet implizites TLS, die Settings aktivieren aber STARTTLS. Mit ⟦dj⟧ ⟦v⟧ wird die Verbindung sofort geschlossen; richtig ist `EMAIL_USE_SSL = True` ohne `EMAIL_USE_TLS`.",
                      fr="le port ⟦p⟧ attend du TLS implicite, mais les settings activent STARTTLS. Avec ⟦dj⟧ ⟦v⟧ la connexion est fermée tout de suite ; il faut `EMAIL_USE_SSL = True` sans `EMAIL_USE_TLS`.",
                      es="el puerto ⟦p⟧ espera TLS implícito, pero los settings activan STARTTLS. Con ⟦dj⟧ ⟦v⟧ la conexión se cierra enseguida; hay que usar `EMAIL_USE_SSL = True` sin `EMAIL_USE_TLS`."),
                  p=x.port(port), dj=x.ent("Django"), v=x.ver(ver)),
                "\n", x.url("docs", "https://docs.djangoproject.com/en/5.0/ref/settings/"))
        d.tool("edit", "config/settings/production.py",
               lines("-EMAIL_USE_TLS = True", "+EMAIL_USE_SSL = True", "+EMAIL_TIMEOUT = 10"))
    d.tool("sh", "python manage.py sendtestemail --admins --settings=config.settings.production",
           lines(T("1 message sent to ⟦n⟧ recipient(s)", n=x.num(len(admins)))))
    if r.random() < 0.5:
        d.user(say(d, "anything_else"))
        d.agent(say(d, "secret_warning", x="SECRET_KEY"), " ",
                d.L(en="It should come from the environment like the other credentials.",
                    it="Dovrebbe arrivare dall'ambiente come le altre credenziali.",
                    de="Er sollte wie die anderen Zugangsdaten aus der Umgebung kommen.",
                    fr="Elle devrait venir de l'environnement comme les autres identifiants.",
                    es="Debería venir del entorno como las demás credenciales."))
    else:
        d.agent(say(d, "not_committed"))


@template("gha_deploy_failure", "colon", "file", "log")
def gha_deploy_failure(d):
    g, x, r = d.g, d.x, d.rng
    actor = d.me
    run_id = x.num(lo=4_000_000_000, hi=9_999_999_999)
    server_ip = g.ip("public")
    d.user(T(d.L(en="Deploy workflow on main failed again (run ⟦id⟧). What's wrong?",
                 it="Il workflow di deploy su main è fallito di nuovo (run ⟦id⟧). Cosa non va?",
                 de="Der Deploy-Workflow auf main ist wieder fehlgeschlagen (Run ⟦id⟧). Was ist los?",
                 fr="Le workflow de déploiement sur main a encore échoué (run ⟦id⟧). Qu'est-ce qui cloche ?",
                 es="El workflow de deploy en main ha vuelto a fallar (run ⟦id⟧). ¿Qué pasa?"), id=run_id))
    hook = g.secret("slack_webhook") if d.secret_ok else x.ph("url", "$SLACK_WEBHOOK_URL")
    wf = T('''name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@⟦v1⟧
      - uses: actions/setup-node@⟦v2⟧
        with:
          node-version: 20
      - run: npm ci && npm run build
      - name: Upload over SSH
        uses: appleboy/ssh-action@⟦v3⟧
        with:
          host: ⟦ip⟧
          username: deploy
          key: ${{ secrets.DEPLOY_KEY }}
          port: ⟦port⟧
          script: |
            cd /srv/⟦proj⟧ && ./release.sh ${{ github.sha }}
      - name: Notify
        if: always()
        run: |
          curl -s -X POST -H 'Content-type: application/json' \\
            --data '{"text":"deploy ${{ job.status }} by ${{ github.actor }}"}' \\
            ⟦hook⟧
''', v1=x.ver("v4"), v2=x.ver("v4"), v3=x.ver("v1.0.3"), ip=server_ip, port=x.port(22), proj=d.project, hook=hook)
    d.tool("read", ".github/workflows/deploy.yml", wf)
    log = []
    t0 = x.ts("iso_us", tick=(30, 300))
    log.append(T("deploy\tSet up job\t⟦t⟧ Current runner version: '⟦v⟧'", t=t0, v=x.ver("2.319.1")))
    log.append(T("deploy\tSet up job\t⟦t⟧ Runner name: 'GitHub Actions ⟦n⟧'", t=x.ts("iso_us", tick=(0, 1)), n=x.num(lo=2, hi=60)))
    log.append(T("deploy\tUpload over SSH\t⟦t⟧ ##[group]Run appleboy/ssh-action@⟦v⟧", t=x.ts("iso_us", tick=(40, 90)), v=x.ver("v1.0.3")))
    log.append(T("deploy\tUpload over SSH\t⟦t⟧ with:", t=x.ts("iso_us", tick=(0, 0.1))))
    log.append(T("deploy\tUpload over SSH\t⟦t⟧   host: ⟦ip⟧", t=x.ts("iso_us", tick=(0, 0.1)), ip=server_ip))
    log.append(T("deploy\tUpload over SSH\t⟦t⟧   key: ⟦m⟧", t=x.ts("iso_us", tick=(0, 0.1)), m=x.ph("token", "***")))
    cause = r.choice(["hostkey", "auth", "timeout"])
    msg = {"hostkey": "ssh: handshake failed: knownhosts: key mismatch",
           "auth": "ssh: handshake failed: ssh: unable to authenticate, attempted methods [none publickey], no supported methods remain",
           "timeout": "dial tcp ⟦ip⟧:22: i/o timeout"}[cause]
    t_err = x.ts("iso_us", tick=(10, 30))
    log.append(T("deploy\tUpload over SSH\t⟦t⟧ ⟦t2⟧ " + msg, t=t_err, t2=x.ts("slash"),
                 **({"ip": server_ip} if cause == "timeout" else {})))
    log.append(T("deploy\tUpload over SSH\t⟦t⟧ ##[error]Process completed with exit code 1.", t=x.ts("iso_us", tick=(0, 1))))
    log.append(T("deploy\tNotify\t⟦t⟧ deploy failure by ⟦a⟧", t=x.ts("iso_us", tick=(1, 3)), a=g.user(actor)))
    d.tool("sh", T("gh run view ⟦id⟧ --log-failed", id=run_id), lines(*log))
    if cause == "hostkey":
        expl = d.L(en="The server's host key changed (the box was rebuilt), so the action refuses to connect. Pin the new fingerprint in the `fingerprint:` input instead of disabling the check.",
                   it="La host key del server è cambiata (la macchina è stata ricreata), quindi l'action rifiuta la connessione. Va fissata la nuova fingerprint con l'input `fingerprint:` invece di disattivare il controllo.",
                   de="Der Host-Key des Servers hat sich geändert (die Maschine wurde neu aufgesetzt), daher verweigert die Action die Verbindung. Den neuen Fingerprint über `fingerprint:` pinnen, statt die Prüfung abzuschalten.",
                   fr="La clé d'hôte du serveur a changé (la machine a été recréée), donc l'action refuse de se connecter. Il faut épingler la nouvelle empreinte via `fingerprint:` plutôt que désactiver la vérification.",
                   es="La host key del servidor cambió (la máquina se recreó), así que la action rechaza la conexión. Hay que fijar la nueva huella con `fingerprint:` en vez de desactivar la comprobación.")
    elif cause == "auth":
        expl = d.L(en="`DEPLOY_KEY` no longer matches any key in the deploy user's authorized_keys — it was rotated on the server but not in the repository secrets.",
                   it="`DEPLOY_KEY` non corrisponde più a nessuna chiave in authorized_keys dell'utente deploy: è stata ruotata sul server ma non nei secret del repository.",
                   de="`DEPLOY_KEY` passt zu keinem Schlüssel mehr in den authorized_keys des deploy-Users — er wurde auf dem Server rotiert, aber nicht in den Repository-Secrets.",
                   fr="`DEPLOY_KEY` ne correspond plus à aucune clé dans authorized_keys de l'utilisateur deploy : elle a été changée sur le serveur mais pas dans les secrets du dépôt.",
                   es="`DEPLOY_KEY` ya no coincide con ninguna clave en authorized_keys del usuario deploy: se rotó en el servidor pero no en los secrets del repositorio.")
    else:
        expl = d.L(en="The runner can't reach port 22 at all. GitHub-hosted runners use changing egress IPs, and the firewall only allows the office range.",
                   it="Il runner non raggiunge proprio la porta 22. I runner hosted di GitHub usano IP di uscita variabili e il firewall consente solo il range dell'ufficio.",
                   de="Der Runner erreicht Port 22 überhaupt nicht. GitHub-hosted Runner nutzen wechselnde Egress-IPs, die Firewall lässt nur den Büro-Bereich zu.",
                   fr="Le runner n'atteint pas du tout le port 22. Les runners hébergés par GitHub ont des IP de sortie variables et le pare-feu n'autorise que la plage du bureau.",
                   es="El runner no llega al puerto 22. Los runners alojados de GitHub usan IPs de salida variables y el firewall solo permite el rango de la oficina.")
    d.agent(say(d, "explain"), "\n", expl)
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x="deploy.yml"), " ",
                d.L(en="The Slack webhook URL is hard-coded in the workflow; it belongs in `secrets.SLACK_WEBHOOK`.",
                    it="L'URL del webhook Slack è scritto nel workflow; va messo in `secrets.SLACK_WEBHOOK`.",
                    de="Die Slack-Webhook-URL steht hartkodiert im Workflow; sie gehört in `secrets.SLACK_WEBHOOK`.",
                    fr="L'URL du webhook Slack est en dur dans le workflow ; elle doit aller dans `secrets.SLACK_WEBHOOK`.",
                    es="La URL del webhook de Slack está escrita en el workflow; debe ir en `secrets.SLACK_WEBHOOK`."))
        d.tool("edit", ".github/workflows/deploy.yml",
               lines(F("-            ", hook), "+            ${{ secrets.SLACK_WEBHOOK }}"))
    d.agent(d.L(en="Reference: ", it="Riferimento: ", de="Referenz: ", fr="Référence : ", es="Referencia: "),
            x.url("docs", "https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions"))


@template("readme_maintainers", "box", "file")
def readme_maintainers(d):
    g, x, r = d.g, d.x, d.rng
    team = d.people(r.randint(3, 6))
    d.user(d.L(en="Can you add a Maintainers section to the README using the people in CODEOWNERS, and fix the broken badges?",
               it="Puoi aggiungere una sezione Maintainers al README con le persone di CODEOWNERS e sistemare i badge rotti?",
               de="Kannst du im README einen Abschnitt Maintainers mit den Leuten aus CODEOWNERS ergänzen und die kaputten Badges reparieren?",
               fr="Tu peux ajouter une section Maintainers au README avec les personnes de CODEOWNERS, et réparer les badges cassés ?",
               es="¿Puedes añadir una sección Maintainers al README con la gente de CODEOWNERS y arreglar los badges rotos?"))
    readme = T('''# ⟦proj⟧

[![build](⟦ci1⟧)](⟦ci2⟧)
[![license](⟦b1⟧)](LICENSE) [![python](⟦b2⟧)](⟦pyurl⟧)

Internal service of ⟦comp⟧ that ⟦what⟧.

## Install

```bash
pip install --index-url ⟦reg⟧ -r requirements.txt
cp .env.example .env   # then set API_KEY=⟦ph⟧
```

## Support

On-call this quarter: ⟦oncall⟧ (⟦phone⟧). Escalations: ⟦esc⟧.

## Credits

The retry logic follows the approach described by ⟦fig⟧; HTTP layer built on ⟦lib⟧.

## License

⟦lic⟧
''', proj=d.project,
        ci1=g.raw("private_url", f"https://ci.{d.int_domain}/buildStatus/icon?job={d.project}", "url"),
        ci2=g.raw("private_url", f"https://ci.{d.int_domain}/job/{d.project}/", "url"), b1=x.url("badge", "https://img.shields.io/badge/license-MIT-blue.svg"),
        b2=x.url("badge", "https://img.shields.io/badge/python-3.12-blue"), pyurl=x.url("docs", "https://docs.python.org/3/library/logging.html"),
        comp=d.company, what=r.choice(["syncs invoices with the ERP", "sends booking reminders", "exports payroll data",
                                       "aggregates telemetry from the fleet"]),
        reg=x.url("registry", "https://pypi.org/simple/"), ph=x.ph("api_key", "YOUR_API_KEY"),
        oncall=g.name(team[0]), phone=g.phone(team[0]), esc=g.email(team[1]),
        fig=x.fig(), lib=x.ent(r.choice(["httpx", "requests", "aiohttp"])),
        lic=x.url("license", "https://opensource.org/licenses/MIT"))
    d.tool("read", "README.md", readme)
    co_rows = ["# Code owners — reviewed quarterly"]
    for i, p in enumerate(team):
        path = ["*", "/billing/", "/api/", "/infra/", "/docs/", "/scripts/"][i]
        co_rows.append(T("⟦p⟧ ⟦h⟧", p=path.ljust(12), h=g.handle(p)))
    co_rows.append(F("/infra/terraform/  @", d.slug, "/platform-team"))
    d.tool("read", ".github/CODEOWNERS", lines(*co_rows))
    have_people = r.random() < 0.6
    if have_people:
        prow = ["# people.yml — synced from the HR directory"]
        for p in team:
            prow += [T("- name: ⟦n⟧", n=g.name(p)), T("  github: ⟦u⟧", u=g.user(p)), T("  email: ⟦e⟧", e=g.email(p)),
                     f"  tz: {r.choice(['Europe/Rome', 'Europe/Berlin', 'Europe/Paris', 'Europe/London', 'America/New_York', 'Europe/Madrid'])}"]
        d.tool("read", "docs/people.yml", lines(*prow))
    d.agent(d.L(en="The build badge points at the internal CI, which GitHub can't render for outside viewers, and the license badge is fine. I'll switch the build badge to the Actions badge and add the table.",
                it="Il badge di build punta alla CI interna, che GitHub non riesce a mostrare all'esterno; quello della licenza va bene. Passo al badge di Actions e aggiungo la tabella.",
                de="Das Build-Badge zeigt auf die interne CI, die GitHub für Externe nicht rendern kann; das Lizenz-Badge passt. Ich stelle auf das Actions-Badge um und ergänze die Tabelle.",
                fr="Le badge de build pointe vers la CI interne, que GitHub ne peut pas afficher à l'extérieur ; celui de licence est bon. Je passe au badge Actions et j'ajoute le tableau.",
                es="El badge de build apunta a la CI interna, que GitHub no puede mostrar fuera; el de licencia está bien. Cambio al badge de Actions y añado la tabla."))
    rows = [[g.name(p), g.handle(p), g.email(p) if have_people else x.ph("generic", "—")] for p in team]
    d.tool("edit", "README.md", F("+## Maintainers\n+\n", [F("+", ln) for ln in _split_lines(grid(["Name", "GitHub", "Contact"], rows, style="md"))]))
    d.agent(say(d, "done"), "\n",
            d.L(en="- Maintainers table added (from CODEOWNERS)\n- build badge now uses the public Actions badge",
                it="- aggiunta la tabella Maintainers (da CODEOWNERS)\n- il badge di build ora usa quello pubblico di Actions",
                de="- Maintainers-Tabelle ergänzt (aus CODEOWNERS)\n- Build-Badge nutzt jetzt das öffentliche Actions-Badge",
                fr="- tableau Maintainers ajouté (depuis CODEOWNERS)\n- le badge de build utilise maintenant le badge Actions public",
                es="- añadida la tabla Maintainers (desde CODEOWNERS)\n- el badge de build usa ahora el badge público de Actions"))
    if r.random() < 0.5:
        d.user(d.L(en="Should the on-call phone number really be in the README?",
                   it="Ma il numero di telefono del reperibile deve stare davvero nel README?",
                   de="Gehört die Telefonnummer der Rufbereitschaft wirklich ins README?",
                   fr="Le numéro de téléphone de l'astreinte doit vraiment être dans le README ?",
                   es="¿De verdad debe estar el teléfono de guardia en el README?"))
        d.agent(d.L(en="Better not — it's personal data in a file every contractor can read. I'd link the on-call schedule instead.",
                    it="Meglio di no: è un dato personale in un file che legge ogni consulente. Metterei il link al calendario di reperibilità.",
                    de="Lieber nicht — das sind personenbezogene Daten in einer Datei, die jeder Dienstleister lesen kann. Besser auf den Bereitschaftsplan verlinken.",
                    fr="Mieux vaut pas : c'est une donnée personnelle dans un fichier que tous les prestataires peuvent lire. Je mettrais plutôt un lien vers le planning d'astreinte.",
                    es="Mejor no: es un dato personal en un fichero que puede leer cualquier contratista. Pondría un enlace al calendario de guardias."))


def _split_lines(frag):
    """Split a fragment into per-line fragments (tagged segments never contain newlines here)."""
    out, cur = [], []
    for s in frag:
        if s.tagged or "\n" not in s.text:
            cur.append(s)
            continue
        parts = s.text.split("\n")
        for i, p in enumerate(parts):
            if p:
                cur.append(Seg(p))
            if i < len(parts) - 1:
                cur.append(Seg("\n"))
                out.append(cur)
                cur = []
    if cur:
        out.append(cur)
    return out


@template("dockerfile_build_args", "jsonl", "file", "shell")
def dockerfile_build_args(d):
    g, x, r = d.g, d.x, d.rng
    me = d.me
    idx_user = g.user(me)
    idx_tok = g.secret(r.choice(["bearer_opaque", "gitlab_pat", "hex32"]))
    nx_path = f"nexus.{d.int_domain}/repository/pypi-internal/simple"
    nx = g.raw("private_url", nx_path, fallback=x.ph("url", "nexus.example.com/repository/pypi/simple"))
    d.user(d.L(en="docker build dies at the pip install step against our private index. It worked last week.",
               it="docker build si pianta allo step di pip install sull'indice privato. La settimana scorsa funzionava.",
               de="docker build bricht beim pip install gegen unseren privaten Index ab. Letzte Woche ging es noch.",
               fr="docker build plante à l'étape pip install sur notre index privé. Ça marchait la semaine dernière.",
               es="docker build falla en el paso de pip install contra nuestro índice privado. La semana pasada funcionaba."))
    dockerfile = T('''# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
LABEL maintainer="⟦n⟧ <⟦e⟧>"
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir \\
      --index-url https://⟦u⟧:⟦t⟧@⟦nx⟧ \\
      --extra-index-url ⟦pypi⟧ \\
      -r requirements.txt
COPY . .
ENV PORT=⟦port⟧
EXPOSE ⟦port2⟧
CMD ["gunicorn", "-b", "⟦bind⟧:⟦port3⟧", "app.wsgi"]
''', n=g.name(me), e=g.email(me), u=idx_user, t=idx_tok, nx=nx,
        pypi=x.url("registry", "https://pypi.org/simple/"), port=x.port(8000), port2=x.port(8000), bind=x.rip(False),
        port3=x.port(8000))
    d.tool("read", "Dockerfile", dockerfile)
    steps = [T("#0 building with \"desktop-linux\" instance using docker driver"),
             T("#1 [internal] load build definition from Dockerfile"),
             T("#1 transferring dockerfile: ⟦n⟧B done", n=x.num(lo=600, hi=900)),
             T("#2 [internal] load metadata for docker.io/library/python:3.12-slim"),
             T("#2 DONE ⟦s⟧s", s=x.num(f"{r.uniform(0.4, 2.5):.1f}")),
             T("#5 [build 1/5] FROM docker.io/library/python:3.12-slim@sha256:⟦h⟧", h=x.sha256()),
             T("#7 [build 3/5] RUN pip install --no-cache-dir       --index-url https://⟦u⟧:⟦t⟧@⟦nx⟧ ...",
               u=idx_user, t=idx_tok, nx=nx),
             T("#7 ⟦s⟧ Looking in indexes: https://⟦u⟧:⟦mask⟧@⟦nx⟧, ⟦pypi⟧",
               s=x.num(f"{r.uniform(1, 3):.3f}"), u=idx_user, nx=nx, mask=x.ph("password", "****"), pypi=x.url("registry", "https://pypi.org/simple/")),
             T("#7 ⟦s⟧ ERROR: HTTP error 401 while getting ⟦nxu⟧",
               s=x.num(f"{r.uniform(3, 6):.3f}"),
               nxu=g.raw("private_url", f"https://{nx_path}/{r.choice(['acme-auth', 'billing-client', 'shared-models'])}/", "url")),
             T("#7 ERROR: process \"/bin/sh -c pip install ...\" did not complete successfully: exit code: 1")]
    d.tool("sh", "docker build -t app:dev .", lines(*steps))
    d.agent(say(d, "explain"), "\n",
            d.L(en="The index token embedded in the Dockerfile expired (401), and because it is baked into a RUN line it also ends up in the image history. Switching to a BuildKit secret mount fixes both.",
                it="Il token dell'indice dentro il Dockerfile è scaduto (401) e, stando in una riga RUN, finisce anche nella history dell'immagine. Con un secret mount di BuildKit si risolvono entrambe le cose.",
                de="Das Index-Token im Dockerfile ist abgelaufen (401), und weil es in einer RUN-Zeile steht, landet es auch in der Image-History. Ein BuildKit-Secret-Mount löst beides.",
                fr="Le jeton de l'index écrit dans le Dockerfile a expiré (401), et comme il est dans une ligne RUN il se retrouve aussi dans l'historique de l'image. Un secret mount BuildKit règle les deux problèmes.",
                es="El token del índice escrito en el Dockerfile caducó (401) y, al estar en una línea RUN, también queda en el historial de la imagen. Un secret mount de BuildKit arregla ambas cosas."),
            "\n", x.url("docs", "https://docs.docker.com/build/building/secrets/"))
    d.tool("edit", "Dockerfile",
           lines("-RUN pip install --no-cache-dir \\",
                 T("-      --index-url https://⟦u⟧:⟦t⟧@⟦nx⟧ \\", u=idx_user, t=idx_tok, nx=nx),
                 "+RUN --mount=type=secret,id=pipconf,target=/etc/pip.conf \\",
                 "+    pip install --no-cache-dir \\"))
    new_tok = g.secret(r.choice(["bearer_opaque", "gitlab_pat"]))
    d.user(d.L(en="New token: ", it="Token nuovo: ", de="Neues Token: ", fr="Nouveau jeton : ", es="Token nuevo: "), new_tok,
           d.L(en=" — put it wherever it needs to go", it=" — mettilo dove serve", de=" — trag es ein, wo es hingehört",
               fr=" — mets-le où il faut", es=" — ponlo donde haga falta"))
    d.tool("write", "~/.config/pip/pip.conf",
           lines("[global]", T("index-url = https://⟦u⟧:⟦t⟧@⟦nx⟧", u=idx_user, t=new_tok, nx=nx),
                 T("extra-index-url = ⟦p⟧", p=x.url("registry", "https://pypi.org/simple/"))))
    d.tool("sh", "docker build --secret id=pipconf,src=$HOME/.config/pip/pip.conf -t app:dev .",
           lines(T("#7 [build 3/5] RUN --mount=type=secret,id=pipconf,target=/etc/pip.conf pip install ..."),
                 T("#7 DONE ⟦s⟧s", s=x.num(f"{r.uniform(20, 70):.1f}")),
                 T("#9 exporting to image"),
                 T("#9 writing image sha256:⟦h⟧ done", h=x.sha256()),
                 T("#9 naming to docker.io/library/app:dev done")))
    d.agent(say(d, "done"), "\n", d.L(en="- token moved out of the Dockerfile into a BuildKit secret\n- local pip.conf holds the new token (outside the repo)",
                                      it="- token tolto dal Dockerfile e passato come secret BuildKit\n- il pip.conf locale contiene il nuovo token (fuori dal repo)",
                                      de="- Token aus dem Dockerfile in ein BuildKit-Secret verschoben\n- lokale pip.conf enthält das neue Token (außerhalb des Repos)",
                                      fr="- jeton sorti du Dockerfile vers un secret BuildKit\n- le pip.conf local contient le nouveau jeton (hors du dépôt)",
                                      es="- token sacado del Dockerfile a un secret de BuildKit\n- el pip.conf local guarda el token nuevo (fuera del repo)"))


@template("terraform_tfvars", "tslog", "file", "shell")
def terraform_tfvars(d):
    g, x, r = d.g, d.x, d.rng
    owner = d.me
    region = r.choice(["eu-central-1", "eu-west-1", "eu-south-1", "us-east-1"])
    d.user(d.L(en="terraform plan wants to replace the bastion host every single time. Why?",
               it="terraform plan vuole ricreare il bastion ogni volta. Perché?",
               de="terraform plan will den Bastion-Host jedes Mal ersetzen. Warum?",
               fr="terraform plan veut remplacer le bastion à chaque fois. Pourquoi ?",
               es="terraform plan quiere reemplazar el bastion cada vez. ¿Por qué?"))
    tfvars = T('''region          = "⟦reg⟧"
environment     = "prod"
owner           = "⟦own⟧"
alert_email     = "⟦mail⟧"
admin_cidrs     = ["⟦ip1⟧/32", "⟦ip2⟧/32"]
db_password     = "⟦pw⟧"
cloudflare_token = "⟦cf⟧"
''', reg=region, own=g.name(owner), mail=g.email(owner), ip1=g.ip("public"), ip2=g.ip("public"), pw=g.password(),
        cf=g.secret(r.choice(["bearer_opaque", "hex32"])))
    d.tool("read", "envs/prod/terraform.tfvars", tfvars)
    ami = x.id("ami-0" + x.short(16).text)
    main = T('''resource "aws_instance" "bastion" {
  ami                    = "⟦ami⟧"
  instance_type          = "t3.micro"
  subnet_id              = module.vpc.public_subnets[0]
  vpc_security_group_ids = [aws_security_group.bastion.id]
  user_data = templatefile("${path.module}/bastion.sh.tpl", {
    admins     = var.admin_cidrs
    rendered_at = timestamp()
  })
  tags = {
    Name  = "bastion-prod"
    Owner = var.owner
  }
}
''', ami=ami)
    d.tool("read", "modules/bastion/main.tf", main)
    plan = [
        T("aws_instance.bastion: Refreshing state... [id=⟦i⟧]", i=x.id("i-0" + x.short(16).text)),
        "",
        "Terraform will perform the following actions:",
        "",
        "  # aws_instance.bastion must be replaced",
        "-/+ resource \"aws_instance\" \"bastion\" {",
        T("      ~ arn                          = \"arn:aws:ec2:⟦r⟧:⟦acct⟧:instance/⟦i⟧\" -> (known after apply)",
          r=region, acct=x.num(lo=100000000000, hi=999999999999), i=x.id("i-0" + x.short(16).text)),
        T("      ~ private_ip                   = \"⟦ip⟧\" -> (known after apply)", ip=g.ip("private")),
        T("      ~ public_ip                    = \"⟦ip⟧\" -> (known after apply)", ip=g.ip("public")),
        "        tags                         = {",
        T("            \"Owner\" = \"⟦o⟧\"", o=g.name(owner)),
        "        }",
        T("      ~ user_data                    = \"⟦a⟧\" -> \"⟦b⟧\" # forces replacement", a=x.short(40), b=x.short(40)),
        "    }",
        "",
    ]
    n_rules = r.choice([0, 0, 4, 9, 16, 30])
    if n_rules:
        plan += ["  # aws_security_group.bastion will be updated in-place", "  ~ resource \"aws_security_group\" \"bastion\" {",
                 "      ~ ingress = ["]
        for _ in range(n_rules):
            who = d.person()
            plan += ["          + {", T("              + cidr_blocks      = [\"⟦ip⟧/32\"]", ip=g.ip("public")),
                     T("              + description      = \"ssh ⟦n⟧ (home)\"", n=g.name(who, r.choice(["full", "family", "given"]))),
                     T("              + from_port        = ⟦p⟧", p=x.port(22)), "              + protocol         = \"tcp\"",
                     T("              + to_port          = ⟦p⟧", p=x.port(22)), "            },"]
        plan += ["        ]", "    }", ""]
    plan.append(f"Plan: 1 to add, {1 if n_rules else 0} to change, 1 to destroy.")
    d.tool("sh", "terraform -chdir=envs/prod plan -no-color", lines(*plan))
    d.agent(say(d, "explain"), "\n",
            d.L(en="`timestamp()` inside templatefile() changes on every run, so user_data always differs and user_data forces replacement on aws_instance. Drop the timestamp, or add `ignore_changes = [user_data]`.",
                it="`timestamp()` dentro templatefile() cambia a ogni esecuzione, quindi user_data è sempre diverso e su aws_instance user_data forza la sostituzione. Togli il timestamp o aggiungi `ignore_changes = [user_data]`.",
                de="`timestamp()` in templatefile() ändert sich bei jedem Lauf, user_data ist also immer anders, und user_data erzwingt bei aws_instance einen Ersatz. Timestamp entfernen oder `ignore_changes = [user_data]` setzen.",
                fr="`timestamp()` dans templatefile() change à chaque exécution, donc user_data diffère toujours et force le remplacement de aws_instance. Supprime le timestamp ou ajoute `ignore_changes = [user_data]`.",
                es="`timestamp()` dentro de templatefile() cambia en cada ejecución, así que user_data siempre difiere y fuerza el reemplazo de aws_instance. Quita el timestamp o añade `ignore_changes = [user_data]`."))
    d.user(say(d, "go_ahead"))
    d.tool("edit", "modules/bastion/main.tf", lines("-    rendered_at = timestamp()", "   })", "+  lifecycle {", "+    ignore_changes = [ami]", "+  }"))
    d.tool("sh", "terraform -chdir=envs/prod plan -no-color | tail -n 3",
           lines(T("aws_instance.bastion: Refreshing state... [id=⟦i⟧]", i=x.id("i-0" + x.short(16).text)), "",
                 "No changes. Your infrastructure matches the configuration."))
    if r.random() < 0.6:
        d.agent(say(d, "secret_warning", x="terraform.tfvars"), " ",
                d.L(en="db_password and the Cloudflare token should come from TF_VAR_* or a secrets backend, and the file should be in .gitignore.",
                    it="db_password e il token Cloudflare dovrebbero arrivare da TF_VAR_* o da un backend di secret, e il file andrebbe in .gitignore.",
                    de="db_password und das Cloudflare-Token sollten aus TF_VAR_* oder einem Secrets-Backend kommen, und die Datei gehört in .gitignore.",
                    fr="db_password et le jeton Cloudflare devraient venir de TF_VAR_* ou d'un backend de secrets, et le fichier devrait être dans .gitignore.",
                    es="db_password y el token de Cloudflare deberían venir de TF_VAR_* o de un backend de secretos, y el fichero debería estar en .gitignore."))


@template("ssh_config_hosts", "hai", "file", "shell")
def ssh_config_hosts(d):
    g, x, r = d.g, d.x, d.rng
    me = d.me
    bastion_old, bastion_new = g.ip("public"), g.ip("public")
    stg_ip = g.ip("private")
    if r.random() < 0.3:
        _ssh_config_quick(d)
        return
    d.user(d.L(en="`ssh staging` just hangs since Monday. My ssh config hasn't changed.",
               it="`ssh staging` resta appeso da lunedì. La mia config ssh non è cambiata.",
               de="`ssh staging` hängt seit Montag einfach. An meiner SSH-Config hat sich nichts geändert.",
               fr="`ssh staging` reste bloqué depuis lundi. Ma config ssh n'a pas changé.",
               es="`ssh staging` se queda colgado desde el lunes. Mi config de ssh no ha cambiado."))
    home = d.home()
    hosts = [
        T("Host bastion\n  HostName ⟦ip⟧\n  User ⟦u⟧\n  IdentityFile ⟦h⟧/.ssh/id_ed25519\n  Port ⟦p⟧\n", ip=bastion_old, u=g.user(me), h=home, p=x.port(r.choice([22, 2222]))),
        T("Host staging\n  HostName ⟦ip⟧\n  User deploy\n  ProxyJump bastion\n  IdentityFile ⟦h⟧/.ssh/id_ed25519\n", ip=stg_ip, h=home),
        T("Host github.com\n  User git\n  IdentityFile ⟦h⟧/.ssh/github_ed25519\n  AddKeysToAgent yes\n", h=home),
    ]
    if r.random() < 0.6:
        hosts.append(T("Host nas\n  HostName ⟦ip⟧\n  User ⟦u⟧\n  # MAC for wake-on-lan: ⟦mac⟧\n", ip=g.ip("private"), u=g.user(me), mac=g.mac()))
    r.shuffle(hosts)
    d.tool("read", "~/.ssh/config", J("\n", hosts))
    fp = x.id("SHA256:" + x.short(43).text)
    dbg = [
        "OpenSSH_9.6p1, LibreSSL 3.3.6",
        T("debug1: Reading configuration data ⟦h⟧/.ssh/config", h=home),
        "debug1: Setting implicit ProxyCommand from ProxyJump: ssh -vvv -W '[%h]:%p' bastion",
        T("debug1: Connecting to ⟦ip⟧ [⟦ip⟧] port 22.", ip=bastion_old),
        "debug1: connect to address port 22: Operation timed out",
        "ssh: connect to host bastion port 22: Operation timed out",
        "Connection closed by UNKNOWN port 65535",
    ]
    d.tool("sh", "ssh -vvv staging 2>&1 | head -n 20", lines(*dbg))
    d.tool("sh", "dig +short bastion." + d.int_domain, lines(bastion_new))
    d.agent(say(d, "explain"), " ",
            T(d.L(en="the bastion was moved to a new address (DNS now resolves to ⟦n⟧) but your config pins the old IP ⟦o⟧. Using the DNS name avoids this next time.",
                  it="il bastion è stato spostato su un nuovo indirizzo (il DNS ora risolve ⟦n⟧) ma la tua config ha ancora l'IP vecchio ⟦o⟧. Usando il nome DNS non succede più.",
                  de="der Bastion hat eine neue Adresse (DNS liefert jetzt ⟦n⟧), deine Config pinnt aber noch die alte IP ⟦o⟧. Mit dem DNS-Namen passiert das nicht wieder.",
                  fr="le bastion a changé d'adresse (le DNS résout maintenant ⟦n⟧) mais ta config fixe encore l'ancienne IP ⟦o⟧. Avec le nom DNS, ça n'arrivera plus.",
                  es="el bastion cambió de dirección (el DNS resuelve ahora ⟦n⟧) pero tu config fija la IP antigua ⟦o⟧. Usando el nombre DNS no volverá a pasar."),
              n=bastion_new, o=bastion_old))
    d.tool("edit", "~/.ssh/config", lines("Host bastion", T("-  HostName ⟦ip⟧", ip=bastion_old), F("+  HostName bastion.", d.int_domain)))
    d.tool("sh", "ssh -o ConnectTimeout=5 staging 'hostname; uptime'",
           lines("stg-app-01", T(" ⟦t⟧ up ⟦n⟧ days,  2 users,  load average: 0.21, 0.18, 0.11", t=x.ts("time", tick=(5, 20)), n=x.num(lo=3, hi=200))))
    if r.random() < 0.5:
        d.tool("sh", "ssh-keygen -F bastion." + d.int_domain,
               lines(T("# Host bastion.⟦dom⟧ found: line ⟦n⟧", dom=d.int_domain, n=x.num(lo=3, hi=40)),
                     T("bastion.⟦dom⟧ ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI⟦k⟧", dom=d.int_domain, k=x.short(43))))
    d.user(say(d, "thanks"))


@template("ansible_inventory_vault", "irc", "file")
def ansible_inventory_vault(d):
    g, x, r = d.g, d.x, d.rng
    oncall = d.people(r.randint(2, 3))
    d.user(d.L(en="site.yml fails on prod with 'Decryption failed'. The vault password file is the usual one.",
               it="site.yml fallisce in prod con 'Decryption failed'. Il file della password del vault è il solito.",
               de="site.yml scheitert auf prod mit 'Decryption failed'. Die Vault-Passwortdatei ist die übliche.",
               fr="site.yml échoue en prod avec 'Decryption failed'. Le fichier de mot de passe du vault est le même que d'habitude.",
               es="site.yml falla en prod con 'Decryption failed'. El fichero de contraseña del vault es el de siempre."))
    web = [g.ip("private") for _ in range(r.randint(2, 4))]
    dbs = [g.ip("private") for _ in range(r.randint(1, 2))]
    inv = ["[web]"] + [T("web-0⟦i⟧ ansible_host=⟦ip⟧ ansible_user=deploy", i=str(i + 1), ip=ip) for i, ip in enumerate(web)]
    inv += ["", "[db]"] + [T("db-0⟦i⟧ ansible_host=⟦ip⟧ ansible_user=⟦u⟧", i=str(i + 1), ip=ip, u=g.user(oncall[0])) for i, ip in enumerate(dbs)]
    inv += ["", "[prod:children]", "web", "db"]
    d.tool("read", "inventory/prod/hosts.ini", lines(*inv))
    contacts = []
    for p in oncall:
        contacts += [T("  - name: \"⟦n⟧\"", n=g.name(p)), T("    email: ⟦e⟧", e=g.email(p)), T("    phone: \"⟦ph⟧\"", ph=g.phone(p, intl=True))]
    vars_yml = F(lines("---", "app_env: production", T("smtp_relay_user: ⟦e⟧", e=g.email(d.person())),
                       T('db_password: "⟦v⟧"', v=x.ph("password", "{{ vault_db_password }}")),
                       "oncall_contacts:"), lines(*contacts))
    d.tool("read", "inventory/prod/group_vars/all/vars.yml", vars_yml)
    head = "$ANSIBLE_VAULT;1.2;AES256;" + r.choice(["prod", "default"])
    blob = [x.short(80).text for _ in range(r.randint(4, 8))]
    d.tool("read", "inventory/prod/group_vars/all/vault.yml", lines(head, *blob))
    vid = head.split(";")[-1]
    d.agent(T(d.L(en="The vault file is encrypted with vault-id `⟦v⟧`, but ansible.cfg only provides the default identity. Let me check ansible.cfg.",
                  it="Il file vault è cifrato con vault-id `⟦v⟧`, ma ansible.cfg fornisce solo l'identità di default. Controllo ansible.cfg.",
                  de="Die Vault-Datei ist mit der vault-id `⟦v⟧` verschlüsselt, ansible.cfg liefert aber nur die Default-Identität. Ich prüfe ansible.cfg.",
                  fr="Le fichier vault est chiffré avec le vault-id `⟦v⟧`, mais ansible.cfg ne fournit que l'identité par défaut. Je vérifie ansible.cfg.",
                  es="El fichero vault está cifrado con el vault-id `⟦v⟧`, pero ansible.cfg solo da la identidad por defecto. Reviso ansible.cfg."), v=vid))
    d.tool("read", "ansible.cfg", lines("[defaults]", "inventory = inventory/prod", T("vault_password_file = ⟦h⟧/.ansible/vault_pass_old", h=d.home()),
                                       "host_key_checking = True", "retry_files_enabled = False"))
    d.tool("sh", "ansible-vault view --vault-id prod@~/.ansible/vault_pass inventory/prod/group_vars/all/vault.yml",
           lines(T("vault_db_password: \"⟦pw⟧\"", pw=g.password()),
                 T("vault_smtp_password: \"⟦pw⟧\"", pw=g.password()),
                 T("vault_datadog_api_key: \"⟦k⟧\"", k=g.secret("datadog"))))
    d.tool("edit", "ansible.cfg", lines("-vault_password_file = ~/.ansible/vault_pass_old", "+vault_identity_list = prod@~/.ansible/vault_pass"))
    recap = ["PLAY RECAP *********************************************************************"]
    for i, ip in enumerate(web):
        recap.append(T("web-0⟦i⟧ (⟦ip⟧)  : ok=⟦a⟧  changed=⟦b⟧  unreachable=0  failed=0", i=str(i + 1), ip=ip,
                       a=x.num(lo=10, hi=30), b=x.num(lo=0, hi=4)))
    d.tool("sh", "ansible-playbook site.yml --check --diff | tail -n " + str(len(recap)), lines(*recap))
    d.agent(say(d, "done"), " ", d.L(en="ansible.cfg now uses the `prod` vault identity; the check run is clean.",
                                     it="ansible.cfg ora usa l'identità vault `prod`; il check è pulito.",
                                     de="ansible.cfg nutzt jetzt die Vault-Identität `prod`; der Check-Lauf ist sauber.",
                                     fr="ansible.cfg utilise maintenant l'identité vault `prod` ; le check est propre.",
                                     es="ansible.cfg usa ahora la identidad de vault `prod`; el check sale limpio."))


@template("spring_application_yml", "react", "file", "trace")
def spring_application_yml(d):
    g, x, r = d.g, d.x, d.rng
    admin = d.person()
    d.user(d.L(en="The Spring service won't start with the prod profile. Local profile is fine.",
               it="Il servizio Spring non parte con il profilo prod. Con quello local va.",
               de="Der Spring-Service startet mit dem prod-Profil nicht. Mit local geht es.",
               fr="Le service Spring ne démarre pas avec le profil prod. En local ça marche.",
               es="El servicio Spring no arranca con el perfil prod. Con el local va bien."))
    d.agent(say(d, "look_first", x="application-prod.yml"))
    bad = r.choice(["indent", "type"])
    pool = "maximum-pool-size: twenty" if bad == "type" else "maximum-pool-size: 20"
    yml = T('''spring:
  datasource:
    url: jdbc:postgresql://⟦ip⟧:⟦port⟧/⟦db⟧?sslmode=require
    username: ⟦db⟧_svc
    password: ⟦pw⟧
    hikari:
      ⟦pool⟧
⟦indent⟧connection-timeout: 30000
  mail:
    host: smtp.⟦dom⟧
    username: ⟦mu⟧
    password: ⟦mp⟧
app:
  support:
    contact-name: ⟦cn⟧
    contact-phone: "⟦cp⟧"
  geocoder:
    api-key: ⟦gk⟧
management:
  endpoints.web.exposure.include: health,info
''', ip=g.ip("private"), port=x.port(5432), db=d.project.split("-")[0], pw=g.password(), pool=pool,
        indent="    " if bad == "indent" else "      ", dom=d.domain, mu=g.email(admin), mp=g.password(), cn=g.name(admin),
        cp=g.phone(admin), gk=g.secret("google_api"))
    d.tool("read", "src/main/resources/application-prod.yml", yml)
    log = [
        T("⟦t⟧  INFO ⟦pid⟧ --- [           main] c.⟦s⟧.Application : Starting Application v⟦v⟧ using Java 21.0.4",
          t=x.ts("space_dot", tick=(1, 3)), pid=x.num(lo=1000, hi=99999), s=d.slug, v=x.ver()),
        T("⟦t⟧  INFO ⟦pid⟧ --- [           main] c.⟦s⟧.Application : The following 1 profile is active: \"prod\"",
          t=x.ts("space_dot", tick=(0, 1)), pid=x.num(lo=1000, hi=99999), s=d.slug),
        T("⟦t⟧  WARN ⟦pid⟧ --- [           main] ConfigServletWebServerApplicationContext : Exception encountered during context initialization",
          t=x.ts("space_dot", tick=(1, 2)), pid=x.num(lo=1000, hi=99999)),
        "",
        "***************************",
        "APPLICATION FAILED TO START",
        "***************************",
        "",
        "Description:",
        "",
    ]
    if bad == "type":
        log += ["Failed to bind properties under 'spring.datasource.hikari.maximum-pool-size' to int:", "",
                "    Property: spring.datasource.hikari.maximum-pool-size", "    Value: \"twenty\"",
                "    Origin: class path resource [application-prod.yml] - 7:26",
                "    Reason: failed to convert java.lang.String to int"]
    else:
        log += ["Failed to bind properties under 'spring.datasource' to javax.sql.DataSource:", "",
                "    Property: spring.datasource.connection-timeout", "    Value: \"30000\"",
                "    Origin: class path resource [application-prod.yml] - 8:5",
                "    Reason: The elements [spring.datasource.connection-timeout] were left unbound."]
    log += ["", "Action:", "", "Update your application's configuration"]
    d.tool("sh", "./mvnw -q spring-boot:run -Dspring-boot.run.profiles=prod", lines(*log))
    if bad == "type":
        d.agent(d.L(en="maximum-pool-size is a string; Hikari needs an integer.",
                    it="maximum-pool-size è una stringa; Hikari vuole un intero.",
                    de="maximum-pool-size ist ein String; Hikari erwartet eine Ganzzahl.",
                    fr="maximum-pool-size est une chaîne ; Hikari attend un entier.",
                    es="maximum-pool-size es una cadena; Hikari necesita un entero."))
        d.tool("edit", "src/main/resources/application-prod.yml", lines("-      maximum-pool-size: twenty", "+      maximum-pool-size: 20"))
    else:
        d.agent(d.L(en="connection-timeout is indented one level too shallow, so it lands under spring.datasource instead of hikari.",
                    it="connection-timeout ha un livello di indentazione in meno, quindi finisce sotto spring.datasource invece che sotto hikari.",
                    de="connection-timeout ist eine Ebene zu wenig eingerückt und landet unter spring.datasource statt unter hikari.",
                    fr="connection-timeout est indenté d'un niveau de moins, il se retrouve sous spring.datasource au lieu de hikari.",
                    es="connection-timeout tiene un nivel de sangría de menos, así que cae bajo spring.datasource en vez de hikari."))
        d.tool("edit", "src/main/resources/application-prod.yml", lines("-    connection-timeout: 30000", "+      connection-timeout: 30000"))
    d.tool("sh", "./mvnw -q spring-boot:run -Dspring-boot.run.profiles=prod | grep -E 'Started|Tomcat'",
           lines(T("⟦t⟧  INFO ⟦pid⟧ --- [           main] o.s.b.w.embedded.tomcat.TomcatWebServer  : Tomcat started on port ⟦p⟧ (http) with context path '/'",
                   t=x.ts("space_dot", tick=(20, 40)), pid=x.num(lo=1000, hi=99999), p=x.port(8080)),
                 T("⟦t⟧  INFO ⟦pid⟧ --- [           main] c.⟦s⟧.Application : Started Application in ⟦s1⟧ seconds (process running for ⟦s2⟧)",
                   t=x.ts("space_dot", tick=(0, 1)), pid=x.num(lo=1000, hi=99999), s=d.slug,
                   s1=x.num(f"{r.uniform(3, 9):.3f}"), s2=x.num(f"{r.uniform(9, 12):.3f}"))))
    if d.secret_ok and r.random() < 0.7:
        d.agent(say(d, "secret_warning", x="application-prod.yml"))
    d.agent(say(d, "not_committed"))


def _ssh_config_quick(d):
    """Short variant: a one-question lookup in ~/.ssh/config."""
    g, x, r = d.g, d.x, d.rng
    me = d.me
    nas_ip = g.ip("private")
    d.user(d.L(en="quick one: which IP and user does my `nas` entry use? I need it for the backup app",
               it="domanda veloce: che IP e che utente usa la voce `nas`? Mi serve per l'app di backup",
               de="kurze Frage: welche IP und welchen User nutzt mein `nas`-Eintrag? Brauche ich für die Backup-App",
               fr="petite question : quelle IP et quel utilisateur pour mon entrée `nas` ? J'en ai besoin pour l'appli de sauvegarde",
               es="pregunta rápida: ¿qué IP y qué usuario usa mi entrada `nas`? Lo necesito para la app de backup"))
    user = g.user(me)
    d.tool("grep", "-A4 '^Host nas' ~/.ssh/config",
           lines("Host nas", T("  HostName ⟦ip⟧", ip=nas_ip), T("  User ⟦u⟧", u=user), T("  Port ⟦p⟧", p=x.port(r.choice([22, 2222, 5022]))),
                 T("  IdentityFile ⟦h⟧/.ssh/id_nas", h=d.home())))
    d.agent(T(d.L(en="`nas` → ⟦ip⟧, user `⟦u⟧`, key ~/.ssh/id_nas.",
                  it="`nas` → ⟦ip⟧, utente `⟦u⟧`, chiave ~/.ssh/id_nas.",
                  de="`nas` → ⟦ip⟧, User `⟦u⟧`, Schlüssel ~/.ssh/id_nas.",
                  fr="`nas` → ⟦ip⟧, utilisateur `⟦u⟧`, clé ~/.ssh/id_nas.",
                  es="`nas` → ⟦ip⟧, usuario `⟦u⟧`, clave ~/.ssh/id_nas."), ip=nas_ip, u=user))
    if r.random() < 0.5:
        d.user(say(d, "thanks"))
