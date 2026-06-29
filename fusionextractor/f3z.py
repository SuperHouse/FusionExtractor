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
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterator

try:
    import zipfile_zstd  # noqa: F401 — registers zstd (type 93) with zipfile when present
except ImportError:
    pass

from .exceptions import FileNotFoundInArchiveError, FusionExtractorError

try:
    _VERSION = version("fusionextractor")
except PackageNotFoundError:
    _VERSION = "0.0.0"


@dataclass
class BomEntry:
    reference: str    # reference designator, e.g. "C1"
    device: str       # component type (Eagle deviceset), e.g. "CAP", "AD5593R"
    package: str      # footprint (Eagle device variant), e.g. "0603", "TSSOP16"
    value: str        # component value, e.g. "100nF" — empty string when not set
    library: str      # Eagle library name, e.g. "SuperHouse-Capacitors"


@dataclass
class PlacementEntry:
    reference: str    # reference designator, e.g. "R1"
    value: str        # component value, e.g. "10K" — empty string when not set
    package: str      # footprint, e.g. "C0603", "TSSOP16"
    x: float          # X position in mm, Eagle board coordinates (Y increasing upward)
    y: float          # Y position in mm, Eagle board coordinates (Y increasing upward)
    rotation: float   # rotation in degrees, 0-360
    side: str         # "top" or "bottom"


@dataclass
class PreviewImage:
    source: str            # which nested archive: "schematic", "board", "project", "3d_model"
    path: str              # path inside the nested archive
    data: bytes
    view_type: str | None = None  # "schematic", "pcb_top", "pcb_3d_top", "pcb_3d_bottom", "thumbnail"


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

    @staticmethod
    def _png_color_type(header: bytes) -> int | None:
        """Return the IHDR color_type byte from the first 26 bytes of a PNG, or None."""
        if len(header) < 26 or header[:8] != b'\x89PNG\r\n\x1a\n':
            return None
        return header[25]

    @staticmethod
    def _classify_fprj_images(
        items: list[tuple[zipfile.ZipInfo, int | None]],
    ) -> dict[str, str]:
        """Classify Images.BlobParts entries from the .fprj archive by view type.

        Uses ZIP metadata only — no pixel decoding, no colour assumptions:

        - RGB images (color_type=2, stored without PNG-level compression so file_size
          reflects raw pixel data): rank by ``compress_size / file_size``.  The PCB top
          layout (copper fills, coloured layer backgrounds) is far less compressible than
          any schematic page (predominantly white), so the single *least*-compressible
          RGB image is labelled ``"pcb_top"`` and the rest ``"schematic"``.  This
          correctly handles multi-page schematics.

        - RGBA images (color_type=6, PNG-compressed internally): preserve ZIP central-
          directory order.  Fusion consistently writes the bottom render before the top
          render regardless of board complexity, so the first RGBA entry is labelled
          ``"pcb_3d_bottom"`` and the second ``"pcb_3d_top"``.
        """
        rgb: list[zipfile.ZipInfo] = []
        rgba: list[zipfile.ZipInfo] = []
        for info, ct in items:
            if ct == 2:
                rgb.append(info)
            elif ct == 6:
                rgba.append(info)

        result: dict[str, str] = {}

        if rgb:
            by_ratio = sorted(rgb, key=lambda i: i.compress_size / max(i.file_size, 1))
            # Least compressible (last after ascending sort) = pcb_top; all others = schematic
            result[by_ratio[-1].filename] = "pcb_top"
            for info in by_ratio[:-1]:
                result[info.filename] = "schematic"

        if rgba:
            # Preserve ZIP order: Fusion writes bottom before top
            result[rgba[0].filename] = "pcb_3d_bottom"
            for info in rgba[1:]:
                result[info.filename] = "pcb_3d_top"

        return result

    @staticmethod
    def _format_columns(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
        """Left-justify *headers* + *rows* into aligned, space-delimited columns."""
        widths = [
            max(len(headers[i]), max((len(row[i]) for row in rows), default=0)) + 2
            for i in range(len(headers))
        ]
        lines = ["".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip()]
        for row in rows:
            lines.append("".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
        return lines

    @classmethod
    def _format_placements_kicad(cls, entries: list[PlacementEntry]) -> str:
        """Render placements as a KiCad-format .pos file (all sides, one file)."""
        timestamp = datetime.now().astimezone().strftime("%a %d %b %Y %H:%M:%S %Z")
        headers = ("# Ref", "Val", "Package", "PosX", "PosY", "Rot", "Side")
        rows = [
            (
                e.reference,
                e.value,
                e.package,
                f"{e.x:.4f}",
                # KiCad's PCB editor uses Y-increases-downward; Eagle uses
                # Y-increases-upward, so the axis is flipped on export.
                f"{-e.y:.4f}",
                f"{e.rotation:.1f}",
                e.side,
            )
            for e in entries
        ]
        lines = [
            f"### Module positions - created on {timestamp} ###",
            f"### Printed by FusionExtractor V{_VERSION} in KiCad V8.0 format",
            "## Unit = mm, Angle = deg.",
            "## Side = top/bottom",
            *cls._format_columns(headers, rows),
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def _format_placements_eagle(cls, entries: list[PlacementEntry]) -> str:
        """Render placements as an Eagle mount.ulp-format .mnt/.mnb file."""
        headers = ("# Part", "X", "Y", "Rotation", "Value")
        rows = [
            (e.reference, f"{e.x:.3f}", f"{e.y:.3f}", f"{e.rotation:g}", e.value)
            for e in entries
        ]
        lines = [
            f"# Exported by FusionExtractor V{_VERSION} in Fusion Electronics / EAGLE mount.ulp format",
            "# Grid units: mm",
            "#",
            *cls._format_columns(headers, rows),
        ]
        return "\n".join(lines) + "\n"

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

        Each returned :class:`PreviewImage` has a ``view_type`` field set to one of:

        * ``"thumbnail"`` — small ``Previews/small.png`` preview
        * ``"schematic"`` — schematic diagram (from .fprj)
        * ``"pcb_top"`` — PCB top-layer 2-D layout (from .fprj)
        * ``"pcb_3d_top"`` — 3-D render from the top (from .fprj or .f3d)
        * ``"pcb_3d_bottom"`` — 3-D render from the bottom (from .fprj or .f3d)

        Classification is based on ZIP metadata only (no pixel decoding).

        Parameters
        ----------
        include_large_images:
            When True (default) include the large ``Images.BlobParts`` PNGs.
            Set to False to get only the small ``Previews/small.png`` thumbnails.
        """
        results: list[PreviewImage] = []
        for label, zf in self._nested_zips():
            # Pre-classify large images in the electronics-project archive.
            view_type_map: dict[str, str] = {}
            if include_large_images and label == "project":
                items: list[tuple[zipfile.ZipInfo, int | None]] = []
                for info in zf.infolist():
                    lower = info.filename.lower()
                    if "/images.blobparts/" not in lower or not lower.endswith(".png"):
                        continue
                    ct: int | None
                    try:
                        with zf.open(info.filename) as fh:
                            ct = self._png_color_type(fh.read(26))
                    except Exception:
                        ct = None
                    items.append((info, ct))
                view_type_map = self._classify_fprj_images(items)

            for name in zf.namelist():
                lower = name.lower()
                is_thumbnail = lower.endswith("/previews/small.png")
                is_large = (
                    include_large_images
                    and "/images.blobparts/" in lower
                    and lower.endswith(".png")
                )
                if not (is_thumbnail or is_large):
                    continue
                try:
                    data = zf.read(name)
                except NotImplementedError:
                    continue  # unsupported codec (e.g. zstd); install zipfile-zstd

                if is_thumbnail:
                    vt: str | None = "thumbnail"
                elif label == "project":
                    vt = view_type_map.get(name)
                elif label == "3d_model":
                    vt = "pcb_3d_top"
                else:
                    vt = None

                results.append(PreviewImage(source=label, path=name, data=data, view_type=vt))
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

    def get_placements(self) -> list[PlacementEntry]:
        """
        Return component placement data parsed from the board.

        ``x``/``y`` are in mm using Eagle's native board coordinate system
        (Y increasing upward). Mirrored (bottom-side) elements are reported
        via ``side="bottom"`` rather than as a negative or offset angle —
        ``rotation`` is always the plain 0-360 degree value.
        """
        tree = ET.fromstring(self.get_board())
        elements_elem = tree.find(".//elements")
        if elements_elem is None:
            return []
        results: list[PlacementEntry] = []
        for el in elements_elem:
            if el.tag != "element":
                continue
            rot = el.get("rot", "")
            angle_str = rot.lstrip("SMR")
            results.append(PlacementEntry(
                reference=el.get("name", ""),
                value=el.get("value", ""),
                package=el.get("package", ""),
                x=float(el.get("x", "0")),
                y=float(el.get("y", "0")),
                rotation=float(angle_str) if angle_str else 0.0,
                side="bottom" if "M" in rot else "top",
            ))
        return results

    def get_board_image(self, view_type: str) -> bytes:
        """Return the PNG bytes for *view_type*.

        Parameters
        ----------
        view_type:
            One of ``"schematic"``, ``"pcb_top"``, ``"pcb_3d_top"``, ``"pcb_3d_bottom"``.

        Raises
        ------
        FileNotFoundInArchiveError
            If no image with that view type can be found (e.g. the .f3d archive
            requires ``zipfile-zstd`` for ``"pcb_3d_top"`` images).
        """
        for preview in self.get_previews(include_large_images=True):
            if preview.view_type == view_type:
                return preview.data
        raise FileNotFoundInArchiveError(
            f"No {view_type!r} image found in {self.path.name}"
        )

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

    def extract_board_image(
        self,
        view_type: str,
        dest: str | os.PathLike | None = None,
    ) -> Path:
        """
        Write the PNG for *view_type* to *dest*.

        Parameters
        ----------
        view_type:
            One of ``"schematic"``, ``"pcb_top"``, ``"pcb_3d_top"``, ``"pcb_3d_bottom"``.
        dest:
            Directory or file path.  If a directory (or None), the file is named
            ``{design_name}_{view_type}.png``.

        Returns the Path of the written file.
        """
        data = self.get_board_image(view_type)
        return self._write(data, f"{self.design_name}_{view_type}.png", dest)

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

    def extract_placements_kicad(self, dest: str | os.PathLike | None = None) -> Path:
        """
        Write component placements as a KiCad-format .pos file (single file,
        both sides).

        If *dest* is a directory the file is named ``{design_name}.pos``.
        If *dest* is None the file is written to the current directory.
        Returns the Path of the written file.
        """
        data = self._format_placements_kicad(self.get_placements())
        return self._write(data.encode(), f"{self.design_name}.pos", dest)

    def extract_placements_eagle(self, dest: str | os.PathLike | None = None) -> tuple[Path, Path]:
        """
        Write component placements as Eagle mount.ulp-format files: a
        ``.mnt`` for top-side components and a ``.mnb`` for bottom-side
        components.

        *dest* is treated as a directory (defaults to the current directory).
        Returns a ``(mnt_path, mnb_path)`` tuple.
        """
        dest_dir = Path(dest) if dest is not None else Path.cwd()
        dest_dir.mkdir(parents=True, exist_ok=True)
        entries = self.get_placements()
        top = [e for e in entries if e.side == "top"]
        bottom = [e for e in entries if e.side == "bottom"]
        mnt_path = dest_dir / f"{self.design_name}.mnt"
        mnt_path.write_text(self._format_placements_eagle(top))
        mnb_path = dest_dir / f"{self.design_name}.mnb"
        mnb_path.write_text(self._format_placements_eagle(bottom))
        return mnt_path, mnb_path

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
