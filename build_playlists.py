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
    rmc = {"name": "RMC", "url": RMC_URL, "group": "Info", "logo": ""}
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
                    if e["group"] not in ("NTS", "Radios indé") and not (norm(e["name"]) == "rmc" or RMC_PATTERN.search(e["url"]))]
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
    head += "".join(extinf(n["name"], n["url"], "NTS") for n in nts)
    head += "".join(extinf(e["name"], e["url"], e["group"] or "Radios indé", e["logo"]) for e in inde)
    head_urls = {rmc["url"]} | {n["url"] for n in nts} | {e["url"] for e in inde}
    inde_names = {norm(e["name"]) for e in inde}

    # radios-fr-short.m3u
    body = "".join(extinf(e["name"], e["url"], e["group"], e["logo"]) for e in main_entries)
    (out / "radios-fr-short.m3u").write_text("#EXTM3U\n" + head + body)

    # radios-fr-full.m3u
    seen, body, n_rb = set(head_urls), [], 0
    for s in stations:
        url = s["url_resolved"].strip()
        if url in seen or RMC_PATTERN.search(url) or norm(s["name"]) in inde_names:
            continue
        seen.add(url)
        tag = (s.get("tags") or "").split(",")[0].strip()
        body.append(extinf(s["name"], url, tag, s.get("favicon", "")))
        n_rb += 1
    (out / "radios-fr-full.m3u").write_text("#EXTM3U\n" + head + "".join(body))

    print(json.dumps({
        "radios_fr": 1 + len(nts) + len(inde) + len(main_entries),
        "radios_fr_complet": 1 + len(nts) + len(inde) + n_rb,
        "inde": len(inde), "inde_dead": inde_dead,
        "nts": len(nts), "nts_dead": [n["name"] for n in nts_dead],
        "fixes": fixes, "unfixed": unfixed,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:5])
