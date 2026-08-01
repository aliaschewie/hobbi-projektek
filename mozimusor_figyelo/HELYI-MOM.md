# Cinema MOM figyelő — helyi telepítés

A MOM-figyelő **nem a felhőben fut**, hanem ezen a gépen. Oka: a
`cinemamom.hu` az adatközponti IP-ket (így a GitHub futtatóit is) egy
„Kis türelmet…" című JavaScript-ellenőrző oldalra irányítja a műsor helyett.
Az otthoni kapcsolatot nem szűri. Ezt a védelmet nem kerüljük meg.

A Cinema City és később az Etele **marad a felhőben** — azoknak valódi JSON
API-juk van, nincs szűrés.

---

## Telepítés — négy lépés

### 1. A küldő e-mail-cím (a repón kívül)

```bash
mkdir -p ~/"Library/Application Support/mozimusor"
cat > ~/"Library/Application Support/mozimusor/config.env" <<'EOF'
GMAIL_USER=aliascsuvi@gmail.com
EOF
```

Ha máshova kérnéd a levelet, vehetsz fel egy `EMAIL_TO=...` sort is.

*Ez a fájl szándékosan a repón kívül van: a repo publikus, oda nem való
e-mail-cím.*

### 2. Az app-jelszó a kulcstartóba

Ugyanaz a 16 karakteres Google app-jelszó, ami a GitHub secretben van.

```zsh
read -s "PW?Gmail app-jelszó: "
security add-generic-password -U -a "$USER" -s mozimusor-gmail -w "$PW"
unset PW
```

A jelszó így **nem kerül be a Terminál előzményébe**, és titkosítva tárolódik.

### 3. Az ütemezés bekapcsolása

```bash
mkdir -p ~/Library/LaunchAgents ~/Library/Logs
sed -e "s|MOM_SZKRIPT_UTVONAL|$HOME/hobbi projektek/mozimusor_figyelo/mom_local.sh|" \
    -e "s|MOM_NAPLO_UTVONAL|$HOME/Library/Logs/mozimusor-mom.log|" \
    ~/"hobbi projektek/mozimusor_figyelo/hu.mozimusor.mom.plist" \
    > ~/Library/LaunchAgents/hu.mozimusor.mom.plist

chmod +x ~/"hobbi projektek/mozimusor_figyelo/mom_local.sh"
launchctl unload ~/Library/LaunchAgents/hu.mozimusor.mom.plist 2>/dev/null
launchctl load  ~/Library/LaunchAgents/hu.mozimusor.mom.plist
```

A `RunAtLoad` miatt **azonnal lefut egyszer**.

### 4. Ellenőrzés

```bash
sleep 20
cat ~/Library/Logs/mozimusor-mom.log
```

Az első futásnál ezt kell látnod:

```
===== 2026-08-01 13:05:00 =====
[mozi] Cinema MOM — The Odyssey
[seed] allapot elmentve: 5 vetites (The Odyssey). Ertesites nem ment ki.
```

**Az első futás szándékosan néma** — rögzíti a kiindulási állapotot. Onnantól
csak akkor ír, ha tényleg új időpont került ki.

> A kulcstartó első hozzáférésekor felugorhat egy engedélykérő ablak.
> Válaszd az **Always Allow** gombot, különben minden futásnál kérdezni fog.

---

## Napi működés

| | |
|---|---|
| gyakoriság | negyedóránként, amíg a gép ébren van |
| alvó gép | nem fut; ébredéskor a launchd egyszer bepótolja |
| állapot | `~/Library/Application Support/mozimusor/mom.json` |
| napló | `~/Library/Logs/mozimusor-mom.log` |
| e-mail | ugyanaz a cím, `[MOM]` előtaggal |

Az állapotfájl **szándékosan a repón kívül van**. Ha a repóban lenne, minden
futás piszkossá tenné a munkakönyvtárat, és ütközne a GitHub-bot commitjaival.

## Kézi futtatás

```bash
bash ~/"hobbi projektek/mozimusor_figyelo/mom_local.sh"
```

## Kikapcsolás

```bash
launchctl unload ~/Library/LaunchAgents/hu.mozimusor.mom.plist
```

## Ha nem jön levél

```bash
tail -40 ~/Library/Logs/mozimusor-mom.log
```

| a naplóban ez áll | mit jelent |
|---|---|
| `[csend] nincs uj idopont` | minden rendben, nincs miről szólni |
| `[hiba] nincs 'mozimusor-gmail' bejegyzes` | a 2. lépés kimaradt |
| `[hiba] hianyzik a konfiguracio` | az 1. lépés kimaradt |
| `Kis türelmet…` a diagnosztikában | téged is szűrni kezdett az oldal — szólj |
| semmi, üres napló | a launchd nem tölti be; `launchctl list \| grep mozimusor` |
