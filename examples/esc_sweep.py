"""Press ESC at every prompt of a command and check that OSMODE comes back.

    python3 examples/esc_sweep.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from lispsim import ScriptedInputs  # noqa: E402
from lispsim.harness import session  # noqa: E402

OSMODE = 4133


def run(command, esc_at=None):
    inputs = ScriptedInputs(rules=[("getpoint", None, [0, 0]), ("getpoint", None, [100, 50])], esc_at=esc_at)
    it, cad = session(inputs, [HERE], entry="draw_box.lsp", osmode=OSMODE)
    return cad, inputs, it.run_command(command)


for command in ("boxbad", "boxgood"):
    cad, inputs, res = run(command)
    print("%s: normal run -> %s, %d lines, final OSMODE %s" % (command, res[0], len(cad.entities), cad.osmode))
    for n in range(1, inputs.count + 1):
        cad, inputs2, res = run(command, esc_at=n)
        verdict = "ok" if cad.osmode == OSMODE else "STUCK at %s" % cad.osmode
        print("    ESC at prompt #%d (%s): OSMODE %s" % (n, inputs2.history[n - 1][1].strip(), verdict))
