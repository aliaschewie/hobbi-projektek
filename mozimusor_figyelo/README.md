# Cinema City műsorfigyelő

Szól e-mailben, amikor a Cinema City új vetítéseket ír ki. Két üzemmódja van,
és a `watch.py` tetején lévő **CONFIG** blokk dönti el, melyik fut.

| mód | mikor aktív | mire szól |
|---|---|---|
| **film** | `FILM_SZURO` ki van töltve | egy konkrét film **minden új időpontjára** — akkor is, ha egy meglévő naphoz vesznek fel újat |
| **horizont** | `FILM_SZURO` üres lista | amikor a mozi **új napokra** ír ki műsort |

Ha a műsort részletekben töltik fel, minden részletről külön értesítés megy,
mindig csak az újdonsággal. Változatlan futás néma.

## Hol fut

GitHub Actionsben, 5 percenként. **A saját géped lehet kikapcsolva** — a
GitHub szerverein fut. Ez a mappa csak a forrás, ahonnan a repóba kerül.

Az állapotot a repóban lévő `state/seen.json` tartja: a workflow minden
változásnál visszacommitolja. Innen tudja, mi az, amiről már szólt.

**Publikus repo kell.** Az Actions-percek csak publikus repóban ingyenesek és
korlátlanok; privátnál az 5 perces ütemezés az első két napban megenné a havi
2000 perces keretet. A repóban semmi érzékeny nincs — egy szkript és egy
dátumlista.

## Beállítás

A `watch.py` tetején, a CONFIG blokkban:

```python
MOZI_NEVE  = "arena"          # a link végéről: /cinemas/[arena]/1132
MOZI_SZAMA = "1132"           # a link végéről: /cinemas/arena/[1132]

FILM_SZURO = ["Odüsszeia"]    # [] = minden filmre megy
```

A magyar mozik neve és száma a CONFIG blokk kommentjében megtalálható.
A szűrő ékezet- és kisbetű-tűrő, elég a cím egy része: `"odusszeia"` is jó.
Több film: `["Odüsszeia", "Toy Story"]`.

Kódmódosítás nélkül is átállítható: **Settings → Secrets and variables →
Actions → Variables** fülön felvett `MOZI_NEVE`, `MOZI_SZAMA`, `FILM_SZURO`
felülírja a CONFIG-ot. Az üres változó nem számít beállításnak.

Ha a mozit, a módot vagy a szűrőt megváltoztatod, a szkript észreveszi, hogy a
mentett állapot már nem érvényes, és **újrakezdi** — nem küld egy nagy
spam-értesítést a "váratlanul felbukkant" vetítésekről.

### Finomhangolás

| beállítás | mit csinál |
|---|---|
| `FULL_MIN_EVENTS` | horizont módban ettől a vetítésszámtól "teljes" egy nap (alap: 15) |
| `NOTIFY_PARTIAL` | horizont módban szóljon-e az előre nyitott premierekre is (1/0) |
| `HORIZON_DAYS` | hány napra előre nézzen (alap: 60) |
| `NTFY_TOPIC` | ha megadod *secretként*, mobil push is megy ntfy.sh-on |

## Kézi futtatás

```bash
python3 watch.py --state state/seen.json                  # normál futás
python3 watch.py --state state/seen.json --force-report   # jelenlegi állapot kiírása
python3 watch.py --state state/seen.json --seed           # állapot rögzítése némán
```

GitHubon ugyanez: **Actions → Cinema City műsorfigyelő → Run workflow**, ott a
két kapcsoló ugyanezt csinálja.

## Hogyan működik

A cinemacity.hu Angular SPA, HTML-scrape nem működik rajta. Van viszont
mögötte nyilvános JSON API, kulcs és bejelentkezés nélkül:

```
# mely napokra van egyáltalán műsor
/hu/data-api-service/v1/quickbook/10102/dates/in-cinema/1132/until/{YYYY-MM-DD}?attr=&lang=hu_HU

# egy nap filmjei és vetítései
/hu/data-api-service/v1/quickbook/10102/film-events/in-cinema/1132/at-date/{YYYY-MM-DD}?attr=&lang=hu_HU
```

`10102` = a magyar oldal site ID-ja, `1132` = Aréna. A `dates` végpont csak
azokat a napokat adja vissza, amikre van vetítés — nincs üres nap, így a
horizont tolódása tiszta halmazkülönbség.

**Miért nem elég a "új dátum jelent meg" figyelés?** Mert a mozi hetekkel
előre nyit egy-egy premiervetítést, és minden ilyen téves riasztás lenne.
Ezért a horizont mód naponkénti vetítésszámot tárol: a teljes nap ~100
vetítés, egy előre nyitott premier 1–2. A `FULL_MIN_EVENTS=15` a kettő közti
szakadékban van, így nem kell dátumot hardcode-olni.

Mért adat (Aréna, 2026-08-01): teljes nap = 100 vetítés / 20 film;
2026-08-12 előre nyitott premier = 1 vetítés / 1 film.

## Hibakeresés

| tünet | mi a teendő |
|---|---|
| nem jön e-mail | GitHub → Settings → Notifications → *Participating* legyen e-mailen bekapcsolva |
| minden futás értesít | valószínűleg nem íródik vissza az állapot; nézd meg a "Állapot visszaírása" lépést |
| soha nem értesít | Actions → Run workflow → *force_report* — kiírja, mit lát egyáltalán |
| "nincs műsoron" | a szűrt film jelenleg nem szerepel a műsorban; ez normális, majd szól ha felkerül |
| leállt az ütemezés | a GitHub 60 nap repo-inaktivitás után kikapcsolja az ütemezett workflow-kat; egy commit újraindítja |
