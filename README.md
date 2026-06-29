# FusionExtractor

A Python library for extracting resources from Autodesk Fusion Electronics `.f3z` project files.

## Overview

`.f3z` files are ZIP archives that embed multiple nested archives containing schematic (`.sch`), PCB (`.brd`), and preview image data. FusionExtractor unpacks these without any third-party dependencies.

## Installation

```bash
pip install fusionextractor                  # stdlib only
pip install "fusionextractor[zstd]"          # adds Zstandard support for 3D model previews
```

## Examples

A sample Fusion Electronics project is included in `examples/IOMOD-AD5593R_v2_0.f3z` for 
use by automatic tests and for you to use when trying out the library.

To run `examples/extract.py`, open a terminal in the library folder and type:

```
pip install -e ".[zstd]"
python examples/extract.py examples/IOMOD-AD5593R-v2_0.f3z
```

This will create a new folder called `output` in the current directory, and extract various 
assets from the sample project into it. Check the source of `extract.py` to see the 
options it uses relating to output filenames, etc.

## Usage

```python
from fusionextractor import FusionProject

with FusionProject("design.f3z") as proj:
    # Read the design name from embedded metadata
    print(proj.design_name)

    # Get raw bytes
    sch_bytes = proj.get_schematic()   # Eagle .sch file
    brd_bytes = proj.get_board()       # Eagle .brd file
    previews   = proj.get_previews()    # list[PreviewImage]
    bom        = proj.get_bom()         # list[BomEntry]
    placements = proj.get_placements()  # list[PlacementEntry]

    # Extract to disk
    proj.extract_schematic("output/")           # writes original filename into output/
    proj.extract_board("output/my_board.brd")   # writes to exact path
    proj.extract_previews("output/previews/")   # writes all preview PNGs
    proj.extract_bom("output/")                 # writes {design_name}_bom.csv
    proj.extract_placements_kicad("output/")    # writes {design_name}.pos
    proj.extract_placements_eagle("output/")    # writes {design_name}.mnt and {design_name}.mnb

    # Extract named board images
    proj.extract_board_image("schematic",    "output/")   # {design_name}_schematic.png
    proj.extract_board_image("pcb_top",      "output/")   # {design_name}_pcb_top.png
    proj.extract_board_image("pcb_3d_top",   "output/")   # {design_name}_pcb_3d_top.png
    proj.extract_board_image("pcb_3d_bottom","output/")   # {design_name}_pcb_3d_bottom.png
```

### Destination path behaviour

`extract_schematic` and `extract_board` accept an optional `dest` argument:

| `dest` value | Result |
|---|---|
| `None` (default) | Written to the current directory, original filename preserved |
| A directory path or path ending with `/` | Original filename preserved inside that directory |
| A full file path (with extension) | Written to that exact path |

### Board images

`get_board_image` and `extract_board_image` retrieve specific named views of the board:

| `view_type` | Content |
|---|---|
| `"schematic"` | Schematic diagram (one or more pages) |
| `"pcb_top"` | PCB top-layer 2D layout |
| `"pcb_3d_top"` | 3D render from the top |
| `"pcb_3d_bottom"` | 3D render from the bottom |

```python
top_png    = proj.get_board_image("pcb_3d_top")    # returns bytes
bottom_png = proj.get_board_image("pcb_3d_bottom")

proj.extract_board_image("pcb_3d_top", "output/")  # writes {design_name}_pcb_3d_top.png
proj.extract_board_image("pcb_3d_top", "render.png")  # writes to exact path
```

### Preview images

`get_previews` and `extract_previews` return all images from all nested archives, including small thumbnails and the large renders above.  Each `PreviewImage` has a `view_type` field populated automatically.

Pass `include_large_images=False` to retrieve thumbnails only.

```python
for preview in proj.get_previews(include_large_images=False):
    print(preview.source, len(preview.data), "bytes")
    # e.g. "schematic 4821 bytes"
```

`PreviewImage` fields:

| Field | Type | Description |
|---|---|---|
| `source` | `str` | Archive the image came from (`"schematic"`, `"board"`, `"project"`, `"3d_model"`) |
| `path` | `str` | Path of the image inside the nested archive |
| `data` | `bytes` | Raw PNG bytes |
| `view_type` | `str \| None` | `"schematic"`, `"pcb_top"`, `"pcb_3d_top"`, `"pcb_3d_bottom"`, or `"thumbnail"` |

Extracted preview files are named `{source}__{original_filename}` to avoid collisions when multiple archives contain a `small.png`.

## API reference

```python
class FusionProject:
    path: str | Path                                          # path to the .f3z file

    design_name: str                                          # property; from embedded metadata

    def get_schematic() -> bytes
    def get_board() -> bytes
    def get_previews(*, include_large_images: bool = True) -> list[PreviewImage]
    def get_board_image(view_type: str) -> bytes              # "schematic"|"pcb_top"|"pcb_3d_top"|"pcb_3d_bottom"
    def get_bom(*, include_power_symbols: bool = False) -> list[BomEntry]
    def get_placements() -> list[PlacementEntry]

    def extract_schematic(dest=None) -> Path
    def extract_board(dest=None) -> Path
    def extract_previews(dest=None, *, include_large_images: bool = True) -> list[Path]
    def extract_board_image(view_type: str, dest=None) -> Path
    def extract_bom(dest=None, *, include_power_symbols: bool = False) -> Path
    def extract_placements_kicad(dest=None) -> Path
    def extract_placements_eagle(dest=None) -> tuple[Path, Path]
```

### BOM

`get_bom` parses the component list from the embedded schematic.  Supply/power symbols
(GND, VCC, NC, etc.) are excluded by default; pass `include_power_symbols=True` to
include them.

```python
for entry in proj.get_bom():
    print(entry.reference, entry.device, entry.package, entry.value)
    # e.g. "C1  CAP  0603  100nF"
```

`BomEntry` fields:

| Field | Type | Description |
|---|---|---|
| `reference` | `str` | Reference designator (`"C1"`, `"U1"`) |
| `device` | `str` | Component type / part number base (`"CAP"`, `"AD5593R"`) |
| `package` | `str` | Footprint / package (`"0603"`, `"TSSOP16"`) |
| `value` | `str` | Component value (`"100nF"`, `"10K"`) — empty string when not set |
| `library` | `str` | Eagle library name (`"SuperHouse-Capacitors"`) |

`extract_bom` writes the BOM as a CSV file named `{design_name}_bom.csv`.

### Placements

`get_placements` parses component placement data (position, rotation, side) from the
embedded board.

```python
for entry in proj.get_placements():
    print(entry.reference, entry.x, entry.y, entry.rotation, entry.side)
    # e.g. "R1  6.0  4.0  90.0  top"
```

`PlacementEntry` fields:

| Field | Type | Description |
|---|---|---|
| `reference` | `str` | Reference designator (`"R1"`, `"U1"`) |
| `value` | `str` | Component value (`"100nF"`, `"10K"`) — empty string when not set |
| `package` | `str` | Footprint (`"C0603"`, `"TSSOP16"`) |
| `x` | `float` | X position in mm, Eagle's native board coordinates (Y increasing upward) |
| `y` | `float` | Y position in mm, Eagle's native board coordinates (Y increasing upward) |
| `rotation` | `float` | Rotation in degrees (0-360) |
| `side` | `str` | `"top"` or `"bottom"` |

Two extraction formats are available:

* `extract_placements_kicad` writes a single KiCad-format `.pos` file covering both sides.
  Because KiCad's PCB editor uses a Y-increases-downward axis while Eagle uses
  Y-increases-upward, `PosY` is the negation of `PlacementEntry.y`.
* `extract_placements_eagle` writes a pair of Eagle `mount.ulp`-format files split by side:
  `{design_name}.mnt` (top) and `{design_name}.mnb` (bottom). X/Y are written unchanged.

```python
proj.extract_placements_kicad("output/")        # output/{design_name}.pos
mnt_path, mnb_path = proj.extract_placements_eagle("output/")  # .mnt + .mnb
```

## Exceptions

| Exception | Raised when |
|---|---|
| `FileNotFoundError` | The `.f3z` file path does not exist |
| `FusionExtractorError` | The file is not a valid ZIP/f3z archive |
| `FileNotFoundInArchiveError` | A required entry is missing from inside the archive |

Both custom exceptions are subclasses of `FusionExtractorError` and are importable from the package root:

```python
from fusionextractor import FusionExtractorError, FileNotFoundInArchiveError
```

## Requirements

Python 3.9+. No required third-party dependencies.

The `.f3d` archive (3D model) uses Zstandard compression, which Python's stdlib `zipfile` does not support. Without the optional extra, 3D model previews are silently skipped. Install `.[zstd]` to enable them.
