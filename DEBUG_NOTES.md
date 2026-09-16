# Debug-Stand: Mehrfachdruck auf dem M110

Stand: 2026-09-16. Tool funktioniert grundsätzlich (XML-Parsing, Google-Drive-
Bild-Download, Rendering, `--dry-run`). Offenes Problem: **beim Drucken von
mehr als einem Label in einem Lauf wird nur das erste Label physisch
gedruckt.**

## Symptom

```bash
thermal-deck print "cards(2).xml" --label 48x0
```

- Job 1 (z. B. "Sol Ring") druckt korrekt.
- Nach der Wartezeit (`--delay`, aktuell Default 3.0s) wird für Job 2
  (z. B. "Black Lotus") nur ein kurzes Stück Papier eingezogen — **kein**
  Druckbild, **keine** Fehlermeldung/Exception im Terminal. Der Prozess
  beendet sich normal (Exit-Code 0).

## Bereits ausgeschlossen

1. **Verbindungsabbruch/Exception** — nicht die Ursache. Es gibt keinen
   Traceback, `print_raster()` für Job 2 kehrt ohne Fehler zurück.
2. **Media-Modus (`--continuous` vs. Default `MEDIA_LABEL_WITH_GAPS`)** —
   macht keinen Unterschied. Beide Modi zeigen exakt das gleiche Verhalten
   (Job 1 ok, Job 2 nur Mini-Feed).
3. **Kurze Pause zwischen Jobs (0.5s)** — schon auf 3.0s erhöht, kein
   Unterschied.
4. **Reconnect pro Job** (statt einer offenen Verbindung für den ganzen
   Batch) — *verschlechtert* das Verhalten sogar: dabei wurde teils **gar
   kein** Label mehr gedruckt (auch Job 1 nicht). Vermutlich weil zu schnell
   nach dem Trennen neu verbunden wurde (M110 braucht laut `pyphomemo`-Code
   nach einem Druck kurz Zeit, bevor BLE wieder zuverlässig verbindbar ist —
   siehe `printer.py`-Docstring in der pyphomemo-Quelle:
   "Connecting again right after a print often fails on BlueZ with
   br-connection-profile-unavailable"). Dieser Ansatz wurde daher wieder
   zurückgebaut auf eine einzige offene Verbindung für den ganzen Batch
   (aktueller Stand in `cli.py::cmd_print`).

## Offene Hypothesen (noch nicht final verifiziert)

- **Rein mechanisches Timing**: Das Kartenbild ist bei 48mm Breite recht
  hoch (~65-70mm bei MTG-Seitenverhältnis). Der Thermokopf braucht dafür
  eventuell länger als die aktuellen 3s, um Job 1 komplett zu drucken +
  auszuwerfen, bevor er für Job 2 bereit ist. **Nächster Test (noch nicht
  durchgeführt/Ergebnis noch nicht bekannt):**

  ```bash
  thermal-deck print "cards(2).xml" --label 48x0 --delay 10
  ```

  Falls das Job 2 zum Drucken bringt: reines Timing-Problem, dann Default
  hochsetzen bzw. adaptiv nach Bildhöhe berechnen.

- Falls auch 10s nicht reichen: vermutlich braucht der M110 zwischen zwei
  Druckjobs auf derselben Verbindung einen expliziten Reset (`ESC @` /
  `0x1b 0x40`) oder es muss auf eine "ready"-Notification von der
  `NOTIFY_CHAR_UUID` (0xff03) gewartet werden, bevor der nächste Job
  gesendet wird. `pyphomemo`s `PhomemoPrinter` abonniert diese Notify-
  Characteristic bereits intern (`self._notifications`), wertet sie aber
  nicht aus. Wäre der nächste Ansatz: nach `print_raster()` auf eine
  Notification warten (oder ein festes, aber ausreichend langes Timeout),
  bevor der nächste Job gestartet wird.

- Alternativ: Reconnect-pro-Job nochmal versuchen, aber dieses Mal mit
  **spürbarer Pause zwischen Trennen und Neuverbinden** (z. B. 3-5s), nicht
  nur zwischen den Druckjobs selbst. Beim letzten Versuch gab es dafür keine
  extra Pause.

- Laut offiziellem Phomemo-Support-Artikel
  ("Label Printer is skipping labels or continuously feeding") kann der
  Drucker bei nicht "gelerntem" Etikettentyp/-Lücke verwirrt feeden. Bezieht
  sich primär auf USB/Windows-Treiber-Workflow, aber falls nichts anderes
  hilft: physische Kalibrierung am Gerät probieren (Feed-Taste einige
  Sekunden gedrückt halten, laut M110-Handbuch positioniert das Gerät
  Etiketten/Lücken neu).

## Code-Stand

- `src/thermal_deck/cli.py::cmd_print` — eine offene `PhomemoPrinter`-
  Verbindung für den ganzen Batch, `--delay` (Default 3.0s) zwischen Jobs,
  `--continuous`-Flag für Media-Modus (aktuell ohne nachgewiesenen Effekt).
- `src/thermal_deck/images.py` — Google-Drive-Download via `gdown`,
  funktioniert nachweislich (siehe `.thermal-deck-cache/` bzw. Test mit der
  echten Beispiel-ID aus dem MPC-Autofill-Wiki).
- `src/thermal_deck/mpcfill.py` — XML-Parser, funktioniert.
- Getestet mit `cards(2).xml` (echte Bestellung des Nutzers, 2 Karten: Sol
  Ring, Black Lotus) und `examples/order.xml` (Beispiel aus der
  MPC-Autofill-Doku).
- Drucker: Phomemo M110, Bluetooth LE, Endlosrolle 57mm breit (Druckkopf
  physisch nur 48mm/384 Dots breit, Rest bleibt weiß — normal).

## Nächster Schritt

`--delay 10` testen (siehe oben), Ergebnis hier eintragen bzw. mit den
Hypothesen weiterarbeiten.
