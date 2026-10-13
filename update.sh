#!/usr/bin/env bash
# Régénère radios-fr.m3u, radios-fr-complet.m3u et epg.xml.
# Usage : ./update.sh <url_publique_de_epg.xml>
set -euo pipefail
cd "$(dirname "$0")"
EPG_URL="${1:?url de epg.xml requise}"
DATA="$(mktemp -d)"
trap 'rm -rf "$DATA"' EXIT
UA="radios-fr-m3u/1.0"

# 1. Radio Browser (pagination par 1000, serveurs de secours)
for host in de1 fi1 nl1; do
  rm -f "$DATA"/p*.json
  offset=0; ok=1
  while :; do
    url="https://$host.api.radio-browser.info/json/stations/bycountrycodeexact/FR?hidebroken=true&order=clickcount&reverse=true&limit=1000&offset=$offset"
    curl -sf -m 60 -A "$UA" "$url" -o "$DATA/p$(printf %05d $offset).json" || { ok=0; break; }
    n=$(jq length "$DATA/p$(printf %05d $offset).json")
    [ "$n" -lt 1000 ] && break
    offset=$((offset + 1000))
  done
  [ "$ok" = 1 ] && break
done
[ "$ok" = 1 ] || { echo "Radio Browser injoignable" >&2; exit 1; }
jq -s add "$DATA"/p*.json > "$DATA/fr.json"
[ "$(jq length "$DATA/fr.json")" -gt 1000 ] || { echo "Trop peu de stations, abandon" >&2; exit 1; }

# 2. NTS : mixtapes + grille en direct
curl -sf -m 30 -A "$UA" https://www.nts.live/api/v2/mixtapes -o "$DATA/nts.json"
curl -sf -m 30 -A "$UA" https://www.nts.live/api/v2/live -o "$DATA/live.json"

# 3. Génération
python3 -I build_playlists.py "$DATA/fr.json" "$DATA/nts.json" . radios-fr.source.m3u
python3 -I enrich_playlists.py "$DATA/fr.json" "$DATA/nts.json" "$DATA/live.json" .
sed -i.bak "s#__EPG_URL__#$EPG_URL#g" radios-fr.m3u radios-fr-complet.m3u && rm -f ./*.bak
