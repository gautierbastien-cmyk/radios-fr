#!/usr/bin/env python3
"""Ajoute logos vérifiés, tvg-id et un EPG XMLTV aux playlists générées par build_playlists.py.

Usage : python3 enrich_playlists.py <fr.json> <nts.json> <nts_live.json> <dossier>
Écrit epg.xml et réécrit radios-fr-short.m3u / radios-fr-full.m3u avec url-tvg="__EPG_URL__".
"""
import html
import json
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

UA = "radios-fr-m3u/1.0"
PARIS = ZoneInfo("Europe/Paris")
NTS_LOGO = "https://www.nts.live/apple-touch-icon.png"
EPG_DAYS = 7


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean(s):
    return re.sub(r'[\r\n"]', "", s or "").strip()


def image_ok(url):
    if not url.startswith("http"):
        return False
    r = subprocess.run(["curl", "-sL", "-m", "5", "-A", UA, "-o", "/dev/null",
                        "-w", "%{http_code} %{content_type}", url], capture_output=True, text=True)
    code, _, ctype = r.stdout.partition(" ")
    return code.startswith("2") and ("image" in ctype or "octet-stream" in ctype)


def check_images(urls):
    urls = sorted({u for u in urls if u})
    with ThreadPoolExecutor(32) as pool:
        return dict(zip(urls, pool.map(image_ok, urls)))


def png_logo(url):
    """Les SVG Wikimedia ne s'affichent pas partout : on prend la vignette PNG."""
    m = re.match(r"https://upload\.wikimedia\.org/wikipedia/(\w+)/(\w)/(\w\w)/([^/]+\.svg)$", url or "")
    if not m:
        return url
    lang, a, ab, f = m.groups()
    return f"https://upload.wikimedia.org/wikipedia/{lang}/thumb/{a}/{ab}/{f}/500px-{f}.png"


def site_icon(homepage):
    host = urlparse(homepage or "").netloc
    if not host:
        return ""
    return ("https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON"
            f"&fallback_opts=TYPE,SIZE,URL&url=http://{host}&size=256")


def avatar(name):
    return f"https://ui-avatars.com/api/?name={quote_plus(name[:40])}&size=256&background=random&bold=true"


def parse_m3u(path):
    entries, lines = [], [l.strip() for l in Path(path).read_text().splitlines()]
    for i, l in enumerate(lines):
        if l.startswith("#EXTINF") and i + 1 < len(lines):
            m = re.match(r'#EXTINF:\S*((?:\s+[\w-]+="[^"]*")*)\s*,(.*)', l)
            attrs, name = (m.group(1), m.group(2)) if m else l.split(",", 1)
            g = re.search(r'group-title="([^"]*)"', attrs)
            lg = re.search(r'tvg-logo="([^"]*)"', attrs)
            entries.append({"name": name, "url": lines[i + 1],
                            "group": g.group(1) if g else "", "logo": lg.group(1) if lg else ""})
    return entries


# Logos refaits à la main (hébergés dans logos/ du dépôt), prioritaires : nom normalisé -> fichier
REPO_RAW = "https://raw.githubusercontent.com/gautierbastien-cmyk/radios-fr/main"
LOGO_OVERRIDES = {"radionova": "logos/radio-nova.png", "nova": "logos/radio-nova.png",
                  "radionovalanuit": "logos/radio-nova.png", "novavintage": "logos/radio-nova.png",
                  "radionovavintage": "logos/radio-nova.png"}
LOGO_OVERRIDES.update({f"fip{n.replace('-', '')}": f"logos/fip-{n}.png" for n in
                       ["rock", "jazz", "groove", "monde", "reggae", "electro", "metal", "pop", "hip-hop", "cultes"]})
LOGO_OVERRIDES.update({"rinsefrance": "logos/rinse.png", "rinsefm": "logos/rinse.png"})
# Logos officiels en 300-600 px trouvés sur radio.net / TuneIn (nom exact) pour les radios dont le favicon
# était trop petit : nom normalisé -> URL complète. Les logos faits main ci-dessus restent prioritaires.
_TROUVES = Path(__file__).with_name("logos") / "overrides.json"
if _TROUVES.exists():
    LOGO_OVERRIDES = {**json.loads(_TROUVES.read_text()), **LOGO_OVERRIDES}

# Radios indé publiant leur grille : nom normalisé -> (type, identifiant)
SCHEDULES = {
    "netilradio": ("airtime", "netilradio"), "kioskradio": ("airtime", "kioskradiobxl"),
    "cashmereradio": ("airtime", "cashmereradio"), "radio80000": ("airtime", "radio80k"),
    "radioraheem": ("airtime", "radioraheem"), "dublab": ("airtime", "dublab"),
    "refugeworldwide": ("refuge", ""), "kexp": ("kexp", ""),
}
UTC = ZoneInfo("UTC")

# Descriptifs des radios indé (EPG quand la radio ne publie pas sa grille)
DESCRIPTIONS = {
    "rinsefrance": "Paris – club et électronique, scène parisienne. La plus proche de NTS en France.",
    "lylradio": "Lyon / Paris – ultra éclectique, de l'expérimental au rap.",
    "pinataradio": "Marseille – électronique et musiques méditerranéennes, ambiance solaire.",
    "radiogrenouille": "Marseille – radio associative historique, culturelle et défricheuse.",
    "rinsefm": "Londres – ex-radio pirate, berceau du garage, du grime et du dubstep.",
    "worldwidefm": "Londres – la radio de Gilles Peterson : jazz, soul, musiques du monde.",
    "netilradio": "Londres – petite radio indé de Hackney, très éclectique.",
    "noodsradio": "Bristol – émissions pointues et décalées, bass music.",
    "kioskradio": "Bruxelles – émet depuis un kiosque dans un parc : électronique, disco, musiques du monde.",
    "refugeworldwide": "Berlin – radio communautaire et engagée, club et expérimental.",
    "cashmereradio": "Berlin – expérimental, ambient, art sonore.",
    "radio80000": "Munich – disco, house, jazz, ambiance chaleureuse.",
    "operatorradio": "Rotterdam – électronique et scène locale.",
    "intergalacticfm": "La Haye – électro, italo, techno à l'ancienne, très culte.",
    "radioraheem": "Milan – électronique, jazz, scène italienne.",
    "thelotradio": "New York – depuis un conteneur à Brooklyn : house, techno, disco (flux vidéo).",
    "dublab": "Los Angeles – pionnière des webradios : beats, ambient, expérimental.",
    "kexp": "Seattle – rock indé et alternatif, célèbre pour ses sessions live.",
    "orokoradio": "Accra – radio indé tournée vers les musiques africaines et de la diaspora.",
}


def fetch_json(url):
    r = subprocess.run(["curl", "-sfL", "-m", "15", "-A", UA, url], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def external_schedule(name, today):
    """-> liste de (début, fin, titre, description) ou [] si indisponible."""
    kind, ident = SCHEDULES.get(norm(name), (None, None))
    slots = []
    if kind == "airtime":
        data = fetch_json(f"https://{ident}.airtime.pro/api/week-info?timezone=UTC") or {}
        for day in data.values():
            for s in day if isinstance(day, list) else []:
                try:
                    a = datetime.fromisoformat(s["starts"]).replace(tzinfo=UTC)
                    b = datetime.fromisoformat(s["ends"]).replace(tzinfo=UTC)
                except (KeyError, ValueError):
                    continue
                slots.append((a, b, strip_html(s.get("name")), strip_html(s.get("description"))[:500]))
    elif kind == "refuge":
        data = fetch_json("https://refugeworldwide.com/api/schedule") or {}
        for s in data.get("nextUp") or []:
            try:
                slots.append((datetime.fromisoformat(s["date"].replace("Z", "+00:00")),
                              datetime.fromisoformat(s["dateEnd"].replace("Z", "+00:00")), s["title"], ""))
            except (KeyError, ValueError, AttributeError):
                continue
    elif kind == "kexp":
        la = ZoneInfo("America/Los_Angeles")
        data = fetch_json("https://api.kexp.org/v2/timeslots/?limit=500") or {}
        ts = [s for s in data.get("results") or [] if not s.get("end_date")]
        day0 = datetime.now(la).replace(hour=0, minute=0, second=0, microsecond=0)
        for d in range(-1, EPG_DAYS):
            day = day0 + timedelta(days=d)
            for s in ts:
                if s.get("weekday") != day.isoweekday():
                    continue
                h1, m1, _ = map(int, s["start_time"].split(":"))
                h2, m2, _ = map(int, s["end_time"].split(":"))
                a = day.replace(hour=h1, minute=m1)
                b = day.replace(hour=h2, minute=m2)
                if b <= a:
                    b += timedelta(days=1)
                hosts = ", ".join(s.get("host_names") or [])
                slots.append((a, b, s.get("program_name") or "KEXP", f"Avec {hosts}" if hosts else ""))
    slots = sorted({(a, b, ti, de) for a, b, ti, de in slots if b > a and ti}, key=lambda x: x[0])
    # supprime les chevauchements éventuels
    out, last = [], None
    for a, b, ti, de in slots:
        if last and a < last:
            continue
        out.append((a, b, ti, de))
        last = b
    return out


def xmltv_time(dt):
    return dt.astimezone(PARIS).strftime("%Y%m%d%H%M%S %z")


def main(fr_json, nts_json, live_json, folder):
    folder = Path(folder)
    stations = [s for s in json.load(open(fr_json)) if s.get("url_resolved")]
    mixtapes = {f"NTS – {m['title']}": m for m in json.load(open(nts_json))["results"]}
    live = {f"NTS {c['channel_name']}": c for c in json.load(open(live_json))["results"]}
    by_url = {s["url_resolved"].strip(): s for s in reversed(stations)}  # 1re occurrence gagne
    by_name = {}
    for s in stations:
        by_name.setdefault(norm(s["name"]), []).append(s)

    playlists = {p: parse_m3u(folder / p) for p in ("radios-fr-short.m3u", "radios-fr-full.m3u")}
    channels = {}  # url -> entrée enrichie (partagée entre les deux playlists)
    for entries in playlists.values():
        for e in entries:
            channels.setdefault(e["url"], e)

    # Candidats logos, par ordre de préférence
    for e in channels.values():
        st = by_url.get(e["url"])
        same = by_name.get(norm(e["name"]), [])
        homepage = (st or {}).get("homepage") or next((s["homepage"] for s in same if s.get("homepage")), "")
        if e["name"] in mixtapes:
            cands = [mixtapes[e["name"]]["media"].get("picture_medium", ""), NTS_LOGO]
        elif "NTS" in e["group"]:
            cands = [NTS_LOGO]
        else:
            cands = [e["logo"], (st or {}).get("favicon", "")] + [s["favicon"] for s in same]
            cands.append(site_icon(homepage))
            if norm(e["name"]) in LOGO_OVERRIDES:
                o = LOGO_OVERRIDES[norm(e["name"])]
                cands.insert(0, o if o.startswith("http") else f"{REPO_RAW}/{o}")
        cands = [html.unescape(c) for c in cands if c]  # ex. « &#038; » dans certaines adresses
        cands = [c for c in cands if not re.search(r"google\.com/images/branding|googlelogo", c)]
        e["cands"] = [c for c in dict.fromkeys(png_logo(c) for c in cands) if c]
        e["st"] = st

    ok = check_images(c for e in channels.values() for c in e["cands"])
    stats = {"kept": 0, "replaced": 0, "avatar": 0}
    used_ids = set()
    for e in channels.values():
        good = next((c for c in e["cands"] if ok.get(c)), None)
        if good and good == e["logo"]:
            stats["kept"] += 1
        elif good:
            stats["replaced"] += 1
        else:
            good = avatar(e["name"])
            stats["avatar"] += 1
        e["logo"] = good
        base = norm(e["name"]) or "radio"
        tid, n = f"{base}.fr", 2
        while tid in used_ids:
            tid, n = f"{base}{n}.fr", n + 1
        used_ids.add(tid)
        e["id"] = tid

    # EPG XMLTV
    today = datetime.now(PARIS).replace(hour=0, minute=0, second=0, microsecond=0)
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<tv generator-info-name="radios-fr-m3u">']
    for e in channels.values():
        xml.append(f'  <channel id="{escape(e["id"])}"><display-name lang="fr">{escape(clean(e["name"]))}'
                   f'</display-name><icon src="{escape(e["logo"])}"/></channel>')

    def programme(cid, start, stop, title, desc="", icon="", cat=""):
        xml.append(f'  <programme start="{xmltv_time(start)}" stop="{xmltv_time(stop)}" channel="{escape(cid)}">'
                   f'<title lang="fr">{escape(title)}</title>'
                   + (f'<desc lang="fr">{escape(desc)}</desc>' if desc else "")
                   + (f'<category lang="fr">{escape(cat)}</category>' if cat else "")
                   + (f'<icon src="{escape(icon)}"/>' if icon else "") + "</programme>")

    n_real = 0
    for e in channels.values():
        name = clean(e["name"])
        if e["name"] in live:
            c = live[e["name"]]
            slots = [c["now"]] + [c[k] for k in sorted((k for k in c if k.startswith("next")),
                                                       key=lambda k: int(k[4:] or 1))]
            for b in slots:
                d = (b.get("embeds") or {}).get("details") or {}
                programme(e["id"], datetime.fromisoformat(b["start_timestamp"]),
                          datetime.fromisoformat(b["end_timestamp"]), b["broadcast_title"],
                          (d.get("description") or "")[:500],
                          (d.get("media") or {}).get("picture_medium", ""), "Musique")
                n_real += 1
            continue
        ext = external_schedule(e["name"], today) if norm(e["name"]) in SCHEDULES else []
        if ext:
            for a, b, ti, de in ext:
                programme(e["id"], a, b, ti, de or DESCRIPTIONS.get(norm(e["name"]), ""), e["logo"], "Musique")
                n_real += 1
            continue
        if e["name"] in mixtapes:
            m = mixtapes[e["name"]]
            title, desc, cat = name, f"{m.get('subtitle', '')} {m.get('description', '')}".strip(), "Musique"
        else:
            tags = ((e["st"] or {}).get("tags") or e["group"]).replace(",", ", ")
            desc = DESCRIPTIONS.get(norm(e["name"]), tags)
            title, cat = f"{name} – En direct", e["group"] or "Radio"
        for d in range(EPG_DAYS):
            start = today + timedelta(days=d)
            programme(e["id"], start, start + timedelta(days=1), title, desc, e["logo"], cat)
    xml.append("</tv>")
    (folder / "epg.xml").write_text("\n".join(xml) + "\n")

    # Réécriture des playlists
    for p, entries in playlists.items():
        title = "Radios FR – Full" if "full" in p else "Radios FR – Short"
        out = ['#EXTM3U url-tvg="__EPG_URL__" x-tvg-url="__EPG_URL__"', f"#PLAYLIST:{title}"]
        for e in entries:
            c = channels[e["url"]]
            out.append(f'#EXTINF:-1 tvg-id="{c["id"]}" tvg-name="{clean(c["name"])}" tvg-logo="{clean(c["logo"])}" '
                       f'group-title="{clean(e["group"])}",{clean(e["name"])}')
            out.append(e["url"])
        (folder / p).write_text("\n".join(out) + "\n")

    print(json.dumps({"channels": len(channels), "logos": stats, "nts_live_programmes": n_real},
                     indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:5])
