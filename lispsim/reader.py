"""AutoLISP reader: text -> Python data (lists, Sym, int, float, str)."""
import re
from .types import Sym, DPair, sym, LispError

_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
_DELIM = set(" \t\r\n\f()'\";")


def _unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c != "\\" or i + 1 >= len(s):
            out.append(c)
            i += 1
            continue
        n = s[i + 1]
        if n in "nN":
            out.append("\n"); i += 2
        elif n in "rR":
            out.append("\r"); i += 2
        elif n in "tT":
            out.append("\t"); i += 2
        elif n in "eE":
            out.append("\x1b"); i += 2
        elif n.isdigit():
            j = i + 1
            while j < len(s) and j < i + 4 and s[j] in "01234567":
                j += 1
            out.append(chr(int(s[i + 1:j], 8))); i = j
        else:
            out.append(n); i += 2
    return "".join(out)


def parse_atom(tok):
    if _INT.match(tok):
        return int(tok)
    if _FLOAT.match(tok):
        return float(tok)
    return sym(tok)


def read_all(text):
    """Parse every top-level form in `text`."""
    pos, n, forms = 0, len(text), []
    stack = []  # open lists

    def emit(x):
        if stack:
            stack[-1].append(x)
        else:
            forms.append(x)

    quote_pending = []  # per-depth count of pending quotes
    qstack = [0]

    def apply_quotes(x):
        while qstack[-1] > 0:
            qstack[-1] -= 1
            x = [sym("QUOTE"), x]
        return x

    while pos < n:
        c = text[pos]
        if c in " \t\r\n\f":
            pos += 1
        elif c == ";":
            if text.startswith(";|", pos):
                j = text.find("|;", pos + 2)
                pos = n if j < 0 else j + 2
            else:
                j = text.find("\n", pos)
                pos = n if j < 0 else j
        elif c == "(":
            stack.append([]); qstack.append(0); pos += 1
        elif c == ")":
            if not stack:
                raise LispError("reader: extra ')' near char %d" % pos)
            lst = stack.pop(); qstack.pop(); pos += 1
            # dotted pair  (a . b)
            if len(lst) == 3 and lst[1] is _DOT:
                lst = DPair(lst[0], lst[2])
            emit(apply_quotes(lst))
        elif c == "'":
            qstack[-1] += 1; pos += 1
        elif c == '"':
            j = pos + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            emit(apply_quotes(_unescape(text[pos + 1:j]))); pos = j + 1
        else:
            j = pos
            while j < n and text[j] not in _DELIM:
                j += 1
            tok = text[pos:j]; pos = j
            if tok == ".":
                emit(_DOT)
            else:
                emit(apply_quotes(parse_atom(tok)))
    if stack:
        raise LispError("reader: %d unclosed '('" % len(stack))
    return forms


_DOT = object()
