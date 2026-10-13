#!/usr/bin/env python3
"""Ajoute logos vérifiés, tvg-id et un EPG XMLTV aux playlists générées par build_playlists.py.

Usage : python3 enrich_playlists.py <fr.json> <nts.json> <nts_live.json> <dossier>
Écrit epg.xml et réécrit radios-fr.m3u / radios-fr-complet.m3u avec url-tvg="__EPG_URL__".
"""
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

    playlists = {p: parse_m3u(folder / p) for p in ("radios-fr.m3u", "radios-fr-complet.m3u")}
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
        elif e["group"] == "NTS":
            cands = [NTS_LOGO]
        else:
            cands = [e["logo"], (st or {}).get("favicon", "")] + [s["favicon"] for s in same]
            cands.append(site_icon(homepage))
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
        if e["name"] in mixtapes:
            m = mixtapes[e["name"]]
            title, desc, cat = name, f"{m.get('subtitle', '')} {m.get('description', '')}".strip(), "Musique"
        else:
            tags = ((e["st"] or {}).get("tags") or e["group"]).replace(",", ", ")
            title, desc, cat = f"{name} – En direct", tags, e["group"] or "Radio"
        for d in range(EPG_DAYS):
            start = today + timedelta(days=d)
            programme(e["id"], start, start + timedelta(days=1), title, desc, e["logo"], cat)
    xml.append("</tv>")
    (folder / "epg.xml").write_text("\n".join(xml) + "\n")

    # Réécriture des playlists
    for p, entries in playlists.items():
        out = ['#EXTM3U url-tvg="__EPG_URL__" x-tvg-url="__EPG_URL__"']
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
