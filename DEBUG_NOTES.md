# Debug notes: multi-label printing on the M110 (resolved)

## Symptom

```bash
thermal-deck print "cards(2).xml"
```

- Job 1 (e.g. "Sol Ring") printed correctly.
- After the delay, job 2 (e.g. "Black Lotus") only fed a short strip of
  paper - **no** printed image, **no** error/exception in the terminal. The
  process exited normally (exit code 0).

This also showed up as the *last* job in a batch never printing, or (when
testing a single card in isolation) as no job printing at all.

## Root cause

`cmd_print` only slept `--delay` seconds *between* jobs:

```python
await printer.print_raster(raster, height, width_bytes=width_px // 8, media=media)
if i < len(jobs):
    await asyncio.sleep(args.delay)
```

`print_raster()` returns as soon as the raster data has been written over
BLE - the print head still needs real time afterwards to mechanically finish
printing and eject the label. The `if i < len(jobs)` guard skipped that wait
for the *last* job in the batch, right before `async with PhomemoPrinter(...)`
closed the connection. Closing the BLE connection while the head was still
mid-print aborted the physical print (short paper feed, no image, no
exception - the abort happens on the printer's mechanics, invisible to BLE).

This explains every earlier observation:
- Job 1 in a multi-job run always had the trailing delay before job 2 started
  (connection stayed open) -> always finished printing.
- The last job in any run never got that delay -> always cut off.
- A reconnect-per-job approach made things worse: every job became "the last
  job" of its own connection -> all of them got cut off, including job 1.
- A single combined image (one job, but taller) failed completely for the
  same reason - it's still "the last job".
- Testing a lone card in an isolated single-card XML always failed too, for
  the same reason - a lone job is also "the last job".
- The earlier `--delay 10` test (between jobs) didn't help because it never
  touched the one job that needed the wait.

## Fix

Wait `--delay` seconds after *every* `print_raster()` call, including the
last one, before the connection closes (`src/thermal_deck/cli.py::cmd_print`).
Default raised from 3.0s to 5.0s, since the second job in a run needs
noticeably longer than the first (the head is already warm).

## Follow-up: card frame

MPC-Autofill card images print with the card's own black border filling a
large share of a 48mm-wide label. Added `--crop-pct` (default 8, matches the
~6-9%-per-edge border measured on Sol Ring / Black Lotus) to crop that
margin before scaling, so name/art fill the label width instead.
