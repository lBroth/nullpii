# SPDX-License-Identifier: Apache-2.0
"""Templates centred on interactive shell sessions (network, disk, containers,
databases, cloud CLIs, shell history, cron, dumps, SSH keys)."""

from __future__ import annotations

import base64
import datetime as dt

from .. import values as V
from ..core import F, J, T, Seg, esc_json, grid, lines, numbered, table
from ..phrases import say
from . import template

# ---------------------------------------------------------------- private helpers

_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "okhttp/4.12.0",
]


def _gip(d, value: str, v6: bool = False):
    """A template-computed host address: gold, or a reserved address in clean documents."""
    return d.g.raw("private_ip", value) if d.gold_ok else d.x.rip(v6)


def _home(d) -> list:
    """Home directory fragment, stable within one document."""
    if "_b_home" not in d.state:
        d.state["_b_home"] = d.home()
    return d.state["_b_home"]


def _owner(d):
    """The local account name as shown in ls/ps columns."""
    if d.clean:
        return d.state.setdefault("_b_owner", d.rng.choice(["runner", "dev", "vscode"]))
    _home(d)
    return d.state["home_user"]


def _past(d, days_lo: int, days_hi: int) -> dt.datetime:
    return d.clock.t - dt.timedelta(days=d.rng.randint(days_lo, days_hi), seconds=d.rng.randint(0, 86399))


def _ts_seg(text: str) -> Seg:
    return Seg(text, cls="machine_timestamp")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _res(text: str) -> Seg:
    """A loopback / unspecified / documentation-range address (reserved_ip distractor)."""
    return Seg(text, cls="reserved_ip")


def _lan(r) -> str:
    return f"192.168.{r.choice([0, 1, 1, 2, 10, 178, 188])}"


# ================================================================ 1. network debugging over VPN


@template("ip_addr_network_debug", "steps", "shell")
def ip_addr_network_debug(d):
    g, x, r = d.g, d.x, d.rng
    svc = r.choice(["git", "jenkins", "grafana", "nexus", "wiki", "argocd", "sonar"])
    host = f"{svc}.{d.int_domain}"
    target = f"10.{r.choice([30, 40, 52, 64, 96])}.{r.randint(0, 20)}.{r.randint(2, 250)}"
    vpn_net = f"10.{r.choice([8, 20, 21])}"
    my_vpn = f"{vpn_net}.0.{r.randint(2, 250)}"
    vpn_dns = f"{vpn_net}.0.{r.choice([1, 2, 53])}"
    lan = _lan(r)
    my_lan = f"{lan}.{r.randint(20, 220)}"
    gw = f"{lan}.1"
    linux = d.os != "mac"
    cause = r.choice(["allowed_ips", "hosts", "dns"])
    url = g.raw("private_url", f"https://{host}{r.choice(['/', '/login', '/api/health', '/dashboard'])}", "url")
    d.user(T(d.L(
        en="I'm connected to the VPN but ⟦u⟧ just times out. Colleagues can open it. Can you figure out what's wrong with my machine?",
        it="Sono connesso alla VPN ma ⟦u⟧ va in timeout. I colleghi lo aprono senza problemi. Riesci a capire cosa non va sulla mia macchina?",
        de="Ich bin im VPN, aber ⟦u⟧ läuft in einen Timeout. Bei den Kollegen geht es. Kannst du rausfinden, was bei mir kaputt ist?",
        fr="Je suis connecté au VPN mais ⟦u⟧ part en timeout. Les collègues y accèdent sans souci. Tu peux voir ce qui cloche sur ma machine ?",
        es="Estoy conectado a la VPN pero ⟦u⟧ da timeout. Mis compañeros sí pueden abrirlo. ¿Puedes ver qué le pasa a mi máquina?"), u=url))
    d.agent(d.L(en="Let me start with the network interfaces and the tunnel state.",
                it="Parto dalle interfacce di rete e dallo stato del tunnel.",
                de="Ich fange mit den Netzwerkschnittstellen und dem Tunnelstatus an.",
                fr="Je commence par les interfaces réseau et l'état du tunnel.",
                es="Empiezo por las interfaces de red y el estado del túnel."))
    wg_if = "wg0" if linux else f"utun{r.randint(3, 6)}"
    mac_wifi = g.mac(0)
    v6_global = g.ip("v6")
    ll = "fe80::" + ":".join(f"{r.randint(0, 0xffff):x}" for _ in range(4))
    if linux:
        ifname = r.choice(["wlp0s20f3", "wlp2s0", "enp0s31f6", "eth0"])
        body = F(
            "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000\n",
            "    link/loopback ", x.ph("mac", "00:00:00:00:00:00"), " brd ", x.ph("mac", "00:00:00:00:00:00"), "\n",
            "    inet ", _res("127.0.0.1"), "/8 scope host lo\n",
            "       valid_lft forever preferred_lft forever\n",
            "    inet6 ", _res("::1"), "/128 scope host noprefixroute\n",
            "       valid_lft forever preferred_lft forever\n",
            f"2: {ifname}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000\n",
            "    link/ether ", mac_wifi, " brd ", x.ph("mac", "ff:ff:ff:ff:ff:ff"), "\n",
            "    inet ", _gip(d, my_lan), "/24 brd ", _gip(d, f"{lan}.255"), f" scope global dynamic noprefixroute {ifname}\n",
            f"       valid_lft {r.randint(3000, 86000)}sec preferred_lft {r.randint(3000, 86000)}sec\n",
            "    inet6 ", v6_global, "/64 scope global dynamic noprefixroute\n",
            "    inet6 ", _gip(d, ll, True), "/64 scope link noprefixroute\n",
            "3: wg0: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1420 qdisc noqueue state UNKNOWN group default qlen 1000\n",
            "    link/none\n",
            "    inet ", _gip(d, my_vpn), "/32 scope global wg0\n",
            "4: docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN group default\n",
            "    link/ether ", g.mac(0), " brd ", x.ph("mac", "ff:ff:ff:ff:ff:ff"), "\n",
            "    inet ", _gip(d, "172.17.0.1"), "/16 brd ", _gip(d, "172.17.255.255"), " scope global docker0\n",
        )
        d.tool("sh", "ip addr", body)
    else:
        body = F(
            "lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n",
            "\toptions=1203<RXCSUM,TXCSUM,TXSTATUS,SW_TIMESTAMP>\n",
            "\tinet ", _res("127.0.0.1"), " netmask 0xff000000\n",
            "\tinet6 ", _res("::1"), " prefixlen 128\n",
            "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n",
            "\toptions=6460<TSO4,TSO6,CHANNEL_IO,PARTIAL_CSUM,ZEROINVERT_CSUM>\n",
            "\tether ", mac_wifi, "\n",
            "\tinet6 ", _gip(d, ll, True), "%en0 prefixlen 64 secured scopeid 0xe\n",
            "\tinet ", _gip(d, my_lan), " netmask 0xffffff00 broadcast ", _gip(d, f"{lan}.255"), "\n",
            "\tinet6 ", v6_global, " prefixlen 64 autoconf secured\n",
            "\tnd6 options=201<PERFORMNUD,DAD>\n\tmedia: autoselect\n\tstatus: active\n",
            f"{wg_if}: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n",
            "\tinet ", _gip(d, my_vpn), " --> ", _gip(d, my_vpn), " netmask 0xffffff00\n",
        )
        d.tool("sh", "ifconfig", body)

    # VPN client status
    peer_ip = g.ip("public")
    allowed = [f"{vpn_net}.0.0/16", "10.20.0.0/16" if vpn_net != "10.20" else "10.21.0.0/16"]
    if cause != "allowed_ips":
        allowed.append(".".join(target.split(".")[:2]) + ".0.0/16")
    if r.random() < 0.5:
        status = F(
            f"interface: {wg_if}\n",
            "  public key: ", x.id(V.rand_str(r, V.ALNUM + "+/", 43) + "="), "\n",
            "  private key: (hidden)\n",
            "  listening port: ", x.port(r.randint(40000, 60000)), "\n\n",
            "peer: ", x.id(V.rand_str(r, V.ALNUM + "+/", 43) + "="), "\n",
            "  endpoint: ", peer_ip, ":", x.port(51820), "\n",
            "  allowed ips: ", J(", ", [T("⟦a⟧/⟦m⟧", a=_gip(d, a.split("/")[0]), m=a.split("/")[1]) for a in allowed]), "\n",
            f"  latest handshake: {r.randint(1, 50)} seconds ago\n",
            f"  transfer: {r.randint(2, 900)}.{r.randint(10, 99)} MiB received, {r.randint(1, 400)}.{r.randint(10, 99)} KiB sent\n",
        )
        d.tool("sh", "sudo wg show", status)
    else:
        who = g.email(d.me, "work")
        status = F(
            "State:            Connected\n",
            "Account:          ", who, "\n",
            "Gateway:          vpn-gw (", peer_ip, ")\n",
            "Assigned address: ", _gip(d, my_vpn), "\n",
            "Connected since:  ", x.ts("space", t=d.clock.t - dt.timedelta(minutes=r.randint(5, 300))), "\n",
            "Split tunnel:     ", J(", ", [T("⟦a⟧/⟦m⟧", a=_gip(d, a.split("/")[0]), m=a.split("/")[1]) for a in allowed]), "\n",
            "Client version:   ", x.ver(), "\n",
        )
        d.tool("sh", "vpnctl status", status)

    if cause == "allowed_ips":
        d.agent(d.L(
            en="The tunnel is up, but its routes only cover the listed subnets. Let me see where traffic to that host actually goes.",
            it="Il tunnel è attivo, ma instrada solo le subnet elencate. Vediamo dove va davvero il traffico verso quell'host.",
            de="Der Tunnel steht, routet aber nur die aufgelisteten Subnetze. Ich schaue, wohin der Verkehr zu dem Host wirklich geht.",
            fr="Le tunnel est monté, mais il ne route que les sous-réseaux listés. Voyons où part réellement le trafic vers cet hôte.",
            es="El túnel está levantado, pero solo enruta las subredes listadas. Veamos a dónde va realmente el tráfico hacia ese host."))
        dig_ip = _gip(d, target)
        d.tool("sh", f"dig +short {host}", F(dig_ip, "\n"))
        hops = [F(" 1  ", "_gateway" if linux else "router.lan", " (", _gip(d, gw), ")  ",
                  f"{r.uniform(1, 4):.3f} ms  {r.uniform(1, 4):.3f} ms  {r.uniform(1, 4):.3f} ms")]
        n_hops = r.randint(2, 6)
        for i in range(2, 2 + n_hops):
            if r.random() < 0.25:
                hops.append(F(f"{i:2d}  * * *"))
                continue
            hip = g.ip("public")
            hops.append(F(f"{i:2d}  ", hip, " (", hip, ")  ",
                          f"{r.uniform(8, 40):.3f} ms  {r.uniform(8, 40):.3f} ms  {r.uniform(8, 40):.3f} ms"))
        for i in range(2 + n_hops, 2 + n_hops + r.randint(2, 4)):
            hops.append(F(f"{i:2d}  * * *"))
        d.tool("sh", T("traceroute -n -m ⟦m⟧ ⟦ip⟧", m=str(len(hops)), ip=dig_ip),
               F("traceroute to ", dig_ip, " (", dig_ip, f"), {len(hops)} hops max, 60 byte packets\n"),
               lines(*hops))
        d.agent(say(d, "explain"), "\n",
                T(d.L(en="⟦h⟧ resolves to an address outside the tunnel's allowed ranges, so the packets leave through your home router (hop 1) and die at your ISP. The VPN profile on your laptop is older than the one IT published when that subnet was added.",
                      it="⟦h⟧ risolve a un indirizzo fuori dalle reti consentite dal tunnel, quindi i pacchetti escono dal router di casa (hop 1) e si perdono presso il provider. Il profilo VPN sul tuo portatile è più vecchio di quello pubblicato dall'IT quando hanno aggiunto quella subnet.",
                      de="⟦h⟧ löst auf eine Adresse außerhalb der erlaubten Tunnel-Netze auf, daher gehen die Pakete über deinen Heimrouter (Hop 1) raus und versanden beim Provider. Dein VPN-Profil ist älter als das, das die IT beim Hinzufügen des Subnetzes verteilt hat.",
                      fr="⟦h⟧ résout vers une adresse hors des plages autorisées du tunnel : les paquets sortent par ta box (saut 1) et se perdent chez le FAI. Ton profil VPN est plus ancien que celui publié par l'IT quand ce sous-réseau a été ajouté.",
                      es="⟦h⟧ resuelve a una dirección fuera de los rangos permitidos del túnel, así que los paquetes salen por tu router (salto 1) y se pierden en el proveedor. Tu perfil VPN es anterior al que publicó IT cuando se añadió esa subred."), h=host))
        d.user(d.L(en="How do I fix it without waiting for IT?", it="Come lo sistemo senza aspettare l'IT?",
                   de="Wie behebe ich das, ohne auf die IT zu warten?", fr="Comment je corrige ça sans attendre l'IT ?",
                   es="¿Cómo lo arreglo sin esperar a IT?"))
        d.agent(d.L(en="Re-import the current profile from the self-service portal, or as a stopgap add the subnet to AllowedIPs in the [Peer] section and reconnect:",
                    it="Reimporta il profilo aggiornato dal portale self-service, oppure come soluzione temporanea aggiungi la subnet ad AllowedIPs nella sezione [Peer] e riconnettiti:",
                    de="Importiere das aktuelle Profil aus dem Self-Service-Portal neu, oder trage übergangsweise das Subnetz unter AllowedIPs im Abschnitt [Peer] ein und verbinde dich neu:",
                    fr="Réimporte le profil à jour depuis le portail self-service, ou en attendant ajoute le sous-réseau à AllowedIPs dans la section [Peer] et reconnecte-toi :",
                    es="Vuelve a importar el perfil actual desde el portal de autoservicio o, de forma temporal, añade la subred a AllowedIPs en la sección [Peer] y reconecta:"),
                "\n\n    AllowedIPs = ", J(", ", [T("⟦a⟧/⟦m⟧", a=_gip(d, a.split("/")[0]), m=a.split("/")[1]) for a in allowed]),
                ", ", _gip(d, ".".join(target.split(".")[:2]) + ".0.0"), "/16")
    elif cause == "hosts":
        stale = f"10.{r.choice([11, 12, 15])}.{r.randint(0, 9)}.{r.randint(2, 250)}"
        d.tool("sh", f"ping -c 3 {host}",
               F("PING ", host, " (", _gip(d, stale), "): 56 data bytes\n",
                 "Request timeout for icmp_seq 0\nRequest timeout for icmp_seq 1\n\n",
                 "--- ", host, " ping statistics ---\n3 packets transmitted, 0 packets received, 100.0% packet loss\n"))
        dns_ans = _gip(d, target)
        d.tool("sh", f"dig {host}",
               F("; <<>> DiG ", x.ver(r.choice(["9.10.6", "9.18.28"])), " <<>> ", host, "\n",
                 ";; global options: +cmd\n;; Got answer:\n",
                 ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: ", x.num(lo=1000, hi=65000), "\n",
                 ";; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1\n\n",
                 ";; QUESTION SECTION:\n;", host, ".\t\tIN\tA\n\n",
                 ";; ANSWER SECTION:\n", host, ".\t", str(r.choice([60, 300, 3600])), "\tIN\tA\t", dns_ans, "\n\n",
                 ";; Query time: ", str(r.randint(8, 60)), " msec\n",
                 ";; SERVER: ", _gip(d, vpn_dns), "#53(", _gip(d, vpn_dns), ")\n",
                 ";; WHEN: ", x.ts("git", local=True), "\n",
                 ";; MSG SIZE  rcvd: ", str(r.randint(48, 90)), "\n"))
        d.agent(d.L(en="DNS returns a different address than the one ping used. Something local overrides it — checking /etc/hosts.",
                    it="Il DNS restituisce un indirizzo diverso da quello usato da ping. Qualcosa in locale lo sovrascrive: controllo /etc/hosts.",
                    de="Das DNS liefert eine andere Adresse als die, die ping benutzt. Lokal überschreibt etwas den Eintrag — ich prüfe /etc/hosts.",
                    fr="Le DNS renvoie une autre adresse que celle utilisée par ping. Quelque chose la surcharge en local — je regarde /etc/hosts.",
                    es="El DNS devuelve otra dirección distinta de la que usa ping. Algo local la sobrescribe: reviso /etc/hosts."))
        who = d.person()
        hosts_body = F("##\n# Host Database\n#\n# localhost is used to configure the loopback interface\n##\n",
                       _res("127.0.0.1"), "\tlocalhost\n",
                       _res("::1"), "             localhost\n",
                       T("\n# temporary — migration test, ask ⟦n⟧\n", n=g.name(who, r.choice(["given", "full"]))),
                       _gip(d, stale), "\t", host, "\n")
        if r.random() < 0.5:
            hosts_body += F(_gip(d, f"10.{r.randint(1, 60)}.{r.randint(0, 9)}.{r.randint(2, 250)}"), "\t",
                            f"{r.choice(['minio', 'keycloak', 'mailhog'])}.local\n")
        d.tool("read", "/etc/hosts", hosts_body)
        d.agent(say(d, "explain"), "\n",
                d.L(en="A leftover line in /etc/hosts pins the hostname to the pre-migration address. Removing it (and flushing the resolver cache) fixes the lookup.",
                    it="Una riga dimenticata in /etc/hosts fissa il nome host al vecchio indirizzo di prima della migrazione. Rimuovendola (e svuotando la cache del resolver) la risoluzione torna corretta.",
                    de="Eine vergessene Zeile in /etc/hosts nagelt den Hostnamen auf die Adresse vor der Migration fest. Wenn sie entfernt und der Resolver-Cache geleert wird, stimmt die Auflösung wieder.",
                    fr="Une ligne oubliée dans /etc/hosts fige le nom d'hôte sur l'adresse d'avant la migration. La supprimer (et vider le cache du résolveur) corrige la résolution.",
                    es="Una línea olvidada en /etc/hosts fija el nombre al antiguo destino previo a la migración. Quitándola (y vaciando la caché del resolver) se arregla."))
        d.user(say(d, "go_ahead"))
        cmd = "sudo sed -i '' '/" + svc + r"\./d' /etc/hosts && sudo dscacheutil -flushcache" if not linux else \
            "sudo sed -i '/" + svc + r"\./d' /etc/hosts && resolvectl flush-caches"
        d.tool("sh", cmd, F(""))
        d.tool("sh", f"curl -sS -o /dev/null -w '%{{http_code}}\\n' https://{host}/", F("200\n"))
    else:
        d.tool("sh", f"dig {host}",
               F("; <<>> DiG ", x.ver(r.choice(["9.10.6", "9.18.28"])), " <<>> ", host, "\n",
                 ";; global options: +cmd\n;; Got answer:\n",
                 ";; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: ", x.num(lo=1000, hi=65000), "\n\n",
                 ";; QUESTION SECTION:\n;", host, ".\t\tIN\tA\n\n",
                 ";; Query time: ", str(r.randint(8, 60)), " msec\n",
                 ";; SERVER: ", _gip(d, gw), "#53(", _gip(d, gw), ")\n",
                 ";; WHEN: ", x.ts("git", local=True), "\n"))
        d.agent(d.L(en="The query went to your home router instead of the VPN resolver, which knows nothing about internal names.",
                    it="La query è andata al router di casa invece che al resolver della VPN, che è l'unico a conoscere i nomi interni.",
                    de="Die Anfrage ging an deinen Heimrouter statt an den VPN-Resolver, und nur der kennt die internen Namen.",
                    fr="La requête est partie vers ta box au lieu du résolveur VPN, qui est le seul à connaître les noms internes.",
                    es="La consulta fue al router de casa en lugar de al resolver de la VPN, que es el único que conoce los nombres internos."))
        if linux:
            d.tool("sh", "resolvectl status | sed -n '1,20p'",
                   F("Global\n       Protocols: +LLMNR +mDNS -DNSOverTLS DNSSEC=no/unsupported\n",
                     "resolv.conf mode: stub\n\n",
                     "Link 2 (wlp0s20f3)\n    Current Scopes: DNS\n  Current DNS Server: ", _gip(d, gw), "\n",
                     "       DNS Servers: ", _gip(d, gw), "\n\n",
                     "Link 3 (wg0)\n    Current Scopes: none\n"))
            fix = F("sudo resolvectl dns wg0 ", _gip(d, vpn_dns), " && sudo resolvectl domain wg0 '~", d.int_domain, "'")
        else:
            d.tool("sh", "scutil --dns | grep -E 'nameserver|search domain' | head -n 6",
                   F("  nameserver[0] : ", _gip(d, gw), "\n", "  search domain[0] : lan\n",
                     "  nameserver[0] : ", _gip(d, gw), "\n"))
            fix = F("sudo mkdir -p /etc/resolver && echo 'nameserver ", _gip(d, vpn_dns), "' | sudo tee /etc/resolver/",
                    d.int_domain)
        d.agent(d.L(en="Route only the internal zone to the VPN resolver:", it="Instrada solo la zona interna verso il resolver della VPN:",
                    de="Leite nur die interne Zone an den VPN-Resolver:", fr="Envoie seulement la zone interne vers le résolveur VPN :",
                    es="Envía solo la zona interna al resolver de la VPN:"))
        d.tool("sh", fix, F(""))
        d.tool("sh", f"dig +short {host}", F(_gip(d, target), "\n"))
    if r.random() < 0.55:
        d.user(d.L(en="While you're at it, what's all that stuff in the ARP table?",
                   it="Già che ci sei, cos'è tutta quella roba nella tabella ARP?",
                   de="Wo du schon dabei bist: was ist das alles in der ARP-Tabelle?",
                   fr="Pendant que tu y es, c'est quoi tout ça dans la table ARP ?",
                   es="Ya que estás, ¿qué es todo eso de la tabla ARP?"))
        names = r.sample(["router.lan", "fritz.box", "printer-hall.lan", "nas.lan", "?", "?", "tv-livingroom.lan",
                          "hue-bridge.lan", "?"], r.randint(3, 6))
        if linux:
            rows = [F(_gip(d, gw if i == 0 else f"{lan}.{r.randint(2, 250)}"), f" dev {r.choice(['wlp0s20f3', 'wlp2s0'])} lladdr ",
                      g.mac(0), " ", r.choice(["REACHABLE", "STALE", "DELAY"])) for i, _ in enumerate(names)]
            d.tool("sh", "ip neigh", lines(*rows))
        else:
            rows = [F(n, " (", _gip(d, gw if i == 0 else f"{lan}.{r.randint(2, 250)}"), ") at ", g.mac(0),
                      " on en0 ifscope [ethernet]") for i, n in enumerate(names)]
            rows.append(F("? (", _gip(d, f"{lan}.255"), ") at ", x.ph("mac", "ff:ff:ff:ff:ff:ff"), " on en0 ifscope [ethernet]"))
            d.tool("sh", "arp -a", lines(*rows))
        d.agent(d.L(en="Those are the other devices on your home network (router, printer, NAS…) — normal, nothing to do with the VPN.",
                    it="Sono gli altri dispositivi della tua rete di casa (router, stampante, NAS…): normale, non c'entrano con la VPN.",
                    de="Das sind die anderen Geräte in deinem Heimnetz (Router, Drucker, NAS…) — normal, hat nichts mit dem VPN zu tun.",
                    fr="Ce sont les autres appareils de ton réseau domestique (box, imprimante, NAS…) — normal, rien à voir avec le VPN.",
                    es="Son los otros dispositivos de tu red de casa (router, impresora, NAS…): normal, nada que ver con la VPN."))


# ================================================================ 2. home directory disk cleanup


def _ls_size(r, big: bool = False) -> int:
    return r.randint(400_000_000, 6_000_000_000) if big else r.randint(1_200, 48_000_000)


@template("home_disk_cleanup", "aider", "shell")
def home_disk_cleanup(d):
    g, x, r = d.g, d.x, d.rng
    mac = d.os == "mac"
    home = _home(d)
    own = _owner(d)
    d.user(d.L(en="my disk is almost full and docker won't start anymore. help me find what to delete",
               it="ho il disco quasi pieno e docker non parte più. aiutami a capire cosa cancellare",
               de="meine Platte ist fast voll und Docker startet nicht mehr. hilf mir rauszufinden, was weg kann",
               fr="mon disque est presque plein et docker ne démarre plus. aide-moi à trouver quoi supprimer",
               es="tengo el disco casi lleno y docker ya no arranca. ayúdame a ver qué borrar"))
    if mac:
        df = table([["Filesystem", "Size", "Used", "Avail", "Capacity", "Mounted on"],
                    ["/dev/disk3s1s1", "460Gi", "10Gi", f"{r.randint(1, 9)}.{r.randint(0, 9)}Gi", "83%", "/"],
                    ["/dev/disk3s5", "460Gi", f"{r.randint(430, 452)}Gi", f"{r.randint(1, 9)}.{r.randint(0, 9)}Gi", "99%", "/System/Volumes/Data"],
                    ["/dev/disk3s6", "460Gi", "2.0Gi", "1.9Gi", "52%", "/System/Volumes/VM"]], right=(1, 2, 3, 4))
    else:
        df = table([["Filesystem", "Size", "Used", "Avail", "Use%", "Mounted on"],
                    ["/dev/nvme0n1p2", "468G", f"{r.randint(455, 465)}G", f"{r.randint(1, 9)}.{r.randint(0, 9)}G", "99%", "/"],
                    ["tmpfs", "16G", "2.1M", "16G", "1%", "/dev/shm"],
                    ["/dev/nvme0n1p1", "511M", "61M", "451M", "12%", "/boot/efi"]], right=(1, 2, 3, 4))
    d.tool("sh", "df -h", df)
    dirs = [("Documents", r.randint(2, 30)), ("Downloads", r.randint(30, 140)), ("Pictures", r.randint(1, 40)),
            ("Desktop", r.randint(1, 9)), ("code" if r.random() < 0.5 else "src", r.randint(8, 60))]
    dirs.append(("Library", r.randint(60, 180)) if mac else (".local", r.randint(10, 60)))
    dirs.append(("Movies" if mac else "Videos", r.randint(1, 80)))
    dirs.sort(key=lambda t: t[1])
    du = [F(f"{s}G\t", home, "/", n) for n, s in dirs]
    d.tool("sh", "du -sh ~/* ~/.local 2>/dev/null | sort -h | tail -n 8" if not mac else "du -sh ~/* 2>/dev/null | sort -h | tail -n 8",
           lines(*du))
    d.agent(d.L(en="Downloads is the biggest user-owned folder. Listing it.",
                it="Downloads è la cartella più grande. La elenco.",
                de="Downloads ist der größte Ordner. Ich liste ihn auf.",
                fr="Downloads est le plus gros dossier. Je le liste.",
                es="Downloads es la carpeta más grande. La listo."))
    files = []
    people = d.people(r.randint(2, 4))
    lang = d.lang
    for p in people:
        kind = r.choice(["cv", "cv", "passport", "contract", "boarding", "payslip"])
        if kind == "cv":
            pre = {"it": "CV_", "de": "Lebenslauf_", "fr": "CV_", "es": "CV_"}.get(lang, "CV_")
            name = F(pre, g.name(p, "given"), "_", g.name(p, "family"), ".pdf")
            files.append((name, _ls_size(r), False))
        elif kind == "passport":
            pre = {"it": "scansione_passaporto_", "de": "Reisepass_Scan_", "fr": "scan_passeport_",
                   "es": "pasaporte_escaneado_"}.get(lang, "passport_scan_")
            files.append((F(pre, g.name(p, "family"), r.choice([".jpg", ".pdf", ".png"])), _ls_size(r), True))
        elif kind == "contract":
            pre = {"it": "contratto_", "de": "Arbeitsvertrag_", "fr": "contrat_", "es": "contrato_"}.get(lang, "contract_")
            files.append((F(pre, g.name(p, "family"), "_signed.pdf"), _ls_size(r), False))
        elif kind == "boarding":
            files.append((F("boarding-pass-", g.name(p, "family"), "-", g.name(p, "given"), ".pdf"), _ls_size(r), False))
        else:
            files.append((F("payslip_", g.name(p, "family"), f"_{r.choice(['03', '06', '09', '11'])}.pdf"), _ls_size(r), False))
    exp_date = _past(d, 3, 60)
    export_name = F("export_customers_", x.ts("date", t=exp_date), ".csv")
    files.append((export_name, r.randint(3_000_000, 90_000_000), exp_date + dt.timedelta(minutes=r.randint(1, 600))))
    iso_ver = r.choice(["24.04.1", "22.04.4", "24.10"])
    files += [
        (F("ubuntu-", x.ver(iso_ver), "-desktop-amd64.iso"), _ls_size(r, True), False),
        (F("node-v", x.ver(r.choice(["20.11.1", "22.9.0", "18.20.4"])), "-darwin-arm64.tar.gz" if mac else "-linux-x64.tar.xz"), _ls_size(r), False),
        (F("IMG_", x.num(lo=1000, hi=9999), ".HEIC"), _ls_size(r), False),
        (F(d.project, "-main.zip"), _ls_size(r), False),
    ]
    if mac:
        files.append((F("Docker-", x.ver(r.choice(["4.34.2", "4.29.0"])), ".dmg"), _ls_size(r, True), False))
    if r.random() < 0.5:
        files.append((F("prod_dump_", x.ts("date", t=_past(d, 10, 90)), ".sql.gz"), _ls_size(r, True), False))
    for _ in range(r.randint(0, 6) if r.random() < 0.7 else r.randint(15, 45)):
        files.append((F(r.choice(["invoice_", "Fattura_", "Rechnung_", "facture_"]), x.num(lo=1000, hi=99999), ".pdf"),
                      _ls_size(r), False))
    r.shuffle(files)
    grp = "staff" if mac else own
    rows = [["total " + str(r.randint(10_000_000, 90_000_000) // 512)],
            ["drwx------@" if mac else "drwxr-xr-x", str(len(files) + 2), own, grp, "4096", x.ts("ls", t=_past(d, 0, 2)), "."],
            ["drwxr-x---+" if mac else "drwxr-x---", str(r.randint(30, 80)), own, grp, "2560", x.ts("ls", t=_past(d, 0, 5)), ".."]]
    for name, size, mt in files:
        when = mt if isinstance(mt, dt.datetime) else _past(d, 1, 400)
        rows.append(["-rw-r--r--@" if mac else "-rw-r--r--", "1", own, grp, str(size), x.ts("ls", t=when), name])
    head = rows[:1]
    body = table(rows[1:], gap=1, right=(1, 4))
    d.tool("sh", "ls -la ~/Downloads", lines(*head), body)
    big = [f for f in files if f[1] > 400_000_000]
    find_rows = [F(home, "/Downloads/", n) for n, s, _ in big]
    if mac:
        find_rows.append(F(home, "/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw"))
    else:
        find_rows.append(F(home, "/.local/share/containers/storage/overlay/", x.sha256(), "/diff/usr/lib/libLLVM-17.so"))
    find_rows.append(F(home, "/", "Movies" if mac else "Videos", "/screen-recording-", x.ts("date", t=_past(d, 20, 200)), ".mov"))
    d.tool("sh", "find ~ -type f -size +500M 2>/dev/null", lines(*find_rows))
    d.agent(d.L(en="Before suggesting deletions, let me check what that customer export is — it's not something that should sit in Downloads.",
                it="Prima di proporre cosa cancellare, controllo cos'è quell'export clienti: non dovrebbe stare in Downloads.",
                de="Bevor ich Löschungen vorschlage, schaue ich mir den Kundenexport an — der gehört nicht in Downloads.",
                fr="Avant de proposer des suppressions, je regarde cet export clients — il n'a rien à faire dans Downloads.",
                es="Antes de proponer borrados, miro qué es ese export de clientes: no debería estar en Downloads."))
    hdr = r.choice([["id", "first_name", "last_name", "email", "phone", "city"],
                    ["customer_no", "name", "email", "mobile", "postcode", "city"]])
    csv_rows = [F(",".join(hdr))]
    for _ in range(r.randint(3, 6)):
        c = d.person()
        if hdr[0] == "id":
            csv_rows.append(F(x.num(lo=1000, hi=99999), ",", g.name(c, "given"), ",", g.name(c, "family"), ",",
                              g.email(c, "personal"), ",", g.phone(c), ",", g.addr(c, "city")))
        else:
            csv_rows.append(F(g.cust(), ",\"", g.name(c), "\",", g.email(c, "personal"), ",", g.phone(c, True), ",",
                              g.addr(c, "postcode"), ",", g.addr(c, "city")))
    d.tool("sh", F("head -n ", str(len(csv_rows)), " ~/Downloads/", export_name), lines(*csv_rows))
    d.agent(say(d, "pii_warning"), "\n\n",
            d.L(en="Safe to delete (re-downloadable): the ISO, the installers, the node tarball, old zips. "
                   "Personal documents (CVs, ID scans, contracts) and the customer export are yours to decide — but the export and any ID scans should go to the company drive or be deleted, not stay unencrypted on a laptop. "
                   "Also `docker system prune -a` usually frees 20–60 GB.",
                it="Si possono cancellare (riscaricabili): la ISO, gli installer, il tarball di node, gli zip vecchi. "
                   "Sui documenti personali (CV, scansioni di documenti, contratti) e sull'export clienti decidi tu — ma l'export e le scansioni dei documenti dovrebbero stare sul drive aziendale o essere eliminati, non in chiaro su un portatile. "
                   "Anche `docker system prune -a` di solito libera 20–60 GB.",
                de="Kann weg (wieder herunterladbar): die ISO, die Installer, das Node-Tarball, alte Zips. "
                   "Bei persönlichen Dokumenten (Lebensläufe, Ausweisscans, Verträge) und dem Kundenexport entscheidest du — der Export und Ausweisscans gehören aber aufs Firmenlaufwerk oder gelöscht, nicht unverschlüsselt auf einen Laptop. "
                   "Außerdem bringt `docker system prune -a` meist 20–60 GB.",
                fr="Supprimables sans risque (re-téléchargeables) : l'ISO, les installeurs, l'archive node, les vieux zips. "
                   "Pour les documents personnels (CV, scans de pièces d'identité, contrats) et l'export clients, c'est toi qui vois — mais l'export et les scans d'identité devraient aller sur le drive de l'entreprise ou être supprimés, pas rester en clair sur un portable. "
                   "Et `docker system prune -a` libère souvent 20 à 60 Go.",
                es="Se puede borrar (se vuelve a descargar): la ISO, los instaladores, el tarball de node, los zip viejos. "
                   "Los documentos personales (CV, escaneos de documentos, contratos) y el export de clientes los decides tú, pero el export y los escaneos de identidad deberían ir al drive de la empresa o borrarse, no quedarse sin cifrar en un portátil. "
                   "Además `docker system prune -a` suele liberar 20–60 GB."))
    d.user(d.L(en="delete the iso, installers and the export. leave my personal stuff. then prune docker",
               it="cancella la iso, gli installer e l'export. lascia stare le mie cose personali. poi fai prune di docker",
               de="lösch die ISO, die Installer und den Export. meine privaten Sachen bleiben. dann docker prune",
               fr="supprime l'iso, les installeurs et l'export. laisse mes trucs perso. puis prune docker",
               es="borra la iso, los instaladores y el export. deja mis cosas personales. luego haz prune de docker"))
    d.tool("sh", F("rm -v ~/Downloads/ubuntu-*.iso ~/Downloads/node-v*", " ~/Downloads/Docker-*.dmg" if mac else "",
                   " ~/Downloads/", export_name),
           lines(*[F(home, "/Downloads/", n) for n, s, _ in files
                   if any(k in "".join(s2.text for s2 in n) for k in ("ubuntu-", "node-v", "Docker-", "export_customers_"))]))
    reclaimed = f"{r.randint(18, 64)}.{r.randint(1, 9)}GB"
    d.tool("sh", "docker system prune -a -f",
           F("Deleted Images:\n",
             lines(*[T("untagged: ⟦i⟧", i=x.short(12)) for _ in range(r.randint(2, 5))]),
             lines(*[T("deleted: sha256:⟦s⟧", s=x.sha256()) for _ in range(r.randint(2, 6))]),
             "\nTotal reclaimed space: ", reclaimed, "\n"))
    d.agent(say(d, "done"), "\n",
            d.L(en=f"- removed installers/ISO and the customer export\n- docker prune reclaimed {reclaimed}\n- personal documents untouched",
                it=f"- rimossi installer/ISO e l'export clienti\n- docker prune ha liberato {reclaimed}\n- documenti personali non toccati",
                de=f"- Installer/ISO und Kundenexport gelöscht\n- docker prune hat {reclaimed} freigegeben\n- persönliche Dokumente unverändert",
                fr=f"- installeurs/ISO et export clients supprimés\n- docker prune a libéré {reclaimed}\n- documents personnels intacts",
                es=f"- eliminados instaladores/ISO y el export de clientes\n- docker prune liberó {reclaimed}\n- documentos personales intactos"))


# ================================================================ 3. docker logs of a failing container


@template("docker_logs_container", "plain", "shell", "log")
def docker_logs_container(d):
    g, x, r = d.g, d.x, d.rng
    svc = r.choice(["checkout", "api", "orders", "notifier", "billing"])
    cname = f"{d.project}-{svc}-1"
    d.user(T(d.L(en="⟦c⟧ keeps returning 500 on POST since the last deploy. Check the logs?",
                 it="⟦c⟧ continua a rispondere 500 sulle POST dall'ultimo deploy. Puoi guardare i log?",
                 de="⟦c⟧ liefert seit dem letzten Deploy bei POST immer 500. Schaust du in die Logs?",
                 fr="⟦c⟧ renvoie des 500 sur les POST depuis le dernier déploiement. Tu regardes les logs ?",
                 es="⟦c⟧ devuelve 500 en los POST desde el último despliegue. ¿Miras los logs?"), c=cname))
    ver = x.ver()
    ps_rows = [["CONTAINER ID", "IMAGE", "COMMAND", "CREATED", "STATUS", "PORTS", "NAMES"]]
    for name, img, cmd, port in [(svc, F(f"registry.{d.int_domain}/{d.project}:", ver), '"docker-entrypoint.s…"', 8080),
                                 ("db", "postgres:16-alpine", '"docker-entrypoint.s…"', 5432),
                                 ("redis", "redis:7.2", '"redis-server --appe…"', 6379),
                                 ("proxy", "nginx:1.27-alpine", '"/docker-entrypoint.…"', 80)][: r.randint(2, 4)]:
        ports = T("⟦ip⟧:⟦p⟧->⟦q⟧/tcp", ip=x.rip(False), p=x.port(port), q=x.port(port))
        ps_rows.append([x.short(12), img, cmd, r.choice(["2 hours ago", "41 minutes ago", "3 days ago"]),
                        r.choice(["Up 2 hours", "Up 41 minutes (healthy)", "Up 3 days"]), ports, f"{d.project}-{name}-1"])
    d.tool("sh", "docker ps", table(ps_rows, gap=3))
    cause = r.choice(["stripe", "smtp", "db"])
    fmt = r.choice(["json", "text"])
    n = r.randint(6, 26) if r.random() < 0.7 else r.randint(40, 70)
    log_rows = []
    secret_key = g.secret("stripe_live") if cause == "stripe" else None
    for i in range(n):
        c = d.person()
        ip = g.ip(r.choice(["public", "public", "private"]))
        email = g.email(c, "personal")
        ts = x.ts("iso_z", tick=(0.2, 9))
        path = r.choice(["/api/checkout", "/api/orders", "/api/cart", "/api/login", "/healthz"])
        status = 500 if path in ("/api/checkout", "/api/orders") and r.random() < 0.7 else r.choice([200, 200, 201, 204, 304])
        if path == "/healthz":
            status = 200
        rid = x.rid()
        if fmt == "json":
            if path == "/healthz":
                log_rows.append(F('{"level":"debug","time":"', ts, '","msg":"healthcheck ok"}'))
                continue
            log_rows.append(F('{"level":"', "error" if status >= 500 else "info", '","time":"', ts, '","req_id":"', rid,
                              '","method":"POST","path":"', path, '","status":', str(status), ',"ip":"', ip,
                              '","user":"', email, '","ms":', str(r.randint(4, 900)), "}"))
        else:
            if path == "/healthz":
                log_rows.append(F(ts, " DEBUG healthcheck ok"))
                continue
            log_rows.append(F(ts, " ", "ERROR" if status >= 500 else "INFO ", " [", rid, "] ", ip, " POST ", path, " ",
                              str(status), " user=", email))
        if status >= 500:
            if cause == "stripe":
                tail = secret_key.text[-4:] if secret_key.label else V.rand_str(r, V.ALNUM, 4)
                msg = F("StripeAuthenticationError: Invalid API Key provided: ", x.ph("api_key", "sk_live_********" + tail))
            elif cause == "smtp":
                msg = F("Error: Invalid login: 535-5.7.8 Username and Password not accepted (smtp.", d.domain, ":", x.port(587), ")")
            else:
                msg = F("Error: remaining connection slots are reserved for non-replication superuser connections")
            if fmt == "json":
                log_rows.append(F('{"level":"error","time":"', x.ts("iso_z", tick=(0, 0.05)), '","req_id":"', rid,
                                  '","err":"', msg, '"}'))
            else:
                log_rows.append(F(x.ts("iso_z", tick=(0, 0.05)), " ERROR [", rid, "] ", msg))
                if r.random() < 0.4:
                    log_rows.append(F("    at ", r.choice(["PaymentService.charge", "Mailer.send", "Pool.connect"]),
                                      " (/app/src/", r.choice(["payments", "mail", "db"]), ".js:", x.num(lo=10, hi=400), ":",
                                      x.num(lo=2, hi=60), ")"))
    d.tool("sh", f"docker logs --tail {len(log_rows)} {cname}", lines(*log_rows))
    d.agent(d.L(en="The 500s all fail at the same dependency. Let me look at the container's environment and network.",
                it="I 500 falliscono tutti sulla stessa dipendenza. Guardo l'ambiente e la rete del container.",
                de="Alle 500er scheitern an derselben Abhängigkeit. Ich schaue mir Umgebung und Netzwerk des Containers an.",
                fr="Les 500 échouent tous sur la même dépendance. Je regarde l'environnement et le réseau du conteneur.",
                es="Todos los 500 fallan en la misma dependencia. Miro el entorno y la red del contenedor."))
    net = f"172.{r.randint(18, 30)}.0"
    env = [F('"DATABASE_URL=postgres://shop:', g.password(), '@db:', x.port(5432), '/shop"'),
           F('"REDIS_URL=redis://redis:', x.port(6379), '/0"')]
    if cause == "stripe":
        env.append(F('"STRIPE_API_KEY=', secret_key, '"'))
    else:
        env.append(F('"STRIPE_API_KEY=', g.secret("stripe_live"), '"'))
    env.append(F('"SMTP_USER=', g.email(d.me, "work"), '"'))
    env.append(F('"SMTP_PASSWORD=', g.password(), '"'))
    if r.random() < 0.5:
        env.append(F('"SENTRY_DSN=', g.secret("sentry_dsn"), '"'))
    env += [F('"NODE_VERSION=', x.ver(r.choice(["20.11.1", "20.15.0", "22.9.0"])), '"'),
            '"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"']
    insp = F("[\n  [\n", J(",\n", [F("    ", e) for e in env]), "\n  ],\n  {\n",
             f'    "{d.project}_default": {{\n',
             '      "IPAMConfig": null,\n',
             '      "Gateway": "', _gip(d, f"{net}.1"), '",\n',
             '      "IPAddress": "', _gip(d, f"{net}.{r.randint(2, 9)}"), '",\n',
             '      "IPPrefixLen": 16,\n',
             '      "MacAddress": "', g.mac(0), '",\n',
             '      "NetworkID": "', x.sha256(), '",\n',
             '      "EndpointID": "', x.sha256(), '"\n',
             "    }\n  }\n]\n")
    d.tool("sh", f"docker inspect {cname} | jq '[.[0].Config.Env, .[0].NetworkSettings.Networks]'", insp)
    if cause == "stripe":
        d.agent(say(d, "explain"), "\n",
                d.L(en="The key in STRIPE_API_KEY was revoked (the error shows its masked tail). The deploy picked up the old value from the compose override instead of the rotated one.",
                    it="La chiave in STRIPE_API_KEY è stata revocata (l'errore ne mostra la coda mascherata). Il deploy ha preso il vecchio valore dall'override di compose invece di quello ruotato.",
                    de="Der Schlüssel in STRIPE_API_KEY wurde widerrufen (der Fehler zeigt das maskierte Ende). Das Deployment hat den alten Wert aus dem Compose-Override übernommen statt des rotierten.",
                    fr="La clé de STRIPE_API_KEY a été révoquée (l'erreur affiche sa fin masquée). Le déploiement a repris l'ancienne valeur depuis l'override compose au lieu de la nouvelle.",
                    es="La clave de STRIPE_API_KEY fue revocada (el error muestra su final enmascarado). El despliegue cogió el valor antiguo del override de compose en lugar del rotado."))
    elif cause == "smtp":
        d.agent(say(d, "explain"), "\n",
                d.L(en="Order creation sends the confirmation mail synchronously, and the SMTP login is rejected — so every POST fails. The mailbox password was changed; the container still has the old one.",
                    it="La creazione dell'ordine invia la mail di conferma in modo sincrono e il login SMTP viene rifiutato, quindi ogni POST fallisce. La password della casella è cambiata; il container ha ancora quella vecchia.",
                    de="Beim Anlegen der Bestellung wird die Bestätigungsmail synchron verschickt und der SMTP-Login wird abgelehnt — daher scheitert jeder POST. Das Postfach-Passwort wurde geändert, der Container hat noch das alte.",
                    fr="La création de commande envoie le mail de confirmation en synchrone et la connexion SMTP est refusée — donc chaque POST échoue. Le mot de passe de la boîte a changé ; le conteneur a encore l'ancien.",
                    es="Al crear el pedido se envía el correo de confirmación de forma síncrona y el login SMTP es rechazado, así que todos los POST fallan. La contraseña del buzón cambió y el contenedor tiene la vieja."))
    else:
        d.agent(say(d, "explain"), "\n",
                d.L(en="Postgres is out of connection slots: the new image raised the pool size to 50 per replica and there are 4 replicas against max_connections=100.",
                    it="Postgres ha esaurito gli slot di connessione: la nuova immagine ha portato il pool a 50 per replica e ci sono 4 repliche con max_connections=100.",
                    de="Postgres hat keine freien Verbindungen mehr: das neue Image hat den Pool auf 50 pro Replika erhöht, bei 4 Replikas und max_connections=100.",
                    fr="Postgres n'a plus de slots de connexion : la nouvelle image a passé le pool à 50 par réplique, avec 4 répliques pour max_connections=100.",
                    es="Postgres se quedó sin conexiones: la nueva imagen subió el pool a 50 por réplica y hay 4 réplicas con max_connections=100."))
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x="docker inspect"))
    d.user(say(d, r.choice(["thanks", "rotate_later"])))


# ================================================================ 4. kubectl pod debugging


@template("kubectl_pod_debug", "cc", "shell", "log")
def kubectl_pod_debug(d):
    g, x, r = d.g, d.x, d.rng
    ns = r.choice(["staging", "prod", "payments", "default", d.project.split("-")[0]])
    app = d.project
    d.user(T(d.L(en="⟦a⟧ pods in ⟦n⟧ are in CrashLoopBackOff after the secret rotation this morning. Can you look?",
                 it="I pod di ⟦a⟧ in ⟦n⟧ sono in CrashLoopBackOff dopo la rotazione dei secret di stamattina. Ci guardi?",
                 de="Die ⟦a⟧-Pods in ⟦n⟧ hängen seit der Secret-Rotation heute früh in CrashLoopBackOff. Kannst du draufschauen?",
                 fr="Les pods ⟦a⟧ dans ⟦n⟧ sont en CrashLoopBackOff depuis la rotation des secrets ce matin. Tu peux regarder ?",
                 es="Los pods de ⟦a⟧ en ⟦n⟧ están en CrashLoopBackOff tras la rotación de secretos de esta mañana. ¿Le echas un ojo?"),
                 a=app, n=ns))
    pod_net = f"10.{r.choice([42, 44, 96, 112])}.{r.randint(0, 15)}"
    nodes = [f"{r.choice(['worker', 'pool-a', 'gke-std', 'node'])}-{r.randint(1, 40)}" for _ in range(3)]
    node_ips = {n: f"10.0.{r.randint(0, 3)}.{r.randint(10, 250)}" for n in nodes}
    n_pods = r.randint(2, 6)
    pods = []
    rows = [["NAME", "READY", "STATUS", "RESTARTS", "AGE", "IP", "NODE", "NOMINATED NODE", "READINESS GATES"]]
    rs_hash = V.rand_str(r, 'bcdfghjklmnpqrstvwxz2456789', 10)
    for i in range(n_pods):
        pname = f"{app}-{rs_hash}-{V.rand_str(r, 'bcdfghjklmnpqrstvwxz2456789', 5)}"
        ip = f"{pod_net}.{r.randint(2, 250)}"
        node = r.choice(nodes)
        crash = i < n_pods - (1 if r.random() < 0.4 else 0)
        pods.append((pname, ip, node, crash))
        rows.append([pname, "0/1" if crash else "1/1", "CrashLoopBackOff" if crash else "Running",
                     f"{r.randint(3, 14)} ({r.randint(1, 5)}m ago)" if crash else "0", f"{r.randint(20, 90)}m",
                     _gip(d, ip), node, "<none>", "<none>"])
    d.tool("sh", f"kubectl get pods -n {ns} -l app={app} -o wide", table(rows, gap=3))
    pname, pip, pnode, _ = pods[0]
    sec_name = f"{app}-secrets"
    image_ver = x.ver()
    started = d.clock.t - dt.timedelta(minutes=r.randint(20, 90))
    ev_rows = [["Type", "Reason", "Age", "From", "Message"],
               ["----", "------", "----", "----", "-------"],
               ["Normal", "Scheduled", f"{r.randint(30, 90)}m", "default-scheduler", F(f"Successfully assigned {ns}/{pname} to {pnode}")],
               ["Normal", "Pulled", f"{r.randint(2, 9)}m (x{r.randint(3, 9)} over {r.randint(30, 80)}m)", "kubelet",
                F('Container image "', f"registry.{d.int_domain}/{app}:", image_ver, '" already present on machine')],
               ["Warning", "BackOff", f"{r.randint(5, 50)}s (x{r.randint(40, 300)} over {r.randint(30, 80)}m)", "kubelet",
                "Back-off restarting failed container app in pod " + pname + f"_{ns}"]]
    desc = F(
        "Name:             ", pname, "\n",
        "Namespace:        ", ns, "\n",
        "Priority:         0\n",
        "Service Account:  ", app, "\n",
        "Node:             ", pnode, "/", _gip(d, node_ips[pnode]), "\n",
        "Start Time:       ", x.ts("rfc2822", t=started), "\n",
        "Labels:           app=", app, "\n",
        "                  pod-template-hash=", x.id(pname.split("-")[-2]), "\n",
        "Status:           Running\n",
        "IP:               ", _gip(d, pip), "\n",
        "Containers:\n",
        "  app:\n",
        "    Container ID:   containerd://", x.sha256(), "\n",
        "    Image:          registry.", d.int_domain, "/", app, ":", image_ver, "\n",
        "    Image ID:       registry.", d.int_domain, "/", app, "@sha256:", x.sha256(), "\n",
        "    Port:           ", x.port(8080), "/TCP\n",
        "    State:          Waiting\n",
        "      Reason:       CrashLoopBackOff\n",
        "    Last State:     Terminated\n",
        "      Reason:       Error\n",
        "      Exit Code:    1\n",
        "    Environment Variables from:\n",
        "      ", sec_name, "  Secret  Optional: false\n",
        "    Environment:\n",
        "      NODE_ENV:  production\n",
        "Events:\n",
        table(ev_rows, gap=2),
    )
    d.tool("sh", f"kubectl describe pod {pname} -n {ns}", desc)
    cause = r.choice(["newline", "key", "stale"])
    db_ip = f"10.{r.randint(0, 9)}.{r.randint(0, 9)}.{r.randint(2, 250)}"
    log_lines = [F(x.ts("iso_z", tick=(1, 2)), " info  booting ", app, " v", image_ver),
                 F(x.ts("iso_z", tick=(0.1, 0.4)), " info  loading config from env")]
    if r.random() < 0.6:
        c = d.person()
        log_lines.append(F(x.ts("iso_z", tick=(0.1, 0.4)), " info  replaying job for ", g.email(c), " (client ",
                           g.ip("public"), ")"))
    if cause == "key":
        log_lines.append(F(x.ts("iso_z", tick=(0.1, 0.3)), " fatal config error: missing required env DB_PASSWORD"))
    else:
        log_lines.append(F(x.ts("iso_z", tick=(0.2, 1.2)), ' error connect to ', _gip(d, db_ip), ':', x.port(5432),
                           ' failed: FATAL:  password authentication failed for user "', app.replace("-", "_"), '"'))
    log_lines.append(F(x.ts("iso_z", tick=(0, 0.1)), " info  exiting with code 1"))
    d.tool("sh", f"kubectl logs {pname} -n {ns} --previous", lines(*log_lines))
    d.agent(say(d, "check_next", x=f"secret/{sec_name}"))
    pw = g.password()
    raw_pw = pw.text + ("\n" if cause == "newline" else "")

    def b64seg(seg, raw_text):
        enc = _b64(raw_text)
        if seg.label:
            return d.g.raw("secret", enc, "password")
        return x.ph("password", enc)

    pw_b64 = b64seg(pw, raw_pw)
    api = g.secret(r.choice(["stripe_live", "sendgrid", "twilio_auth", "openai"]))
    api_b64 = b64seg(api, api.text)
    key_name = "DB_PASSWORD" if cause != "key" else "DB_PASS"
    yaml = F(
        "apiVersion: v1\n",
        "data:\n",
        "  API_KEY: ", api_b64, "\n",
        "  ", key_name, ": ", pw_b64, "\n",
        "  DB_USER: ", _b64(app.replace("-", "_")), "\n",
        "kind: Secret\n",
        "metadata:\n",
        "  creationTimestamp: \"", x.ts("iso_s", t=d.clock.t - dt.timedelta(hours=r.randint(1, 6))), "\"\n",
        "  name: ", sec_name, "\n",
        "  namespace: ", ns, "\n",
        "  resourceVersion: \"", x.num(lo=1_000_000, hi=99_999_999), "\"\n",
        "  uid: ", x.uuid(), "\n",
        "type: Opaque\n",
    )
    d.tool("sh", f"kubectl get secret {sec_name} -n {ns} -o yaml", yaml)
    if cause == "key":
        d.agent(say(d, "explain"), "\n",
                d.L(en="The rotated secret was recreated with the key `DB_PASS`, but the app reads `DB_PASSWORD`. The pod crashes on the missing variable before it even tries to connect.",
                    it="Il secret ruotato è stato ricreato con la chiave `DB_PASS`, ma l'app legge `DB_PASSWORD`. Il pod va in crash per la variabile mancante prima ancora di connettersi.",
                    de="Das rotierte Secret wurde mit dem Schlüssel `DB_PASS` neu angelegt, die App liest aber `DB_PASSWORD`. Der Pod stürzt wegen der fehlenden Variable ab, bevor er sich überhaupt verbindet.",
                    fr="Le secret renouvelé a été recréé avec la clé `DB_PASS`, mais l'appli lit `DB_PASSWORD`. Le pod plante sur la variable manquante avant même de se connecter.",
                    es="El secreto rotado se recreó con la clave `DB_PASS`, pero la app lee `DB_PASSWORD`. El pod se cae por la variable que falta antes de conectar."))
        d.tool("sh", f"kubectl patch secret {sec_name} -n {ns} --type=json -p '[{{\"op\":\"move\",\"from\":\"/data/DB_PASS\",\"path\":\"/data/DB_PASSWORD\"}}]'",
               F(f"secret/{sec_name} patched\n"))
    else:
        dec = F(pw, "\n" if cause == "newline" else "")
        d.tool("sh", F("echo '", pw_b64, "' | base64 -d | cat -A" if cause == "newline" else "' | base64 -d"),
               dec if cause != "newline" else F(pw, "$\n"))
        if cause == "newline":
            d.agent(say(d, "explain"), "\n",
                    d.L(en="The decoded value ends with `\\n`: whoever rotated it ran `echo pw | base64` without `-n`, so Postgres receives the password plus a newline.",
                        it="Il valore decodificato termina con `\\n`: chi l'ha ruotato ha fatto `echo pw | base64` senza `-n`, quindi Postgres riceve la password più un a capo.",
                        de="Der dekodierte Wert endet mit `\\n`: beim Rotieren wurde `echo pw | base64` ohne `-n` benutzt, Postgres bekommt also Passwort plus Zeilenumbruch.",
                        fr="La valeur décodée se termine par `\\n` : la rotation a été faite avec `echo pw | base64` sans `-n`, Postgres reçoit donc le mot de passe suivi d'un saut de ligne.",
                        es="El valor decodificado termina en `\\n`: quien lo rotó usó `echo pw | base64` sin `-n`, así que Postgres recibe la contraseña con un salto de línea."))
        else:
            d.agent(say(d, "explain"), "\n",
                    d.L(en="The secret decodes fine, but the pods were started before the new value was applied; envFrom is only read at container start. A rollout restart picks it up.",
                        it="Il secret si decodifica correttamente, ma i pod sono partiti prima che il nuovo valore venisse applicato; envFrom viene letto solo all'avvio del container. Un rollout restart lo recepisce.",
                        de="Das Secret dekodiert korrekt, aber die Pods liefen schon vor dem neuen Wert; envFrom wird nur beim Containerstart gelesen. Ein Rollout-Restart übernimmt ihn.",
                        fr="Le secret se décode bien, mais les pods ont démarré avant l'application de la nouvelle valeur ; envFrom n'est lu qu'au démarrage du conteneur. Un rollout restart la prend en compte.",
                        es="El secreto se decodifica bien, pero los pods arrancaron antes de aplicar el valor nuevo; envFrom solo se lee al arrancar el contenedor. Un rollout restart lo recoge."))
    d.user(say(d, "go_ahead"))
    d.tool("sh", f"kubectl rollout restart deploy/{app} -n {ns} && kubectl rollout status deploy/{app} -n {ns}",
           F(f"deployment.apps/{app} restarted\n",
             f'Waiting for deployment "{app}" rollout to finish: 1 of {n_pods} updated replicas are available...\n',
             f'deployment "{app}" successfully rolled out\n'))
    d.agent(say(d, "done"), "\n- ",
            d.L(en="pods healthy again; the secret value itself was not changed in git (it lives only in the cluster)",
                it="pod di nuovo sani; il valore del secret non è stato toccato in git (vive solo nel cluster)",
                de="Pods wieder gesund; der Secret-Wert selbst liegt nicht in git (nur im Cluster)",
                fr="pods de nouveau sains ; la valeur du secret n'est pas dans git (elle vit seulement dans le cluster)",
                es="pods sanos otra vez; el valor del secreto no está en git (solo vive en el clúster)"))


# ================================================================ 5. psql: user cannot log in


def _cap_variant(text: str) -> str:
    local, _, dom = text.partition("@")
    parts = [p[:1].upper() + p[1:] for p in local.split(".")]
    return ".".join(parts) + "@" + dom


@template("psql_user_lookup", "xml", "shell")
def psql_user_lookup(d):
    g, x, r = d.g, d.x, d.rng
    cust = d.person()
    supp = d.person()
    email = g.email(cust, "personal")
    d.user(T(d.L(en="Ticket from ⟦s⟧ in support: customer ⟦n⟧ (⟦e⟧) can't log in since yesterday and says the reset mail never arrives. Can you check the prod DB (read-only role)?",
                 it="Ticket da ⟦s⟧ del supporto: il cliente ⟦n⟧ (⟦e⟧) non riesce ad accedere da ieri e dice che la mail di reset non arriva mai. Puoi controllare il DB di prod (ruolo in sola lettura)?",
                 de="Ticket von ⟦s⟧ aus dem Support: Kunde ⟦n⟧ (⟦e⟧) kann sich seit gestern nicht einloggen, die Reset-Mail kommt angeblich nie an. Kannst du in der Prod-DB nachsehen (Read-only-Rolle)?",
                 fr="Ticket de ⟦s⟧ au support : le client ⟦n⟧ (⟦e⟧) ne peut plus se connecter depuis hier et dit que le mail de réinitialisation n'arrive jamais. Tu peux vérifier la base de prod (rôle lecture seule) ?",
                 es="Ticket de ⟦s⟧ de soporte: el cliente ⟦n⟧ (⟦e⟧) no puede entrar desde ayer y dice que nunca le llega el correo de reseteo. ¿Puedes mirar la BD de prod (rol de solo lectura)?"),
             s=g.name(supp, "given"), n=g.name(cust), e=email))
    cause = r.choice(["locked", "bounce", "duplicate"])
    uid = r.randint(10_000, 2_400_000)
    if r.random() < 0.5:
        cols = [["id", "bigint", "", "not null", "nextval('users_id_seq'::regclass)"],
                ["email", "citext" if cause != "duplicate" else "character varying(320)", "", "not null", ""],
                ["full_name", "text", "", "", ""], ["phone", "text", "", "", ""],
                ["date_of_birth", "date", "", "", ""], ["password_hash", "text", "", "not null", ""],
                ["failed_logins", "integer", "", "not null", "0"], ["locked_until", "timestamp with time zone", "", "", ""],
                ["last_login_ip", "inet", "", "", ""], ["created_at", "timestamp with time zone", "", "not null", "now()"]]
        d.tool("sh", 'psql "$PROD_RO_URL" -c "\\d users"',
               F('                                  Table "public.users"\n'),
               grid(["Column", "Type", "Collation", "Nullable", "Default"], cols, footer="Indexes:\n    \"users_pkey\" PRIMARY KEY, btree (id)\n    \"users_email_key\" UNIQUE CONSTRAINT, btree (email)\n"))
    q = F("SELECT id, email, full_name, phone, date_of_birth, created_at, last_login_ip, failed_logins, locked_until "
          "FROM users WHERE lower(email) = lower('", email, "');")
    hdr = ["id", "email", "full_name", "phone", "date_of_birth", "created_at", "last_login_ip", "failed_logins", "locked_until"]
    created = _past(d, 200, 1500)

    def row(i, em, fails, locked):
        return [x.num(i), em, g.name(cust), g.phone(cust), g.birth(cust, "iso"), x.ts("space", t=created),
                g.ip("public"), str(fails), locked]

    rows = []
    if cause == "locked":
        rows.append(row(uid, email, r.randint(10, 25), x.ts("iso_off", t=d.clock.t + dt.timedelta(hours=r.randint(2, 20)))))
    elif cause == "bounce":
        rows.append(row(uid, email, r.randint(0, 3), ""))
    else:
        variant = g.raw("private_email", _cap_variant(email.text), "email") if email.label else x.ph("email")
        rows.append(row(uid, email, r.randint(0, 2), ""))
        created = _past(d, 10, 120)
        rows.append(row(uid + r.randint(1000, 90000), variant, r.randint(4, 9), ""))
    d.tool("sh", F('psql "$PROD_RO_URL" -c "', q, '"'), grid(hdr, rows))
    if cause == "locked":
        d.agent(d.L(en="The account is locked after repeated failures. Let me see where the attempts come from.",
                    it="L'account è bloccato dopo troppi tentativi falliti. Vediamo da dove arrivano.",
                    de="Das Konto ist nach wiederholten Fehlversuchen gesperrt. Mal sehen, woher die Versuche kommen.",
                    fr="Le compte est verrouillé après des échecs répétés. Voyons d'où viennent les tentatives.",
                    es="La cuenta está bloqueada tras varios fallos. Veamos de dónde vienen los intentos."))
        att = []
        t = d.clock.t - dt.timedelta(hours=r.randint(3, 20))
        bad_ips = [g.ip("public") for _ in range(r.randint(2, 5))]
        for _ in range(r.randint(8, 20)):
            t += dt.timedelta(seconds=r.randint(2, 400))
            att.append([x.ts("iso_off", t=t), r.choice(bad_ips), "f", r.choice(["python-requests/2.31.0", "curl/8.4.0", "Go-http-client/1.1", _UAS[3]])[:42]])
        att.reverse()
        d.tool("sh", F('psql "$PROD_RO_URL" -c "SELECT attempted_at, ip, success, user_agent FROM login_attempts WHERE user_id = ',
                       x.num(uid), ' ORDER BY attempted_at DESC LIMIT ', str(len(att)), ';"'),
               grid(["attempted_at", "ip", "success", "user_agent"], att))
        d.agent(say(d, "explain"), "\n",
                d.L(en="These are scripted attempts from a handful of hosting-provider IPs — classic credential stuffing. The lock is doing its job; the customer just can't get past it, and the reset flow is blocked while locked_until is in the future.",
                    it="Sono tentativi automatizzati da pochi IP di provider di hosting: credential stuffing classico. Il blocco funziona; il cliente però non riesce a superarlo, e il reset è bloccato finché locked_until è nel futuro.",
                    de="Das sind skriptgesteuerte Versuche von einigen Hosting-IPs — klassisches Credential Stuffing. Die Sperre funktioniert; der Kunde kommt nur nicht vorbei, und der Reset ist blockiert, solange locked_until in der Zukunft liegt.",
                    fr="Ce sont des tentatives scriptées depuis quelques IP d'hébergeurs — du credential stuffing classique. Le verrouillage fonctionne ; le client ne peut juste pas le contourner, et la réinitialisation est bloquée tant que locked_until est dans le futur.",
                    es="Son intentos automatizados desde unas pocas IP de proveedores de hosting: credential stuffing de manual. El bloqueo funciona; el cliente simplemente no puede pasarlo y el reseteo queda bloqueado mientras locked_until esté en el futuro."))
        d.user(d.L(en="ok unlock it, I have a write session open", it="ok sbloccalo, ho una sessione in scrittura aperta",
                   de="ok entsperr es, ich hab eine Schreib-Session offen", fr="ok débloque-le, j'ai une session en écriture ouverte",
                   es="vale, desbloquéalo, tengo una sesión de escritura abierta"))
        d.tool("sh", F('psql "$PROD_RW_URL" -c "UPDATE users SET failed_logins = 0, locked_until = NULL, force_password_reset = true WHERE id = ',
                       x.num(uid), ';"'), F("UPDATE 1\n"))
    elif cause == "bounce":
        d.agent(d.L(en="Nothing wrong with the account itself. Since the reset mail never arrives, checking the suppression list.",
                    it="L'account in sé è a posto. Visto che la mail di reset non arriva, controllo la lista di soppressione.",
                    de="Mit dem Konto selbst ist alles ok. Da die Reset-Mail nie ankommt, prüfe ich die Suppression-Liste.",
                    fr="Rien d'anormal sur le compte. Comme le mail de réinitialisation n'arrive jamais, je regarde la liste de suppression.",
                    es="La cuenta en sí está bien. Como el correo de reseteo no llega, reviso la lista de supresión."))
        sup = [[email, "hard_bounce", r.choice(["550 5.1.1 mailbox unavailable", "552 5.2.2 mailbox full", "550 5.7.1 rejected by policy"]),
                x.ts("space", t=_past(d, 30, 400))]]
        d.tool("sh", F('psql "$PROD_RO_URL" -c "SELECT email, reason, smtp_response, created_at FROM email_suppressions WHERE lower(email) = lower(\'',
                       email, '\');"'), grid(["email", "reason", "smtp_response", "created_at"], sup))
        d.agent(say(d, "explain"), "\n",
                d.L(en="The address bounced once months ago (mailbox full at the time) and we never send to suppressed addresses again — including password resets. Removing the suppression entry lets the reset go out.",
                    it="L'indirizzo è rimbalzato una volta mesi fa (casella piena all'epoca) e non inviamo più nulla agli indirizzi soppressi — reset password compresi. Rimuovendo la voce di soppressione il reset parte.",
                    de="Die Adresse ist vor Monaten einmal gebounct (Postfach damals voll) und an unterdrückte Adressen senden wir nie wieder — auch keine Passwort-Resets. Ohne den Suppression-Eintrag geht der Reset raus.",
                    fr="L'adresse a rebondi une fois il y a des mois (boîte pleine à l'époque) et on n'envoie plus rien aux adresses supprimées — réinitialisations comprises. Retirer l'entrée permet d'envoyer le mail.",
                    es="La dirección rebotó una vez hace meses (buzón lleno entonces) y nunca volvemos a enviar a direcciones suprimidas, tampoco reseteos. Quitando la entrada el correo sale."))
        d.user(say(d, "go_ahead"))
        d.tool("sh", F('psql "$PROD_RW_URL" -c "DELETE FROM email_suppressions WHERE lower(email) = lower(\'', email, '\');"'),
               F("DELETE 1\n"))
    else:
        d.agent(say(d, "explain"), "\n",
                d.L(en="There are two accounts whose emails differ only in capitalisation — the column is varchar, not citext, so the unique constraint didn't catch it. The login form lowercases the input and hits the older row; the reset mail goes to the newer one.",
                    it="Ci sono due account con email che differiscono solo per maiuscole/minuscole: la colonna è varchar, non citext, quindi il vincolo unique non li ha intercettati. Il login converte in minuscolo e trova la riga vecchia; la mail di reset va a quella nuova.",
                    de="Es gibt zwei Konten, deren E-Mails sich nur in der Groß-/Kleinschreibung unterscheiden — die Spalte ist varchar statt citext, daher greift der Unique-Constraint nicht. Das Login-Formular schreibt klein und trifft die ältere Zeile; die Reset-Mail geht an die neuere.",
                    fr="Il y a deux comptes dont les emails ne diffèrent que par la casse — la colonne est en varchar, pas en citext, donc la contrainte unique ne les a pas détectés. Le formulaire met en minuscules et tombe sur l'ancienne ligne ; le mail part vers la nouvelle.",
                    es="Hay dos cuentas cuyos emails solo cambian en mayúsculas/minúsculas: la columna es varchar, no citext, así que la restricción unique no lo detectó. El login pasa a minúsculas y encuentra la fila antigua; el correo de reseteo va a la nueva."))
        d.user(d.L(en="don't touch prod data, just tell support what to do",
                   it="non toccare i dati di prod, dimmi solo cosa dire al supporto",
                   de="fass die Prod-Daten nicht an, sag nur dem Support, was zu tun ist",
                   fr="ne touche pas aux données de prod, dis juste au support quoi faire",
                   es="no toques datos de prod, solo dime qué decirle a soporte"))
    cl = d.lang_of(cust)
    if cause == "duplicate":
        reply = d.Lp(cl, en="Hi ⟦c⟧, we found two accounts registered with your address. We have just sent a reset link to the one you use to log in; our team will merge the two accounts within two working days.",
                     it="Gentile ⟦c⟧, abbiamo trovato due account registrati con il suo indirizzo. Le abbiamo appena inviato un link di reimpostazione per quello con cui accede; il nostro team unirà i due account entro due giorni lavorativi.",
                     de="Hallo ⟦c⟧, wir haben zwei Konten mit Ihrer Adresse gefunden. Wir haben Ihnen soeben einen Reset-Link für das Konto geschickt, mit dem Sie sich anmelden; unser Team führt beide Konten innerhalb von zwei Werktagen zusammen.",
                     fr="Bonjour ⟦c⟧, nous avons trouvé deux comptes enregistrés avec votre adresse. Nous venons d'envoyer un lien de réinitialisation pour celui que vous utilisez ; notre équipe fusionnera les deux comptes sous deux jours ouvrés.",
                     es="Hola ⟦c⟧, hemos encontrado dos cuentas registradas con su dirección. Le acabamos de enviar un enlace de restablecimiento para la que usa al entrar; nuestro equipo unirá ambas cuentas en dos días laborables.")
    else:
        reply = d.Lp(cl, en="Hi ⟦c⟧, your account is accessible again. Please request a new password reset link from the login page; it will arrive within a few minutes. If it doesn't, reply to this message.",
                     it="Gentile ⟦c⟧, il suo account è di nuovo accessibile. Richieda un nuovo link di reimpostazione della password dalla pagina di accesso; arriverà entro pochi minuti. In caso contrario, risponda a questo messaggio.",
                     de="Hallo ⟦c⟧, Ihr Konto ist wieder erreichbar. Bitte fordern Sie auf der Login-Seite einen neuen Link zum Zurücksetzen des Passworts an; er kommt innerhalb weniger Minuten. Falls nicht, antworten Sie einfach auf diese Nachricht.",
                     fr="Bonjour ⟦c⟧, votre compte est de nouveau accessible. Demandez un nouveau lien de réinitialisation depuis la page de connexion ; il arrivera d'ici quelques minutes. Sinon, répondez à ce message.",
                     es="Hola ⟦c⟧, su cuenta vuelve a estar accesible. Solicite un nuevo enlace para restablecer la contraseña desde la página de acceso; llegará en unos minutos. Si no, responda a este mensaje.")
    d.agent(T(d.L(en="Draft reply ⟦s⟧ can send to the customer:", it="Bozza di risposta che ⟦s⟧ può mandare al cliente:",
                  de="Antwortentwurf, den ⟦s⟧ an den Kunden schicken kann:",
                  fr="Brouillon de réponse que ⟦s⟧ peut envoyer au client :",
                  es="Borrador de respuesta que ⟦s⟧ puede enviar al cliente:"), s=g.name(supp, "given")),
            "\n\n> ", T(reply, c=g.name(cust, r.choice(["full", "given"]))))


# ================================================================ 6. redis: random logouts


@template("redis_sessions", "md", "shell")
def redis_sessions(d):
    g, x, r = d.g, d.x, d.rng
    rip = g.ip("private")
    rpw = g.password()
    d.user(d.L(en="Users keep getting logged out of the dashboard at random, sometimes after a couple of minutes. Sessions are in Redis. Can you dig in?",
               it="Gli utenti vengono sloggati dalla dashboard a caso, a volte dopo un paio di minuti. Le sessioni stanno in Redis. Ci guardi?",
               de="Nutzer fliegen zufällig aus dem Dashboard, manchmal schon nach ein paar Minuten. Die Sessions liegen in Redis. Kannst du das untersuchen?",
               fr="Les utilisateurs sont déconnectés du dashboard au hasard, parfois au bout de deux minutes. Les sessions sont dans Redis. Tu peux creuser ?",
               es="A los usuarios se les cierra la sesión del dashboard al azar, a veces a los dos minutos. Las sesiones están en Redis. ¿Lo investigas?"))
    d.agent(say(d, "look_first", x="Redis"))
    cli = F("redis-cli -h ", rip, " -a '", rpw, "' --no-auth-warning")
    cause = r.choice(["eviction", "ttl"])
    used = r.randint(900, 1023) if cause == "eviction" else r.randint(80, 400)
    d.tool("sh", F(cli, " INFO memory | grep -E 'used_memory_human|maxmemory_human|maxmemory_policy'"),
           lines(f"used_memory_human:{used}.{r.randint(10, 99)}M", "maxmemory_human:1.00G",
                 f"maxmemory_policy:{'allkeys-lru' if cause == 'eviction' else 'volatile-lru'}"))
    d.tool("sh", F(cli, " INFO stats | grep -E 'evicted_keys|expired_keys|keyspace_hits'"),
           lines(f"expired_keys:{r.randint(10_000, 900_000)}",
                 f"evicted_keys:{r.randint(40_000, 900_000) if cause == 'eviction' else 0}",
                 f"keyspace_hits:{r.randint(10**6, 10**8)}"))
    u = d.person()
    exp = d.clock.t + dt.timedelta(seconds=r.randint(30, 86000))
    csrf = F(',"csrfSecret":"', g.secret("bearer_opaque"), '"') if d.secret_ok else ""
    sess_json = F('{"cookie":{"originalMaxAge":', str(86400 if cause == "ttl" else 86400000), ',"expires":"',
                  x.ts("iso_z", t=exp), '","secure":true,"httpOnly":true,"path":"/","sameSite":"lax"},',
                  '"passport":{"user":{"id":', x.num(lo=1000, hi=999999), ',"email":"', g.email(u, r.choice(["work", "personal"])),
                  '","name":"', g.name(u), '","role":"', r.choice(["admin", "viewer", "editor"]), '"}},',
                  '"ip":"', g.ip("public"), '","ua":"', r.choice(_UAS), '"', csrf, '}\n')
    if d.secret_ok:
        sids = [g.secret("session") for _ in range(r.randint(4, 12))]
        d.tool("sh", F(cli, " --scan --pattern 'sess:*' | head -n ", str(len(sids))), lines(*[F("sess:", s) for s in sids]))
        pick = sids[r.randrange(len(sids))]
        key = F("sess:", pick)
    else:
        d.tool("sh", F(cli, " --scan --pattern 'sess:*' | wc -l"), F(f"{r.randint(800, 90_000):>8}\n"))
        d.tool("sh", F("KEY=$(", cli, " --scan --pattern 'sess:*' | head -n 1); echo \"${KEY:0:13}…\""),
               F(x.ph("token", "sess:" + V.rand_str(r, "abcdefghijklmnopqrstuvwxyz0123456789", 8) + "…"), "\n"))
        key = F('"$KEY"')
    d.tool("sh", F(cli, " GET ", key), sess_json)
    ttl = r.randint(3, 80) if cause == "ttl" else r.randint(40_000, 86_000)
    d.tool("sh", F(cli, " TTL ", key), F(f"(integer) {ttl}\n"))
    if r.random() < 0.5:
        d.tool("sh", F(cli, " INFO keyspace"),
               lines("# Keyspace", f"db0:keys={r.randint(20_000, 2_000_000)},expires={r.randint(20_000, 2_000_000)},avg_ttl={r.randint(1000, 90_000_000)},subexpiry=0",
                     f"db1:keys={r.randint(10, 9000)},expires=0,avg_ttl=0,subexpiry=0"))
    if cause == "eviction":
        d.agent(say(d, "explain"), "\n",
                d.L(en="Redis is at its memory limit with `allkeys-lru`, so under pressure it evicts *any* key — including live sessions. The rate-limiter and cache keys share the same instance and push sessions out.",
                    it="Redis è al limite di memoria con `allkeys-lru`, quindi sotto pressione elimina *qualsiasi* chiave, sessioni attive comprese. Le chiavi del rate limiter e della cache condividono la stessa istanza e spingono fuori le sessioni.",
                    de="Redis ist mit `allkeys-lru` am Speicherlimit und wirft unter Druck *beliebige* Schlüssel raus — auch aktive Sessions. Rate-Limiter- und Cache-Keys teilen sich die Instanz und verdrängen die Sessions.",
                    fr="Redis est à sa limite mémoire avec `allkeys-lru` : sous pression il évince *n'importe quelle* clé, sessions actives comprises. Les clés du rate limiter et du cache partagent l'instance et poussent les sessions dehors.",
                    es="Redis está en su límite de memoria con `allkeys-lru`, así que bajo presión desaloja *cualquier* clave, sesiones activas incluidas. Las claves del rate limiter y la caché comparten instancia y expulsan las sesiones."),
                "\n\n", d.L(en="Options: move sessions to their own db/instance with `volatile-ttl`, or raise maxmemory. See ",
                            it="Opzioni: spostare le sessioni in un'istanza dedicata con `volatile-ttl`, oppure alzare maxmemory. Vedi ",
                            de="Optionen: Sessions in eine eigene Instanz mit `volatile-ttl` verschieben oder maxmemory erhöhen. Siehe ",
                            fr="Options : déplacer les sessions dans une instance dédiée en `volatile-ttl`, ou augmenter maxmemory. Voir ",
                            es="Opciones: mover las sesiones a una instancia propia con `volatile-ttl` o subir maxmemory. Ver "),
                x.url("docs", "https://redis.io/docs/latest/develop/reference/eviction/"))
        d.user(say(d, "go_ahead"))
        d.tool("sh", F(cli, " CONFIG SET maxmemory-policy volatile-lru && ", "redis-cli -h ", rip, " -a '", rpw,
                       "' --no-auth-warning CONFIG SET maxmemory 2gb"), lines("OK", "OK"))
    else:
        d.agent(d.L(en="The TTL is tiny and originalMaxAge looks like seconds. Checking the session setup in the code.",
                    it="Il TTL è minuscolo e originalMaxAge sembra espresso in secondi. Controllo la configurazione della sessione nel codice.",
                    de="Die TTL ist winzig und originalMaxAge sieht nach Sekunden aus. Ich prüfe das Session-Setup im Code.",
                    fr="Le TTL est minuscule et originalMaxAge ressemble à des secondes. Je regarde la config de session dans le code.",
                    es="El TTL es diminuto y originalMaxAge parece estar en segundos. Reviso la configuración de sesión en el código."))
        fallback = g.secret("hex32") if d.secret_ok else None
        secret_line = F("  secret: process.env.SESSION_SECRET || '", fallback, "',\n") if fallback else F("  secret: process.env.SESSION_SECRET,\n")
        src = F(
            "import session from 'express-session';\n",
            "import RedisStore from 'connect-redis';\n",
            "import { redis } from './redis';\n\n",
            "export const sessions = session({\n",
            "  store: new RedisStore({ client: redis, prefix: 'sess:' }),\n",
            secret_line,
            "  resave: false,\n",
            "  saveUninitialized: false,\n",
            "  cookie: {\n",
            "    secure: true,\n",
            "    sameSite: 'lax',\n",
            "    maxAge: 24 * 60 * 60, // one day\n",
            "  },\n",
            "});\n")
        d.tool("read", "src/session.ts", numbered(src, width=3, sep="  "))
        d.agent(say(d, "explain"), "\n",
                d.L(en="`cookie.maxAge` is in **milliseconds** in express-session; `24*60*60` is 86 seconds. The store derives the Redis TTL from it, so sessions expire after ~1.5 minutes of inactivity.",
                    it="In express-session `cookie.maxAge` è in **millisecondi**; `24*60*60` sono 86 secondi. Lo store ricava il TTL di Redis da lì, quindi le sessioni scadono dopo circa un minuto e mezzo di inattività.",
                    de="`cookie.maxAge` ist in express-session in **Millisekunden**; `24*60*60` sind 86 Sekunden. Der Store leitet die Redis-TTL davon ab, Sessions laufen also nach ~1,5 Minuten Inaktivität ab.",
                    fr="Dans express-session, `cookie.maxAge` est en **millisecondes** ; `24*60*60` font 86 secondes. Le store en déduit le TTL Redis, donc les sessions expirent après ~1 min 30 d'inactivité.",
                    es="En express-session `cookie.maxAge` va en **milisegundos**; `24*60*60` son 86 segundos. El store calcula el TTL de Redis a partir de ahí, así que las sesiones caducan tras ~1,5 minutos de inactividad."))
        if d.secret_ok:
            d.agent(say(d, "secret_warning", x="src/session.ts"))
        d.tool("edit", "src/session.ts",
               F(F("-", secret_line, "+  secret: requireEnv('SESSION_SECRET'),\n") if fallback else "",
                 "-    maxAge: 24 * 60 * 60, // one day\n+    maxAge: 24 * 60 * 60 * 1000, // one day, in ms\n"))
    d.agent(say(d, "done"), "\n",
            d.L(en="- root cause identified and fixed\n- no session data was copied anywhere",
                it="- causa individuata e corretta\n- nessun dato di sessione copiato altrove",
                de="- Ursache gefunden und behoben\n- keine Session-Daten irgendwohin kopiert",
                fr="- cause trouvée et corrigée\n- aucune donnée de session copiée ailleurs",
                es="- causa encontrada y corregida\n- no se copiaron datos de sesión a ningún sitio"))


# ================================================================ 7. AWS CLI: exposed access key


@template("aws_cli_keys", "colon", "shell")
def aws_cli_keys(d):
    g, x, r = d.g, d.x, d.rng
    me = d.me
    iam_user = g.user(me, r.choice([0, 1, 9]))
    acct = V.rand_str(r, "0123456789", 12)
    region = r.choice(["eu-central-1", "eu-west-1", "eu-south-1", "us-east-1", "eu-west-3"])
    leaked = g.secret("aws_akid")
    other = g.secret("aws_akid")
    case_no = x.num(lo=10**9, hi=10**10 - 1)
    d.user(T(d.L(en="AWS sent an email to ⟦e⟧ (case ⟦c⟧) saying one of our access keys was found exposed on a public site. Help me figure out which one and rotate it.",
                 it="AWS ha mandato una mail a ⟦e⟧ (caso ⟦c⟧) dicendo che una delle nostre access key è stata trovata esposta su un sito pubblico. Aiutami a capire quale e a ruotarla.",
                 de="AWS hat eine Mail an ⟦e⟧ geschickt (Case ⟦c⟧): einer unserer Access Keys wurde öffentlich gefunden. Hilf mir herauszufinden, welcher, und ihn zu rotieren.",
                 fr="AWS a envoyé un mail à ⟦e⟧ (dossier ⟦c⟧) disant qu'une de nos clés d'accès a été trouvée exposée sur un site public. Aide-moi à trouver laquelle et à la renouveler.",
                 es="AWS mandó un correo a ⟦e⟧ (caso ⟦c⟧) diciendo que una de nuestras access keys apareció expuesta en un sitio público. Ayúdame a ver cuál es y a rotarla."),
             e=g.email(me, "work"), c=case_no))
    d.tool("sh", "aws sts get-caller-identity",
           F('{\n    "UserId": "', x.id("AIDA" + V.rand_str(r, V.UPPER + "234567", 17)), '",\n',
             '    "Account": "', x.id(acct), '",\n',
             '    "Arn": "arn:aws:iam::', x.id(acct), ':user/', iam_user, '"\n}\n'))
    created = [_past(d, 300, 900), _past(d, 5, 120)]
    keys = [(leaked, created[0]), (other, created[1])]
    r.shuffle(keys)
    meta = J(",\n", [F('        {\n            "UserName": "', iam_user, '",\n            "AccessKeyId": "', k,
                       '",\n            "Status": "Active",\n            "CreateDate": "', x.ts("iso_off", t=t), '"\n        }')
                     for k, t in keys])
    d.tool("sh", F("aws iam list-access-keys --user-name ", iam_user),
           F('{\n    "AccessKeyMetadata": [\n', meta, "\n    ]\n}\n"))
    tail_ak = leaked.text[-4:] if leaked.label else "MPLE"
    conf = table([["      Name", "Value", "Type", "Location"],
                  ["      ----", "-----", "----", "--------"],
                  ["   profile", "<not set>", "None", "None"],
                  ["access_key", x.ph("api_key", "****************" + tail_ak), "shared-credentials-file", ""],
                  ["secret_key", x.ph("api_key", "****************" + V.rand_str(r, V.ALNUM, 4)), "shared-credentials-file", ""],
                  ["    region", region, "config-file", "~/.aws/config"]], gap=4)
    d.tool("sh", "aws configure list", conf)
    d.agent(d.L(en="Your default profile uses the older key. Let me check what is in the credentials file.",
                it="Il profilo di default usa la chiave più vecchia. Controllo cosa c'è nel file delle credenziali.",
                de="Dein Default-Profil nutzt den älteren Schlüssel. Ich schaue in die Credentials-Datei.",
                fr="Ton profil par défaut utilise l'ancienne clé. Je regarde le fichier de credentials.",
                es="Tu perfil por defecto usa la clave antigua. Miro qué hay en el fichero de credenciales."))
    cred = F("[default]\naws_access_key_id = ", leaked, "\naws_secret_access_key = ", g.secret("aws_secret"), "\n")
    if r.random() < 0.6:
        cred += F("\n[", d.slug, "-ci]\naws_access_key_id = ", other, "\naws_secret_access_key = ", g.secret("aws_secret"),
                  "\nregion = ", region, "\n")
    if r.random() < 0.4:
        cred += F("\n[personal]\naws_access_key_id = ", g.secret("aws_akid"), "\naws_secret_access_key = ",
                  g.secret("aws_secret"), "\n")
    d.tool("read", "~/.aws/credentials", cred)
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x="~/.aws/credentials"))
    n_ev = r.randint(4, 14)
    ev_rows = []
    t = d.clock.t - dt.timedelta(minutes=n_ev * 125 + r.randint(30, 900))
    foreign = [g.ip("public") for _ in range(r.randint(1, 3))]
    office = g.ip("public")
    for i in range(n_ev):
        t += dt.timedelta(minutes=r.randint(1, 120))
        bad = r.random() < 0.6
        ev_rows.append(F(x.ts("iso_off", t=t), "\t",
                         r.choice(["ListBuckets", "GetCallerIdentity", "DescribeInstances", "RunInstances", "CreateUser"])
                         if bad else r.choice(["GetObject", "PutObject", "DescribeStacks"]),
                         "\t", iam_user, "\t", r.choice(foreign) if bad else office, "\t",
                         r.choice(["aws-cli/2.15.30 Python/3.11.8", "Boto3/1.34.69", "python-requests/2.31.0"]) if bad else "aws-cli/2.17.0"))
    d.tool("sh", F("aws cloudtrail lookup-events --region ", region, " --lookup-attributes AttributeKey=AccessKeyId,AttributeValue=",
                   leaked, " --max-results ", str(n_ev),
                   " | jq -r '.Events[] | [.EventTime, .EventName, .Username, (.CloudTrailEvent|fromjson|.sourceIPAddress), (.CloudTrailEvent|fromjson|.userAgent)] | @tsv'"),
           lines(*ev_rows))
    d.agent(say(d, "explain"), "\n",
            d.L(en="The older key is being used from addresses that are not your office egress, and someone already tried RunInstances/CreateUser. Deactivate it now, then create a replacement.",
                it="La chiave più vecchia viene usata da indirizzi che non sono l'uscita del vostro ufficio, e qualcuno ha già provato RunInstances/CreateUser. Va disattivata subito, poi ne creiamo una nuova.",
                de="Der ältere Schlüssel wird von Adressen benutzt, die nicht euer Büro-Ausgang sind, und jemand hat schon RunInstances/CreateUser versucht. Sofort deaktivieren, dann Ersatz anlegen.",
                fr="L'ancienne clé est utilisée depuis des adresses qui ne sont pas la sortie de votre bureau, et quelqu'un a déjà tenté RunInstances/CreateUser. Il faut la désactiver tout de suite, puis en créer une nouvelle.",
                es="La clave antigua se está usando desde direcciones que no son la salida de vuestra oficina, y alguien ya probó RunInstances/CreateUser. Hay que desactivarla ya y crear una nueva."))
    d.user(say(d, "go_ahead"))
    d.tool("sh", F("aws iam update-access-key --user-name ", iam_user, " --access-key-id ", leaked, " --status Inactive"), F(""))
    d.tool("sh", F("aws iam create-access-key --user-name ", iam_user),
           F('{\n    "AccessKey": {\n        "UserName": "', iam_user, '",\n        "AccessKeyId": "', g.secret("aws_akid"),
             '",\n        "Status": "Active",\n        "SecretAccessKey": "', g.secret("aws_secret"),
             '",\n        "CreateDate": "', x.ts("iso_off", tick=(30, 120)), '"\n    }\n}\n'))
    if r.random() < 0.5:
        d.tool("sh", "aws s3 ls",
               lines(*[F(x.ts("space", t=_past(d, 100, 2000)), " ", d.slug, "-", b)
                       for b in r.sample(["backups", "customer-exports", "static-assets", "terraform-state", "logs", "invoices"], r.randint(3, 6))]))
        d.agent(d.L(en="Worth checking the access logs of the export and invoice buckets for the same source IPs.",
                    it="Conviene controllare gli access log dei bucket di export e fatture per gli stessi IP sorgente.",
                    de="Es lohnt sich, die Access-Logs der Export- und Rechnungs-Buckets auf dieselben Quell-IPs zu prüfen.",
                    fr="Il faudrait vérifier les logs d'accès des buckets d'export et de factures pour les mêmes IP sources.",
                    es="Conviene revisar los logs de acceso de los buckets de exportaciones y facturas buscando las mismas IP de origen."))
    d.agent(say(d, "done"), "\n",
            d.L(en="- leaked key set to Inactive (delete it after 24h if nothing breaks)\n- new key created — put it in ~/.aws/credentials yourself, I didn't write it to disk\n- reply to the AWS case once the old key is deleted",
                it="- chiave esposta impostata su Inactive (eliminala dopo 24h se non si rompe nulla)\n- nuova chiave creata: mettila tu in ~/.aws/credentials, non l'ho scritta su disco\n- rispondi al caso AWS dopo aver eliminato la vecchia chiave",
                de="- geleakter Schlüssel auf Inactive (nach 24h löschen, wenn nichts kaputtgeht)\n- neuer Schlüssel erstellt — trag ihn selbst in ~/.aws/credentials ein, ich habe ihn nicht gespeichert\n- AWS-Case beantworten, sobald der alte Schlüssel gelöscht ist",
                fr="- clé exposée passée en Inactive (supprime-la après 24 h si rien ne casse)\n- nouvelle clé créée — mets-la toi-même dans ~/.aws/credentials, je ne l'ai pas écrite sur disque\n- réponds au dossier AWS une fois l'ancienne clé supprimée",
                es="- clave expuesta en Inactive (bórrala pasadas 24 h si no se rompe nada)\n- nueva clave creada: ponla tú en ~/.aws/credentials, no la he escrito en disco\n- responde al caso de AWS cuando borres la clave vieja"))


# ================================================================ 8. npm publish 401


@template("npm_publish_auth", "jsonl", "shell", "file")
def npm_publish_auth(d):
    g, x, r = d.g, d.x, d.rng
    me = d.me
    scope = "@" + d.slug
    pkg = r.choice(["ui-kit", "api-client", "eslint-config", "logger", "feature-flags", "i18n-utils"])
    full = f"{scope}/{pkg}"
    ver = x.ver(f"{r.randint(0, 4)}.{r.randint(0, 20)}.{r.randint(0, 12)}")
    cause = r.choice(["expired", "github"])
    d.user(T(d.L(en="npm publish fails with a 401 for ⟦p⟧, it worked last month. Can you sort it out?",
                 it="npm publish fallisce con un 401 per ⟦p⟧, il mese scorso funzionava. Riesci a sistemarlo?",
                 de="npm publish schlägt für ⟦p⟧ mit 401 fehl, letzten Monat ging es noch. Kannst du das klären?",
                 fr="npm publish échoue avec un 401 pour ⟦p⟧, ça marchait le mois dernier. Tu peux régler ça ?",
                 es="npm publish falla con un 401 para ⟦p⟧, el mes pasado funcionaba. ¿Lo arreglas?"), p=full))
    reg = "https://registry.npmjs.org/" if cause == "expired" else "https://npm.pkg.github.com/"
    log_ts = x.ts("iso_z", tick=(1, 4))
    log_name = _ts_seg(log_ts.text.replace(":", "_").replace(".", "_"))
    files_n = r.randint(8, 60)
    pub = F("npm notice\n",
            "npm notice 📦  ", full, "@", ver, "\n",
            "npm notice === Tarball Contents ===\n",
            lines(*[F("npm notice ", f"{r.randint(1, 90)}.{r.randint(0, 9)}kB".ljust(8), " ", f)
                    for f in r.sample(["README.md", "dist/index.js", "dist/index.d.ts", "dist/index.mjs", "package.json",
                                       "LICENSE", "dist/utils.js", "CHANGELOG.md"], r.randint(3, 7))]),
            "npm notice === Tarball Details ===\n",
            "npm notice name:          ", full, "\n",
            "npm notice version:       ", ver, "\n",
            "npm notice filename:      ", d.slug, "-", pkg, "-", ver, ".tgz\n",
            "npm notice package size:  ", f"{r.randint(5, 300)}.{r.randint(0, 9)} kB\n",
            "npm notice unpacked size: ", f"{r.randint(20, 900)}.{r.randint(0, 9)} kB\n",
            "npm notice shasum:        ", x.sha(), "\n",
            "npm notice integrity:     sha512-", x.id(V.rand_str(r, V.B64, 20) + "[...]" + V.rand_str(r, V.B64, 8) + "=="), "\n",
            "npm notice total files:   ", str(files_n), "\n",
            "npm notice\n",
            "npm notice Publishing to ", x.url("registry", reg), " with tag latest and restricted access\n",
            "npm ERR! code E401\n",
            "npm ERR! 401 Unauthorized - PUT ", x.url("registry", reg.rstrip("/") + "/" + full.replace("/", "%2f")),
            " - ", "unauthenticated: User cannot be authenticated with the token provided." if cause == "expired"
            else "authentication token not provided", "\n\n",
            "npm ERR! A complete log of this run can be found in: ", _home(d), "/.npm/_logs/", log_name, "-debug-0.log\n")
    d.tool("sh", "npm publish", pub)
    d.agent(say(d, "look_first", x="~/.npmrc"))
    tok = g.secret("npm")
    rc = F("//registry.npmjs.org/:_authToken=", tok, "\n",
           "init-author-name=", g.name(me), "\n",
           "init-author-email=", g.email(me, r.choice(["work", "personal"])), "\n",
           "init-license=MIT\n")
    if r.random() < 0.5:
        rc += F("registry=", x.url("registry", "https://registry.npmjs.org/"), "\n")
    d.tool("read", "~/.npmrc", rc)
    if cause == "github":
        d.tool("read", ".npmrc", F(scope, ":registry=", x.url("registry", "https://npm.pkg.github.com/"), "\n",
                                   "//npm.pkg.github.com/:_authToken=", x.ph("token", "${GITHUB_TOKEN}"), "\n"))
    contribs = d.people(r.randint(1, 4))
    author_url = g.url("profile", me)
    pkg_json = F('{\n  "name": "', full, '",\n  "version": "', ver, '",\n',
                 '  "description": "', {"ui-kit": "Shared UI components", "api-client": "Typed client for the internal API",
                                       "eslint-config": "House ESLint rules", "logger": "Structured logger",
                                       "feature-flags": "Feature flag helpers", "i18n-utils": "Translation helpers"}[pkg], '",\n',
                 '  "author": "', g.name(me), " <", g.email(me, "work"), "> (", author_url, ')",\n',
                 '  "contributors": [\n',
                 J(",\n", [F('    "', g.name(c), " <", g.email(c, "work"), '>"') for c in contribs]),
                 "\n  ],\n",
                 '  "repository": {\n    "type": "git",\n    "url": "', g.url("repo", me), '"\n  },\n',
                 '  "main": "dist/index.js",\n  "types": "dist/index.d.ts",\n',
                 '  "publishConfig": {\n    "access": "restricted"', ',\n    "registry": "' if cause == "github" else "",
                 x.url("registry", "https://npm.pkg.github.com/") if cause == "github" else "",
                 '"' if cause == "github" else "", "\n  },\n",
                 '  "license": "', r.choice(["MIT", "UNLICENSED", "Apache-2.0"]), '",\n',
                 '  "devDependencies": {\n    "typescript": "^', x.ver(r.choice(["5.4.5", "5.6.3"])), '",\n    "tsup": "^',
                 x.ver(r.choice(["8.0.2", "8.3.0"])), '"\n  }\n}\n')
    d.tool("read", "package.json", pkg_json)
    if cause == "expired":
        d.tool("sh", "npm whoami", F("npm ERR! code E401\nnpm ERR! 401 Unauthorized - GET ",
                                     x.url("registry", "https://registry.npmjs.org/-/whoami"), "\n"))
        d.agent(say(d, "explain"), "\n",
                d.L(en="The token in ~/.npmrc is no longer valid — granular tokens expire, and this one is older than its lifetime. Log in again to mint a new one.",
                    it="Il token in ~/.npmrc non è più valido: i token granulari scadono e questo ha superato la sua durata. Rifai il login per generarne uno nuovo.",
                    de="Das Token in ~/.npmrc ist nicht mehr gültig — granulare Tokens laufen ab, und dieses ist älter als seine Laufzeit. Neu einloggen erzeugt ein neues.",
                    fr="Le jeton de ~/.npmrc n'est plus valide — les jetons granulaires expirent, et celui-ci a dépassé sa durée. Reconnecte-toi pour en générer un nouveau.",
                    es="El token de ~/.npmrc ya no es válido: los tokens granulares caducan y este superó su vigencia. Vuelve a hacer login para generar uno nuevo."))
        d.user(d.L(en="done, I ran npm login in my terminal", it="fatto, ho lanciato npm login nel mio terminale",
                   de="erledigt, ich habe npm login in meinem Terminal ausgeführt", fr="c'est fait, j'ai lancé npm login dans mon terminal",
                   es="hecho, he ejecutado npm login en mi terminal"))
        d.tool("sh", "npm whoami", F(g.user(me), "\n"))
    else:
        d.agent(say(d, "explain"), "\n",
                d.L(en="The scope is published to GitHub Packages, and the project .npmrc reads the token from GITHUB_TOKEN, which isn't set in this shell. The token in ~/.npmrc is for npmjs.org and isn't used for this scope.",
                    it="Lo scope è pubblicato su GitHub Packages e il .npmrc del progetto legge il token da GITHUB_TOKEN, che in questa shell non è impostato. Il token in ~/.npmrc è per npmjs.org e non viene usato per questo scope.",
                    de="Der Scope wird nach GitHub Packages veröffentlicht, und die Projekt-.npmrc liest das Token aus GITHUB_TOKEN, das in dieser Shell nicht gesetzt ist. Das Token in ~/.npmrc gilt für npmjs.org und wird für diesen Scope nicht benutzt.",
                    fr="Le scope est publié sur GitHub Packages et le .npmrc du projet lit le jeton dans GITHUB_TOKEN, qui n'est pas défini dans ce shell. Le jeton de ~/.npmrc est pour npmjs.org et n'est pas utilisé pour ce scope.",
                    es="El scope se publica en GitHub Packages y el .npmrc del proyecto lee el token de GITHUB_TOKEN, que no está definido en esta shell. El token de ~/.npmrc es de npmjs.org y no se usa para este scope."))
        gh = g.secret("github_pat")
        d.user(d.L(en="here's a PAT with write:packages: ", it="ecco un PAT con write:packages: ",
                   de="hier ein PAT mit write:packages: ", fr="voilà un PAT avec write:packages : ",
                   es="aquí tienes un PAT con write:packages: "), gh)
        d.tool("sh", F("GITHUB_TOKEN=", gh, " npm whoami --registry=https://npm.pkg.github.com"), F(g.user(me), "\n"))
    d.tool("sh", "npm publish" if cause == "expired" else F("GITHUB_TOKEN=", x.ph("token", "***"), " npm publish"),
           F("npm notice Publishing to ", x.url("registry", reg), " with tag latest and restricted access\n+ ", full, "@", ver, "\n"))
    d.agent(say(d, "done"), "\n", T(d.L(en="- ⟦p⟧ published\n- no token was written to the repository",
                                        it="- ⟦p⟧ pubblicato\n- nessun token è stato scritto nel repository",
                                        de="- ⟦p⟧ veröffentlicht\n- kein Token wurde ins Repository geschrieben",
                                        fr="- ⟦p⟧ publié\n- aucun jeton n'a été écrit dans le dépôt",
                                        es="- ⟦p⟧ publicado\n- no se escribió ningún token en el repositorio"), p=F(full, "@", ver)))


# ================================================================ 9. shell history audit


def _hist_cmds(d, people) -> list:
    """(kind, fragment) pairs for history lines that a secret grep would match."""
    g, x, r = d.g, d.x, d.rng
    me = d.me
    so = d.secret_ok

    def ref(text):
        return x.ph("password", text)

    c = []
    c.append(("token", F("export GITHUB_TOKEN=", g.secret("github_pat") if so else ref("$(op read op://Private/github/token)"))))
    c.append(("password", F("mysql -u root -p", g.password(), " -h ", g.ip("private"), " shop") if so
              else F("mysql -u root -p -h ", g.ip("private"), " shop")))
    c.append(("bearer", F('curl -sH "Authorization: Bearer ', g.jwt({"email": g.email(me).text}) if so else ref("$TOKEN"),
                          '" https://api.', d.domain, "/v1/customers/", x.num(lo=1000, hi=999999))))
    for p in people:
        c.append(("ssh", F("ssh ", g.user(p), "@", g.ip(r.choice(["private", "public"])))))
    c.append(("scp", F("scp prod_dump.sql.gz ", g.user(r.choice(people)), "@bastion.", d.int_domain, ":/tmp/")))
    c.append(("password", F("psql postgres://admin:", g.password() if so else ref("${PGPASSWORD}"), "@", g.ip("private"),
                            ":", x.port(5432), "/prod")))
    c.append(("aws", F("aws configure set aws_secret_access_key ", g.secret("aws_secret") if so else ref("\"$(pass aws/secret)\""))))
    c.append(("token", F("docker login -u ", g.user(me), " -p ", g.secret("dockerhub")) if so
              else F("docker login -u ", g.user(me), " --password-stdin < ~/.docker/token")))
    c.append(("token", F("git clone https://", g.user(me), ":", g.secret("github_pat"), "@github.com/", d.slug, "/", d.project, ".git") if so
              else F("git clone ", g.url("repo", me))))
    c.append(("api_key", F("export OPENAI_API_KEY=", g.secret("openai") if so else ref("$(security find-generic-password -s openai -w)"))))
    c.append(("password", F("curl -u ", g.email(me), ":", g.password() if so else ref("\"$JIRA_PW\""),
                            " https://jira.", d.int_domain, "/rest/api/2/myself")))
    c.append(("api_key", F("export STRIPE_SECRET_KEY=", g.secret("stripe_live") if so else ref("sk_test_XXXXXXXXXXXXXXXXXXXXXXXX"))))
    c.append(("webhook", F("curl -X POST -d '{\"text\":\"deploy done\"}' ", g.secret("slack_webhook") if so else ref("$SLACK_WEBHOOK_URL"))))
    c.append(("password", F("redis-cli -h ", g.ip("private"), " -a ", g.password() if so else ref("\"$REDIS_PASSWORD\""))))
    c.append(("api_key", F("kubectl create secret generic mail --from-literal=SENDGRID_API_KEY=",
                           g.secret("sendgrid") if so else ref("\"$SENDGRID_API_KEY\""))))
    return c


_BORING = ["git status", "git pull --rebase", "npm test", "npm run dev", "make lint", "docker compose up -d",
           "docker compose logs -f api", "ls -la", "cd ..", "code .", "git push", "pytest -x -q", "k9s",
           "kubectl get pods -n staging", "brew upgrade", "htop", "git log --oneline -n 20", "terraform plan",
           "npm ci", "go test ./...", "cargo build --release", "vim ~/.zshrc", "source ~/.zshrc", "tig"]


@template("shell_history_audit", "tslog", "shell")
def shell_history_audit(d):
    g, x, r = d.g, d.x, d.rng
    home = _home(d)
    d.user(d.L(en="I'm handing this laptop back to IT on Friday. Before that, check my shell history for anything sensitive and clean it up.",
               it="Venerdì restituisco questo portatile all'IT. Prima controlla la mia shell history per roba sensibile e ripuliscila.",
               de="Ich gebe den Laptop am Freitag an die IT zurück. Prüf vorher meine Shell-History auf sensible Sachen und räum sie auf.",
               fr="Je rends ce portable à l'IT vendredi. Avant ça, vérifie mon historique shell pour tout ce qui est sensible et nettoie-le.",
               es="El viernes devuelvo este portátil a IT. Antes revisa mi historial de la shell por si hay algo sensible y límpialo."))
    total = r.randint(4000, 60000)
    d.tool("sh", "wc -l ~/.zsh_history", F(f"{total:>8} ", home, "/.zsh_history\n"))
    t = d.clock.t - dt.timedelta(days=r.randint(200, 700))

    def stamp():
        nonlocal t
        t += dt.timedelta(seconds=r.randint(5, 9 * 3600))
        if t > d.clock.t:
            t = d.clock.t - dt.timedelta(seconds=r.randint(60, 3600))
        return x.ts("epoch", t=t)

    if r.random() < 0.5:
        k = r.randint(12, 45) if r.random() < 0.7 else r.randint(60, 140)
        tail_rows = []
        tt = d.clock.t - dt.timedelta(hours=r.randint(2, 30))
        for _ in range(k):
            tt += dt.timedelta(seconds=r.randint(3, 600))
            cmd = r.choice(_BORING)
            if r.random() < 0.12:
                cmd = F("ssh ", g.user(d.me), "@", g.ip("private"))
            tail_rows.append(F(": ", x.ts("epoch", t=min(tt, d.clock.t)), ":", str(r.randint(0, 40)), ";", cmd))
        d.tool("sh", f"tail -n {k} ~/.zsh_history", lines(*tail_rows))
    people = [d.me] + d.people(r.randint(1, 3))
    cmds = _hist_cmds(d, people)
    chosen = r.sample(cmds, r.randint(6, min(16, len(cmds))))
    lnos = sorted(r.sample(range(40, total), len(chosen)))
    hits = []
    for ln, (kind, frag) in zip(lnos, chosen):
        hits.append((ln, kind, frag))
    pat = "'TOKEN|SECRET|PASSWORD|_KEY|Bearer|-p[^ ]|-a |ssh |scp |://[^ /]*:[^ /]*@|hooks\\.slack'"
    d.tool("sh", f"grep -nE {pat} ~/.zsh_history",
           lines(*[F(x.num(ln), ":: ", stamp(), ":0;", frag) for ln, _, frag in hits]))
    sec_kinds = {"token", "bearer", "aws", "api_key", "webhook", "password"}
    live = [h for h in hits if h[1] in sec_kinds] if d.secret_ok else []
    if live:
        d.agent(d.L(en=f"Found {len(live)} lines with credentials in clear text, plus some lines that only reveal hosts and usernames:",
                    it=f"Ho trovato {len(live)} righe con credenziali in chiaro, più alcune che rivelano solo host e nomi utente:",
                    de=f"{len(live)} Zeilen enthalten Zugangsdaten im Klartext, dazu einige, die nur Hosts und Benutzernamen verraten:",
                    fr=f"{len(live)} lignes contiennent des identifiants en clair, plus quelques-unes qui ne révèlent que des hôtes et des noms d'utilisateur :",
                    es=f"He encontrado {len(live)} líneas con credenciales en claro, además de algunas que solo revelan hosts y usuarios:"),
                "\n", lines(*[F("  - line ", x.num(ln), ": ", {"token": "access token", "bearer": "bearer token (JWT)",
                                                               "aws": "AWS secret key", "api_key": "API key",
                                                               "webhook": "Slack webhook URL", "password": "password"}[k])
                              for ln, k, _ in live]),
                "\n", d.L(en="All of these should be rotated regardless of the cleanup — history files get synced and backed up.",
                          it="Vanno ruotate tutte comunque, a prescindere dalla pulizia: i file di history vengono sincronizzati e salvati nei backup.",
                          de="Die sollten unabhängig vom Aufräumen alle rotiert werden — History-Dateien landen in Syncs und Backups.",
                          fr="Il faut toutes les renouveler, nettoyage ou pas — les fichiers d'historique sont synchronisés et sauvegardés.",
                          es="Hay que rotarlas todas igualmente: los ficheros de historial se sincronizan y van a las copias de seguridad."))
    else:
        d.agent(d.L(en="No credentials in clear text — the secret-looking lines use references (env vars, password manager). What remains are hosts, IPs and usernames, which IT doesn't need either.",
                    it="Nessuna credenziale in chiaro: le righe sospette usano riferimenti (variabili d'ambiente, password manager). Restano host, IP e nomi utente, che comunque all'IT non servono.",
                    de="Keine Zugangsdaten im Klartext — die verdächtigen Zeilen nutzen Referenzen (Umgebungsvariablen, Passwortmanager). Übrig bleiben Hosts, IPs und Benutzernamen, die die IT auch nicht braucht.",
                    fr="Aucun identifiant en clair — les lignes suspectes utilisent des références (variables d'environnement, gestionnaire de mots de passe). Restent des hôtes, des IP et des noms d'utilisateur, dont l'IT n'a pas besoin non plus.",
                    es="No hay credenciales en claro: las líneas sospechosas usan referencias (variables de entorno, gestor de contraseñas). Quedan hosts, IP y usuarios, que IT tampoco necesita."))
    d.user(d.L(en="ok, wipe those lines (keep a backup until I've rotated everything)",
               it="ok, cancella quelle righe (tieni un backup finché non ho ruotato tutto)",
               de="ok, lösch die Zeilen (behalte ein Backup, bis ich alles rotiert habe)",
               fr="ok, efface ces lignes (garde une sauvegarde jusqu'à ce que j'aie tout renouvelé)",
               es="vale, borra esas líneas (guarda una copia hasta que lo haya rotado todo)"))
    sed_i = "-i ''" if d.os == "mac" else "-i"
    d.tool("sh", f"cp ~/.zsh_history ~/.zsh_history.pre-audit && chmod 600 ~/.zsh_history.pre-audit && "
                 f"LC_ALL=C sed {sed_i} -E '/TOKEN=|SECRET|_KEY=|Bearer |-p[^ ]|-a [^$]|:[^ /@]+@github|hooks\\.slack/d' ~/.zsh_history && wc -l ~/.zsh_history",
           F(f"{total - len(live) - r.randint(0, 3):>8} ", home, "/.zsh_history\n"))
    d.tool("edit", "~/.zshrc", F("+setopt HIST_IGNORE_SPACE   # commands starting with a space are not saved\n",
                                 "+setopt HIST_REDUCE_BLANKS\n"))
    d.agent(say(d, "done"), "\n",
            d.L(en="- matching lines removed; backup at ~/.zsh_history.pre-audit (delete it with `rm -P` once rotation is done)\n- from now on, prefix a command with a space to keep it out of history",
                it="- righe corrispondenti rimosse; backup in ~/.zsh_history.pre-audit (cancellalo con `rm -P` finita la rotazione)\n- d'ora in poi, anteponi uno spazio a un comando per non salvarlo nella history",
                de="- passende Zeilen entfernt; Backup unter ~/.zsh_history.pre-audit (nach der Rotation mit `rm -P` löschen)\n- künftig ein Leerzeichen voranstellen, damit ein Befehl nicht in der History landet",
                fr="- lignes correspondantes supprimées ; sauvegarde dans ~/.zsh_history.pre-audit (à effacer avec `rm -P` après la rotation)\n- désormais, préfixe une commande d'un espace pour qu'elle ne soit pas enregistrée",
                es="- líneas eliminadas; copia en ~/.zsh_history.pre-audit (bórrala con `rm -P` cuando termines de rotar)\n- a partir de ahora, empieza un comando con un espacio para que no quede en el historial"))


# ================================================================ 10. cron / systemd backup failing


@template("cron_systemd_backup", "box", "shell", "log")
def cron_systemd_backup(d):
    g, x, r = d.g, d.x, d.rng
    ops = d.person()
    old_owner = d.person()
    host = r.choice(["db-backup-01", "pg-main", "db-primary", "batch-runner"])
    db_ip = f"10.{r.randint(0, 40)}.{r.randint(0, 9)}.{r.randint(2, 250)}"
    remote_ip = g.ip(r.choice(["private", "public"]))
    remote_user = g.user(old_owner) if r.random() < 0.5 else "backup"
    days = r.randint(3, 9)
    d.user(T(d.L(en="The nightly DB backup on ⟦h⟧ hasn't produced a file for ⟦n⟧ days and nobody got an alert. Can you find out why?",
                 it="Il backup notturno del DB su ⟦h⟧ non produce file da ⟦n⟧ giorni e nessuno ha ricevuto un avviso. Riesci a capire perché?",
                 de="Das nächtliche DB-Backup auf ⟦h⟧ hat seit ⟦n⟧ Tagen keine Datei erzeugt, und niemand wurde alarmiert. Findest du raus, warum?",
                 fr="La sauvegarde nocturne de la base sur ⟦h⟧ ne produit plus de fichier depuis ⟦n⟧ jours et personne n'a été alerté. Tu peux trouver pourquoi ?",
                 es="La copia nocturna de la BD en ⟦h⟧ lleva ⟦n⟧ días sin generar fichero y nadie recibió alerta. ¿Averiguas por qué?"),
             h=host, n=str(days)))
    cron = F("MAILTO=", g.email(ops, "work"), "\n", "SHELL=/bin/bash\n", "# m h  dom mon dow   command\n",
             "#30 2 * * * /opt/backup/backup.sh >> /var/log/backup.log 2>&1   # moved to systemd timer (",
             g.name(old_owner, "initial"), ", ", x.ts("date", t=_past(d, 60, 300)), ")\n",
             "15 */6 * * * /usr/local/bin/cleanup-tmp.sh\n")
    d.tool("sh", "crontab -l", cron)
    d.agent(d.L(en="The cron entry is commented out in favour of a systemd timer — and MAILTO only applies to cron, which explains the missing alerts. Checking the timer.",
                it="La riga di cron è commentata a favore di un timer systemd, e MAILTO vale solo per cron: ecco perché non arrivano avvisi. Controllo il timer.",
                de="Der Cron-Eintrag ist zugunsten eines systemd-Timers auskommentiert — und MAILTO gilt nur für Cron, daher keine Alarme. Ich prüfe den Timer.",
                fr="L'entrée cron est commentée au profit d'un timer systemd — et MAILTO ne s'applique qu'à cron, d'où l'absence d'alertes. Je vérifie le timer.",
                es="La entrada de cron está comentada en favor de un timer de systemd, y MAILTO solo aplica a cron: por eso no hay alertas. Reviso el timer."))
    now = d.clock.t
    last_run = now.replace(hour=2, minute=30, second=r.randint(0, 59))
    if last_run > now:
        last_run -= dt.timedelta(days=1)
    next_run = last_run + dt.timedelta(days=1)
    last_fail = last_run + dt.timedelta(seconds=r.randint(20, 400))
    ago_h = max(1, int((now - last_fail).total_seconds() // 3600))
    left_h = max(1, int((next_run - now).total_seconds() // 3600))
    d.tool("sh", "systemctl status backup.timer backup.service --no-pager",
           F("● backup.timer - Nightly database backup\n",
             "     Loaded: loaded (/etc/systemd/system/backup.timer; enabled; preset: enabled)\n",
             "     Active: active (waiting) since ", x.ts("space", t=_past(d, 20, 90)), " UTC; ", str(r.randint(3, 12)), " weeks ago\n",
             "    Trigger: ", x.ts("space", t=next_run), " UTC; ", str(left_h), "h left\n",
             "   Triggers: ● backup.service\n\n",
             "× backup.service - Nightly database backup\n",
             "     Loaded: loaded (/etc/systemd/system/backup.service; static)\n",
             "     Active: failed (Result: exit-code) since ", x.ts("space", t=last_fail), " UTC; ", str(ago_h), "h ago\n",
             "   Main PID: ", x.num(lo=1000, hi=99999), " (code=exited, status=", str(r.choice([1, 2, 12, 23, 255])), ")\n",
             "        CPU: ", f"{r.randint(1, 900)}ms\n"))
    cause = r.choice(["password", "hostkey", "disk"])
    jl = []
    shown = min(days, r.randint(2, 6))
    for back in range(shown - 1, -1, -1):
        t = last_run - dt.timedelta(days=back)
        pid = str(r.randint(1000, 99999))

        def jline(msg, src=f"backup.sh[{pid}]"):
            nonlocal t
            t += dt.timedelta(seconds=r.randint(0, 40))
            return F(x.ts("syslog", t=t), " ", host, " ", src, ": ", msg)

        jl.append(jline("Starting backup.service - Nightly database backup...", "systemd[1]"))
        if cause == "password":
            jl.append(jline(F('pg_dump: error: connection to server at "', _gip(d, db_ip), '", port ', x.port(5432),
                              ' failed: FATAL:  password authentication failed for user "backup"')))
        elif cause == "hostkey":
            jl.append(jline(F("pg_dump finished, ", str(r.randint(200, 9000)), " MB written")))
            jl.append(jline("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@"))
            jl.append(jline("@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @"))
            jl.append(jline(F("Host key for ", remote_ip, " has changed and you have requested strict checking.")))
            jl.append(jline("Host key verification failed."))
            jl.append(jline("rsync: connection unexpectedly closed (0 bytes received so far) [sender]"))
        else:
            jl.append(jline(F("pg_dump: error: could not write to output file: No space left on device")))
        jl.append(jline("backup.service: Main process exited, code=exited, status=1/FAILURE", "systemd[1]"))
        jl.append(jline("backup.service: Failed with result 'exit-code'.", "systemd[1]"))
    d.tool("sh", f"journalctl -u backup.service --since '-{days}d' --no-pager | tail -n {len(jl)}", lines(*jl))
    pw = g.password()
    script = F("#!/usr/bin/env bash\n",
               "# Nightly backup — maintained by ", g.name(old_owner), " <", g.email(old_owner, "work"), ">\n",
               "set -euo pipefail\n\n",
               "export PGPASSWORD='", pw, "'\n",
               "OUT=/var/backups/app-$(date +%F).sql.gz\n\n",
               "pg_dump -h ", _gip(d, db_ip), " -U backup -d app | gzip > \"$OUT\"\n",
               "rsync -az -e \"ssh -i /root/.ssh/backup_ed25519\" /var/backups/ ", remote_user, "@", remote_ip, ":/srv/backups/", host, "/\n",
               "find /var/backups -name 'app-*.sql.gz' -mtime +", str(r.choice([7, 14, 30])), " -delete\n",
               "echo \"backup ok: $OUT\" | mail -s \"[", host, "] backup ok\" ", g.email(ops, "work"), "\n")
    d.tool("read", "/opt/backup/backup.sh", numbered(script, width=3, sep="  "))
    if cause == "password":
        d.agent(say(d, "explain"), "\n",
                d.L(en="The `backup` role's password was rotated, but the script still exports the old value inline. Moving it to /root/.pgpass (mode 600) avoids hard-coding it again.",
                    it="La password del ruolo `backup` è stata ruotata, ma lo script esporta ancora il vecchio valore in chiaro. Spostarla in /root/.pgpass (permessi 600) evita di riscriverla nello script.",
                    de="Das Passwort der Rolle `backup` wurde rotiert, das Skript exportiert aber noch den alten Wert. Mit /root/.pgpass (Modus 600) muss es nicht mehr im Skript stehen.",
                    fr="Le mot de passe du rôle `backup` a été renouvelé, mais le script exporte encore l'ancienne valeur en dur. Le passer dans /root/.pgpass (mode 600) évite de le recoder.",
                    es="La contraseña del rol `backup` se rotó, pero el script sigue exportando el valor viejo. Pasarla a /root/.pgpass (modo 600) evita tenerla en el script."))
        d.tool("write", "/root/.pgpass", F(_gip(d, db_ip), ":", x.port(5432), ":app:backup:", g.password(), "\n"))
    elif cause == "hostkey":
        d.tool("sh", F("ssh-keygen -F ", remote_ip, " | head -n 2; ssh-keyscan -t ed25519 ", remote_ip, " 2>/dev/null"),
               F("# Host ", remote_ip, " found: line ", x.num(lo=2, hi=40), "\n",
                 remote_ip, " ssh-ed25519 ", x.id("AAAAC3NzaC1lZDI1NTE5AAAAI" + V.rand_str(r, V.B64, 43)), "\n",
                 remote_ip, " ssh-ed25519 ", x.id("AAAAC3NzaC1lZDI1NTE5AAAAI" + V.rand_str(r, V.B64, 43)), "\n"))
        d.agent(say(d, "explain"), "\n",
                d.L(en="The backup target was reinstalled and has a new host key, so strict host checking aborts rsync. Confirm the new fingerprint with whoever rebuilt it before replacing the known_hosts entry.",
                    it="La destinazione dei backup è stata reinstallata e ha una nuova host key, quindi il controllo stretto blocca rsync. Conferma la nuova fingerprint con chi l'ha reinstallata prima di sostituire la voce in known_hosts.",
                    de="Das Backup-Ziel wurde neu installiert und hat einen neuen Host-Key, daher bricht rsync wegen strikter Prüfung ab. Bestätige den neuen Fingerprint mit dem, der den Host neu aufgesetzt hat, bevor du known_hosts änderst.",
                    fr="La cible de sauvegarde a été réinstallée et a une nouvelle clé d'hôte, donc la vérification stricte arrête rsync. Confirme la nouvelle empreinte avec la personne qui l'a réinstallée avant de remplacer l'entrée known_hosts.",
                    es="El destino de las copias se reinstaló y tiene una host key nueva, así que la comprobación estricta corta rsync. Confirma la nueva huella con quien lo reinstaló antes de reemplazar la entrada de known_hosts."))
    else:
        d.tool("sh", "df -h /var/backups && ls -1t /var/backups | head -n 5",
               F(table([["Filesystem", "Size", "Used", "Avail", "Use%", "Mounted on"],
                        ["/dev/sdb1", "200G", "200G", "0", "100%", "/var/backups"]]),
                 lines(*[F("app-", x.ts("date", t=_past(d, days + i, days + i)), ".sql.gz") for i in range(5)])))
        d.agent(say(d, "explain"), "\n",
                d.L(en="The volume is full: retention deletes files older than N days only *after* a successful run, so once one run failed for space, cleanup never ran again.",
                    it="Il volume è pieno: la retention cancella i file vecchi solo *dopo* un'esecuzione riuscita, quindi dopo il primo fallimento per spazio la pulizia non è più partita.",
                    de="Das Volume ist voll: die Aufbewahrung löscht alte Dateien erst *nach* einem erfolgreichen Lauf — nachdem ein Lauf am Platz gescheitert ist, lief die Bereinigung nie wieder.",
                    fr="Le volume est plein : la rétention ne supprime les vieux fichiers qu'*après* une exécution réussie, donc après un premier échec faute de place, le nettoyage n'a plus jamais tourné.",
                    es="El volumen está lleno: la retención borra los ficheros viejos solo *después* de una ejecución correcta, así que tras el primer fallo por espacio la limpieza no volvió a ejecutarse."))
    if d.secret_ok:
        d.agent(say(d, "secret_warning", x="/opt/backup/backup.sh"))
    d.agent(d.L(en="For alerts: add `OnFailure=notify-email@%n.service` to the unit — MAILTO in the crontab no longer does anything.",
                it="Per gli avvisi: aggiungi `OnFailure=notify-email@%n.service` alla unit — il MAILTO del crontab ormai non fa più nulla.",
                de="Für Alarme: `OnFailure=notify-email@%n.service` in die Unit eintragen — MAILTO in der Crontab bewirkt nichts mehr.",
                fr="Pour les alertes : ajoute `OnFailure=notify-email@%n.service` à l'unité — le MAILTO de la crontab ne sert plus à rien.",
                es="Para las alertas: añade `OnFailure=notify-email@%n.service` a la unidad; el MAILTO del crontab ya no hace nada."))
    d.user(say(d, r.choice(["thanks", "go_ahead"])))


# ================================================================ 11. mysql dump restore


def _sq(d, seg: Seg) -> Seg:
    """Value as mysqldump writes it inside a single-quoted literal."""
    if seg.label and "'" in seg.text:
        return d.g.raw(seg.label, seg.text.replace("'", "\\'"))
    return seg


@template("mysql_dump_restore", "hai", "shell", "file")
def mysql_dump_restore(d):
    g, x, r = d.g, d.x, d.rng
    db = r.choice(["shop", "crm", "bookings", "loyalty"])
    dump_day = _past(d, 1, 3)
    d.user(T(d.L(en="I need yesterday's prod dump of ⟦db⟧ restored into my local ⟦db⟧_dev to reproduce a bug in the invoice export.",
                 it="Mi serve il dump di prod di ieri di ⟦db⟧ ripristinato nel mio ⟦db⟧_dev locale per riprodurre un bug nell'export fatture.",
                 de="Ich brauche den gestrigen Prod-Dump von ⟦db⟧ in meiner lokalen ⟦db⟧_dev, um einen Bug im Rechnungsexport nachzustellen.",
                 fr="J'ai besoin du dump de prod d'hier de ⟦db⟧ restauré dans mon ⟦db⟧_dev local pour reproduire un bug dans l'export des factures.",
                 es="Necesito el dump de prod de ayer de ⟦db⟧ restaurado en mi ⟦db⟧_dev local para reproducir un bug en la exportación de facturas."),
             db=db))
    fname = F(db, "_", x.ts("date", t=dump_day), ".sql.gz")
    ls_rows = [["-rw-r--r--", "1", _owner(d), "staff" if d.os == "mac" else _owner(d), f"{r.randint(80, 900)}M",
                x.ts("ls", t=dump_day + dt.timedelta(hours=3)), fname]]
    for i in range(r.randint(1, 4)):
        ls_rows.append(["-rw-r--r--", "1", _owner(d), "staff" if d.os == "mac" else _owner(d), f"{r.randint(80, 900)}M",
                        x.ts("ls", t=dump_day - dt.timedelta(days=7 * (i + 1))), F(db, "_", x.ts("date", t=dump_day - dt.timedelta(days=7 * (i + 1))), ".sql.gz")])
    d.tool("sh", "ls -lh ~/dumps/", table(ls_rows, gap=1))
    src_ip = g.ip("private")
    n = r.randint(3, 20) if r.random() < 0.7 else r.randint(25, 60)
    tuples = []
    for i in range(n):
        p = d.person()
        tuples.append(F("(", x.num(1000 + i * r.randint(1, 9)), ",'", _sq(d, g.name(p, "given")), "','", _sq(d, g.name(p, "family")),
                        "','", g.email(p, "personal"), "','", g.phone(p), "','", _sq(d, g.addr(p, "street_full")), "','",
                        g.addr(p, "postcode"), "','", g.addr(p, "city"), "','", p.country, "','", g.birth(p, "iso"), "',",
                        F("'", g.iban(p=p, printed=False), "'") if r.random() < 0.8 else "NULL", ",'",
                        x.ts("space", t=_past(d, 30, 1200)), "')"))
    head = F("-- MySQL dump 10.13  Distrib ", x.ver("8.0.36"), ", for Linux (x86_64)\n--\n",
             "-- Host: ", src_ip, "    Database: ", db, "\n",
             "-- ------------------------------------------------------\n",
             "-- Server version\t", x.ver("8.0.36"), "\n\n",
             "/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;\n",
             "/*!50503 SET NAMES utf8mb4 */;\n",
             "/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;\n/*!40103 SET TIME_ZONE='+00:00' */;\n",
             "/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;\n\n",
             "--\n-- Table structure for table `customers`\n--\n\n",
             "DROP TABLE IF EXISTS `customers`;\n",
             "CREATE TABLE `customers` (\n",
             "  `id` int unsigned NOT NULL AUTO_INCREMENT,\n",
             "  `first_name` varchar(80) NOT NULL,\n  `last_name` varchar(80) NOT NULL,\n",
             "  `email` varchar(255) NOT NULL,\n  `phone` varchar(32) DEFAULT NULL,\n",
             "  `street` varchar(160) DEFAULT NULL,\n  `postcode` varchar(16) DEFAULT NULL,\n  `city` varchar(80) DEFAULT NULL,\n",
             "  `country` char(2) DEFAULT NULL,\n  `birth_date` date DEFAULT NULL,\n  `iban` varchar(34) DEFAULT NULL,\n",
             "  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,\n",
             "  PRIMARY KEY (`id`),\n  UNIQUE KEY `uq_email` (`email`)\n",
             ") ENGINE=InnoDB AUTO_INCREMENT=", x.num(lo=20000, hi=900000), " DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;\n\n",
             "--\n-- Dumping data for table `customers`\n--\n\n",
             "LOCK TABLES `customers` WRITE;\n",
             "/*!40000 ALTER TABLE `customers` DISABLE KEYS */;\n",
             "INSERT INTO `customers` VALUES ", J(",", tuples), ";\n")
    d.tool("sh", F("zcat ~/dumps/", fname, " | head -n 60"), head)
    pw = g.password()
    mariadb = r.random() < 0.5
    out = F("mysql: [Warning] Using a password on the command line interface can be insecure.\n")
    if mariadb:
        out = F("ERROR 1273 (HY000) at line 25: Unknown collation: 'utf8mb4_0900_ai_ci'\n")
    d.tool("sh", F("mysql -u root -p", pw, f" -e 'CREATE DATABASE IF NOT EXISTS {db}_dev' && zcat ~/dumps/", fname,
                   f" | mysql -u root -p", pw, f" {db}_dev"), out)
    if mariadb:
        d.agent(d.L(en="Your local server is MariaDB, which doesn't know MySQL 8's default collation. Rewriting it on the fly.",
                    it="Il server locale è MariaDB, che non conosce la collation di default di MySQL 8. La riscrivo al volo.",
                    de="Lokal läuft MariaDB, das die Standard-Collation von MySQL 8 nicht kennt. Ich schreibe sie beim Einspielen um.",
                    fr="Ton serveur local est MariaDB, qui ne connaît pas la collation par défaut de MySQL 8. Je la réécris à la volée.",
                    es="Tu servidor local es MariaDB, que no conoce la collation por defecto de MySQL 8. La reescribo al vuelo."))
        d.tool("sh", F("zcat ~/dumps/", fname, " | sed 's/utf8mb4_0900_ai_ci/utf8mb4_unicode_ci/g' | mysql -u root -p", pw, f" {db}_dev"),
               F(""))
    d.tool("sh", F("mysql -u root -p", pw, f" {db}_dev -e 'SELECT COUNT(*) FROM customers'"),
           grid(["COUNT(*)"], [[str(r.randint(20_000, 900_000))]], style="mysql",
                footer="" if r.random() < 0.5 else None))
    d.agent(say(d, "pii_warning"), "\n\n",
            d.L(en="Since this is a full copy of production customers (names, addresses, birth dates, IBANs), I'd scrub it right away. The invoice bug doesn't depend on the real values. Proposed script:",
                it="Visto che è una copia completa dei clienti di produzione (nomi, indirizzi, date di nascita, IBAN), la anonimizzerei subito. Il bug delle fatture non dipende dai valori reali. Script proposto:",
                de="Da das eine vollständige Kopie der Produktionskunden ist (Namen, Adressen, Geburtsdaten, IBANs), würde ich sie sofort anonymisieren. Der Rechnungsbug hängt nicht von echten Werten ab. Vorschlag:",
                fr="Comme c'est une copie complète des clients de production (noms, adresses, dates de naissance, IBAN), je l'anonymiserais tout de suite. Le bug des factures ne dépend pas des vraies valeurs. Script proposé :",
                es="Como es una copia completa de los clientes de producción (nombres, direcciones, fechas de nacimiento, IBAN), la anonimizaría ya. El bug de facturas no depende de los valores reales. Script propuesto:"))
    scrub = F("-- scrub.sql: replace personal data in a local copy, keep shapes and lengths\n",
              "UPDATE customers SET\n",
              "  first_name = CONCAT('First', id),\n",
              "  last_name  = CONCAT('Last', id),\n",
              "  email      = CONCAT('customer', id, '@example.test'),\n",
              "  phone      = IF(phone IS NULL, NULL, CONCAT('+000', LPAD(id, 9, '0'))),\n",
              "  street     = CONCAT('Street ', id % 200),\n",
              "  birth_date = IF(birth_date IS NULL, NULL, MAKEDATE(YEAR(birth_date), 1)),\n",
              "  iban       = IF(iban IS NULL, NULL, CONCAT(LEFT(iban, 2), '00TEST', LPAD(id, 12, '0')));\n")
    if r.random() < 0.5:
        scrub += F("UPDATE orders SET shipping_address = NULL, notes = NULL;\n")
    d.tool("write", "scripts/scrub.sql", scrub)
    d.user(say(d, "go_ahead"))
    d.tool("sh", F("mysql -u root -p", pw, f" {db}_dev < scripts/scrub.sql"),
           F("mysql: [Warning] Using a password on the command line interface can be insecure.\n"))
    d.agent(say(d, "done"), "\n",
            T(d.L(en="- dump restored into ⟦db⟧_dev and scrubbed\n- the dump file itself still contains real data: I'd delete it or keep it on the encrypted volume\n- use `~/.my.cnf` instead of `-p…` so the password stops showing up in shell history",
                  it="- dump ripristinato in ⟦db⟧_dev e anonimizzato\n- il file di dump contiene ancora dati reali: lo cancellerei o lo terrei sul volume cifrato\n- usa `~/.my.cnf` invece di `-p…` così la password non finisce nella history",
                  de="- Dump in ⟦db⟧_dev eingespielt und anonymisiert\n- die Dump-Datei selbst enthält noch echte Daten: löschen oder auf dem verschlüsselten Volume lassen\n- `~/.my.cnf` statt `-p…` verwenden, damit das Passwort nicht in der History landet",
                  fr="- dump restauré dans ⟦db⟧_dev et anonymisé\n- le fichier de dump contient encore des données réelles : à supprimer ou à garder sur le volume chiffré\n- utilise `~/.my.cnf` au lieu de `-p…` pour que le mot de passe n'apparaisse plus dans l'historique",
                  es="- dump restaurado en ⟦db⟧_dev y anonimizado\n- el fichero del dump sigue teniendo datos reales: bórralo o déjalo en el volumen cifrado\n- usa `~/.my.cnf` en lugar de `-p…` para que la contraseña no salga en el historial"),
              db=db))


# ================================================================ 12. ssh deploy key


def _randomart(r) -> list:
    rows = [[" "] * 17 for _ in range(9)]
    y, xx = 4, 8
    for _ in range(64):
        y = min(8, max(0, y + r.choice([-1, 1])))
        xx = min(16, max(0, xx + r.choice([-1, 1])))
        cur = rows[y][xx]
        order = " .o+=*BOX@%&#/^"
        rows[y][xx] = order[min(len(order) - 1, order.index(cur) + 1)] if cur in order else cur
    rows[4][8] = "S"
    rows[y][xx] = "E"
    return ["+--[ED25519 256]--+"] + ["|" + "".join(row) + "|" for row in rows] + ["+----[SHA256]-----+"]


@template("ssh_keygen_deploy_key", "irc", "shell", "file")
def ssh_keygen_deploy_key(d):
    g, x, r = d.g, d.x, d.rng
    me = d.me
    repo = f"{d.slug}/{d.project}"
    kname = f"{d.project}_deploy"
    home = _home(d)
    d.user(T(d.L(en="can you set up a read-only deploy key so CI can pull ⟦r⟧?",
                 it="mi configuri una deploy key in sola lettura così la CI può fare pull di ⟦r⟧?",
                 de="kannst du einen Read-only-Deploy-Key einrichten, damit die CI ⟦r⟧ ziehen kann?",
                 fr="tu peux mettre en place une deploy key en lecture seule pour que la CI puisse puller ⟦r⟧ ?",
                 es="¿puedes configurar una deploy key de solo lectura para que la CI pueda hacer pull de ⟦r⟧?"), r=repo))
    comment = g.email(me, "work")
    fp = x.id("SHA256:" + V.rand_str(r, V.ALNUM + "+/", 43))
    d.tool("sh", F('ssh-keygen -t ed25519 -C "', comment, '" -f ~/.ssh/', kname, ' -N ""'),
           F("Generating public/private ed25519 key pair.\n",
             "Your identification has been saved in ", home, "/.ssh/", kname, "\n",
             "Your public key has been saved in ", home, "/.ssh/", kname, ".pub\n",
             "The key fingerprint is:\n", fp, " ", comment, "\n",
             "The key's randomart image is:\n", lines(*_randomart(r))))
    pub_body = x.id("AAAAC3NzaC1lZDI1NTE5AAAAI" + V.rand_str(r, V.B64, 43))
    leak = r.choice(["agent", "user", "none"]) if d.secret_ok else "none"
    if leak == "agent":
        d.tool("sh", F("cat ~/.ssh/", kname), F(g.pem("openssh"), "\n"))
        d.agent(d.L(en="Sorry — that printed the private half instead of the .pub. It's now in this session log, so I'll discard this pair and generate a fresh one.",
                    it="Scusa: ho stampato la parte privata invece del .pub. Ora è nel log di questa sessione, quindi butto questa coppia e ne genero una nuova.",
                    de="Sorry — das war der private Teil statt der .pub. Er steht jetzt im Sitzungslog, also verwerfe ich das Paar und erzeuge ein neues.",
                    fr="Désolé — j'ai affiché la partie privée au lieu du .pub. Elle est maintenant dans le journal de session, donc je jette cette paire et j'en génère une nouvelle.",
                    es="Perdón: he mostrado la parte privada en lugar del .pub. Ahora está en el log de la sesión, así que descarto este par y genero uno nuevo."))
        fp = x.id("SHA256:" + V.rand_str(r, V.ALNUM + "+/", 43))
        d.tool("sh", F("rm ~/.ssh/", kname, " ~/.ssh/", kname, '.pub && ssh-keygen -t ed25519 -C "', comment, '" -f ~/.ssh/',
                       kname, ' -N "" -q && ssh-keygen -lf ~/.ssh/', kname, ".pub"),
               F("256 ", fp, " ", comment, " (ED25519)\n"))
        pub_body = x.id("AAAAC3NzaC1lZDI1NTE5AAAAI" + V.rand_str(r, V.B64, 43))
    d.tool("sh", F("cat ~/.ssh/", kname, ".pub"), F("ssh-ed25519 ", pub_body, " ", comment, "\n"))
    if leak == "user":
        d.user(d.L(en="and this goes in the CI variable, right?\n", it="e questa va nella variabile della CI, giusto?\n",
                   de="und das kommt in die CI-Variable, oder?\n", fr="et ça, ça va dans la variable de la CI, c'est ça ?\n",
                   es="y esto va en la variable de la CI, ¿no?\n"), g.pem("openssh"))
        d.agent(d.L(en="Yes, the private key goes into a masked CI variable — but not after it has been pasted into a chat. Let me regenerate it; paste the new one only into the CI settings page.",
                    it="Sì, la chiave privata va in una variabile mascherata della CI — ma non dopo essere stata incollata in una chat. La rigenero; incolla quella nuova solo nelle impostazioni della CI.",
                    de="Ja, der private Schlüssel gehört in eine maskierte CI-Variable — aber nicht, nachdem er in einen Chat kopiert wurde. Ich erzeuge ihn neu; füge den neuen nur in den CI-Einstellungen ein.",
                    fr="Oui, la clé privée va dans une variable CI masquée — mais pas après avoir été collée dans un chat. Je la régénère ; colle la nouvelle uniquement dans les paramètres de la CI.",
                    es="Sí, la clave privada va en una variable enmascarada de la CI, pero no después de pegarla en un chat. La regenero; pega la nueva solo en la configuración de la CI."))
        pub_body = x.id("AAAAC3NzaC1lZDI1NTE5AAAAI" + V.rand_str(r, V.B64, 43))
        d.tool("sh", F("rm ~/.ssh/", kname, "* && ssh-keygen -t ed25519 -C \"", comment, "\" -f ~/.ssh/", kname,
                       " -N \"\" -q && cat ~/.ssh/", kname, ".pub"),
               F("ssh-ed25519 ", pub_body, " ", comment, "\n"))
    title = f"ci-{r.choice(['pull', 'readonly', 'runner'])}"
    d.tool("sh", F("gh repo deploy-key add ~/.ssh/", kname, ".pub --repo ", repo, " --title ", title),
           F("✓ Deploy key added to ", repo, "\n"))
    if r.random() < 0.6:
        d.tool("sh", "ssh -T git@github.com",
               F("Hi ", g.user(me, r.choice([1, 2, 9])), "! You've successfully authenticated, but GitHub does not provide shell access.\n"))
    d.tool("sh", F("ssh -T -i ~/.ssh/", kname, " -o IdentitiesOnly=yes git@github.com"),
           F("Hi ", repo, "! You've successfully authenticated, but GitHub does not provide shell access.\n"))
    d.agent(d.L(en="Works. For the CI runner, known_hosts also needs to be pinned — current entries:",
                it="Funziona. Per il runner della CI va fissato anche known_hosts — voci attuali:",
                de="Funktioniert. Für den CI-Runner sollte known_hosts auch fest hinterlegt werden — aktuelle Einträge:",
                fr="Ça marche. Pour le runner CI, il faut aussi figer known_hosts — entrées actuelles :",
                es="Funciona. Para el runner de la CI también hay que fijar known_hosts; entradas actuales:"))
    kh = [F("github.com ssh-ed25519 ", x.id("AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"))]
    for _ in range(r.randint(2, 6)):
        if r.random() < 0.4:
            kh.append(F("|1|", x.id(V.rand_str(r, V.B64, 27) + "="), "|", x.id(V.rand_str(r, V.B64, 27) + "="),
                        " ecdsa-sha2-nistp256 ", x.id("AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBB" + V.rand_str(r, V.B64, 87) + "=")))
        else:
            ip = g.ip(r.choice(["private", "private", "public"]))
            kh.append(F(ip, " ssh-ed25519 ", x.id("AAAAC3NzaC1lZDI1NTE5AAAAI" + V.rand_str(r, V.B64, 43))))
    if r.random() < 0.5:
        kh.append(F("[", g.ip("private"), "]:", x.port(2222), " ssh-ed25519 ", x.id("AAAAC3NzaC1lZDI1NTE5AAAAI" + V.rand_str(r, V.B64, 43))))
    d.tool("read", "~/.ssh/known_hosts", lines(*kh))
    d.agent(d.L(en="Only the github.com line matters for CI; the others are your own servers and shouldn't be copied into the pipeline config.",
                it="Per la CI conta solo la riga di github.com; le altre sono tuoi server e non vanno copiate nella configurazione della pipeline.",
                de="Für die CI zählt nur die github.com-Zeile; die anderen sind deine eigenen Server und gehören nicht in die Pipeline-Konfiguration.",
                fr="Pour la CI, seule la ligne github.com compte ; les autres sont tes propres serveurs et n'ont rien à faire dans la config du pipeline.",
                es="Para la CI solo importa la línea de github.com; las demás son tus servidores y no deben copiarse en la configuración del pipeline."))
    d.user(say(d, "thanks"))
