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
    sch_bytes = proj.get_schematic()   # Eagle/KiCad .sch file
    brd_bytes = proj.get_board()       # Eagle/KiCad .brd file
    previews  = proj.get_previews()    # list[PreviewImage]

    # Extract to disk
    proj.extract_schematic("output/")           # writes original filename into output/
    proj.extract_board("output/my_board.brd")   # writes to exact path
    proj.extract_previews("output/previews/")   # writes all preview PNGs
```

### Destination path behaviour

`extract_schematic` and `extract_board` accept an optional `dest` argument:

| `dest` value | Result |
|---|---|
| `None` (default) | Written to the current directory, original filename preserved |
| A directory path or path ending with `/` | Original filename preserved inside that directory |
| A full file path (with extension) | Written to that exact path |

### Preview images

`get_previews` and `extract_previews` return images from all four nested archives:

- `small.png` — thumbnail present in every nested archive (schematic, board, project, 3D model)
- Large PNG renders — present in the project (`.fprj`) and 3D model (`.f3d`) archives only

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

Extracted preview files are named `{source}__{original_filename}` to avoid collisions when multiple archives contain a `small.png`.

## API reference

```python
class FusionProject:
    path: str | Path                                          # path to the .f3z file

    design_name: str                                          # property; from embedded metadata

    def get_schematic() -> bytes
    def get_board() -> bytes
    def get_previews(*, include_large_images: bool = True) -> list[PreviewImage]

    def extract_schematic(dest=None) -> Path
    def extract_board(dest=None) -> Path
    def extract_previews(dest=None, *, include_large_images: bool = True) -> list[Path]
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
