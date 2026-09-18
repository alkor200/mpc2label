# mpc2label

Prints identification labels for physical *Magic: The Gathering* proxy
cards straight from an [MPC-Autofill](https://github.com/chilli-axe/mpc-autofill)
`order.xml` - the same order file MPC-Autofill uses to send your deck off for
printing. mpc2label reads that file, downloads the image for each referenced
card from Google Drive, and prints a separate label with the card image for
**every physical copy** (every slot) on a Phomemo M110 label printer - over
Bluetooth LE, using [pyphomemo](https://github.com/mkuhlmann/pyphomemo).

## Installation

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .
```

`pyphomemo` isn't on PyPI and is installed straight from GitHub (see
`pyproject.toml`). It pulls in `bleak` (BLE) and `Pillow` (rendering); `gdown`
is installed separately for the Google Drive downloads.

## Pairing the printer / finding its address

```bash
./.venv/bin/mpc2label scan
```

Lists nearby BLE devices, flagging any detected Phomemo printers along with
their Bluetooth MAC address. Pass that address via `--addr`, or set it as an
environment variable:

```bash
export PHOMEMO_ADDR="12:CB:A3:08:0F:34"
```

## Listing the cards in the XML (without printing)

```bash
./.venv/bin/mpc2label list order.xml
```

## Printing labels

```bash
./.venv/bin/mpc2label print order.xml
```

For each `<card>` element in `<fronts>`, the image is first downloaded from
Google Drive (once per card design, then served from the cache), and then
**one label with the card image is printed for every entry in `<slots>`** -
e.g. `slots=4,5,6` prints the same image label three times. If the download
fails (e.g. the file is no longer shared "Anyone with the link", or a Google
Drive rate limit kicks in), a text label with the card name is printed
instead and a warning is shown - the run doesn't abort.

Printing always uses the **full printer width** (48 mm / 384 dots, even if a
wider roll such as 57 mm is loaded - the print head itself is only 48 mm
wide, the rest stays blank) and **continuous-roll media mode** (not the
gap-sensor mode for pre-cut labels) - this is fixed to match our continuous-
roll hardware, and neither is configurable. Each label's height follows the
aspect ratio of the (cropped) card image automatically. Options:

- `--addr MAC` - Bluetooth address of the M110 (otherwise `PHOMEMO_ADDR` or
  auto-scan).
- `--crop-pct 8` - before scaling, crops this percentage of width/height off
  every edge of the card image (default: 8, removes the black card frame on
  MPC-Autofill images so the name/art fill the full label width). `0` = no
  crop, full card image.
- `--threshold 0-255` - fixed black/white threshold instead of
  Floyd-Steinberg dithering (default: dithering, usually looks better for
  card art).
- `--font-size 32`, `--align center|left|right` - only used for the text
  fallback.
- `--include-backs` - also prints labels for individual card backs from
  `<backs>` (the generic `<cardback>` is ignored since it's the same for
  every card).
- `--sort name` - print alphabetically instead of in XML order.
- `--cache-dir DIRECTORY` - where downloaded images are cached (default:
  `.mpc2label-cache` next to the XML). Images aren't re-downloaded on
  repeated runs with the same XML.
- `--dry-run DIRECTORY` - instead of printing, writes PNG previews of the
  labels to the given directory (no printer needed, good for testing).
- `--delay 5.0` - pause after **every** label (including the last) in
  seconds, before the next job is sent or the BLE connection is closed.
  `print_raster()` returns as soon as the data has been sent - the print
  head still needs time afterwards to mechanically finish printing and eject
  the label. If the connection is closed while that's happening, the
  physical print aborts (a short paper feed, no image, no exception). Raise
  this if a label comes out incomplete, especially for larger/darker labels.

**Note on Google Drive:** images are only downloaded if the file is shared
"Anyone with the link" (the default for MPC-Autofill image repos). For very
large decks, Google Drive may temporarily throttle access via `gdown`
("have had many accesses") - the cache at least ensures already-downloaded
images aren't fetched again on a re-run.

## How it works

- **MPC-Autofill XML**: `<order><fronts><card>` contains one card design per
  entry, with `id` (Google Drive ID or local path), `sourceType`, `name`,
  `query`, and `slots` (comma-separated slot indices - one entry per
  physical copy in the deck). `src/mpc2label/mpcfill.py` parses the plain
  XML.
- **Image download**: `src/mpc2label/images.py` downloads Google Drive
  entries via `gdown.download(id=...)` (which automatically follows the
  confirmation-token flow Google requires for larger files) and caches them
  locally under the Drive ID as filename. `sourceType == "Local File"`
  reads directly from disk instead.
- **Phomemo M110**: 203 dpi / 8 dots per mm, connects over Bluetooth LE
  (GATT service `0xff00`, write characteristic `0xff02`), data is streamed
  in 128-byte chunks as ESC/POS-style raster commands. `pyphomemo` wraps all
  of that; we render the card image (or text fallback) with Pillow into a
  1-bit raster (`image_to_raster` / `text_to_raster`) and send it over one
  open `PhomemoPrinter` connection.

## Acknowledgements

- [MPC-Autofill](https://github.com/chilli-axe/mpc-autofill) for the
  `order.xml` format and the whole proxy-printing workflow this tool builds
  on top of.
- [pyphomemo](https://github.com/mkuhlmann/pyphomemo) for the Phomemo M110
  Bluetooth LE protocol implementation that does all the actual printing.
