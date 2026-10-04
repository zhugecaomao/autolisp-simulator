#!/usr/bin/env python3
"""Extract the geometry of a drawing made by the real AutoCAD tool into JSON.

    dwg2dxf -y -o ref.dxf drawing.dwg        # LibreDWG, converts DWG -> DXF
    python3 -m lispsim.extract_golden ref.dxf tests/golden/<name>.json

Only the entities the tools create (LINE, POINT, TEXT) are exported; polylines
are skipped because the PT code never draws them (they were added by hand).
"""
import json
import sys

import ezdxf


def r(v):
    return round(float(v), 2)


def main(dxf, out):
    m = ezdxf.readfile(dxf).modelspace()
    g = {
        "lines": sorted([r(e.dxf.start.x), r(e.dxf.start.y), r(e.dxf.end.x), r(e.dxf.end.y)] for e in m.query("LINE")),
        "points": sorted([r(e.dxf.location.x), r(e.dxf.location.y)] for e in m.query("POINT")),
        "texts": [],
    }
    for e in m.query("TEXT"):
        aligned = e.dxf.halign != 0 or e.dxf.valign != 0
        p = e.dxf.align_point if aligned and e.dxf.hasattr("align_point") else e.dxf.insert
        g["texts"].append({"text": e.dxf.text, "x": r(p.x), "y": r(p.y), "rot": r(e.dxf.rotation),
                           "height": r(e.dxf.height)})
    g["texts"].sort(key=lambda t: (t["x"], t["y"], t["text"]))
    json.dump(g, open(out, "w"), indent=1)
    print({k: len(v) for k, v in g.items()})


if __name__ == "__main__":
    main(*sys.argv[1:3])
