"""Mock CAD environment: system variables, entities, (command), dialogs, input."""
import math
import re
import tempfile
from pathlib import Path

from .types import LispError, Sym, DPair, sym, T, nil_p
from .interp import Builtin, Lambda, truthy

ESC = object()          # scripted input meaning "user pressed ESC"
SNAP_MASK = 0x3FFF      # OSMODE bits 1..8192 = running snaps; 16384 only means "all off"


class Ename:
    def __init__(self, ent):
        self.ent = ent

    def __repr__(self):
        return "<Entity name: %s>" % self.ent["id"]


class InputMismatch(Exception):
    pass


class ScriptedInputs:
    """Ordered answers for getpoint/getkword/getint/...  Each rule is
    (kind, prompt_regex_or_None, value).  Use ESC as the value to cancel."""

    def __init__(self, rules=(), dialogs=(), esc_at=None, fallback=None, repeat_last_dialog=False):
        self.repeat_last_dialog = repeat_last_dialog   # reuse the last dialog answer when more are needed
        self.fallback = fallback     # optional fn(kind, prompt) -> value, used when no rule is left
        self.rules = list(rules)
        self.dialogs = list(dialogs)
        self.esc_at = esc_at         # 1-based index of the input call that gets ESC
        self.count = 0               # number of input calls so far
        self.history = []

    def next(self, kind, prompt):
        self.count += 1
        self.history.append((kind, prompt))
        if self.esc_at is not None and self.count == self.esc_at:
            return ESC
        if not self.rules:
            if self.fallback is not None:
                return self.fallback(kind, prompt)
            raise InputMismatch("no scripted answer left for %s %r (call #%d)" % (kind, prompt, self.count))
        k, rx, val = self.rules.pop(0)
        if k != kind or (rx and not re.search(rx, prompt, re.I)):
            raise InputMismatch("expected %s /%s/ but program asked %s %r (call #%d)"
                                % (k, rx, kind, prompt, self.count))
        return val

    def next_dialog(self, name):
        self.count += 1
        self.history.append(("dialog", name))
        if self.esc_at is not None and self.count == self.esc_at:
            return ESC
        if not self.dialogs:
            raise InputMismatch("no scripted dialog left for %r (call #%d)" % (name, self.count))
        d = self.dialogs.pop(0) if len(self.dialogs) > 1 or not self.repeat_last_dialog else self.dialogs[0]
        return d


def parse_dcl(text):
    """-> {dialog_name_lower: {key_lower: default_value_or_None}}"""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = {}
    for m in re.finditer(r"^\s*(\w+)\s*:\s*dialog\s*\{", text, re.M):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += (text[i] == "{") - (text[i] == "}")
            i += 1
        body = text[m.end():i]
        keys = {}
        for km in re.finditer(r'\bkey\s*=\s*"?(\w+)"?\s*;', body):
            keys[km.group(1).lower()] = None
        out[m.group(1).lower()] = keys
    return out


class MockCad:
    def __init__(self, inputs=None, osmode=4133, workdir=None):
        self.inputs = inputs or ScriptedInputs()
        self.sysvars = {
            "osmode": osmode, "cmdecho": 1, "pdmode": 0, "cecolor": "BYLAYER",
            "clayer": "0", "textstyle": "Standard", "dimtxt": 2.5, "dimscale": 1.0,
            "dwgname": "Drawing1.dwg", "dwgprefix": "C:\\Temp\\", "lastpoint": [0.0, 0.0, 0.0],
            "pickfirst": 1, "angbase": 0, "angdir": 0, "orthomode": 0,
        }
        self.entities, self._next_id = [], 0x100
        self.log = []                 # every (command ...) call: dict
        self.osmode_history = [osmode]
        self.snap_violations = []     # drawing commands executed while snaps were on
        self.unknown_commands = []
        self.warnings = []
        self.styles = {}
        self.kwlist = None
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="lispsim_"))
        self.files = {}
        self._fid = 0
        # dialogs
        self.dcl = {}                 # dcl id -> (filename, parsed)
        self._dcl_id = 0
        self.cur = None               # (dcl_id, dialog_name)
        self.actions = {}
        self.tiles = {}
        self.dialog_result = None
        self.dialog_log = []

    # -------------------------------------------------------------- wiring
    def install(self, it):
        self.it = it
        g = it.g

        def reg(name, fn):
            g[name.upper()] = Builtin(fn, name.lower())

        reg("getvar", self.getvar)
        reg("setvar", self.setvar)
        reg("command", self.command)
        reg("entlast", lambda it: Ename(self.entities[-1]) if self.entities else None)
        reg("entget", self.entget)
        reg("entsel", lambda it, p="": self._ask("entsel", p))
        reg("getpoint", lambda it, *a: self._point("getpoint", a))
        reg("getcorner", lambda it, *a: self._point("getcorner", a))
        reg("getkword", lambda it, p="": self._ask("getkword", p))
        reg("getint", lambda it, p="": self._ask("getint", p))
        reg("getreal", lambda it, p="": self._ask("getreal", p))
        reg("getstring", lambda it, *a: self._ask("getstring", a[-1] if a and isinstance(a[-1], str) else ""))
        reg("getdist", lambda it, *a: self._ask("getdist", a[-1] if a and isinstance(a[-1], str) else ""))
        reg("getangle", lambda it, *a: self._ask("getangle", a[-1] if a and isinstance(a[-1], str) else ""))
        reg("initget", self.initget)
        reg("graphscr", lambda it: None)
        reg("textscr", lambda it: None)
        reg("redraw", lambda it, *a: None)
        reg("menucmd", lambda it, *a: None)
        reg("exit", lambda it: (_ for _ in ()).throw(LispError("quit / exit abort")))
        reg("quit", lambda it: (_ for _ in ()).throw(LispError("quit / exit abort")))
        reg("load_dialog", self.load_dialog)
        reg("unload_dialog", lambda it, i: None)
        reg("new_dialog", self.new_dialog)
        reg("action_tile", self.action_tile)
        reg("start_dialog", self.start_dialog)
        reg("done_dialog", self.done_dialog)
        reg("get_tile", self.get_tile)
        reg("set_tile", self.set_tile)
        reg("mode_tile", lambda it, *a: None)
        for n in ("start_list", "add_list", "end_list", "start_image", "end_image", "fill_image",
                  "vector_image", "slide_image", "client_data_tile", "set_tile_text"):
            reg(n, lambda it, *a: None)
        reg("dimx_tile", lambda it, k: 100)
        reg("dimy_tile", lambda it, k: 100)
        reg("open", self.open_)
        reg("close", self.close_)
        reg("write-line", self.write_line)
        reg("read-line", self.read_line)

    # ------------------------------------------------------------ sysvars
    def getvar(self, it, name):
        return self.sysvars.get(name.lower())

    def setvar(self, it, name, val):
        n = name.lower()
        if n not in self.sysvars:
            raise LispError("bad argument value: setvar %s" % name)
        cur = self.sysvars[n]
        if isinstance(cur, str):
            if not isinstance(val, str):
                raise LispError("bad argument type: stringp: %r (setvar %s)" % (val, name))
        elif isinstance(cur, list):
            if not isinstance(val, list):
                raise LispError("bad argument type: point: %r (setvar %s)" % (val, name))
        else:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise LispError("bad argument type: numberp: %r (setvar %s)" % (val, name))
            if isinstance(cur, int):
                val = int(val)
        self.sysvars[n] = val
        if n == "osmode":
            self.osmode_history.append(val)
        return val

    @property
    def osmode(self):
        return self.sysvars["osmode"]

    # --------------------------------------------------------------- input
    def initget(self, it, *a):
        kws = [x for x in a if isinstance(x, str)]
        self.kwlist = kws[0].split() if kws else None
        return None

    def _check(self, kind, prompt, v):
        if v is ESC:
            raise LispError("Function cancelled")
        return v

    def _ask(self, kind, prompt):
        v = self._check(kind, prompt, self.inputs.next(kind, prompt))
        kw, self.kwlist = self.kwlist, None
        if kind == "getkword":
            if v in ("", None):
                return None
            if kw and not any(k.lower() == str(v).lower() or k.lower().startswith(str(v).lower()) and k.isupper() or False for k in kw):
                raise LispError("scripted keyword %r not allowed by initget %r" % (v, kw))
            return v
        if kind == "getint":
            return None if v in ("", None) else int(v)
        if kind in ("getreal", "getdist", "getangle"):
            return None if v in ("", None) else float(v)
        if kind == "entsel":
            if v in ("", None):
                return None
            return [Ename(v), [0.0, 0.0, 0.0]]
        return v if v != "" else None

    def _point(self, kind, a):
        prompt = next((x for x in reversed(a) if isinstance(x, str)), "")
        v = self._check(kind, prompt, self.inputs.next(kind, prompt))
        self.kwlist = None
        if v in ("", None):
            return None
        p = [float(x) for x in v] + ([0.0] if len(v) == 2 else [])
        self.sysvars["lastpoint"] = p
        return p

    # ------------------------------------------------------------ entities
    def add_entity(self, typ, **kw):
        ent = {"id": "%X" % self._next_id, "type": typ, "layer": self.sysvars["clayer"],
               "color": None, "osmode": self.osmode}
        self._next_id += 1
        ent.update(kw)
        self.entities.append(ent)
        if self.osmode & SNAP_MASK:
            self.snap_violations.append((typ, self.osmode, list(self.it.trace)))
        return ent

    def entget(self, it, en):
        e = en.ent
        if e["type"] == "ARC":
            return [DPair(0, "ARC"), [10] + e["center"], DPair(40, e["radius"]),
                    DPair(50, e["a0"]), DPair(51, e["a1"])]
        return [DPair(0, e["type"])]

    # ------------------------------------------------------------- command
    DRAW = {"line", "text", "point", "circle", "pline", "arc", "insert", "dtext"}

    def command(self, it, *args):
        args = list(args)
        if not args:
            return None
        name = args[0].lower() if isinstance(args[0], str) else str(args[0])
        name = name.lstrip(".-_")
        rest = args[1:]
        self.log.append({"cmd": name, "args": rest, "osmode": self.osmode, "trace": list(it.trace)})
        if name in ("line", "copy", "stretch", "point", "circle", "pline"):
            rest = self._coords(rest)
        h = getattr(self, "cmd_" + name, None)
        if h is None:
            self.unknown_commands.append(name)
            return None
        h(rest)
        return None

    _REL_POLAR = re.compile(r"^@\s*(-?[\d.]+)\s*<\s*(-?[\d.]+)$")
    _XY = re.compile(r"^(@?)\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)(?:\s*,\s*(-?[\d.]+))?$")

    def _coords(self, args):
        """Turn "@d<a", "@x,y" and "x,y" strings into points (relative to LASTPOINT)."""
        out = []
        for x in args:
            if isinstance(x, list) and self._pt(x):
                self._last(x)
            elif isinstance(x, str):
                last = self.sysvars["lastpoint"]
                m = self._REL_POLAR.match(x)
                if m:
                    d, a = float(m.group(1)), math.radians(float(m.group(2)))
                    x = [last[0] + d * math.cos(a), last[1] + d * math.sin(a), 0.0]
                    self._last(x)
                else:
                    m = self._XY.match(x)
                    if m:
                        px, py = float(m.group(2)), float(m.group(3))
                        x = [last[0] + px, last[1] + py, 0.0] if m.group(1) else [px, py, 0.0]
                        self._last(x)
            out.append(x)
        return out

    @staticmethod
    def _pt(x):
        return isinstance(x, list) and len(x) >= 2 and all(isinstance(v, (int, float)) for v in x)

    def _last(self, p):
        self.sysvars["lastpoint"] = [float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0]

    def cmd_line(self, a):
        pts = []
        for x in a:
            if self._pt(x):
                pts.append(x)
                self._last(x)
            elif isinstance(x, str) and x.lower() in ("c", "u", ""):
                pass
        for p, q in zip(pts, pts[1:]):
            self.add_entity("LINE", p=[float(v) for v in p[:2]], q=[float(v) for v in q[:2]])

    def cmd_pline(self, a):
        pts = [x for x in a if self._pt(x)]
        for p in pts:
            self._last(p)
        if len(pts) > 1:
            self.add_entity("PLINE", pts=[[float(v) for v in p[:2]] for p in pts])

    def cmd_point(self, a):
        p = next(x for x in a if self._pt(x))
        self._last(p)
        self.add_entity("POINT", p=[float(v) for v in p[:2]])

    def cmd_circle(self, a):
        c = next(x for x in a if self._pt(x))
        r = next(x for x in a if isinstance(x, (int, float)))
        self._last(c)
        self.add_entity("CIRCLE", center=[float(v) for v in c[:2]], r=float(r))

    def cmd_text(self, a):
        a = list(a)
        just = "L"
        if a and isinstance(a[0], str) and a[0].lower() == "j":
            just = a[1]
            a = a[2:]
        elif a and isinstance(a[0], str) and a[0].lower() in ("s",):
            a = a[2:]
        p = a[0]
        if not self._pt(p):
            raise LispError("text: bad start point %r" % (p,))
        self._last(p)
        a = a[1:]
        height = a[0] if a and isinstance(a[0], (int, float)) else None
        if height is not None:
            a = a[1:]
        rot = a[0] if a else "0"
        a = a[1:]
        text = a[0] if a else ""
        try:
            rot = float(rot)
        except (TypeError, ValueError):
            raise LispError("text: bad rotation %r" % (rot,))
        if str(text) == "":      # AutoCAD creates no text for an empty string
            return
        self.add_entity("TEXT", p=[float(v) for v in p[:2]], height=height, rot=rot, text=str(text), just=str(just).upper())

    def cmd_zoom(self, a):
        pass

    def cmd_style(self, a):
        if a and isinstance(a[0], str):
            self.sysvars["textstyle"] = a[0]
            self.styles[a[0]] = a[1:]

    def cmd_layer(self, a):
        a = [x for x in a if x != ""]
        if a and isinstance(a[0], str) and a[0].lower() in ("m", "s", "make", "set") and len(a) > 1:
            self.sysvars["clayer"] = a[1]

    def _targets(self, a):
        a = list(a)
        t = a[0] if a else None
        if isinstance(t, Ename):
            return [t.ent], a[1:]
        if isinstance(t, str) and t.lower() == "l":
            return ([self.entities[-1]] if self.entities else []), a[1:]
        return [], a

    def cmd_chprop(self, a):
        ents, rest = self._targets(a)
        i = 0
        rest = [x for x in rest]
        while i < len(rest):
            x = rest[i]
            if isinstance(x, str) and x.lower() in ("c", "color") and i + 1 < len(rest):
                for e in ents:
                    e["color"] = rest[i + 1]
                i += 2
            elif isinstance(x, str) and x.lower() in ("la", "layer") and i + 1 < len(rest):
                for e in ents:
                    e["layer"] = rest[i + 1]
                i += 2
            else:
                i += 1

    def cmd_erase(self, a):
        ents, _ = self._targets(a)
        for e in ents:
            if e in self.entities:
                self.entities.remove(e)

    def cmd_stretch(self, a):
        pass

    @staticmethod
    def _shift(e, dx, dy):
        for k in ("p", "q", "center"):
            if k in e:
                e[k] = [e[k][0] + dx, e[k][1] + dy]
        if "pts" in e:
            e["pts"] = [[x + dx, y + dy] for x, y in e["pts"]]

    def cmd_copy(self, a):
        ents, rest = self._targets(a)
        pts = [x for x in rest if self._pt(x)]
        if len(pts) < 2:
            raise LispError("copy: need a base point and a displacement, got %r" % (rest,))
        dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        for e in ents:
            c = dict(e)
            c["id"] = "%X" % self._next_id
            self._next_id += 1
            self._shift(c, dx, dy)
            self.entities.append(c)

    # -------------------------------------------------------------- dialogs
    def load_dialog(self, it, name):
        f = it.find_file(name)
        if f is None:
            return -1
        self._dcl_id += 1
        self.dcl[self._dcl_id] = (f.name, parse_dcl(f.read_bytes().decode("latin-1")))
        return self._dcl_id

    def new_dialog(self, it, name, dcl_id, *rest):
        if dcl_id not in self.dcl:
            return None
        fname, dialogs = self.dcl[dcl_id]
        if name.lower() not in dialogs:
            return None
        self.cur = (fname, name.lower(), dialogs[name.lower()])
        self.actions, self.tiles, self.dialog_result = {}, {}, None
        return T

    BASE_KEYS = {"accept", "cancel", "help", "error"}

    def action_tile(self, it, key, expr):
        if self.cur is None:
            raise LispError("action_tile outside a dialog")
        k = key.lower()
        if k not in self.cur[2] and k not in self.BASE_KEYS:
            # AutoCAD just returns nil here; keep a record so tests can look at it
            self.warnings.append("action_tile: key %r not in dialog %s (%s)" % (key, self.cur[1], self.cur[0]))
            return None
        self.actions[k] = expr
        return T

    def get_tile(self, it, key):
        return self.tiles.get(key.lower(), "")

    def set_tile(self, it, key, val):
        self.tiles[key.lower()] = val
        return val

    def done_dialog(self, it, code=1):
        self.dialog_result = code
        return None

    def start_dialog(self, it):
        if self.cur is None:
            raise LispError("start_dialog without new_dialog")
        d = self.inputs.next_dialog(self.cur[1])
        if d is ESC:
            raise LispError("Function cancelled")
        self.dialog_log.append((self.cur[1], dict(d)))
        cancel = d.get("__cancel__", False)
        for key, val in d.items():
            if key.startswith("__"):
                continue
            self.tiles[key.lower()] = val
            expr = self.actions.get(key.lower())
            if expr is not None:
                self._callback(expr, key, val, 2)
        btn = "cancel" if cancel else "accept"
        expr = self.actions.get(btn)
        self.dialog_result = None
        if expr is not None:
            self._callback(expr, btn, "", 1)
        if self.dialog_result is None:
            self.dialog_result = 0 if cancel else 1
        return self.dialog_result

    def _callback(self, expr, key, val, reason):
        g = self.it.g
        old = {n: g.get(n) for n in ("$VALUE", "$KEY", "$REASON", "$DATA")}
        g["$VALUE"], g["$KEY"], g["$REASON"], g["$DATA"] = val, key, reason, None
        try:
            self.it.run_text(expr)
        finally:
            g.update(old)

    # ------------------------------------------------------------ file I/O
    def _path(self, name):
        return self.workdir / re.sub(r"[^\w.\-]", "_", Path(str(name).replace("\\", "/")).name)

    def open_(self, it, name, mode):
        m = mode.lower()
        p = self._path(name)
        if m == "r" and not p.exists():
            return None
        self._fid += 1
        fh = open(p, {"r": "r", "w": "w", "a": "a"}[m], encoding="latin-1")
        self.files[self._fid] = fh
        return self._fid

    def close_(self, it, fid):
        self.files.pop(fid).close()
        return None

    def write_line(self, it, s, fid):
        self.files[fid].write(s + "\n")
        return s

    def read_line(self, it, fid):
        ln = self.files[fid].readline()
        return ln.rstrip("\n") if ln else None

    # ------------------------------------------------------------- helpers
    def entities_of(self, typ):
        return [e for e in self.entities if e["type"] == typ]
