class LispError(Exception):
    """An AutoLISP runtime error (message as AutoLISP would print it)."""


class Abort(Exception):
    """Raised after *error* has run; unwinds to the top level."""


class Sym:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


_syms = {}


def sym(name):
    key = name.upper()
    s = _syms.get(key)
    if s is None:
        s = _syms[key] = Sym(key)
    return s


T = sym("T")


class DPair:
    """Dotted pair (a . b) where b is not a list."""
    __slots__ = ("car", "cdr")

    def __init__(self, car, cdr):
        self.car, self.cdr = car, cdr

    def __repr__(self):
        return "(%r . %r)" % (self.car, self.cdr)

    def __eq__(self, o):
        return isinstance(o, DPair) and self.car == o.car and self.cdr == o.cdr


def nil_p(x):
    return x is None or (isinstance(x, list) and not x)
