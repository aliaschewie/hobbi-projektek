#!/usr/bin/env python3
"""Cinema MOM műsorfigyelő.

Egy konkrét filmet figyel a cinemamom.hu-n, és minden ÚJ vetítési időpontra
szól — akár új napra kerül ki, akár egy meglévő naphoz vesznek fel újat.

A Cinema Cityvel ellentétben itt nincs JSON API: a műsor a főoldal HTML-jébe
van beleírva, szerveroldalon. Ez jó hír (egyetlen kérés az egész műsor), de
törékenyebb is: egy arculatváltás elronthatja az értelmezést. Ezért a szkript
KÜLÖN KEZELI azt, hogy „nincs vetítés" és azt, hogy „nem tudom értelmezni az
oldalt" — utóbbinál hibával áll le, hogy a csend ne tűnjön nyugalomnak.

Csak stdlib, nincs pip függőség.
"""

# ===========================================================================
#
#   C O N F I G
#
# ===========================================================================

# --- 0. Be van-e kapcsolva ez a figyelő? -----------------------------------
#
# False esetén azonnal kilép, egyetlen kérést sem küld, e-mailt nem ír.
# A Cinema City-s figyelő (watch.py) ettől függetlenül fut tovább.
FIGYELD = True

# Az e-mail tárgyának előtagja: "[MOM] Odüsszeia: 1 új időpont …"
CIMKE = "MOM"


# --- 1. Melyik filmre? -----------------------------------------------------
#
# FONTOS KÜLÖNBSÉG a Cinema Cityhez képest: a MOM-nál a szinkronos és a
# feliratos változat KÉT KÜLÖN FILM, más-más címmel:
#
#     "Odüsszeia"                                          <- szinkronos
#     "The Odyssey - Original language with Hungarian subtitles"  <- feliratos
#
# Most a FELIRATOS változatra figyelünk. Ha a szinkronos is érdekelne, írd:
#     FILM_SZURO = ["Odüsszeia", "The Odyssey"]
# Csak szinkronos:
#     FILM_SZURO = ["Odüsszeia"]
#
# Elég a cím egy része, az ékezet és a kis-nagybetű mindegy.
# ÜRES LISTA = minden filmre szól, ami a moziban megjelenik.

FILM_SZURO = ["The Odyssey"]


# --- 2. Milyen vetítésre? --------------------------------------------------
#
# A MOM minden vetítéshez tehet egy betűjelet. Amit eddig láttunk:
#     F  = feliratos
#     (jelöletlen) = szinkronos
#     M, E = ritkábban előfordul, a teljes műsorlistában
#
# Szűrni a betűre, a film címére és a nap nevére is lehet. A vessző „és"-t
# jelent egy elemen belül, a listaelemek között „vagy" van.
#
#   JELLEMZO_SZURO = []            <- minden vetítés
#   JELLEMZO_SZURO = ["feliratos"] <- csak a feliratos jelölésűek

JELLEMZO_SZURO = []


# --- 3. Finomhangolás ------------------------------------------------------

HORIZON_DAYS = 60          # ennél távolabbi napokat figyelmen kívül hagyunk

# ===========================================================================
#   Innentől nem kell hozzányúlni.
# ===========================================================================

import argparse
import html as html_modul
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

HOST = "https://cinemamom.hu"
TIMEOUT = 30
RETRIES = 3
# Böngészőszerű azonosító: a mozi oldala rendes weboldal, nem API.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NAPOK = ["hé", "ke", "sze", "csü", "pé", "szo", "va"]

# betűjel -> olvasható címke
TIPUSOK = {"F": "feliratos", "M": "magyarul", "E": "eredeti nyelven"}

# --- HTML-minták. Ha az oldal átalakul, itt kell javítani. ------------------
RE_TAB = re.compile(r'data-tab="(\d+)"\s+data-date="(\d{4}-\d{2}-\d{2})"')
RE_NAPBLOKK = re.compile(r'<div class="day tab-(\d+)[^"]*">')
RE_FILMDOBOZ = re.compile(r'<div class="movie-box">')
RE_FILMLINK = re.compile(r'href="film/([a-z0-9\-]+?)-(\d+)"')
RE_CIM = re.compile(r'<div class="title"><a[^>]*>([^<]*)</a>')
RE_IDOPONT = re.compile(
    r'<a href="jegyrendeles/(\d+)">\s*<span class="time"><em>([^<]*)</em></span>'
    r'\s*(?:<span class="type">([^<]*)</span>)?')


def ekezettelen(s):
    """Kis-nagybetű és ékezet nélküli alak az összehasonlításhoz."""
    n = unicodedata.normalize("NFKD", str(s).casefold())
    return "".join(c for c in n if not unicodedata.combining(c))


def env(kulcs):
    """Env-változó értéke, üres esetén None.

    A GitHub Actions a nem létező repo-változót is átadja, üres sztringként —
    az nem felülírás, hanem hiány.
    """
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


def listaz(kulcs, alap, elvalaszto=","):
    """Env-változóból lista. "*" = szándékosan üres (nincs szűrés)."""
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
JELLEMZOK_SZURO = listaz("JELLEMZO_SZURO", JELLEMZO_SZURO, ";")
JELLEMZO_KULCS = [[r.strip() for r in ekezettelen(x).split(",") if r.strip()]
                  for x in JELLEMZOK_SZURO]
HORIZONT = egesz("HORIZON_DAYS", HORIZON_DAYS)


# --- letöltés --------------------------------------------------------------

def letolt(url):
    utolso = None
    for kiserlet in range(RETRIES):
        if kiserlet:
            time.sleep(2 ** kiserlet)
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "hu-HU,hu;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:
            utolso = e
    raise RuntimeError(f"sikertelen letoltes: {url} ({utolso})")


# --- értelmezés ------------------------------------------------------------

class ErtelmezesiHiba(Exception):
    """Az oldal szerkezete nem az, amire számítunk.

    Ezt SOHA nem szabad összemosni azzal, hogy „nincs vetítés" — az egyik
    hiba, a másik hír. Ha összemosnánk, egy oldal-átalakítás után a figyelő
    örökre csendben maradna, és azt hinnéd, csak nincs új műsor.
    """


def ertelmez(oldal):
    """A főoldal HTML-jéből: {jegy_id: {...}} a szűrőre illeszkedő vetítésekből.

    Az oldal szerkezete:
      - a napválasztó fülek adják a tab -> dátum megfeleltetést
        <div class="swiper-slide" data-tab="1" data-date="2026-08-01">
      - a tartalom naponként egy blokk:  <div class="day tab-1 hidden"> …
      - azon belül filmenként egy doboz: <div class="movie-box"> …
      - a dobozban a film linkje adja az azonosítót: href="film/<slug>-<id>"
      - az időpontok: <a href="jegyrendeles/<id>"><span class="time"><em>12:00
    """
    tabok = dict(RE_TAB.findall(oldal))
    if not tabok:
        raise ErtelmezesiHiba("egyetlen napvalaszto fulet sem talalok "
                              "(data-tab / data-date)")

    # a napblokkok kezdőpozíciói, hogy szeletelni tudjunk
    hatarok = [(m.group(1), m.start(), m.end()) for m in RE_NAPBLOKK.finditer(oldal)]
    if not hatarok:
        raise ErtelmezesiHiba('egyetlen napblokkot sem talalok (class="day tab-N")')

    ma = date.today().isoformat()
    hatar_nap = (date.today() + timedelta(days=HORIZONT)).isoformat()

    talalt, filmek_info, osszes_doboz, film_osszes = {}, {}, 0, 0
    for i, (tab, _kezd, veg) in enumerate(hatarok):
        blokk_veg = hatarok[i + 1][1] if i + 1 < len(hatarok) else len(oldal)
        blokk = oldal[veg:blokk_veg]
        nap = tabok.get(tab)
        if not nap or not (ma <= nap <= hatar_nap):
            continue

        # a blokkot filmdobozokra vágjuk
        pozok = [m.start() for m in RE_FILMDOBOZ.finditer(blokk)]
        for j, p in enumerate(pozok):
            doboz = blokk[p:pozok[j + 1] if j + 1 < len(pozok) else len(blokk)]
            osszes_doboz += 1
            link = RE_FILMLINK.search(doboz)
            cim_m = RE_CIM.search(doboz)
            if not link or not cim_m:
                continue
            slug, film_id = link.group(1), link.group(2)
            cim = html_modul.unescape(cim_m.group(1)).strip()
            filmek_info[film_id] = {"nev": cim,
                                    "link": f"{HOST}/film/{slug}-{film_id}"}
            if FILM_KULCS and not any(k in ekezettelen(cim) for k in FILM_KULCS):
                continue
            for jegy_id, ido, tipus in RE_IDOPONT.findall(doboz):
                film_osszes += 1
                tipus = (tipus or "").strip()
                jellemzok = [TIPUSOK.get(tipus, tipus)] if tipus else ["szinkronos"]
                info = {
                    "kezdes": f"{nap}T{ido.strip()}:00",
                    "film": cim,
                    "film_id": film_id,
                    "jellemzok": jellemzok,
                    "link": f"{HOST}/jegyrendeles/{jegy_id}",
                }
                if jellemzo_illeszkedik(info):
                    talalt[jegy_id] = info

    if osszes_doboz == 0:
        raise ErtelmezesiHiba("a napblokkokban egyetlen filmdobozt sem talalok "
                              '(class="movie-box") — valoszinuleg atalakult az oldal')
    return talalt, filmek_info, sorted(set(tabok.values())), film_osszes


def jellemzo_illeszkedik(info):
    """Üres szűrő = minden jó. Elemen belül ÉS, elemek között VAGY."""
    if not JELLEMZO_KULCS:
        return True
    szoveg = ekezettelen(" | ".join(info["jellemzok"] + [info["film"]]))
    return any(all(f in szoveg for f in keszlet) for keszlet in JELLEMZO_KULCS)


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
            or [ekezettelen(x) for x in adat.get("jellemzo", [])]
               != [ekezettelen(x) for x in JELLEMZOK_SZURO]):
        print("[info] a beallitas megvaltozott az allapotfajl ota, ujrakezdem",
              file=sys.stderr)
        return None
    return adat.get("adat", {})


def state_ment(utvonal, adat):
    """Állapot mentése — de csak ha ÉRDEMBEN változott.

    A `frissitve` időbélyeg minden futásnál más lenne, a workflow pedig minden
    fájlváltozást commitol. Enélkül negyedóránként keletkezne egy commit, ami
    semmit nem mond: napi ~96, évi ~35 000 üres bejegyzés a történetben.
    """
    os.makedirs(os.path.dirname(utvonal) or ".", exist_ok=True)
    payload = {
        "frissitve": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mozi": "Cinema MOM",
        "szuro": FILMEK_SZURO,
        "jellemzo": JELLEMZOK_SZURO,
        "adat": dict(sorted(adat.items())),
    }
    try:
        with open(utvonal, encoding="utf-8") as f:
            regi = json.load(f)
        if all(regi.get(k) == payload[k] for k in ("mozi", "szuro", "jellemzo", "adat")):
            return False
    except (FileNotFoundError, ValueError):
        pass
    tmp = utvonal + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, utvonal)
    return True


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
    jell = f"  ({', '.join(info['jellemzok'])})" if info["jellemzok"] else ""
    return f"  {mikor}{jell}"


# --- fő logika -------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Cinema MOM műsorfigyelő")
    ap.add_argument("--state", default="state/mom.json",
                    help="állapotfájl útvonala")
    ap.add_argument("--seed", action="store_true",
                    help="állapot rögzítése értesítés nélkül")
    ap.add_argument("--force-report", action="store_true",
                    help="a jelenlegi teljes állapot kiírása változás nélkül is")
    args = ap.parse_args()

    if not AKTIV:
        print(f"[kikapcsolva] a FIGYELD hamis ({ELOTAG}), ez a figyelo nem fut. "
              f"Egyetlen kerest sem kuldtem.")
        return 0

    mit = " / ".join(FILMEK_SZURO) if FILMEK_SZURO else "minden film"
    print(f"[mozi] Cinema MOM — {mit}", file=sys.stderr)

    korabbi = state_betolt(args.state)
    elso_futas = korabbi is None
    regi = multat_nyes(korabbi or {})

    try:
        mostani, filmek_info, napok, film_osszes = ertelmez(letolt(HOST + "/"))
    except ErtelmezesiHiba as e:
        # Ez NEM „nincs vetítés" — ez azt jelenti, hogy az oldal átalakult.
        # Hibával lépünk ki, hogy a futás pirosra váltson és feltűnjön.
        print(f"[HIBA] nem tudom ertelmezni a cinemamom.hu oldalat: {e}\n"
              f"       A muster-figyelo ilyenkor NEM nemul el csendben: az "
              f"ertelmezo mintait kell javitani a mom.py tetejen.",
              file=sys.stderr)
        return 1

    ujak = {k: v for k, v in mostani.items() if k not in regi}
    kiszurt = film_osszes - len(mostani)

    def felirat(halmaz):
        """Rövid cím a tárgysorhoz.

        Csak az ÉRINTETT filmek nevét használjuk, nem az összes illeszkedőét —
        különben a feliratos változat hosszú angol címe ("The Odyssey -
        Original language with Hungarian subtitles") minden tárgysort
        elnyújtana. A gondolatjel utáni magyarázó részt is levágjuk.
        """
        nevek = sorted({v["film"] for v in halmaz.values()})
        if not nevek:
            return " / ".join(FILMEK_SZURO) or "minden film"
        rovid = []
        for n in nevek:
            r = re.split(r"\s+[-–]\s+", n)[0].strip()
            if r not in rovid:
                rovid.append(r)
        return " / ".join(rovid)

    cimke = felirat(mostani)

    def reszletek():
        for k in sorted(mostani, key=lambda k: mostani[k]["kezdes"]):
            print(vetites_sor(mostani[k]))
        if kiszurt:
            print(f"  (+ {kiszurt} tovabbi vetites, amit a jellemzo-szuro "
                  f"kihagyott)")

    def gomb(vonatkozo):
        """A film saját oldala — ott van együtt az összes időpontja.

        Ha több filmre is jött új időpont (pl. a szinkronosra és a feliratosra
        egyszerre), a főoldalra viszünk, mert egyetlen filmoldal féloldalas
        képet adna.
        """
        idk = {v["film_id"] for v in vonatkozo.values() if v.get("film_id")}
        cim = (filmek_info.get(next(iter(idk)), {}).get("link")
               if len(idk) == 1 else HOST + "/")
        return f">> Ugrás a moziműsorra: {cim or HOST + '/'}"

    if args.seed or (elso_futas and not args.force_report):
        state_ment(args.state, mostani)
        print(f"[seed] allapot elmentve: {len(mostani)} vetites ({cimke}). "
              f"Ertesites nem ment ki.")
        reszletek()
        return 0

    if ujak:
        sorok = [f"=== [{ELOTAG}] {felirat(ujak)}: {len(ujak)} új időpont ===",
                 "", gomb(ujak), "", "Új előadások:"]
        sorok += [vetites_sor(ujak[k])
                  for k in sorted(ujak, key=lambda k: ujak[k]["kezdes"])]
        sorok += ["", f"Összesen {len(mostani)} időpont; a mozi jelenleg "
                      f"{max(napok)}-ig írt ki műsort."]
        print("\n".join(sorok))
    elif args.force_report:
        print(f"[jelentes] {cimke}: {len(mostani)} idopont jelenleg")
        reszletek()
    elif not film_osszes:
        print(f"[nincs valtozas] a(z) {mit} jelenleg nincs musoron; "
              f"{len(napok)} jatszasi nap atnezve.")
    else:
        print(f"[nincs valtozas] {cimke}: {len(mostani)} idopont "
              f"({kiszurt} kiszurve), {len(napok)} nap atnezve.")

    state_ment(args.state, mostani)
    return 0


if __name__ == "__main__":
    sys.exit(main())
