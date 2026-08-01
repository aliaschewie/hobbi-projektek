#!/usr/bin/env python3
"""Cinema City műsorfigyelő — két üzemmódban.

  FILM MÓD      (FILM_SZURO ki van töltve)
    Egy konkrét filmet figyel, és minden ÚJ vetítési időpontra szól —
    akár új napra kerül ki, akár egy meglévő naphoz vesznek fel újat.

  HORIZONT MÓD  (FILM_SZURO üres)
    A mozi teljes műsorát figyeli, és akkor szól, amikor ÚJ napokra ír ki
    műsort. Naponkénti vetítésszámot tárol, így megkülönbözteti a teljes
    napot az előre nyitott szórvány premiertől — nincs téves riasztás.

Csak stdlib, nincs pip függőség.
"""

# ===========================================================================
#
#   C O N F I G   —   ebben a blokkban mindent át lehet állítani.
#
# ===========================================================================

# --- 1. Melyik mozi? -------------------------------------------------------

MOZI_NEVE = "arena"      # a név a link végén:  /cinemas/[arena]/1132
MOZI_SZAMA = "1132"      # a szám a link végén: /cinemas/arena/[1132]

# Cinema City Magyarország, 2026-08-01-i állapot:
#
#   név          szám    mozi                     név          szám   mozi
#   -------------------------------------------   ------------------------------
#   arena        1132    Aréna, Budapest          debrecen     1127   Debrecen
#   allee        1133    Allee, Budapest          gyor         1125   Győr
#   westend      1137    WestEnd, Budapest        pecs         1128   Pécs
#   mammut       1144    Mammut I-II., Budapest   szeged       1126   Szeged
#   campona      1139    Campona, Budapest        miskolc      1129   Miskolc
#   dunaplaza    1141    Duna Plaza, Budapest     szolnok      1130   Szolnok
#   alba         1124    Alba, Székesfehérvár     nyiregyhaza  1143   Nyíregyháza
#   balaton      1131    Balaton, Veszprém        sopron       1136   Sopron
#   savaria      1134    Savaria, Szombathely     zala         1135   Zalaegerszeg
#
# Ha nincs a listán: nyisd meg a mozi oldalát, és a címsorból olvasd ki.
#   https://www.cinemacity.hu/cinemas/arena/1132#/buy-tickets-by-cinema?at=...
#                                          ^^^^^ ^^^^
# A link többi része (a # utáni dátum, nézetmód) nem számít.

ORSZAG = "hu"            # "hu" = cinemacity.hu, "cz" = cinemacity.cz


# --- 2. Melyik filmre? -----------------------------------------------------
#
# ÜRES LISTA  ->  minden filmre megy az értesítés (horizont mód): akkor szól,
#                 amikor a mozi új napokra ír ki műsort.
#
# KITÖLTVE    ->  csak a felsorolt filmekre szól, minden új időponthoz külön.
#                 Elég a cím egy része, az ékezet és a kis-nagybetű mindegy:
#                 "odusszeia" is megtalálja az "Odüsszeia"-t.
#
#   FILM_SZURO = []                          <- minden
#   FILM_SZURO = ["Odüsszeia"]               <- csak ez az egy
#   FILM_SZURO = ["Odüsszeia", "Toy Story"]  <- több film egyszerre

FILM_SZURO = ["Odüsszeia"]


# --- 3. Finomhangolás (ritkán kell hozzányúlni) ----------------------------

# HORIZONT MÓDBAN: egy napot ennyi vetítéstől tekintünk "teljesnek". Az Aréna
# teljes napja ~100 vetítés, egy előre nyitott premier 1-2 — a 15 bőven a
# szakadékban van. Kis mozinál (Sopron, Zalaegerszeg) érdemes 8-ra levinni.
FULL_MIN_EVENTS = 15

# HORIZONT MÓDBAN: szóljon-e az előre nyitott szórvány előadásokról is (1/0).
NOTIFY_PARTIAL = 1

# Hány napra előre nézzünk.
HORIZON_DAYS = 60

# ===========================================================================
#   Innentől nem kell hozzányúlni.
# ===========================================================================

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

# A quickbook API "site ID"-ja országonként más.
ORSZAGOK = {
    "hu": ("https://www.cinemacity.hu", "10102", "hu_HU"),
    "cz": ("https://www.cinemacity.cz", "10101", "cs_CZ"),
}

# Amit a vetítés címkéi közül érdemes kiírni; a többi (műfaj, korhatár) megy a kukába.
JELLEMZOK = {
    "imax": "IMAX", "4dx": "4DX", "4dx-3d": "4DX 3D", "screenx": "ScreenX",
    "dolby-cinema": "Dolby Cinema", "vip": "VIP", "kids": "Kids",
    "3d": "3D", "dubbed": "szinkronos", "subbed": "feliratos",
    "original-lang": "eredeti nyelven", "sing-along": "sing-along",
}

TIMEOUT = 30
RETRIES = 3
UA = "mozimusor-figyelo/1.0"
NAPOK = ["hé", "ke", "sze", "csü", "pé", "szo", "va"]


def ekezettelen(s):
    """Kis-nagybetű és ékezet nélküli alak az összehasonlításhoz."""
    n = unicodedata.normalize("NFKD", str(s).casefold())
    return "".join(c for c in n if not unicodedata.combining(c))


def url_ertelmez(url):
    """Böngészőből másolt mozi-URL -> (név, szám, ország).

    Kényelmi lehetőség: a CINEMA_URL env-változó felülírja a CONFIG-ot. A
    linkben lévő dátum és minden egyéb paraméter figyelmen kívül marad.
    """
    p = urllib.parse.urlparse(url if "//" in url else "https://" + url)
    if not p.netloc:
        raise SystemExit(f"[hiba] ertelmezhetetlen CINEMA_URL: {url!r}")
    nev, szam = None, None
    reszek = [r for r in p.path.split("/") if r]
    if "cinemas" in reszek:
        maradek = reszek[reszek.index("cinemas") + 1:]
        if len(maradek) >= 2 and maradek[1].isdigit():
            nev, szam = maradek[0], maradek[1]
        elif len(maradek) == 1:
            nev, szam = (None, maradek[0]) if maradek[0].isdigit() else (maradek[0], None)
    if szam is None:
        m = re.search(r"in-cinema=(\d+)", url)
        if m:
            szam = m.group(1)
    if szam is None:
        raise SystemExit(f"[hiba] nem talalom a mozi szamat ebben: {url!r}\n"
                         "       Valami ilyet varok: .../cinemas/arena/1132")
    return nev or szam, szam, p.netloc.rsplit(".", 1)[-1].lower()


def config_osszerak():
    """CONFIG + env-változók egyesítése. Az env erősebb — így a GitHub
    Actionsben a kód módosítása nélkül is át lehet állítani."""
    nev, szam, orszag = MOZI_NEVE, MOZI_SZAMA, ORSZAG
    if os.environ.get("CINEMA_URL", "").strip():
        nev, szam, orszag = url_ertelmez(os.environ["CINEMA_URL"].strip())
    nev = os.environ.get("MOZI_NEVE", nev)
    szam = os.environ.get("MOZI_SZAMA", szam)
    orszag = os.environ.get("ORSZAG", orszag).lower()
    if orszag not in ORSZAGOK:
        raise SystemExit(f"[hiba] ismeretlen ORSZAG: {orszag!r} "
                         f"(valaszthato: {', '.join(ORSZAGOK)})")

    if "FILM_SZURO" in os.environ:      # vesszővel elválasztva
        szuro = [s.strip() for s in os.environ["FILM_SZURO"].split(",") if s.strip()]
    else:
        szuro = [s.strip() for s in FILM_SZURO if s and s.strip()]

    host, site, lang = ORSZAGOK[orszag]
    return {
        "nev": nev, "szam": str(szam), "host": host, "site": site, "lang": lang,
        "link": f"{host}/cinemas/{nev}/{szam}",
        "szuro": szuro,
        "szuro_kulcs": [ekezettelen(s) for s in szuro],
        "mod": "film" if szuro else "horizont",
    }


def egesz(kulcs, alap):
    try:
        return int(os.environ.get(kulcs, alap))
    except ValueError:
        return int(alap)


CFG = config_osszerak()
BASE = f"{CFG['host']}/hu/data-api-service/v1/quickbook/{CFG['site']}"
TELJES_MIN = egesz("FULL_MIN_EVENTS", FULL_MIN_EVENTS)
SZORVANY_IS = egesz("NOTIFY_PARTIAL", NOTIFY_PARTIAL) == 1
HORIZONT = egesz("HORIZON_DAYS", HORIZON_DAYS)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
KERES_SZUNET = float(os.environ.get("REQUEST_DELAY", "0.7"))


# --- HTTP -----------------------------------------------------------------

def get_json(url):
    """GET + JSON parse, exponenciális backoffal."""
    utolso = None
    for kiserlet in range(RETRIES):
        if kiserlet:
            time.sleep(2 ** kiserlet)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            utolso = e
    raise RuntimeError(f"sikertelen lekeres: {url} ({utolso})")


def jatszasi_napok():
    """Azok a napok, amikre egyáltalán van vetítés. Üres nap nem szerepel."""
    ameddig = (date.today() + timedelta(days=HORIZONT)).isoformat()
    url = (f"{BASE}/dates/in-cinema/{CFG['szam']}/until/{ameddig}"
           f"?attr=&lang={CFG['lang']}")
    return sorted(get_json(url).get("body", {}).get("dates", []))


def nap_lekeres(napi_datum):
    """Egy nap nyers adata: (films lista, events lista)."""
    url = (f"{BASE}/film-events/in-cinema/{CFG['szam']}"
           f"/at-date/{napi_datum}?attr=&lang={CFG['lang']}")
    body = get_json(url).get("body", {})
    return body.get("films", []), body.get("events", [])


# --- állapot --------------------------------------------------------------

def state_betolt(utvonal):
    try:
        with open(utvonal, encoding="utf-8") as f:
            adat = json.load(f)
    except (FileNotFoundError, ValueError):
        return {}
    # Ha közben átálltál másik mozira, módra vagy filmre, a régi állapot
    # nem érvényes rá — nulláról kezdünk, hogy ne spammeljen.
    if (str(adat.get("mozi_szama")) != CFG["szam"]
            or adat.get("mod") != CFG["mod"]
            or [ekezettelen(s) for s in adat.get("szuro", [])] != CFG["szuro_kulcs"]):
        if adat:
            print("[info] a beallitas megvaltozott az allapotfajl ota, "
                  "ujrakezdem", file=sys.stderr)
        return {}
    return adat.get("adat", {})


def state_ment(utvonal, adat):
    os.makedirs(os.path.dirname(utvonal) or ".", exist_ok=True)
    payload = {
        "frissitve": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mozi_neve": CFG["nev"], "mozi_szama": CFG["szam"],
        "mod": CFG["mod"], "szuro": CFG["szuro"],
        "teljes_min": TELJES_MIN,
        "adat": dict(sorted(adat.items())),
    }
    tmp = utvonal + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, utvonal)


# --- értesítés ------------------------------------------------------------

def ntfy_kuld(cim, szoveg):
    if not NTFY_TOPIC:
        return False
    try:
        req = urllib.request.Request(
            f"{NTFY_SERVER}/{NTFY_TOPIC}", data=szoveg.encode("utf-8"),
            headers={  # HTTP fejlécbe nem fér ékezet, ott átírjuk
                "Title": cim.encode("ascii", "replace").decode("ascii"),
                "Tags": "clapper", "Click": CFG["link"], "User-Agent": UA},
            method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT):
            return True
    except Exception as e:                    # az értesítés hibája nem fatális
        print(f"[figyelmeztetes] ntfy kuldes sikertelen: {e}", file=sys.stderr)
        return False


def kiir(sorok):
    """Kiírja a jelentést és elküldi pushban. A '=== ' kezdetű első sor a
    cím — a GitHub Actions is erre keres, hogy tudja, ment-e változás."""
    print("\n".join(sorok))
    ntfy_kuld(sorok[0].strip("= ").strip(), "\n".join(sorok[1:]))


def nap_cimke(d):
    return f"{d} {NAPOK[date.fromisoformat(d).weekday()]}"


# ===========================================================================
#   FILM MÓD — konkrét film új időpontjai
# ===========================================================================

def film_vetitesek():
    """{esemény_id: {...}} a szűrőre illeszkedő filmek összes vetítéséből."""
    talalt = {}
    filmnevek = set()
    napok = jatszasi_napok()
    for i, d in enumerate(napok):
        if i:
            time.sleep(KERES_SZUNET)
        filmek, esemenyek = nap_lekeres(d)
        # a film azonosítója naponta ugyanaz, de a biztonság kedvéért naponta nézzük
        egyezo = {}
        for f in filmek:
            nev = f.get("name", "")
            if any(k in ekezettelen(nev) for k in CFG["szuro_kulcs"]):
                egyezo[f.get("id")] = nev
                filmnevek.add(nev)
        if not egyezo:
            continue
        for e in esemenyek:
            if e.get("filmId") not in egyezo:
                continue
            jell = [JELLEMZOK[a] for a in e.get("attributeIds", []) if a in JELLEMZOK]
            talalt[str(e.get("id"))] = {
                "kezdes": e.get("eventDateTime", ""),
                "film": egyezo[e["filmId"]],
                "terem": e.get("auditorium", ""),
                "jellemzok": jell,
                "link": e.get("bookingLink", ""),
            }
    return talalt, sorted(filmnevek), napok


def vetites_sor(info):
    try:
        d, t = info["kezdes"].split("T")
        mikor = f"{nap_cimke(d)} {t[:5]}"
    except ValueError:
        mikor = info["kezdes"]
    jell = f"  ({', '.join(info['jellemzok'])})" if info["jellemzok"] else ""
    terem = f"  {info['terem']}" if info["terem"] else ""
    return f"  {mikor}{terem}{jell}"


def mult_nyeses_vetitesek(vetitesek):
    ma = date.today().isoformat()
    return {k: v for k, v in vetitesek.items() if v.get("kezdes", "")[:10] >= ma}


def film_mod(args):
    regi = mult_nyeses_vetitesek(state_betolt(args.state))
    mostani, filmnevek, napok = film_vetitesek()
    if not napok:
        print("[hiba] az API egyetlen jatszasi napot sem adott vissza",
              file=sys.stderr)
        return 1

    ujak = {k: v for k, v in mostani.items() if k not in regi}
    cimke = " / ".join(filmnevek) if filmnevek else " / ".join(CFG["szuro"])

    if args.seed or (not regi and not args.force_report):
        state_ment(args.state, mostani)
        print(f"[seed] allapot elmentve: {len(mostani)} vetites "
              f"({cimke}). Ertesites nem ment ki.")
        for k in sorted(mostani, key=lambda k: mostani[k]["kezdes"]):
            print(vetites_sor(mostani[k]))
        return 0

    if ujak:
        sorok = [f"=== {cimke}: {len(ujak)} új időpont ==="]
        sorok += [vetites_sor(ujak[k])
                  for k in sorted(ujak, key=lambda k: ujak[k]["kezdes"])]
        sorok += ["", f"Összesen {len(mostani)} időpont a következő "
                      f"{(date.fromisoformat(max(napok)) - date.today()).days} napban.",
                  CFG["link"]]
        kiir(sorok)
    elif args.force_report:
        print(f"[jelentes] {cimke}: {len(mostani)} idopont jelenleg")
        for k in sorted(mostani, key=lambda k: mostani[k]["kezdes"]):
            print(vetites_sor(mostani[k]))
    elif not mostani:
        print(f"[nincs valtozas] a(z) {' / '.join(CFG['szuro'])} jelenleg "
              f"nincs musoron; {len(napok)} jatszasi nap atnezve.")
    else:
        print(f"[nincs valtozas] {cimke}: {len(mostani)} idopont, "
              f"{len(napok)} nap atnezve.")

    state_ment(args.state, mostani)
    return 0


# ===========================================================================
#   HORIZONT MÓD — mikor kerül ki műsor új napokra
# ===========================================================================

def horizont_mod(args):
    ma = date.today().isoformat()
    regi = {d: v for d, v in state_betolt(args.state).items() if d >= ma}
    napok = jatszasi_napok()
    if not napok:
        print("[hiba] az API egyetlen jatszasi napot sem adott vissza",
              file=sys.stderr)
        return 1

    uj, lekerdezve = {}, 0
    for d in napok:
        elozo = regi.get(d)
        # A már teljesnek ismert napokat nem kérdezzük újra — kérésspórolás.
        if elozo and elozo.get("teljes"):
            uj[d] = elozo
            continue
        if lekerdezve:
            time.sleep(KERES_SZUNET)
        filmek, esemenyek = nap_lekeres(d)
        lekerdezve += 1
        uj[d] = {"vetitesek": len(esemenyek), "filmek": len(filmek),
                 "teljes": len(esemenyek) >= TELJES_MIN}

    friss_teljes, friss_szorvany = [], []
    for d, info in sorted(uj.items()):
        elozo = regi.get(d)
        if info["teljes"] and not (elozo and elozo.get("teljes")):
            friss_teljes.append((d, info))
        elif not info["teljes"] and elozo is None:
            friss_szorvany.append((d, info))

    def sor(d, info):
        jel = "" if info["teljes"] else "  (szórvány)"
        return (f"  {nap_cimke(d):<11} {info['vetitesek']:>3} vetítés, "
                f"{info['filmek']:>2} film{jel}")

    if args.seed or (not regi and not args.force_report):
        state_ment(args.state, uj)
        teljes = sum(1 for i in uj.values() if i["teljes"])
        print(f"[seed] allapot elmentve: {len(uj)} nap ({teljes} teljes), "
              f"{lekerdezve} lekerdezes. Ertesites nem ment ki.")
        for d, info in sorted(uj.items()):
            print(sor(d, info))
        return 0

    sorok = []
    if friss_teljes:
        sorok.append(f"=== {CFG['nev']}: új műsor, {len(friss_teljes)} nap ===")
        sorok += [sor(d, i) for d, i in friss_teljes]
    if friss_szorvany and SZORVANY_IS:
        if not sorok:
            sorok.append(f"=== {CFG['nev']}: előre nyitott előadás, "
                         f"{len(friss_szorvany)} nap ===")
        else:
            sorok += ["", "Emellett előre nyitott előadás:"]
        sorok += [sor(d, i) for d, i in friss_szorvany]

    if sorok:
        utolso = max(uj)
        elore = (date.fromisoformat(utolso) - date.today()).days
        sorok += ["", f"Horizont vége: {utolso} ({elore} nap előre)", CFG["link"]]
        kiir(sorok)
    elif args.force_report:
        teljes = sum(1 for i in uj.values() if i["teljes"])
        print(f"[jelentes] jelenlegi horizont, {len(uj)} nap ({teljes} teljes):")
        for d, info in sorted(uj.items()):
            print(sor(d, info))
    else:
        teljes = sum(1 for i in uj.values() if i["teljes"])
        print(f"[nincs valtozas] {len(uj)} nap ({teljes} teljes), "
              f"horizont vege {max(uj)}, {lekerdezve} lekerdezes.")

    state_ment(args.state, uj)
    return 0


# --- belépési pont --------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Cinema City műsorfigyelő")
    ap.add_argument("--state", default="state/seen.json",
                    help="állapotfájl útvonala")
    ap.add_argument("--seed", action="store_true",
                    help="állapot rögzítése értesítés nélkül")
    ap.add_argument("--force-report", action="store_true",
                    help="a jelenlegi teljes állapot kiírása változás nélkül is")
    args = ap.parse_args()

    mit = (f"film: {' / '.join(CFG['szuro'])}" if CFG["mod"] == "film"
           else f"teljes horizont (teljes nap >= {TELJES_MIN} vetítés)")
    print(f"[mozi] {CFG['nev']} / {CFG['szam']} — {mit}", file=sys.stderr)

    return film_mod(args) if CFG["mod"] == "film" else horizont_mod(args)


if __name__ == "__main__":
    sys.exit(main())
