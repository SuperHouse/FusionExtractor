# Changes

## 1.3.0

- Added `get_placements()` and the `PlacementEntry` dataclass — parses component
  placement data (reference, value, package, X/Y position, rotation, top/bottom
  side) from the embedded board.
- Added `extract_placements_kicad()` — writes a single KiCad-format `.pos` file
  covering both sides. `PosY` is the negation of the native Eagle Y coordinate
  to account for the axis direction difference between the two tools.
- Added `extract_placements_eagle()` — writes a pair of Eagle `mount.ulp`-format
  files split by side: `{design_name}.mnt` (top) and `{design_name}.mnb` (bottom).
- Exported `.pos`, `.mnt`, and `.mnb` files now include a header line crediting
  FusionExtractor and its version, e.g. `### Printed by FusionExtractor V1.3.0
  in KiCad V8.0 format`.

## 1.2.0

- Added explicit methods for extracting named board views: `get_board_image()`
  and `extract_board_image()`, covering `"schematic"`, `"pcb_top"`,
  `"pcb_3d_top"`, and `"pcb_3d_bottom"`.
- Large preview images are now automatically classified by view type using ZIP
  metadata (compression ratio and PNG colour type) rather than left unlabelled.
- Added project URLs (homepage, repository, bug tracker) to package metadata.

## 1.1.0

- Added `get_bom()` and `extract_bom()` for extracting the Bill of Materials
  from the embedded schematic, with the `BomEntry` dataclass. Supply/power
  symbols are excluded by default.
- Packaging changes in preparation for publishing to PyPI (`MANIFEST.in`,
  expanded `pyproject.toml` metadata).

## 1.0.0

- First stable release: extraction of the schematic (`.sch`), board (`.brd`),
  and preview images (`PreviewImage`) from `.f3z` archives.
- Added Zstandard decompression support (optional `zipfile_zstd` dependency)
  for the 3D model archive.
- Added the BSD 3-clause license, integration test suite, and example script.

## 0.1.0

- Initial import: `FusionProject`, exception types, and `pyproject.toml`
  packaging setup.
