import sys
from pathlib import Path

from fusionextractor import FusionProject

if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} <file.f3z>")
    sys.exit(1)

with FusionProject(sys.argv[1]) as proj:
    # Read the design name from embedded metadata
    print(proj.design_name)

    # Get raw bytes
    sch_bytes = proj.get_schematic()   # Eagle/KiCad .sch file
    brd_bytes = proj.get_board()       # Eagle/KiCad .brd file
    previews  = proj.get_previews()    # list[PreviewImage]

    # Extract to disk
    proj.extract_board("output/my_board.brd")   # writes to exact path
    proj.extract_schematic(f"output/{proj.path.stem}.sch")   # named after the .f3z file
    proj.extract_previews("output/previews/")   # writes all preview PNGs
