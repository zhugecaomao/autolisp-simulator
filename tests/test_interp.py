import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lispsim import Interp, MockCad, ScriptedInputs, ESC  # noqa: E402
from lispsim.harness import session, snapshot, diff_geometry  # noqa: E402


def ev(text, **kw):
    it = Interp(cad=MockCad(inputs=ScriptedInputs(**kw)))
    return it, it.run_text(text)


class Core(unittest.TestCase):
    def test_integer_and_real_arithmetic(self):
        self.assertEqual(ev("(/ 5 2)")[1], 2)
        self.assertEqual(ev("(/ 5 2.0)")[1], 2.5)
        self.assertEqual(ev("(+ 1 2.5)")[1], 3.5)
        self.assertEqual(ev("(fix 2.7)")[1], 2)
        self.assertEqual(ev('(rtos 450 2 0)')[1], "450")

    def test_symbols_are_case_insensitive_and_lists_work(self):
        self.assertEqual(ev("(setq Abc (list 1 2 3)) (nth 1 aBC)")[1], 2)
        self.assertEqual(ev("(cdr (assoc 40 (quote ((0 . \"ARC\") (40 . 5.0)))))")[1], 5.0)
        self.assertEqual(ev("(mapcar '1+ '(1 2 3))")[1], [2, 3, 4])

    def test_dynamic_scoping(self):
        # a called function sees the caller's local variable (this is how the PT code works)
        r = ev("(defun inner () x) (defun outer (/ x) (setq x 7) (inner)) (outer)")[1]
        self.assertEqual(r, 7)

    def test_locals_are_restored(self):
        it, _ = ev("(setq x 1) (defun f (/ x) (setq x 2)) (f)")
        self.assertEqual(it.g["X"], 1)

    def test_comments_and_strings(self):
        self.assertEqual(ev('(strcat "a;b" "c") ; trailing\n;| block\n comment |;')[1], "a;bc")

    def test_setvar_checks_types(self):
        it = Interp(cad=MockCad())
        status = it.run_text('(defun c:t () (setvar "textstyle" nil)) 1')
        self.assertEqual(it.run_command("t")[0], "error")


class Errors(unittest.TestCase):
    def test_error_handler_runs_at_the_point_of_error_with_locals_visible(self):
        it = Interp(cad=MockCad())
        it.run_text("""
          (defun c:t (/ old *error*)
            (setq old 42)
            (defun *error* (msg) (setq seen (list msg old)))
            (car 5))""")
        self.assertEqual(it.run_command("t")[0], "error")
        self.assertEqual(it.g["SEEN"][1], 42)

    def test_catch_all_apply_does_not_call_the_handler(self):
        it = Interp(cad=MockCad())
        it.run_text("(defun *error* (m) (setq called T))")
        it.run_text("(setq r (vl-catch-all-apply 'car (list 5)))")
        self.assertIsNone(it.g.get("CALLED"))
        self.assertTrue(it.run_text("(vl-catch-all-error-p r)"))


class Cad(unittest.TestCase):
    def test_relative_coordinates_and_copy(self):
        it, _ = ev('(command "line" (list 0 0) "@100<90" "") (command "copy" "l" "" "0,0" "@50,0")')
        ents = it.cad.entities
        self.assertEqual([e["type"] for e in ents], ["LINE", "LINE"])
        self.assertAlmostEqual(ents[0]["q"][1], 100.0)
        self.assertAlmostEqual(ents[1]["p"][0], 50.0)

    def test_snap_violation_is_recorded(self):
        it, _ = ev('(command "line" (list 0 0) (list 1 0) "")')
        self.assertEqual(len(it.cad.snap_violations), 1)
        it, _ = ev('(setvar "osmode" 0) (command "line" (list 0 0) (list 1 0) "")')
        self.assertEqual(it.cad.snap_violations, [])

    def test_empty_text_creates_nothing(self):
        it, _ = ev('(command "text" "J" "c" (list 0 0) 100 "0" "")')
        self.assertEqual(it.cad.entities, [])

    def test_dialog_callbacks_run_with_scripted_values(self):
        d = Path(__file__).parent / "demo.dcl"
        it = Interp(search_path=[d.parent], cad=MockCad(inputs=ScriptedInputs(dialogs=[{"len": "123"}])))
        it.run_text('''(defun c:t (/ id) (setq id (load_dialog "demo.dcl")) (new_dialog "demo" id)
                         (action_tile "len" "(setq L (atof $value))") (start_dialog) (unload_dialog id) L)''')
        self.assertEqual(it.run_command("t"), ("ok", 123.0))

    def test_esc_cancels_the_nth_input(self):
        it = Interp(cad=MockCad(inputs=ScriptedInputs(rules=[("getpoint", None, [0, 0])], esc_at=1)))
        it.run_text('(defun c:t () (getpoint "p"))')
        self.assertEqual(it.run_command("t"), ("error", "Function cancelled"))


class Golden(unittest.TestCase):
    def test_snapshot_and_diff(self):
        it, _ = ev('(setvar "osmode" 0) (command "line" (list 0 0) (list 10 0) "") '
                   '(command "point" (list 5 5)) (command "text" "J" "c" (list 1 1) 2.5 "90" "hi")')
        snap = snapshot(it.cad)
        self.assertEqual(diff_geometry(snap, snap), [])
        other = dict(snap, points=[[5, 6]])
        self.assertTrue(diff_geometry(snap, other))


if __name__ == "__main__":
    unittest.main()
