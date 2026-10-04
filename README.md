# autolisp-simulator

A small AutoLISP interpreter (pure Python, no dependencies) with a mock CAD, so AutoLISP programs can be
**run, tested and debugged without AutoCAD** - locally and in CI.

一个用 Python 写的 AutoLISP 解释器,外加一个模拟的 CAD 环境。没有 AutoCAD 也能运行、测试、调试 AutoLISP 程序,
可以放进 GitHub Actions 自动跑。

It was written to test a real production tool (PT tendon profile commands, about 5000 lines of AutoLISP with
DCL dialogs) and to chase one specific AutoCAD problem: *a program turns object snap off to draw, gets
interrupted, and the user's snap setting is lost.* `examples/esc_sweep.py` shows this bug being found.

## What it does

- **AutoLISP core**: dynamic scoping (a called function sees the caller's locals, as in AutoCAD),
  `defun` / `lambda` / `cond` / `foreach` / `repeat` / `while`, lists and dotted pairs, strings, integer vs
  real arithmetic, `assoc`, `mapcar`, `vl-catch-all-apply`, file I/O, `load` ...
- **Errors like AutoCAD**: `*error*` is called *at the point of the error*, before the stack unwinds, so a
  local `*error*` can still see the function's local variables. `vl-catch-all-apply` does not call it.
- **System variables with type checks**: `(setvar "textstyle" nil)` is an error, as in AutoCAD.
- **`(command ...)`**: LINE, POINT, CIRCLE, TEXT, COPY, ERASE, CHPROP, STYLE, LAYER, ZOOM, with relative
  coordinates (`"@800<90"`, `"0,0"`) measured from LASTPOINT. Other commands are logged in
  `cad.unknown_commands`.
- **Dialogs**: DCL files are parsed for dialog names and keys; `start_dialog` runs your `action_tile`
  callbacks with scripted values.
- **Scripted input**: answers for `getpoint` / `getkword` / `getint` / ... come from `ScriptedInputs`.
  `esc_at=n` presses ESC at the n-th input, so *"ESC at every prompt"* is a loop.
- **Snap check**: every drawing command is checked against OSMODE; `cad.snap_violations` lists drawings made
  while object snap was on (AutoCAD can place such geometry wrongly).
- **Golden drawings**: compare what the program drew with a drawing made by the real AutoCAD
  (`lispsim.harness.snapshot` / `diff_geometry`, and `python3 -m lispsim.extract_golden` to turn a DXF into JSON).

## What it cannot do

It is not AutoCAD. Geometry comes from a model of each command, dialogs have no layout, and ActiveX
(`vlax-*`) is not implemented. A passing test means "same drawing as the golden AutoCAD result and correct
behaviour on ESC", not "works in every AutoCAD version". Compiling VLX and dialog appearance still need AutoCAD.

## Quick start

```python
from lispsim import ScriptedInputs
from lispsim.harness import session

inputs = ScriptedInputs(rules=[("getpoint", None, [0, 0]), ("getpoint", None, [100, 50])])
it, cad = session(inputs, search_path=["examples"], entry="draw_box.lsp")
print(it.run_command("boxgood"))          # ('ok', None)
print(cad.entities, cad.osmode_history, cad.snap_violations)
```

```
python3 examples/esc_sweep.py             # ESC at every prompt: boxbad leaves OSMODE stuck at 0, boxgood does not
python3 -m unittest discover -s tests -v
```

Answer `ScriptedInputs` with ordered rules `(kind, prompt_regex, value)`, a `fallback(kind, prompt)` function,
dialog dictionaries `{"key": "value"}`, and `ESC` / `esc_at`.

## Extending

Functions live in `lispsim/builtins.py` (standard library) and `lispsim/cad.py` (CAD-specific: `command`,
dialogs, input, entities). If a program uses something that is missing you get an AutoLISP error such as
`no function definition: FOO` - add it there.

## License

[GPL-3.0](LICENSE) (c) zhugecaomao
