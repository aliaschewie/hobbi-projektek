# Hobbi projektek

Monorepo — minden projekt saját alkönyvtárban, saját GitHub Actions
workflow-val.

| projekt | mit csinál | workflow |
|---|---|---|
| [`mozimusor_figyelo/`](mozimusor_figyelo/) | e-mailt küld, amikor a Cinema City új vetítéseket ír ki | [`mozimusor-figyelo.yml`](.github/workflows/mozimusor-figyelo.yml) |

## Új projekt hozzáadása

1. Készíts egy új alkönyvtárat, pl. `uj_projekt/`.
2. Másold le a `.github/workflows/mozimusor-figyelo.yml`-t
   `.github/workflows/uj-projekt.yml` néven, és írd át benne:
   - `name:` — a workflow neve
   - `concurrency.group:` — egyedi legyen, különben a két projekt kizárja egymást
   - `defaults.run.working-directory:` — az új alkönyvtár neve
   - a futtatott parancsot
3. Commit + push. A GitHub magától felveszi az ütemezésbe.

## Fontos tudnivalók

**Publikus repo.** Az Actions-percek csak így ingyenesek és korlátlanok. Ne
tegyél ide jelszót, API-kulcsot, tokent — azoknak a helye
**Settings → Secrets and variables → Actions → Secrets**.

**Beállítások kód nélkül.** Ugyanott a **Variables** fülön felvett változók
felülírják a szkriptek beépített CONFIG blokkjait. A repo-szintű változó
minden workflow-ra érvényes, tehát az egyedi neveket érdemes projektenként
prefixelni, ha ütköznének.

**60 napos szabály.** A GitHub kikapcsolja az ütemezett workflow-kat, ha 60
napig nincs repo-aktivitás. Amíg a figyelő visszacommitolja az állapotát, ez
magától nem következik be.
