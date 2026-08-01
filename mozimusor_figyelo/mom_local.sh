#!/bin/bash
#
# Cinema MOM figyelő — HELYI futtatás a saját gépen.
#
# Miért nem a felhőben? A cinemamom.hu az adatközponti IP-ket (így a GitHub
# futtatóit is) egy „Kis türelmet…" című JavaScript-ellenőrző oldalra
# irányítja a műsor helyett. Az otthoni kapcsolatodat nem szűri. Ezt a
# védelmet nem kerüljük meg — helyette innen, a te gépedről kérdezünk.
#
# Ütemezés: ~/Library/LaunchAgents/hu.mozimusor.mom.plist (negyedóránként)
# Napló:    ~/Library/Logs/mozimusor-mom.log
#
# TITKOK: ebben a fájlban egyetlen jelszó és e-mail-cím sincs — a repo
# publikus. A küldő címe a config.env-ből jön (a repón kívül), az app-jelszó
# a macOS kulcstartóból.

set -uo pipefail

PROJEKT="$HOME/hobbi projektek/mozimusor_figyelo"
ADAT="$HOME/Library/Application Support/mozimusor"
ALLAPOT="$ADAT/mom.json"
KONFIG="$ADAT/config.env"

mkdir -p "$ADAT"

if [ ! -f "$KONFIG" ]; then
  echo "[hiba] hianyzik a konfiguracio: $KONFIG" >&2
  echo "       Hozd letre ezzel a tartalommal:" >&2
  echo "         GMAIL_USER=sajat@gmail.com" >&2
  exit 1
fi

# shellcheck source=/dev/null
set -a; . "$KONFIG"; set +a

# Az app-jelszó a kulcstartóból. Ha nincs, a szkript nem indul el, hogy ne
# fusson feleslegesen és ne nyeljen el egy értesítést.
if ! GMAIL_APP_PASSWORD="$(security find-generic-password -s mozimusor-gmail -w 2>/dev/null)"; then
  echo "[hiba] nincs 'mozimusor-gmail' bejegyzes a kulcstartoban" >&2
  exit 1
fi
export GMAIL_APP_PASSWORD

# A repóban lévő mom.py alapból ki van kapcsolva (a felhőben nem fut) —
# itt környezeti változóval kapcsoljuk be.
export FIGYELD=true

cd "$PROJEKT" || { echo "[hiba] nincs meg a mappa: $PROJEKT" >&2; exit 1; }

echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="

KIMENET="$(python3 mom.py --state "$ALLAPOT" 2>&1)"
KOD=$?
echo "$KIMENET"

if [ "$KOD" -ne 0 ]; then
  echo "[hiba] a mom.py $KOD kilepesi koddal allt le — ertesites nem ment" >&2
  exit "$KOD"
fi

# Csak akkor küldünk levelet, ha van mit jelenteni. A jelentés a "=== " sorral
# kezdődik; ha nincs ilyen, a futás csendes.
if printf '%s\n' "$KIMENET" | grep -q '^=== '; then
  printf '%s\n' "$KIMENET" | sed -n '/^=== /,$p' | python3 notify_email.py
  echo "[email] elkuldve"
else
  echo "[csend] nincs uj idopont"
fi
