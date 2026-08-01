#!/usr/bin/env python3
"""Heti életjel a mozifigyelőről.

Miért kell? Mert ennek a rendszernek egyetlen néma meghibásodási módja van:
ha leáll, **pontosan úgy néz ki, mint amikor nincs új vetítés**. Lejár a
`cron-inditas` token, megszűnik a cron-job.org fiók, átalakul a MOM
honlapja — mindegyik esetben csak annyit veszel észre, hogy nem jön levél. És
azt nehéz megkülönböztetni attól, hogy nincs miről.

Ez a szkript hetente egyszer küld egy rövid jelentést arról, hogy fut és mit
lát. **A levél elmaradása maga a riasztás.**

Nem küld hálózati kérést sehova: a két figyelő állapotfájljából dolgozik.
Ha ez a levél megjön, az bizonyítja, hogy az ébresztő, a workflow és az
e-mail-küldés is működik.

Csak stdlib.
"""

# ===========================================================================
#   C O N F I G
# ===========================================================================

ELETJEL = True             # False = ne küldjön életjelet

NAPOK_KOZOTT = 7           # ennyi naponta egyszer

# Melyik figyelőkről számoljon be. (állapotfájl, előtag, olvasható név)
FORRASOK = [
    ("state/seen.json", "CCITY", "Cinema City Aréna"),
    ("state/etele.json", "ETELE", "Etele Cinema"),
    # A MOM nem a felhőben fut, hanem a Macen (a cinemamom.hu szűri az
    # adatközponti IP-ket) — az állapotfájlja nincs a repóban, ezért itt
    # nem tud róla beszámolni. Részletek: HELYI-MOM.md
]

REPO = "aliaschewie/hobbi-projektek"

# ===========================================================================

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

NAPOK = ["hé", "ke", "sze", "csü", "pé", "szo", "va"]


def env(kulcs):
    ertek = os.environ.get(kulcs, "").strip()
    return ertek or None


def igaz(kulcs, alap):
    ertek = env(kulcs)
    if ertek is None:
        return bool(alap)
    return ertek.lower() in ("1", "true", "igen", "yes", "on")


def egesz(kulcs, alap):
    ertek = env(kulcs)
    try:
        return int(ertek) if ertek is not None else int(alap)
    except ValueError:
        return int(alap)


AKTIV = igaz("ELETJEL", ELETJEL)
KOZ = egesz("ELETJEL_NAPOK", NAPOK_KOZOTT)


def betolt(utvonal):
    try:
        with open(utvonal, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def forras_sorai(utvonal, elotag, nev):
    adat = betolt(utvonal)
    if adat is None:
        return [f"{nev} [{elotag}]",
                f"  nincs allapotfajl ({utvonal}) — meg nem futott, vagy ki van kapcsolva"]
    vetitesek = adat.get("adat", {})
    szuro = " / ".join(adat.get("szuro", [])) or "minden film"
    jell = " vagy ".join(adat.get("jellemzo", []))
    napok = sorted({v.get("kezdes", "")[:10] for v in vetitesek.values() if v.get("kezdes")})
    sorok = [f"{nev} [{elotag}]",
             f"  figyelt film   : {szuro}" + (f"  ({jell})" if jell else ""),
             f"  ismert időpont : {len(vetitesek)}"]
    if napok:
        sorok.append(f"  horizont       : {napok[0]} — {napok[-1]}")
    sorok.append(f"  utolsó változás: {adat.get('frissitve', '—')}")
    return sorok


def esedekes(allapot_utvonal):
    """Igaz, ha legalább KOZ napja nem ment ki életjel."""
    adat = betolt(allapot_utvonal) or {}
    utolso = adat.get("utolso")
    if not utolso:
        return True
    try:
        return (date.today() - date.fromisoformat(utolso)).days >= KOZ
    except ValueError:
        return True


def main():
    ap = argparse.ArgumentParser(description="Heti életjel a mozifigyelőről")
    ap.add_argument("--state", default="state/eletjel.json",
                    help="az életjel saját állapotfájlja")
    ap.add_argument("--most", action="store_true",
                    help="küldje el most, akkor is, ha még nem esedékes")
    args = ap.parse_args()

    if not AKTIV:
        print("[kikapcsolva] az ELETJEL hamis, nem kuldok heti jelentest.")
        return 0

    if not args.most and not esedekes(args.state):
        adat = betolt(args.state) or {}
        print(f"[eletjel] meg nem esedekes (utolso: {adat.get('utolso')}, "
              f"{KOZ} naponta megy).")
        return 0

    ma = date.today()
    sorok = [f"=== [ÉLETJEL] A mozifigyelő él — {ma.isoformat()} "
             f"{NAPOK[ma.weekday()]} ===",
             "",
             f">> Futások megtekintése: https://github.com/{REPO}/actions",
             ""]
    for utvonal, elotag, nev in FORRASOK:
        sorok += forras_sorai(utvonal, elotag, nev)
        sorok.append("")
    sorok += [
        "Ez a levél hetente egyszer megy ki, és csak annyit jelent, hogy a",
        "figyelő fut. Nem kell vele csinálni semmit.",
        "",
        "HA EZ A LEVÉL ELMARAD, az a riasztás: valami leállt. Ilyenkor nézd meg",
        f"a futásokat a fenti linken, és ellenőrizd a cron-job.org feladatot",
        "meg a `cron-inditas` token lejáratát.",
    ]
    print("\n".join(sorok))

    os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
    tmp = args.state + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"utolso": ma.isoformat(),
                   "kuldve": datetime.now(timezone.utc)
                             .strftime("%Y-%m-%dT%H:%M:%SZ")},
                  f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, args.state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
