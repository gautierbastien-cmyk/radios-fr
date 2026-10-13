#!/usr/bin/env python3
"""Génère radios-fr-short.m3u (vérifié) et radios-fr-full.m3u (Radio Browser), avec RMC puis NTS en tête.

Usage : python3 build_playlists.py <fr.json> <nts.json> <dossier_sortie> [<liste_source.m3u>]
"""
import json
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = "radios-fr-m3u/1.0"
NTS_GROUP = "🌐 NTS"
INDE_GROUP = "📡 Radios indé"
RMC_URL = "https://audio.bfmtv.com/rmcradio_128.mp3"
RMC_PATTERN = re.compile(r"rmcradio|hls-rmc\.nextradiotv", re.I)


def alive(url):
    """Lit le flux 5 s max : vivant si HTTP 2xx et des octets reçus."""
    r = subprocess.run(
        ["curl", "-sL", "-m", "5", "-A", UA, "-o", "/dev/null",
         "-w", "%{http_code} %{size_download}", url],
        capture_output=True, text=True)
    try:
        code, size = r.stdout.split()
        return code.startswith("2") and float(size) > 0
    except ValueError:
        return False


def check_all(urls):
    with ThreadPoolExecutor(16) as pool:
        return dict(zip(urls, pool.map(alive, urls)))


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean(s):
    return re.sub(r'[\r\n"]', "", s or "").strip()


def extinf(name, url, group="", logo=""):
    attrs = (f'tvg-logo="{clean(logo)}" ' if logo else "") + f'group-title="{clean(group)}"'
    return f"#EXTINF:-1 {attrs},{clean(name)}\n{url}\n"


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


# Grandes familles pour la playlist complète : (genre, mots-clés cherchés dans tags + nom), par priorité
GENRES = [
    ("✝️ Religieux", r"christ|chretien|catholi|religi|gospel|islam|coran|quran|eglise|rcf|evangel|louange|bible|juda|torah"),
    ("📰 Info & Talk", r"\bnews\b|talk|\binfos?\b|information|actualit|trafic|traffic|meteo|politi|debat|sport|franceinfo"
                      r"|\bculture\b|podcast|france inter|\binter\b|\brfi\b|bfm|\brtl\b(?! ?2)|europe 1|sud radio|\brmc\b"
                      r"|autoroute|107[.,]7|krimi|polar|histoire|europe ?1|sante|senior"),
    ("🎶 Éclectique", r"\bfip\b|\bnova\b|eclecti|\bmeuh\b|\blyl\b|freeform|underground|experimental"),
    ("🎻 Classique", r"classi(cal|que)(?! rock| hits)|opera|baroque|symphon|piano|musique de chambre|violon|france musique"),
    ("🎷 Jazz, Soul & Funk", r"jazz|soul|funk|blues|groove|swing|motown|crooner"),
    ("🎤 Rap & R&B", r"\brap\b|hip.?hop|\br.?n.?b\b|r&b|urban|trap|drill|\bmouv|generations"),
    ("🎧 Électro & Dance", r"electro|electronic|dance|house|techno|tekno|trance|\bedm\b|hotmix|club|disco|dnb|drum|dubstep"
                           r"|hardstyle|minimal|\bfg\b"),
    ("🎸 Rock & Metal", r"rock|metal|punk|alternati|\bindie\b|grunge|hard ?core|oui ?fm"),
    ("🌍 Musiques du monde", r"world|monde|reggae|latin|afri|zouk|kompa|dub\b|outre.?mer|antill|caraib|oriental|maghreb"
                             r"|arab|rai\b|salsa|brazil|bresil|creole|celt|bretagne|breizh|portug|ital|espa|turk|indian"
                             r"|bollywood|kabyl|flamenco|guyane|reunion|martinique|guadeloupe|tahiti|corse|occitan"
                             r"|basque|tieng|viet|chin|polsk|armen|folk|gandharva"),
    ("😌 Chill & Lounge", r"lounge|chill|ambient|relax|zen|meditat|sleep|nature|smooth|easy listening|cafe|piano bar"),
    ("🕺 Années 60-90", r"\b[6-9]0'?s\b|annees|oldies|nostalgi|retro|classic hits|golden|vintage|souvenir|tubes d.hier"
                       r"|memory"),
    ("🇫🇷 Chanson française", r"chanson|variete|\bfrench\b|francais|francophon"),
    ("🎉 Hits & Pop", r"\bpop\b|hits|top ?40|tubes|\bnrj\b|cherie|fun radio|skyrock|virgin|europe 2|rfm|\bmix\b|charts"
                     r"|kids|enfant|petit|poptastic|humour|rire|girl|attitude|sans pub|gay|\bhit\b|emotion|puissance|intensite"),
    ("📍 Radios locales", r"local|regional|ici |france bleu|\bfm\b|associati|campus|\b\d{2,3}[.,]\d\b|\b\d{2,3} ?fm\b"
                          r"|\bradio (saint|st|pays|val|vallee|mont|cote|haute|bas|grand)\b|cantal|ardenne|sud\b|\b\d{2}\b"
                          r"|lyon|lille|paris|marseille|bordeaux|toulouse|nantes|rennes|nice|grenoble|chambery|montmartre"
                          r"|comtois|alsace|normand|savoie|provence|lorrain|picard|vendee|bourgogne|auvergne|limousin"
                          r"|bretagne|aquitaine|champagne|gironde|metropol|1ere|troyes|dijon|metz|nancy|reims|tours|caen|rouen"),
]


def genre(station):
    text = unicodedata.normalize("NFKD", f'{station.get("tags", "")} {station.get("name", "")}')
    text = text.encode("ascii", "ignore").decode().lower().replace(",", " ")
    for name, pattern in GENRES:
        if re.search(pattern, text):
            return name
    return "🎲 Autres"


TECH = (r"no ?pub|sans pub|hi-?fi|metadata|avec metadata|bose|lofi|\d{2,3} ?kb(ps|its?)?|mp3|aac\+?|ogg|flac|hls"
        r"|\bhd\b|\bhq\b|\blq\b|\bsd\b|stream|webradio|officiel(le)?|\^ _ \^")


def dedup_key(name):
    """Nom normalisé pour repérer les doublons (mentions techniques ignorées)."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[\(\[]([^\)\]]*)[\)\]]",
               lambda m: " " if re.fullmatch(rf"[\s+.,/:-]*(({TECH})[\s+.,/:-]*)*", m.group(1)) else f" {m.group(1)} ", n)
    n = re.sub(rf"\b({TECH})\b", " ", n)
    n = re.sub(r"\b\d{2,3}[.,]\d\b", " ", n)  # fréquences FM
    return re.sub(r"[^a-z0-9+]", "", n)


def find_replacement(name, stations, exclude):
    key = norm(name)
    exact = [s for s in stations if norm(s["name"]) == key]
    loose = [s for s in stations if key in norm(s["name"]) and s not in exact]
    for s in (exact + loose)[:8]:
        if s["url_resolved"] not in exclude and alive(s["url_resolved"]):
            return s
    return None


def main(fr_json, nts_json, out_dir, source=None):
    out = Path(out_dir)
    stations = [s for s in json.load(open(fr_json)) if s.get("url_resolved")]
    mixtapes = json.load(open(nts_json))["results"]
    fixes = []

    # a. RMC
    rmc = {"name": "RMC", "url": RMC_URL, "group": "📻 RMC", "logo": ""}
    if not alive(RMC_URL):
        alt = next((s for s in stations if RMC_PATTERN.search(s["url_resolved"])
                    and alive(s["url_resolved"])), None)
        fixes.append(("RMC", RMC_URL, alt["url_resolved"] if alt else None))
        if alt:
            rmc["url"] = alt["url_resolved"]

    # b. NTS
    nts = [{"name": "NTS 1", "url": "https://stream-relay-geo.ntslive.net/stream"},
           {"name": "NTS 2", "url": "https://stream-relay-geo.ntslive.net/stream2"}]
    nts += [{"name": f"NTS – {m['title']}", "url": m["audio_stream_endpoint"]}
            for m in mixtapes if m.get("audio_stream_endpoint")]
    nts_status = check_all([n["url"] for n in nts])
    nts_dead = [n for n in nts if not nts_status[n["url"]]]

    # c. Radios principales : test + remplacement
    main_entries = [e for e in parse_m3u(source or out / "radios-fr-short.m3u")
                    if e["group"] not in (NTS_GROUP, INDE_GROUP) and not (norm(e["name"]) == "rmc" or RMC_PATTERN.search(e["url"]))]
    status = check_all([e["url"] for e in main_entries])
    unfixed = []
    for e in main_entries:
        if status[e["url"]]:
            continue
        alt = find_replacement(e["name"], stations, {e["url"]})
        fixes.append((e["name"], e["url"], alt["url_resolved"] if alt else None))
        if alt:
            e["url"] = alt["url_resolved"]
            e["logo"] = e["logo"] or alt.get("favicon", "")
        else:
            unfixed.append(e["name"])

    # d. Radios indé (fichier éditable, affichées juste après NTS) : flux morts ignorés
    inde_path = Path(source).parent / "radios-inde.source.m3u" if source else out / "radios-inde.source.m3u"
    inde = parse_m3u(inde_path) if inde_path.exists() else []
    inde_status = check_all([e["url"] for e in inde])
    inde_dead = [e["name"] for e in inde if not inde_status[e["url"]]]
    inde = [e for e in inde if inde_status[e["url"]]]

    head = extinf(rmc["name"], rmc["url"], rmc["group"], rmc["logo"])
    head += "".join(extinf(n["name"], n["url"], NTS_GROUP) for n in nts)
    head += "".join(extinf(e["name"], e["url"], e["group"] or INDE_GROUP, e["logo"]) for e in inde)
    head_urls = {rmc["url"]} | {n["url"] for n in nts} | {e["url"] for e in inde}
    inde_names = {norm(e["name"]) for e in inde}

    # radios-fr-short.m3u
    body = "".join(extinf(e["name"], e["url"], e["group"], e["logo"]) for e in main_entries)
    (out / "radios-fr-short.m3u").write_text("#EXTM3U\n" + head + body)

    # radios-fr-full.m3u
    seen, body, n_rb = set(head_urls), [], 0
    seen_keys = {dedup_key(n["name"]) for n in nts} | {dedup_key(e["name"]) for e in inde} | {"rmc"}
    for s in stations:
        url = s["url_resolved"].strip()
        key = dedup_key(s["name"])
        if url in seen or key in seen_keys or RMC_PATTERN.search(url) or norm(s["name"]) in inde_names:
            continue
        seen.add(url)
        seen_keys.add(key)  # stations triées par popularité : on garde la plus écoutée
        body.append((genre(s), extinf(s["name"], url, genre(s), s.get("favicon", ""))))
        n_rb += 1
    # regroupe par famille (ordre de GENRES, « Autres » en dernier), popularité conservée dans chaque famille
    display = [g for g, _ in GENRES if g != "✝️ Religieux"]
    display.insert(display.index("📍 Radios locales"), "✝️ Religieux")
    rank = {g: i for i, g in enumerate(display)}
    body.sort(key=lambda b: rank.get(b[0], len(GENRES)))
    (out / "radios-fr-full.m3u").write_text("#EXTM3U\n" + head + "".join(b for _, b in body))

    print(json.dumps({
        "radios_fr": 1 + len(nts) + len(inde) + len(main_entries),
        "radios_fr_complet": 1 + len(nts) + len(inde) + n_rb,
        "inde": len(inde), "inde_dead": inde_dead,
        "nts": len(nts), "nts_dead": [n["name"] for n in nts_dead],
        "fixes": fixes, "unfixed": unfixed,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:5])
