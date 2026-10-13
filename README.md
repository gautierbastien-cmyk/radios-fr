# Radios françaises + NTS — playlist M3U

Régénérée automatiquement toutes les 6 h par GitHub Actions.

- Playlist complète : `radios-fr-full.m3u` (RMC, NTS, radios indé, puis toutes les radios FR de Radio Browser)
- Playlist courte : `radios-fr-short.m3u` (RMC, NTS, radios indé, principales radios FR)
- EPG XMLTV : `epg.xml` (vrai programme pour NTS 1/2, Netil, Kiosk, Cashmere, Radio 80000, Raheem, Dublab, Refuge, KEXP ; blocs « En direct » pour les autres)

Radios principales : modifier `radios-fr.source.m3u`.
Radios indé (après NTS) : modifier `radios-inde.source.m3u` — pour en retirer une, supprimer ses 2 lignes
(#EXTINF + URL) directement sur GitHub (icône crayon → Commit). La playlist se met à jour au passage suivant
(ou tout de suite via Actions → Run workflow).
Lancer à la main : onglet Actions → « Régénérer les playlists » → Run workflow.
