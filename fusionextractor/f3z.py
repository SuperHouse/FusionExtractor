"""
FusionProject: opens Autodesk Fusion Electronics .f3z files and extracts embedded resources.

.f3z structure:
  Root ZIP
  ├── Manifest.json
  ├── DesignDescription.json
  ├── {uuid}.fprj  (electronics project — also a ZIP)
  ├── {uuid}.f3d   (3D model — also a ZIP)
  ├── {uuid}.fsch  (schematic — also a ZIP)
  │   └── {name}[Active]/electron.BlobParts/ExtFile.{uuid}.sch
  └── {uuid}.fbrd  (PCB board — also a ZIP)
      └── {name}[Active]/electron.BlobParts/ExtFile.{uuid}.brd

Preview images live at:
  {name}[Active]/Previews/small.png  (in every nested ZIP)
  {name}[Active]/Images.BlobParts/Image.{uuid}.png  (in .fprj and .f3d)
"""

from __future__ import annotations

import csv
import io
import json
import os
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

try:
    import zipfile_zstd  # noqa: F401 — registers zstd (type 93) with zipfile when present
except ImportError:
    pass

from .exceptions import FileNotFoundInArchiveError, FusionExtractorError


@dataclass
class BomEntry:
    reference: str    # reference designator, e.g. "C1"
    device: str       # component type (Eagle deviceset), e.g. "CAP", "AD5593R"
    package: str      # footprint (Eagle device variant), e.g. "0603", "TSSOP16"
    value: str        # component value, e.g. "100nF" — empty string when not set
    library: str      # Eagle library name, e.g. "SuperHouse-Capacitors"


@dataclass
class PreviewImage:
    source: str       # which nested archive it came from, e.g. "schematic", "board"
    path: str         # path inside the nested archive
    data: bytes


@dataclass
class FusionProject:
    """
    Opens a .f3z Fusion Electronics project file.

    Usage::

        with FusionProject("design.f3z") as proj:
            proj.extract_schematic("output.sch")
            proj.extract_board("output.brd")
            proj.extract_previews("previews/")
    """

    path: str | os.PathLike

    _root_zip: zipfile.ZipFile = field(init=False, repr=False)
    _manifest: dict = field(init=False, repr=False)
    _description: dict = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if not self.path.exists():
            raise FileNotFoundError(f"File not found: {self.path}")
        if not zipfile.is_zipfile(self.path):
            raise FusionExtractorError(f"Not a valid ZIP/f3z file: {self.path}")

    def __enter__(self) -> FusionProject:
        self._root_zip = zipfile.ZipFile(self.path, "r")
        self._manifest = json.loads(self._root_zip.read("Manifest.json"))
        self._description = json.loads(self._root_zip.read("DesignDescription.json"))
        return self

    def __exit__(self, *_) -> None:
        self._root_zip.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _nested_zip(self, extension: str) -> zipfile.ZipFile:
        """Return the first nested ZIP whose name ends with *extension*."""
        for name in self._root_zip.namelist():
            if name.lower().endswith(extension.lower()):
                data = self._root_zip.read(name)
                return zipfile.ZipFile(io.BytesIO(data), "r")
        raise FileNotFoundInArchiveError(
            f"No {extension!r} entry found in {self.path.name}"
        )

    def _nested_zips(self) -> Iterator[tuple[str, zipfile.ZipFile]]:
        """Yield (label, nested_zip) for each known nested archive type."""
        for ext, label in [(".fsch", "schematic"), (".fbrd", "board"),
                           (".fprj", "project"), (".f3d", "3d_model")]:
            try:
                yield label, self._nested_zip(ext)
            except FileNotFoundInArchiveError:
                pass

    @staticmethod
    def _find_in_zip(zf: zipfile.ZipFile, suffix: str) -> str | None:
        """Return the first entry name that ends with *suffix*, or None."""
        suffix_lower = suffix.lower()
        for name in zf.namelist():
            if name.lower().endswith(suffix_lower):
                return name
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def design_name(self) -> str:
        return self._description.get("dataVersion", {}).get("name", self.path.stem)

    def get_schematic(self) -> bytes:
        """Return the raw bytes of the embedded .sch file."""
        fsch = self._nested_zip(".fsch")
        entry = self._find_in_zip(fsch, ".sch")
        if entry is None:
            raise FileNotFoundInArchiveError("No .sch file found inside .fsch archive")
        return fsch.read(entry)

    def get_board(self) -> bytes:
        """Return the raw bytes of the embedded .brd file."""
        fbrd = self._nested_zip(".fbrd")
        entry = self._find_in_zip(fbrd, ".brd")
        if entry is None:
            raise FileNotFoundInArchiveError("No .brd file found inside .fbrd archive")
        return fbrd.read(entry)

    def get_previews(self, *, include_large_images: bool = True) -> list[PreviewImage]:
        """
        Return all preview images across all nested archives.

        Each nested archive contains a small thumbnail at
        ``{name}[Active]/Previews/small.png``.  The .fprj and .f3d archives
        additionally contain larger PNG images under ``Images.BlobParts/``.

        Parameters
        ----------
        include_large_images:
            When True (default) include the large ``Images.BlobParts`` PNGs
            from the project and 3D-model archives.  Set to False to get only
            the small ``Previews/small.png`` thumbnails.
        """
        results: list[PreviewImage] = []
        for label, zf in self._nested_zips():
            for name in zf.namelist():
                lower = name.lower()
                is_thumbnail = lower.endswith("/previews/small.png")
                is_large = (
                    include_large_images
                    and "/images.blobparts/" in lower
                    and lower.endswith(".png")
                )
                if is_thumbnail or is_large:
                    try:
                        data = zf.read(name)
                    except NotImplementedError:
                        continue  # unsupported codec (e.g. zstd); install zipfile-zstd
                    results.append(PreviewImage(
                        source=label,
                        path=name,
                        data=data,
                    ))
        return results

    def get_bom(self, *, include_power_symbols: bool = False) -> list[BomEntry]:
        """
        Return the bill of materials parsed from the schematic.

        Parameters
        ----------
        include_power_symbols:
            When False (default) supply/power symbols (GND, VCC, NC, etc.)
            are excluded; only real components are returned.  Supply symbols
            are identified by their library name containing "SupplySymbol".
        """
        tree = ET.fromstring(self.get_schematic())
        parts_elem = tree.find(".//parts")
        if parts_elem is None:
            return []
        results: list[BomEntry] = []
        for part in parts_elem:
            if part.tag != "part":
                continue
            library = part.get("library", "")
            if not include_power_symbols and "supplysymbol" in library.lower():
                continue
            results.append(BomEntry(
                reference=part.get("name", ""),
                device=part.get("deviceset", ""),
                package=part.get("device", "").lstrip("-"),
                value=part.get("value", ""),
                library=library,
            ))
        return results

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def extract_schematic(self, dest: str | os.PathLike | None = None) -> Path:
        """
        Write the .sch file to *dest*.

        If *dest* is a directory the original filename is preserved inside it.
        If *dest* is None the file is written to the current directory.
        Returns the Path of the written file.
        """
        fsch = self._nested_zip(".fsch")
        entry = self._find_in_zip(fsch, ".sch")
        if entry is None:
            raise FileNotFoundInArchiveError("No .sch file found inside .fsch archive")
        return self._write(fsch.read(entry), Path(entry).name, dest)

    def extract_board(self, dest: str | os.PathLike | None = None) -> Path:
        """
        Write the .brd file to *dest*.

        If *dest* is a directory the original filename is preserved inside it.
        If *dest* is None the file is written to the current directory.
        Returns the Path of the written file.
        """
        fbrd = self._nested_zip(".fbrd")
        entry = self._find_in_zip(fbrd, ".brd")
        if entry is None:
            raise FileNotFoundInArchiveError("No .brd file found inside .fbrd archive")
        return self._write(fbrd.read(entry), Path(entry).name, dest)

    def extract_previews(
        self,
        dest: str | os.PathLike | None = None,
        *,
        include_large_images: bool = True,
    ) -> list[Path]:
        """
        Write all preview images under *dest* (defaults to current directory).

        Files are named ``{source}__{original_filename}`` to avoid collisions
        when multiple archives contain a ``small.png``.
        Returns a list of written Paths.
        """
        dest_dir = Path(dest) if dest is not None else Path.cwd()
        dest_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for preview in self.get_previews(include_large_images=include_large_images):
            filename = f"{preview.source}__{Path(preview.path).name}"
            out = dest_dir / filename
            out.write_bytes(preview.data)
            written.append(out)
        return written

    def extract_bom(
        self,
        dest: str | os.PathLike | None = None,
        *,
        include_power_symbols: bool = False,
    ) -> Path:
        """
        Write the BOM as a CSV file to *dest*.

        If *dest* is a directory the file is named ``{design_name}_bom.csv``.
        If *dest* is None the file is written to the current directory.
        Returns the Path of the written file.
        """
        entries = self.get_bom(include_power_symbols=include_power_symbols)
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["reference", "device", "package", "value", "library"]
        )
        writer.writeheader()
        for entry in entries:
            writer.writerow({
                "reference": entry.reference,
                "device": entry.device,
                "package": entry.package,
                "value": entry.value,
                "library": entry.library,
            })
        return self._write(buf.getvalue().encode(), f"{self.design_name}_bom.csv", dest)

    @staticmethod
    def _write(data: bytes, filename: str, dest: str | os.PathLike | None) -> Path:
        if dest is None:
            out = Path.cwd() / filename
        else:
            dest_str = str(dest)
            dest = Path(dest)
            # Treat dest as a directory when it ends with a separator, is already
            # a directory, or has no file extension (ambiguous, but safer default).
            if dest_str.endswith(("/", os.sep)) or dest.is_dir() or not dest.suffix:
                dest.mkdir(parents=True, exist_ok=True)
                out = dest / filename
            else:
                out = dest
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return out
