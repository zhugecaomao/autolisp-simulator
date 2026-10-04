"""Helpers for tests: build a session, snapshot the drawing, compare with a golden drawing."""
from .cad import MockCad
from .interp import Interp


def session(inputs, search_path, entry=None, osmode=4133):
    """Interpreter + mock CAD; `entry` (a .lsp found on search_path) is loaded if given."""
    cad = MockCad(inputs=inputs, osmode=osmode)
    it = Interp(search_path=search_path, cad=cad)
    if entry:
        it.load_file(entry)
    return it, cad


def snapshot(cad):
    """Geometry in the same shape as tests/golden/*.json."""
    ents = cad.entities
    return {
        "lines": sorted([round(e["p"][0], 2), round(e["p"][1], 2), round(e["q"][0], 2), round(e["q"][1], 2)]
                        for e in ents if e["type"] == "LINE"),
        "points": sorted([round(e["p"][0], 2), round(e["p"][1], 2)] for e in ents if e["type"] == "POINT"),
        "texts": sorted(({"text": e["text"], "x": round(e["p"][0], 2), "y": round(e["p"][1], 2),
                          "rot": round(e["rot"], 2),
                          "height": None if e["height"] is None else round(e["height"], 2)}
                         for e in ents if e["type"] == "TEXT"),
                        key=lambda t: (t["x"], t["y"], t["text"])),
    }


def diff_geometry(golden, actual, tol=0.01):
    """List of human-readable differences (empty = identical within tol)."""
    out = []

    def close(a, b):
        return all((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= tol)
                   for x, y in zip(a, b))

    for kind in ("lines", "points"):
        g, a = list(golden[kind]), list(actual[kind])
        if len(g) != len(a):
            out.append("%s: expected %d, got %d" % (kind, len(g), len(a)))
        for x in g:
            m = next((y for y in a if close(x, y)), None)
            if m is None:
                out.append("%s: missing %s" % (kind, x))
            else:
                a.remove(m)
        out += ["%s: unexpected %s" % (kind, y) for y in a]
    g, a = list(golden["texts"]), list(actual["texts"])
    if len(g) != len(a):
        out.append("texts: expected %d, got %d" % (len(g), len(a)))
    for x in g:
        m = next((y for y in a if y["text"] == x["text"] and close((x["x"], x["y"], x["rot"], x["height"]),
                                                              (y["x"], y["y"], y["rot"], y["height"]))), None)
        if m is None:
            out.append("texts: missing %s" % x)
        else:
            a.remove(m)
    out += ["texts: unexpected %s" % y for y in a]
    return out
