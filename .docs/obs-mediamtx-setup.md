# Setup OBS A → MediaMTX (SRT) → OBS B avec délai robuste

Ce document décrit un setup local permettant d’introduire un délai déterministe via SRT afin de disposer d’une fenêtre de traitement (ex: STT + analyse + automation OBS).

Architecture cible :

```
Camera + Mic
    ↓
OBS A (temps réel, publish SRT)
    ↓
MediaMTX (serveur SRT)
    ↓
OBS B (read SRT + rendu différé)
    ↓
Stream final (YouTube, Twitch, etc.)
```

Le principe fondamental est que le public voit un flux en retard (ex: 12 secondes), ce qui te laisse une fenêtre pour analyser l’audio et déclencher des changements de scène avant que le contenu n’apparaisse.

---

# 1. Lancer deux instances OBS sous macOS

Sous macOS, pour lancer deux instances d’OBS :

```bash
open -n -a OBS.app
```

Tu obtiens :

* OBS A → encodeur temps réel
* OBS B → programme différé

---

# 2. Docker Compose MediaMTX (SRT)

## docker-compose.yml

```yaml
version: "3.9"

services:
  mediamtx:
    image: bluenviron/mediamtx:latest
    container_name: mediamtx
    restart: unless-stopped
    ports:
      - "8890:8890/udp"   # SRT utilise UDP
    volumes:
      - ./mediamtx.yml:/mediamtx.yml
```

Important : SRT fonctionne en UDP. Si tu oublies `/udp`, ça ne marchera pas.

---

## mediamtx.yml

```yaml
srt: yes
srtAddress: :8890

paths:
  live:
```

Ici :

* `live` est le pathname SRT.
* Il n’y a pas de stream key libre comme en RTMP.
* SRT impose un format strict pour le streamid.

---

## Lancer le serveur

```bash
docker compose up -d
docker logs mediamtx
```

Tu dois voir une ligne du type :

```
SRT listener opened on :8890
```

---

# 3. Configuration OBS A (Publish SRT)

OBS A = encodeur temps réel.

Settings → Stream
Service: Custom

URL :

```
srt://127.0.0.1:8890?mode=caller&streamid=publish:live&latency=12000
```

Explication :

* `mode=caller` → OBS initie la connexion.
* `publish:live` → publie sur le path "live".
* `latency=12000` → 12 secondes de buffer SRT (ms).

Important :

* Aucun Stream Delay activé dans OBS A.
* CBR activé.
* Keyframe interval = 2.
* Résolution/framerate cohérents.

OBS A envoie un flux temps réel au serveur.

---

# 4. Configuration OBS B (Read SRT)

Dans OBS B :

Add → Media Source

URL :

```
srt://127.0.0.1:8890?mode=caller&streamid=read:live
```

Explication :

* `read:live` → lecture du path "live".
* `mode=caller` → MediaMTX reste listener.

Ne mets pas `listener` dans OBS B, sinon conflit.

Aucun Network Buffering manuel nécessaire ici si tu utilises la latence SRT.
La latence est négociée au niveau transport.

---

# 5. Ce qu’il se passe techniquement

## 5.1 OBS A

* Capture caméra + micro.
* Encode en H264 + AAC.
* Envoie en SRT vers MediaMTX.
* SRT introduit une latence négociée (12s ici).

OBS A ne subit aucun délai visuel local.

---

## 5.2 MediaMTX

* Reçoit le flux SRT en mode publish.
* Stocke les paquets selon la fenêtre de latence SRT.
* Redistribue le flux aux clients read.

MediaMTX ne “transforme” pas la vidéo.
Il agit comme relais avec buffer transport.

---

## 5.3 OBS B

* Se connecte en read.
* Reçoit un flux déjà retardé.
* Rend la scène avec ~12 secondes de décalage.

Les changements de scène dans OBS B sont instantanés.

Le délai affecte uniquement le flux vidéo entrant, pas le moteur de rendu.

---

# 6. Fenêtre de traitement STT

Supposons :

* Latence SRT = 12s
* STT = 2s
* Logique + WebSocket = 200ms

Timeline :

T=0   → tu parles
T=2   → STT retourne texte
T=2.2 → tu déclenches un switch OBS B
T=12  → le public voit le moment correspondant

Tu as donc ~9.8 secondes de marge.

Condition de sécurité :

```
latence_STT + latence_decision < latence_SRT
```

---

# 7. Bonnes pratiques

1. Capture le micro directement pour le STT (pas via le flux SRT).
2. Mesure la latence réelle avec un clap visuel + sonore.
3. Prévois une marge (ex: 15s si ton STT peut fluctuer).
4. Active WebSocket dans OBS B pour automation.

---

# 8. Debug rapide

Si OBS A ne se connecte pas :

* Vérifie port 8890 exposé en UDP.
* Vérifie logs Docker.
* Vérifie syntaxe streamid :

  * publish:live
  * read:live
* Utilise 127.0.0.1 plutôt que localhost.

Erreur typique incorrecte :

```
invalid stream ID 'live/stream'
```

Correct :

```
publish:live
read:live
```

---

# 9. Résumé minimal à retenir

1. Lancer MediaMTX.
2. OBS A → `publish:live` avec latence SRT.
3. OBS B → `read:live`.
4. L’automation agit sur OBS B.
5. Le public voit un flux retardé, ce qui te donne une fenêtre de décision.

---

Si tu veux, je peux produire une seconde version du document dédiée uniquement à l’automatisation WebSocket + STT avec exemple Node ou Python.
