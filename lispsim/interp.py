"""AutoLISP evaluator: dynamic scoping, *error* called at the point of error."""
import math
from pathlib import Path

from .types import LispError, Abort, Sym, DPair, sym, T, nil_p
from .reader import read_all


class Lambda:
    def __init__(self, params, locals_, body, name=None):
        self.params, self.locals, self.body, self.name = params, locals_, body, name


class Builtin:
    def __init__(self, fn, name, raw=False):
        self.fn, self.name, self.raw = fn, name, raw


def truthy(x):
    return not nil_p(x)


class Interp:
    def __init__(self, search_path=(), cad=None):
        self.g = {}                      # symbol name -> value
        self.search_path = [Path(p) for p in search_path]
        self.cad = cad
        self.catch_depth = 0
        self.depth = 0
        self.trace = []                  # call-stack names for error reports
        self.loaded = []
        self.out = []                    # princ/prompt output
        from . import builtins
        builtins.install(self)
        if cad is not None:
            cad.install(self)

    # ---------------------------------------------------------------- files
    def find_file(self, name):
        p = Path(name)
        if p.is_absolute() and p.exists():
            return p
        low = name.lower()
        for d in self.search_path:
            if not d.is_dir():
                continue
            for f in d.iterdir():
                if f.is_file() and f.name.lower() == low:
                    return f
        return None

    def load_file(self, name):
        f = self.find_file(name)
        if f is None:
            for ext in (".lsp", ".LSP"):
                f = self.find_file(name + ext)
                if f:
                    break
        if f is None:
            raise LispError("load failed: \"%s\"" % name)
        text = f.read_bytes().decode("latin-1")
        self.loaded.append(f.name)
        r = None
        for form in read_all(text):
            r = self.eval(form)
        return r

    # ----------------------------------------------------------------- eval
    def eval(self, x):
        if isinstance(x, Sym):
            return self.g.get(x.name)
        if not isinstance(x, list) or not x:
            return x
        head = x[0]
        if isinstance(head, Sym):
            sf = SPECIAL.get(head.name)
            if sf is not None:
                return sf(self, x)
            fn = self.g.get(head.name)
            if fn is None:
                self.raise_error("no function definition: %s" % head.name)
        elif isinstance(head, list):
            fn = self.eval(head)
        else:
            self.raise_error("bad function: %r" % (head,))
        if isinstance(fn, Builtin) and fn.raw:
            return self.guard(fn, x[1:], head)
        args = [self.eval(a) for a in x[1:]]
        return self.apply(fn, args, head)

    def guard(self, fn, args, head):
        try:
            return fn.fn(self, *args)
        except (LispError, TypeError, ValueError, ZeroDivisionError, IndexError, AttributeError, OverflowError) as e:
            self.raise_error(self._msg(e, head))

    @staticmethod
    def _msg(e, head):
        if isinstance(e, LispError):
            return str(e)
        if isinstance(e, ZeroDivisionError):
            return "divide by zero"
        return "bad argument type: %s (%s)" % (getattr(head, "name", head), e)

    def apply(self, fn, args, head=None):
        if isinstance(fn, Sym):
            fn = self.g.get(fn.name)
        if isinstance(fn, Builtin):
            try:
                return fn.fn(self, *args)
            except (LispError, TypeError, ValueError, ZeroDivisionError, IndexError, AttributeError, OverflowError) as e:
                self.raise_error(self._msg(e, head or fn.name))
        if not isinstance(fn, Lambda):
            self.raise_error("bad function: %r" % (fn,))
        names = fn.params + fn.locals
        saved = [(n, self.g.get(n)) for n in names]
        for n, v in zip(fn.params, args + [None] * (len(fn.params) - len(args))):
            self.g[n] = v
        for n in fn.locals:
            self.g[n] = None
        self.depth += 1
        if self.depth > 400:
            self.depth -= 1
            self.raise_error("stack overflow (depth > 400): %s" % fn.name)
        self.trace.append(fn.name or "lambda")
        try:
            r = None
            for form in fn.body:
                r = self.eval(form)
            return r
        finally:
            self.trace.pop()
            self.depth -= 1
            for n, v in reversed(saved):
                self.g[n] = v

    def funcall(self, f, *args):
        return self.apply(f, list(args))

    # --------------------------------------------------------------- errors
    def raise_error(self, msg):
        """Call *error* NOW (stack and local bindings still intact), then abort."""
        if self.catch_depth > 0:
            raise LispError(msg)
        handler = self.g.get("*ERROR*")
        self.last_error = msg
        self.last_trace = list(self.trace)
        if isinstance(handler, Lambda):
            try:
                self.catch_depth += 1   # errors inside the handler just end it
                try:
                    self.apply(handler, [msg])
                finally:
                    self.catch_depth -= 1
            except (LispError, Abort):
                pass
        raise Abort(msg)

    # ------------------------------------------------------------------ run
    def run_text(self, text):
        r = None
        for form in read_all(text):
            r = self.eval(form)
        return r

    def run_command(self, name):
        """Invoke (c:name); returns ('ok', value) or ('error', message)."""
        fn = self.g.get("C:" + name.upper())
        if fn is None:
            raise KeyError("command c:%s is not defined" % name)
        self.trace = []
        self.last_error = None
        try:
            return ("ok", self.apply(fn, []))
        except Abort as e:
            return ("error", str(e))


# --------------------------------------------------------- special forms
def _params(plist):
    params, locals_, cur = [], [], None
    cur = params
    for p in plist or []:
        if isinstance(p, Sym) and p.name == "/":
            cur = locals_
        else:
            cur.append(p.name)
    return params, locals_


def sf_quote(it, x):
    return x[1]


def sf_function(it, x):
    return it.eval(x[1]) if isinstance(x[1], list) else x[1]


def sf_lambda(it, x):
    p, l = _params(x[1])
    return Lambda(p, l, x[2:], "lambda")


def sf_defun(it, x):
    name = x[1].name
    p, l = _params(x[2])
    it.g[name] = Lambda(p, l, x[3:], name.lower())
    return x[1]


def sf_setq(it, x):
    v = None
    for i in range(1, len(x), 2):
        v = it.eval(x[i + 1]) if i + 1 < len(x) else None
        if not isinstance(x[i], Sym):
            it.raise_error("bad argument type: symbolp")
        it.g[x[i].name] = v
    return v


def sf_if(it, x):
    if truthy(it.eval(x[1])):
        return it.eval(x[2])
    return it.eval(x[3]) if len(x) > 3 else None


def sf_cond(it, x):
    for clause in x[1:]:
        t = it.eval(clause[0])
        if truthy(t):
            r = t
            for f in clause[1:]:
                r = it.eval(f)
            return r
    return None


def sf_progn(it, x):
    r = None
    for f in x[1:]:
        r = it.eval(f)
    return r


def sf_while(it, x):
    n = 0
    while truthy(it.eval(x[1])):
        for f in x[2:]:
            it.eval(f)
        n += 1
        if n > 1_000_000:
            it.raise_error("infinite loop (while > 1e6 iterations)")
    return None


def sf_repeat(it, x):
    n = it.eval(x[1])
    for _ in range(int(n)):
        for f in x[2:]:
            it.eval(f)
    return None


def sf_foreach(it, x):
    name = x[1].name
    lst = it.eval(x[2]) or []
    old = it.g.get(name)
    try:
        r = None
        for v in list(lst):
            it.g[name] = v
            for f in x[3:]:
                r = it.eval(f)
        return r
    finally:
        it.g[name] = old


def sf_and(it, x):
    r = T
    for f in x[1:]:
        r = it.eval(f)
        if not truthy(r):
            return None
    return r


def sf_or(it, x):
    for f in x[1:]:
        r = it.eval(f)
        if truthy(r):
            return r
    return None


SPECIAL = {
    "QUOTE": sf_quote, "FUNCTION": sf_function, "LAMBDA": sf_lambda,
    "DEFUN": sf_defun, "SETQ": sf_setq, "IF": sf_if, "COND": sf_cond,
    "PROGN": sf_progn, "WHILE": sf_while, "REPEAT": sf_repeat,
    "FOREACH": sf_foreach, "AND": sf_and, "OR": sf_or,
}
