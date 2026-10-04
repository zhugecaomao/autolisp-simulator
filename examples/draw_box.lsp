;; A tiny drawing command with the classic snap problem: it switches object snap
;; off while drawing and relies on reaching the last line to switch it back on.
(defun c:boxbad (/ p1 p2 old)
  (setq old (getvar "osmode"))
  (setq p1 (getpoint "\nFirst corner: "))
  (setvar "osmode" 0)
  (setq p2 (getpoint "\nOpposite corner: "))   ; ESC here leaves OSMODE at 0
  (command "line" p1 (list (car p2) (cadr p1)) p2 (list (car p1) (cadr p2)) p1 "")
  (setvar "osmode" old)
  (princ))

;; The same command with a local *error* handler.
(defun c:boxgood (/ p1 p2 old *error*)
  (setq old (getvar "osmode"))
  (defun *error* (msg) (setvar "osmode" old) (princ))
  (setq p1 (getpoint "\nFirst corner: "))
  (setvar "osmode" 0)
  (setq p2 (getpoint "\nOpposite corner: "))
  (command "line" p1 (list (car p2) (cadr p1)) p2 (list (car p1) (cadr p2)) p1 "")
  (setvar "osmode" old)
  (princ))
