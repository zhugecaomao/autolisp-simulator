"""Standard AutoLISP functions (the common subset: math, strings, lists, geometry, errors)."""
import math
import re

from .types import LispError, Sym, DPair, sym, T, nil_p
from .interp import Builtin, Lambda, truthy


def num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise LispError("bad argument type: numberp: %r" % (x,))
    return x


def i32(n):
    n &= 0xFFFFFFFF
    return n - (1 << 32) if n & 0x80000000 else n


def lst(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    raise LispError("bad argument type: listp: %r" % (x,))


def b(x):
    return T if x else None


def add(it, *a):
    r = 0
    for x in a:
        r += num(x)
    return i32(r) if all(isinstance(x, int) for x in a) else float(r)


def sub(it, *a):
    if not a:
        return 0
    r = num(a[0])
    if len(a) == 1:
        r = -r
    for x in a[1:]:
        r -= num(x)
    return i32(r) if all(isinstance(x, int) for x in a) else float(r)


def mul(it, *a):
    r = 1
    for x in a:
        r *= num(x)
    return i32(r) if all(isinstance(x, int) for x in a) else float(r)


def div(it, *a):
    r = num(a[0])
    ints = all(isinstance(x, int) for x in a)
    for x in a[1:]:
        x = num(x)
        if x == 0:
            raise ZeroDivisionError
        r = int(r / x) if ints else r / x
    return r if ints else float(r)


def cmp_chain(op):
    def f(it, *a):
        for x, y in zip(a, a[1:]):
            if isinstance(x, str) != isinstance(y, str):
                raise LispError("bad argument type: %r %r" % (x, y))
            if not op(x, y):
                return None
        return T
    return f


def eq_(it, *a):
    for x, y in zip(a, a[1:]):
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            if x != y:
                return None
        elif nil_p(x) and nil_p(y):
            continue
        elif not (x == y and type(x) is type(y)):
            return None
    return T


def ne_(it, a, c):
    return None if eq_(it, a, c) else T


def car(it, x):
    if isinstance(x, DPair):
        return x.car
    return lst(x)[0] if lst(x) else None


def cdr(it, x):
    if isinstance(x, DPair):
        return x.cdr
    return lst(x)[1:] or None


def cxr(path):
    def f(it, x):
        for ch in reversed(path):
            x = car(it, x) if ch == "a" else cdr(it, x)
            if x is None:
                return None
        return x
    return f


def cons(it, a, d):
    if d is None:
        return [a]
    if isinstance(d, list):
        return [a] + d
    return DPair(a, d)


def assoc(it, key, alist):
    for e in lst(alist):
        k = e.car if isinstance(e, DPair) else (e[0] if isinstance(e, list) and e else None)
        if k == key and type(k) is type(key):
            return e
        if isinstance(k, (int, float)) and isinstance(key, (int, float)) and k == key:
            return e
    return None


def member(it, x, l):
    l = lst(l)
    for i, e in enumerate(l):
        if e == x and type(e) is type(x) or (isinstance(e, (int, float)) and isinstance(x, (int, float)) and e == x):
            return l[i:]
    return None


def nth(it, n, l):
    l = lst(l)
    return l[n] if 0 <= n < len(l) else None


def mapcar(it, f, *ls):
    ls = [lst(l) for l in ls]
    return [it.apply(f, list(args)) for args in zip(*ls)] or None


def apply_(it, f, args):
    return it.apply(f, list(lst(args)))


def rtos(it, v, mode=2, prec=None):
    v = num(v)
    mode = 2 if mode is None else mode
    prec = 4 if prec is None else prec
    if mode == 1:
        return "%.*E" % (prec, v)
    if mode in (2, 3, 4, 5):
        return "%.*f" % (prec, v)
    raise LispError("bad argument value: rtos mode")


def atof(it, s):
    m = re.match(r"\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s)
    return float(m.group(0)) if m else 0.0


def atoi(it, s):
    m = re.match(r"\s*[+-]?\d+", s)
    return int(m.group(0)) if m else 0


def fix(it, x):
    return int(num(x))


def expt(it, a, c):
    a, c = num(a), num(c)
    r = a ** c
    return int(r) if isinstance(a, int) and isinstance(c, int) and c >= 0 else float(r)


def substr(it, s, start, n=None):
    if not isinstance(s, str):
        raise LispError("bad argument type: stringp")
    i = start - 1
    return s[i:] if n is None else s[i:i + n]


def strcat(it, *a):
    for x in a:
        if not isinstance(x, str):
            raise LispError("bad argument type: stringp: %r" % (x,))
    return "".join(a)


def dist(it, p, q):
    p, q = lst(p), lst(q)
    z1 = p[2] if len(p) > 2 else 0
    z2 = q[2] if len(q) > 2 else 0
    return math.sqrt((p[0]-q[0])**2 + (p[1]-q[1])**2 + (z1-z2)**2)


def angle(it, p, q):
    p, q = lst(p), lst(q)
    a = math.atan2(q[1] - p[1], q[0] - p[0])
    return a + 2 * math.pi if a < 0 else a


def polar(it, p, a, d):
    p = lst(p)
    return [p[0] + d * math.cos(a), p[1] + d * math.sin(a), p[2] if len(p) > 2 else 0.0]


def equal_(it, a, c, fuzz=0):
    if isinstance(a, (int, float)) and isinstance(c, (int, float)):
        return b(abs(a - c) <= (fuzz or 0))
    if isinstance(a, list) and isinstance(c, list):
        return b(len(a) == len(c) and all(equal_(it, x, y, fuzz) for x, y in zip(a, c)))
    return b(a == c)


def type_(it, x):
    if x is None:
        return None
    if isinstance(x, int):
        return sym("INT")
    if isinstance(x, float):
        return sym("REAL")
    if isinstance(x, str):
        return sym("STR")
    if isinstance(x, Sym):
        return sym("SYM")
    if isinstance(x, list):
        return sym("LIST")
    if isinstance(x, (Lambda, Builtin)):
        return sym("SUBR")
    return sym("OBJECT")


def length(it, l):
    return len(lst(l))


def catch_all_apply(it, f, args):
    it.catch_depth += 1
    try:
        return it.apply(f, list(lst(args)))
    except LispError as e:
        return ["%vl-error%", str(e)]
    finally:
        it.catch_depth -= 1


def error_p(it, x):
    return b(isinstance(x, list) and x and x[0] == "%vl-error%")


def error_message(it, x):
    return x[1] if error_p(it, x) else None


def boundp(it, s):
    return b(it.g.get(s.name) is not None)


def princ_(it, *a):
    if a:
        it.out.append(a[0] if isinstance(a[0], str) else repr(a[0]))
        return a[0]
    return None


def load_(it, name, onfail=None):
    try:
        it.load_file(name)
        return T
    except LispError:
        if onfail is not None:
            return onfail
        raise


def install(it):
    g = it.g

    def reg(name, fn, raw=False):
        g[name.upper()] = Builtin(fn, name.lower(), raw)

    for n, f in {
        "+": add, "-": sub, "*": mul, "/": div,
        "=": eq_, "/=": ne_,
        "<": cmp_chain(lambda x, y: x < y), ">": cmp_chain(lambda x, y: x > y),
        "<=": cmp_chain(lambda x, y: x <= y), ">=": cmp_chain(lambda x, y: x >= y),
        "1+": lambda it, x: num(x) + 1, "1-": lambda it, x: num(x) - 1,
        "abs": lambda it, x: abs(num(x)), "float": lambda it, x: float(num(x)),
        "fix": fix, "sqrt": lambda it, x: math.sqrt(num(x)),
        "sin": lambda it, x: math.sin(num(x)), "cos": lambda it, x: math.cos(num(x)),
        "atan": lambda it, y, x=None: math.atan(y) if x is None else math.atan2(y, x),
        "expt": expt, "exp": lambda it, x: math.exp(x), "log": lambda it, x: math.log(x),
        "min": lambda it, *a: min(a), "max": lambda it, *a: max(a),
        "rem": lambda it, a, c: math.fmod(a, c) if isinstance(a, float) or isinstance(c, float) else int(math.fmod(a, c)),
        "not": lambda it, x: b(nil_p(x)), "null": lambda it, x: b(nil_p(x)),
        "atom": lambda it, x: b(not (isinstance(x, list) and x) and not isinstance(x, DPair)),
        "listp": lambda it, x: b(isinstance(x, (list, DPair))),
        "numberp": lambda it, x: b(isinstance(x, (int, float))),
        "minusp": lambda it, x: b(x < 0), "zerop": lambda it, x: b(x == 0),
        "eq": lambda it, a, c: b(a is c or (nil_p(a) and nil_p(c)) or (isinstance(a, (int, float, str)) and a == c)),
        "equal": equal_,
        "car": car, "cdr": cdr, "cons": cons, "list": lambda it, *a: list(a) or None,
        "caar": cxr("aa"), "cadr": cxr("ad"), "cddr": cxr("dd"), "caddr": cxr("add"),
        "cdar": cxr("da"), "cadar": cxr("ada"), "cdddr": cxr("ddd"), "cadddr": cxr("addd"),
        "append": lambda it, *a: [x for l in a for x in lst(l)] or None,
        "reverse": lambda it, l: list(reversed(lst(l))) or None,
        "length": length, "nth": nth, "last": lambda it, l: lst(l)[-1] if lst(l) else None,
        "assoc": assoc, "member": member, "mapcar": mapcar, "apply": apply_,
        "strcat": strcat, "strlen": lambda it, *a: sum(len(s) for s in a),
        "strcase": lambda it, s, lower=None: s.lower() if truthy(lower) else s.upper(),
        "substr": substr, "itoa": lambda it, n: str(int(n)), "atoi": atoi, "atof": atof,
        "rtos": rtos, "type": type_, "boundp": boundp,
        "distance": dist, "angle": angle, "polar": polar,
        "princ": princ_, "prin1": princ_, "print": princ_,
        "prompt": lambda it, s: (it.out.append(s), None)[1],
        "terpri": lambda it: (it.out.append("\n"), None)[1],
        "alert": lambda it, s: (it.out.append("ALERT: " + s), None)[1],
        "load": load_, "vl-load-com": lambda it: None,
        "vl-catch-all-apply": catch_all_apply, "vl-catch-all-error-p": error_p,
        "vl-catch-all-error-message": error_message,
        "vl-princ-to-string": lambda it, x: x if isinstance(x, str) else repr(x),
        "vl-string-search": lambda it, p, s, st=0: (s.find(p, st) if s.find(p, st) >= 0 else None),
        "vl-position": lambda it, x, l: (lst(l).index(x) if x in lst(l) else None),
        "findfile": lambda it, n: (str(it.find_file(n)) if it.find_file(n) else None),
        "ascii": lambda it, s: ord(s[0]), "chr": lambda it, n: chr(n),
        "getenv": lambda it, n: None, "setenv": lambda it, n, v: v,
        "eval": lambda it, x: it.eval(x), "read": lambda it, s: __import__("lispsim.reader", fromlist=["x"]).read_all(s)[0],
        "gc": lambda it: None, "vl-bb-set": lambda it, *a: None,
    }.items():
        reg(n, f)
    g["PI"] = math.pi
    g["PAUSE"] = "\\"
