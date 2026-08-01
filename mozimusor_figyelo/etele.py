#!/usr/bin/env python3
"""Etele Cinema műsorfigyelő.

Egy konkrét filmet figyel az etelecinema.hu-n, és minden ÚJ vetítési időpontra
szól — akár új napra kerül ki, akár egy meglévő naphoz vesznek fel újat.

A három mozi közül ez a legtisztább forrás: valódi JSON API, egyetlen kérés,
és a nyelv (szinkron/felirat) külön mezőben van, nem a film címébe rejtve.

Csak stdlib, nincs pip függőség.
"""

# ===========================================================================
#
#   C O N F I G
#
# ===========================================================================

FIGYELD = True         # False = ez a figyelő nem fut, kérést sem küld
CIMKE = "ETELE"        # az e-mail tárgyának előtagja


# --- Melyik filmre? --------------------------------------------------------
#
# Elég a cím egy része; az ékezet és a kis-nagybetű mindegy. Az API-ban a cím
# néha elgépelt ("Odüsszeía"), az ékezetsemleges illesztés ezt is elkapja.
# ÜRES LISTA = minden filmre szól.

FILM_SZURO = ["Odüsszeia"]


# --- Szinkronos vagy feliratos? --------------------------------------------
#
#   "feliratos"   <- csak eredeti hang, magyar felirattal
#   "szinkronos"  <- csak magyar szinkron
#   ""            <- mindegy, mindkettő érdekel
#
# Ezt a szkript a vetítés `speaking_type` és `subtitles` mezőjéből vezeti le.

NYELV = "feliratos"


# --- További szűrés (ritkán kell) ------------------------------------------
#
# Ugyanaz a logika, mint a másik két figyelőnél: egy elemen belül a vessző
# „és"-t jelent, a listaelemek között „vagy" van. Illeszthetsz a teremre
# ("4. terem"), a képformátumra ("3D"), a hangra ("7.1"), vagy bármelyik
# nyers API-értékre ("DUB", "IMAX").
#
#   JELLEMZO_SZURO = []          <- minden illeszkedő vetítés
#   JELLEMZO_SZURO = ["3D"]      <- csak a 3D-sek

JELLEMZO_SZURO = []

HORIZON_DAYS = 60      # ennél távolabbi napokat figyelmen kívül hagyunk

# Hány EGYMÁS UTÁNI sikertelen lekérés után jelezzünk hibát?
#
# A mozi szervere időnként 500-at ad. Ha minden ilyenre pirosra váltanánk, egy
# fél napos üzemzavar negyedóránként egy riasztó e-mailt jelentene — holott
# nincs vele teendőd, és nem is vész el semmi: az állapot csak sikeres futásnál
# íródik vissza. 4 egymás utáni hiba ~1 óra; ennyi után már érdemes tudni róla.
HIBA_TURES = 4

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
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://api.etelecinema.hu/api/v1/screenings"
MUSOR_OLDAL = "https://etelecinema.hu/musoron"
TIMEOUT = 25
RETRIES = 3
UA = "mozimusor-figyelo/1.0"
NAPOK = ["hé", "ke", "sze", "csü", "pé", "szo", "va"]

# A `speaking_type` ismert értékei. Amit nem ismerünk fel, arról NEM állítunk
# semmit — inkább hangosan jelezzük, mint hogy csendben kihagyjuk.
SZINKRON_JELEK = {"DUB", "DUBBED", "SZINKRON"}
FELIRAT_JELEK = {"SUB", "SUBBED", "OV", "ORIG", "ORIGINAL", "SUBTITLED"}


def ekezettelen(s):
    n = unicodedata.normalize("NFKD", str(s).casefold())
    return "".join(c for c in n if not unicodedata.combining(c))


def env(kulcs):
    """Üres env-változó = nincs beállítva (a GitHub a hiányzót is átadja)."""
    ertek = os.environ.get(kulcs, "").strip()
    return ertek or None


def igaz(kulcs, alap):
    ertek = env(kulcs)
    return bool(alap) if ertek is None else ertek.lower() in (
        "1", "true", "igen", "yes", "on")


def egesz(kulcs, alap):
    ertek = env(kulcs)
    try:
        return int(ertek) if ertek is not None else int(alap)
    except ValueError:
        return int(alap)


def listaz(kulcs, alap, elvalaszto=","):
    nyers = env(kulcs)
    if nyers is None:
        return [x.strip() for x in alap if x and x.strip()]
    if nyers in ("*", "-", "mind", "all"):
        return []
    return [x.strip() for x in nyers.split(elvalaszto) if x.strip()]


AKTIV = igaz("FIGYELD", FIGYELD)
ELOTAG = env("CIMKE") or CIMKE
FILMEK_SZURO = listaz("FILM_SZURO", FILM_SZURO)
FILM_KULCS = [ekezettelen(x) for x in FILMEK_SZURO]
# a NYELV-nél az üres string érvényes választás („mindegy"), ezért a "*" is az
_nyelv = env("NYELV")
NYELV_SZURO = ekezettelen("" if _nyelv in ("*", "-", "mind", "all")
                          else (NYELV if _nyelv is None else _nyelv))
JELLEMZOK_SZURO = listaz("JELLEMZO_SZURO", JELLEMZO_SZURO, ";")
JELLEMZO_KULCS = [[r.strip() for r in ekezettelen(x).split(",") if r.strip()]
                  for x in JELLEMZOK_SZURO]
HORIZONT = egesz("HORIZON_DAYS", HORIZON_DAYS)
TURES = egesz("HIBA_TURES", HIBA_TURES)

ISMERETLEN_NYELVEK = set()   # amit a futás közben nem tudtunk besorolni


class ErtelmezesiHiba(Exception):
    """A válasz nem az, amire számítunk. Nem ugyanaz, mint hogy nincs vetítés."""


# --- letöltés --------------------------------------------------------------

def get_json(url):
    utolso = None
    for kiserlet in range(RETRIES):
        if kiserlet:
            time.sleep(1 + kiserlet)
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            utolso = e
    raise RuntimeError(f"sikertelen lekeres: {url} ({utolso})")


# --- értelmezés ------------------------------------------------------------

def magyar_cim(film):
    """A film magyar címe. Az API néha `title`-t ad, néha `translations`-t."""
    for t in film.get("translations") or []:
        if t.get("locale") == "hu" and t.get("title"):
            return t["title"]
    for t in film.get("translations") or []:
        if t.get("title"):
            return t["title"]
    return film.get("title") or ""


def vetitesek_gyujtese(csomo):
    """Minden vetítés-szerű szótár, akárhogy is van becsomagolva.

    Az API a vetítéseket hol dátum szerinti szótárban, hol listában adja. Nem
    kötjük magunkat egyik alakhoz sem: rekurzívan bejárjuk, és mindent
    összeszedünk, aminek van `screening_time_day` mezője. Így egy átszervezés
    nem töri el az értelmezőt.
    """
    if isinstance(csomo, dict):
        if "screening_time_day" in csomo:
            yield csomo
            return
        for ertek in csomo.values():
            yield from vetitesek_gyujtese(ertek)
    elif isinstance(csomo, list):
        for elem in csomo:
            yield from vetitesek_gyujtese(elem)


def nyelv_besorolas(v):
    """('feliratos' | 'szinkronos' | None, nyers_leiras)

    None esetén nem tudjuk eldönteni — ilyet SOHA nem hagyunk el csendben.
    """
    beszed = (v.get("speaking_type") or "").strip().upper()
    felirat = (v.get("subtitles") or "").strip()
    nyers = f"speaking_type={beszed or '-'} subtitles={felirat or 'null'}"
    if beszed in SZINKRON_JELEK:
        return "szinkronos", nyers
    if beszed in FELIRAT_JELEK or felirat:
        return "feliratos", nyers
    return None, nyers


def jellemzok_listaja(v, nyelv):
    """Amit az értesítésben kiírunk, és amire szűrni lehet."""
    ki = []
    if nyelv:
        ki.append(nyelv)
    kep = (v.get("print_type") or "").strip()
    if kep and kep.upper() != "2D":       # a 2D az alap, azt nem írjuk ki
        ki.append(kep)
    kepernyo = v.get("screen") or {}
    jellemzo = (kepernyo.get("feature") or "").strip()
    if jellemzo:
        ki.append(jellemzo)
    return ki


def terem_neve(v):
    kepernyo = v.get("screen") or {}
    szam = kepernyo.get("number")
    return f"{szam}. terem" if szam is not None else ""


def kereso_szoveg(v, info):
    """Amire a JELLEMZO_SZURO illeszthet.

    Szándékosan bőkezű: a kiírt címkék mellett a NYERS API-értékek is benne
    vannak (hang, képformátum, terem típusa, beszédmód). Így arra is lehet
    szűrni, amit az értesítésben nem írunk ki — pl. "7.1" vagy "DUB".
    """
    kepernyo = v.get("screen") or {}
    darabok = info["jellemzok"] + [
        info["terem"], info["film"],
        v.get("speaking_type") or "", v.get("subtitles") or "",
        v.get("print_type") or "", v.get("sound_type") or "",
        v.get("language") or "",
        kepernyo.get("type") or "", kepernyo.get("feature") or "",
    ]
    return ekezettelen(" | ".join(str(x) for x in darabok if x))


def illeszkedik(info):
    if not JELLEMZO_KULCS:
        return True
    szoveg = info["kereses"]
    return any(all(f in szoveg for f in keszlet) for keszlet in JELLEMZO_KULCS)


def ertelmez(valasz):
    """{vetítés_id: {...}} a szűrőkre illeszkedő vetítésekből."""
    adat = valasz.get("data")
    if not isinstance(adat, (dict, list)) or not adat:
        raise ErtelmezesiHiba("a valaszban nincs hasznalhato 'data' mezo")

    bejegyzesek = adat.values() if isinstance(adat, dict) else adat
    ma = date.today().isoformat()
    hatar = (date.today() + timedelta(days=HORIZONT)).isoformat()

    talalt, filmek_info, film_osszes, napok = {}, {}, 0, set()
    osszes_vetites = 0

    for bejegyzes in bejegyzesek:
        if not isinstance(bejegyzes, dict):
            continue
        film = bejegyzes.get("movie") or bejegyzes
        film_id = film.get("id")
        cim = magyar_cim(film)
        if not cim:
            continue
        filmek_info[film_id] = {"nev": cim}

        vetitesek = list(vetitesek_gyujtese(bejegyzes.get("screenings", {})))
        osszes_vetites += len(vetitesek)
        if FILM_KULCS and not any(k in ekezettelen(cim) for k in FILM_KULCS):
            continue

        for v in vetitesek:
            nap = (v.get("screening_time_day") or "").strip()
            ido = (v.get("screening_time_time") or "").strip()
            if not nap or not ido or not (ma <= nap <= hatar):
                continue
            napok.add(nap)
            film_osszes += 1

            nyelv, nyers = nyelv_besorolas(v)
            if nyelv is None:
                ISMERETLEN_NYELVEK.add(nyers)

            # Nyelvszűrés. Ismeretlen nyelvnél NEM dobjuk el a vetítést —
            # inkább jöjjön be egy fölösleges, mint hogy elvesszen egy kellő.
            if NYELV_SZURO and nyelv is not None and nyelv != NYELV_SZURO:
                continue

            info = {
                "kezdes": f"{nap}T{ido}:00" if len(ido) == 5 else f"{nap}T{ido}",
                "film": cim,
                "film_id": film_id,
                "nyelv": nyelv or "?",
                "terem": terem_neve(v),
                "jellemzok": jellemzok_listaja(v, nyelv),
                "nyers": nyers,
            }
            info["kereses"] = kereso_szoveg(v, info)
            if illeszkedik(info):
                azonosito = str(v.get("id") or f"{film_id}|{nap}|{ido}")
                talalt[azonosito] = info

    if osszes_vetites == 0:
        raise ErtelmezesiHiba(
            "egyetlen vetitest sem talalok a valaszban — valoszinuleg "
            "atalakult az API valaszanak szerkezete")
    return talalt, filmek_info, sorted(napok), film_osszes


# --- állapot ---------------------------------------------------------------

def state_betolt(utvonal):
    """Korábbi állapot, vagy None, ha nincs használható.

    A None és az ÜRES SZÓTÁR nem ugyanaz: az üres azt jelenti, hogy már
    futottunk, csak nem volt találat — ilyenkor a legelső felbukkanó
    vetítésről szólni KELL.
    """
    try:
        with open(utvonal, encoding="utf-8") as f:
            adat = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    if ([ekezettelen(x) for x in adat.get("szuro", [])] != FILM_KULCS
            or ekezettelen(adat.get("nyelv", "")) != NYELV_SZURO
            or [ekezettelen(x) for x in adat.get("jellemzo", [])]
               != [ekezettelen(x) for x in JELLEMZOK_SZURO]):
        print("[info] a beallitas megvaltozott az allapotfajl ota, ujrakezdem",
              file=sys.stderr)
        return None
    return adat.get("adat", {})


def state_ment(utvonal, adat):
    """Csak akkor ír, ha érdemben változott — különben minden futás
    commitot generálna az időbélyeg miatt."""
    os.makedirs(os.path.dirname(utvonal) or ".", exist_ok=True)
    payload = {
        "frissitve": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mozi": "Etele Cinema",
        "szuro": FILMEK_SZURO,
        "nyelv": NYELV_SZURO,
        "jellemzo": JELLEMZOK_SZURO,
        "adat": dict(sorted(adat.items())),
    }
    try:
        with open(utvonal, encoding="utf-8") as f:
            regi = json.load(f)
        if all(regi.get(k) == payload[k]
               for k in ("mozi", "szuro", "nyelv", "jellemzo", "adat")):
            return False
    except (FileNotFoundError, ValueError):
        pass
    tmp = utvonal + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, utvonal)
    return True


def hiba_utvonal(allapot):
    """Az egymás utáni hibák számlálója, a fő állapot mellett külön fájlban.

    Külön fájl, hogy a hibaszámláló írása soha ne keveredjen a vetítések
    állapotával — egy sikertelen lekérésnél épp azt NEM szabad felülírni.
    """
    return os.path.splitext(allapot)[0] + "_hiba.json"


def hibak_szama(allapot):
    try:
        with open(hiba_utvonal(allapot), encoding="utf-8") as f:
            return int(json.load(f).get("egymas_utani", 0))
    except (FileNotFoundError, ValueError, TypeError, KeyError):
        return 0


def hibak_beallit(allapot, n, uzenet=""):
    """Csak akkor ír, ha változott — különben fölösleges commitokat szülne."""
    if hibak_szama(allapot) == n and not uzenet:
        return
    utvonal = hiba_utvonal(allapot)
    os.makedirs(os.path.dirname(utvonal) or ".", exist_ok=True)
    adat = {"egymas_utani": n}
    if uzenet:
        adat["utolso"] = uzenet[:300]
        adat["mikor"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tmp = utvonal + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(adat, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, utvonal)


def multat_nyes(vetitesek):
    ma = date.today().isoformat()
    return {k: v for k, v in vetitesek.items() if v.get("kezdes", "")[:10] >= ma}


# --- megjelenítés ----------------------------------------------------------

def nap_cimke(d):
    return f"{d} {NAPOK[date.fromisoformat(d).weekday()]}"


def vetites_sor(info):
    try:
        d, t = info["kezdes"].split("T")
        mikor = f"{nap_cimke(d)} {t[:5]}"
    except ValueError:
        mikor = info["kezdes"]
    terem = f"  {info['terem']}" if info["terem"] else ""
    jell = f"  ({', '.join(info['jellemzok'])})" if info["jellemzok"] else ""
    return f"  {mikor}{terem}{jell}"


def figyelmeztetes_ismeretlen_nyelv():
    """Ha volt olyan vetítés, aminek a nyelvét nem tudtuk eldönteni.

    Ez azért kap külön hangot, mert pont ez a fajta hiba tud csendben
    hamis képet adni: a szűrő látszólag működik, közben vetítések maradnak ki.
    """
    if not ISMERETLEN_NYELVEK:
        return
    print(f"[figyelmeztetes] {len(ISMERETLEN_NYELVEK)} ismeretlen nyelvi jeloles "
          f"— ezeket NEM szurtem ki, inkabb bejonnek:", file=sys.stderr)
    for nyers in sorted(ISMERETLEN_NYELVEK):
        print(f"                 {nyers}", file=sys.stderr)
    print("                 Ha ez rendszeres, vedd fel a SZINKRON_JELEK / "
          "FELIRAT_JELEK halmazba az etele.py tetejen.", file=sys.stderr)


# --- fő logika -------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Etele Cinema műsorfigyelő")
    ap.add_argument("--state", default="state/etele.json")
    ap.add_argument("--seed", action="store_true",
                    help="állapot rögzítése értesítés nélkül")
    ap.add_argument("--force-report", action="store_true",
                    help="a jelenlegi teljes állapot kiírása változás nélkül is")
    ap.add_argument("--jellemzok", action="store_true",
                    help="milyen nyelvi/formátum-értékek fordulnak elő (felderítés)")
    args = ap.parse_args()

    if not AKTIV:
        print(f"[kikapcsolva] a FIGYELD hamis ({ELOTAG}), ez a figyelo nem fut.")
        return 0

    mit = " / ".join(FILMEK_SZURO) if FILMEK_SZURO else "minden film"
    nyelv_cimke = NYELV_SZURO or "mindegy"
    print(f"[mozi] Etele Cinema — {mit} ({nyelv_cimke})", file=sys.stderr)

    try:
        valasz = get_json(API)
    except RuntimeError as e:
        # A mozi szervere nem elérhető vagy hibát ad. Ez NEM a mi hibánk, és
        # nem is vész el semmi: az állapotot csak sikeres futásnál írjuk
        # vissza, tehát a következő futás ugyanonnan folytatja. Ezért az első
        # néhány alkalommal csendben tűrjük, és csak tartós kiesésnél szólunk.
        n = hibak_szama(args.state) + 1
        hibak_beallit(args.state, n, str(e))
        if n < TURES:
            print(f"[atmeneti hiba] az Etele API most nem valaszol "
                  f"({n}. alkalom, {TURES}-nel szolok). Nem veszett el semmi, "
                  f"a kovetkezo futas ujraprobalja.")
            print(f"                {e}", file=sys.stderr)
            return 0
        print(f"[HIBA] az Etele API mar {n} egymas utani alkalommal nem "
              f"valaszol: {e}", file=sys.stderr)
        return 1

    hibak_beallit(args.state, 0)      # sikerült — a számláló nullázódik

    # Felderítő mód: mit ad valójában az API? Nem küld e-mailt, nem ment.
    if args.jellemzok:
        return felderites(valasz)

    korabbi = state_betolt(args.state)
    elso_futas = korabbi is None
    regi = multat_nyes(korabbi or {})

    try:
        mostani, filmek_info, napok, film_osszes = ertelmez(valasz)
    except ErtelmezesiHiba as e:
        print(f"[HIBA] nem tudom ertelmezni az Etele API valaszat: {e}",
              file=sys.stderr)
        print(f"       a valasz kulcsai: {list(valasz)[:8]}", file=sys.stderr)
        return 1

    figyelmeztetes_ismeretlen_nyelv()

    ujak = {k: v for k, v in mostani.items() if k not in regi}
    kiszurt = film_osszes - len(mostani)
    cimke = " / ".join(sorted({v["film"] for v in mostani.values()})) or mit

    def reszletek():
        for k in sorted(mostani, key=lambda k: mostani[k]["kezdes"]):
            print(vetites_sor(mostani[k]))
        if kiszurt:
            print(f"  (+ {kiszurt} tovabbi vetites, amit a szuro kihagyott)")

    if args.seed or (elso_futas and not args.force_report):
        state_ment(args.state, mostani)
        print(f"[seed] allapot elmentve: {len(mostani)} vetites ({cimke}). "
              f"Ertesites nem ment ki.")
        reszletek()
        return 0

    if ujak:
        ujak_cimke = " / ".join(sorted({v["film"] for v in ujak.values()}))
        sorok = [f"=== [{ELOTAG}] {ujak_cimke}: {len(ujak)} új időpont ===",
                 "", f">> Ugrás a moziműsorra: {MUSOR_OLDAL}", "",
                 "Új előadások:"]
        sorok += [vetites_sor(ujak[k])
                  for k in sorted(ujak, key=lambda k: ujak[k]["kezdes"])]
        sorok += ["", f"Összesen {len(mostani)} illeszkedő időpont; a mozi "
                      f"jelenleg {max(napok)}-ig írt ki műsort."]
        print("\n".join(sorok))
    elif args.force_report:
        print(f"[jelentes] {cimke}: {len(mostani)} idopont jelenleg")
        reszletek()
    elif not film_osszes:
        print(f"[nincs valtozas] a(z) {mit} jelenleg nincs musoron; "
              f"{len(napok)} nap atnezve.")
    elif not mostani:
        print(f"[nincs valtozas] a(z) {cimke} musoron van {film_osszes} "
              f"idoponttal, de egyik sem felel meg a szuronek "
              f"(nyelv: {nyelv_cimke}).")
    else:
        print(f"[nincs valtozas] {cimke}: {len(mostani)} idopont "
              f"({kiszurt} kiszurve), {len(napok)} nap atnezve.")

    state_ment(args.state, mostani)
    return 0


def felderites(valasz):
    """Milyen értékek fordulnak elő? — hogy ne tippelni kelljen."""
    import collections
    szamlalo = collections.defaultdict(collections.Counter)
    filmek, napok = set(), set()
    adat = valasz.get("data") or {}
    bejegyzesek = adat.values() if isinstance(adat, dict) else adat
    db = 0
    for bejegyzes in bejegyzesek:
        if not isinstance(bejegyzes, dict):
            continue
        film = bejegyzes.get("movie") or bejegyzes
        filmek.add(magyar_cim(film))
        for v in vetitesek_gyujtese(bejegyzes.get("screenings", {})):
            db += 1
            napok.add(v.get("screening_time_day"))
            for mezo in ("speaking_type", "subtitles", "language",
                         "print_type", "sound_type"):
                szamlalo[mezo][repr(v.get(mezo))] += 1
            kep = v.get("screen") or {}
            szamlalo["screen.feature"][repr(kep.get("feature"))] += 1
            szamlalo["screen.type"][repr(kep.get("type"))] += 1
    print(f"[felderites] {len(filmek)} film, {db} vetites, "
          f"{min(napok, default='-')} — {max(napok, default='-')}")
    for mezo, ertekek in szamlalo.items():
        print(f"  {mezo}:")
        for ertek, n in ertekek.most_common():
            print(f"      {ertek:<28} {n}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
