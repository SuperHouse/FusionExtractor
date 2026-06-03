# FusionExtractor

Python library for extracting resources from Autodesk Fusion Electronics `.f3z` project files.

## Project layout

```
fusionextractor/
  __init__.py      # exports FusionProject, FusionExtractorError, FileNotFoundInArchiveError
  f3z.py           # FusionProject dataclass — all extraction logic lives here
  exceptions.py    # FusionExtractorError, FileNotFoundInArchiveError
examples/
  extract.py       # runnable example: python examples/extract.py <file.f3z>
AQS-v4_1.f3z      # sample file for manual testing
```

## .f3z file format

A `.f3z` is a ZIP archive containing four nested ZIPs (also ZIP-format, with custom extensions) plus two JSON metadata files:

```
root.f3z
├── Manifest.json
├── DesignDescription.json
├── {uuid}.fprj   — electronics project (ZIP)
├── {uuid}.f3d    — 3D model (ZIP)
├── {uuid}.fsch   — schematic (ZIP)
│   └── {active_folder}/electron.BlobParts/ExtFile.{uuid}.sch
└── {uuid}.fbrd   — PCB board (ZIP)
    └── {active_folder}/electron.BlobParts/ExtFile.{uuid}.brd
```

The `{active_folder}` name (e.g. `"Schematic Document Asset[Active]"`) varies between files, so all lookups use suffix-matching, never hardcoded paths.

Preview images:
- Every nested ZIP: `{active_folder}/Previews/small.png` (thumbnail)
- `.fprj` and `.f3d` only: `{active_folder}/Images.BlobParts/Image.{uuid}.png` (large renders)

## Public API

```python
from fusionextractor import FusionProject

with FusionProject("design.f3z") as proj:
    proj.design_name                              # str
    proj.get_schematic() -> bytes
    proj.get_board() -> bytes
    proj.get_previews(include_large_images=True)  # list[PreviewImage]

    proj.extract_schematic(dest)   # dest = dir path or file path; returns Path
    proj.extract_board(dest)
    proj.extract_previews(dest, include_large_images=True)  # returns list[Path]
```

`PreviewImage` fields: `source` (str label), `path` (path inside nested archive), `data` (bytes).

## Key implementation details

- `FusionProject` is a `@dataclass`; `__enter__`/`__exit__` open and close the root ZIP.
- `_nested_zip(extension)` reads a nested archive into a `BytesIO` buffer and returns a `ZipFile` — avoids temp files.
- `_write()` treats `dest` as a directory (creates it) when the path ends with `/`, is already a directory, or has no file extension. Otherwise treats it as the output file path.
- No required third-party dependencies — stdlib only by default (`zipfile`, `json`, `io`, `pathlib`).
- The `.f3d` archive uses **Zstandard compression (type 93)**, which stdlib `zipfile` does not support. `f3z.py` attempts `import zipfile_zstd` at startup; if present it patches `zipfile` globally and zstd entries work transparently. Preview entries that still can't be decompressed are silently skipped in `get_previews()`. Install the optional extra for full support: `pip install -e ".[zstd]"`.

## Testing

Use the sample file for manual testing:

```bash
python examples/extract.py examples/IOMOD-AD5593R-v2_0.f3z
```

Or inline:

```bash
python3 -c "
from fusionextractor import FusionProject
with FusionProject('examples/IOMOD-AD5593R-v2_0.f3z') as p:
    print(p.design_name)
    print(len(p.get_schematic()), 'bytes')
    print(len(p.get_board()), 'bytes')
    print([(x.source, len(x.data)) for x in p.get_previews()])
"
```
