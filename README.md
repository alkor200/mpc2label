# thermal-deck

Nimmt eine [MPC-Autofill](https://github.com/chilli-axe/mpc-autofill) `order.xml`
entgegen, lädt für jede referenzierte Karte das Bild von Google Drive und
druckt für **jede physische Kopie** (jeden Slot) ein eigenes Label mit dem
Kartenbild auf einem Phomemo-M110-Labeldrucker – über Bluetooth LE, mittels
[pyphomemo](https://github.com/mkuhlmann/pyphomemo).

## Installation

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .
```

`pyphomemo` ist nicht auf PyPI und wird direkt von GitHub installiert
(steht in `pyproject.toml`). Es bringt `bleak` (BLE) und `Pillow` (Rendering)
mit, zusätzlich wird `gdown` für den Google-Drive-Download installiert.

## Drucker koppeln / Adresse finden

```bash
./.venv/bin/thermal-deck scan
```

Listet nahegelegene BLE-Geräte inkl. erkannter Phomemo-Drucker mit ihrer
Bluetooth-MAC-Adresse auf. Die Adresse dann per `--addr` übergeben oder als
Umgebungsvariable setzen:

```bash
export PHOMEMO_ADDR="12:CB:A3:08:0F:34"
```

## Karten aus der XML auflisten (ohne zu drucken)

```bash
./.venv/bin/thermal-deck list bestellung.xml
```

## Labels drucken

```bash
./.venv/bin/thermal-deck print bestellung.xml --label 40x30
```

Für jedes `<card>`-Element in `<fronts>` wird zuerst das Bild von Google Drive
geladen (einmal pro Kartendesign, danach aus dem Cache) und dann **für jeden
Eintrag in `<slots>` ein eigenes Label mit dem Kartenbild** gedruckt – bei
`slots=4,5,6` also dreimal dasselbe Bild-Label. Schlägt der Download fehl
(z. B. Datei nicht mehr "Jeder mit Link" freigegeben, oder Google-Drive-Limit
erreicht), wird stattdessen ein Text-Label mit dem Kartennamen gedruckt und
eine Warnung ausgegeben – der Lauf bricht dafür nicht ab. Optionen:

- `--addr MAC` – Bluetooth-Adresse des M110 (sonst `PHOMEMO_ADDR` oder
  Auto-Scan).
- `--label 40x30` – Labelgröße in mm (Breite x Höhe). Maximalbreite des M110:
  48 mm (384 Dots), auch wenn eine breitere Rolle (z. B. 57 mm) eingelegt ist –
  der Druckkopf selbst ist nur 48 mm breit, der Rest bleibt weiß. Höhe `0`
  (z. B. `--label 48x0`) = Höhe folgt automatisch dem Seitenverhältnis des
  Kartenbilds, kein Zuschnitt auf eine feste Boxgröße.
- `--continuous` – **bei einer Endlosrolle ohne vorgestanzte Lücken/Marken
  unbedingt setzen.** Ohne dieses Flag nimmt der Drucker an, dass er
  vorgestanzte Etiketten mit Lücken-Sensor bedruckt, und kann beim
  Papiervorschub falsch takten.
- `--no-fit` – Bild nur auf Labelbreite skalieren statt in die volle
  `BxH`-Box einzupassen (Default: eingepasst, mit weißen Rändern zentriert).
- `--threshold 0-255` – fester Schwarz/Weiß-Schwellwert statt
  Floyd-Steinberg-Dithering (Default: Dithering, meist besser für Kartenkunst).
- `--font-size 32`, `--align center|left|right` – nur für den Text-Fallback.
- `--include-backs` – druckt zusätzlich Labels für individuelle
  Kartenrückseiten aus `<backs>` (die generische `<cardback>` wird ignoriert,
  da sie für alle Karten gleich ist).
- `--sort name` – alphabetisch statt in XML-Reihenfolge drucken.
- `--cache-dir VERZEICHNIS` – wohin heruntergeladene Bilder gecacht werden
  (Default: `.thermal-deck-cache` neben der XML). Bei mehreren Läufen mit
  derselben XML werden Bilder nicht erneut heruntergeladen.
- `--dry-run VERZEICHNIS` – druckt nicht, sondern schreibt PNG-Vorschauen der
  Labels in das angegebene Verzeichnis (kein Drucker nötig, gut zum Testen).
- `--delay 0.5` – Pause zwischen zwei Labels in Sekunden.

**Hinweis zu Google Drive:** Die Bilder werden nur heruntergeladen, wenn die
jeweilige Datei mit "Jeder mit Link" freigegeben ist (Standard bei
MPC-Autofill-Bild-Repos). Bei sehr großen Decks kann Google Drive den
Zugriff über `gdown` temporär drosseln ("have had many accesses") – der Cache
sorgt zumindest dafür, dass bereits geladene Bilder bei einem erneuten Lauf
nicht nochmal geholt werden müssen.

## Wie es funktioniert

- **MPC-Autofill-XML**: `<order><fronts><card>` enthält je ein Kartendesign
  mit `id` (Google-Drive-ID oder lokaler Pfad), `sourceType`, `name`, `query`
  und `slots` (kommagetrennte Slot-Indizes – ein Eintrag pro physischer
  Kopie im Deck). `src/thermal_deck/mpcfill.py` parst das reine XML.
- **Bild-Download**: `src/thermal_deck/images.py` lädt Google-Drive-Einträge
  per `gdown.download(id=...)` (folgt automatisch dem Bestätigungs-Token-Flow,
  den Google für größere Dateien verlangt) und cacht sie lokal unter der
  Drive-ID als Dateiname. `sourceType == "Local File"` liest stattdessen
  direkt von der Festplatte.
- **Phomemo M110**: 203 dpi / 8 Dots pro mm, verbindet sich per Bluetooth LE
  (GATT-Service `0xff00`, Write-Characteristic `0xff02`), Daten werden in
  128-Byte-Chunks als ESC/POS-artige Rasterbefehle gestreamt. `pyphomemo`
  kapselt das komplett; wir rendern Kartenbild (oder Text-Fallback) mit
  Pillow zu einem 1-Bit-Raster (`image_to_raster` / `text_to_raster`) und
  schicken es über eine offene `PhomemoPrinter`-Verbindung.
