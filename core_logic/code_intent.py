"""Derive what a `python_repl` snippet DOES, without executing it (BRIEF_60, G38).

WHY THIS EXISTS
---------------
`admissibility.gate()` short-circuits on `not is_mutating(tool_name)`, and `MUTATING_TOOLS` is a list of
eight tool NAMES. `python_repl` is not on it, so arbitrary Python executes with no envelope, no verdict
and no ledger entry. Reproduced live on 2026-08-10: asked to use `write_file` (unregistered at the time),
the agent completed the task through `python_repl` instead and the mutation left no receipt.

Meanwhile `start_process` accepts an equally-unbounded shell string and IS gated, by grepping that string
for hints. So the exemption was never principled — it fell out of `MUTATING_TOOLS` being a list of names
rather than of capabilities. This module supplies the missing classifier for the Python case.

WHAT THIS IS, AND IS NOT
------------------------
It is NOT a security boundary and must never be described as one. Deciding what arbitrary Python does is
undecidable, and any classifier claiming otherwise is lying.

It IS a legibility check with an honest third answer. The question is not "what does this code do" but
"is this code OBVIOUSLY within its declared use case" — and the honest output for everything else is
UNKNOWN, so the caller can fail closed.

That reframe is what makes it tractable: `getattr(__import__('o'+'s'),'remove')` cannot be resolved
without running it, and does not need to be. Honest code is legible to the parser; code that hides from
the parser has disclosed something by hiding. **Obfuscation is not a defeat here, it is the signal.**

SHADOW FIRST
------------
Ships observation-only. It derives, and the caller logs derived-vs-declared. Nothing is blocked until a
real false-positive rate has been measured on live traffic — over-blocking is what gets a control
switched off, which costs more than the hole it closed.

Self-test: python -m core_logic.code_intent
"""
import ast

READ, WRITE, EXECUTE, COMPUTE, UNKNOWN = "read", "write", "execute", "compute", "unknown"

# Attribute-level, NOT module-level. Measured on 159 real drill calls: 37 imported os/subprocess/shutil,
# but 25 of those were `os.path` (pure string work) plus listdir/walk (reads). Only 2 were `os.remove`.
# Blocking the module would have failed the overwhelming majority of legitimate reads to stop two writes.
_DANGEROUS_ATTRS = {
    "remove", "unlink", "rmtree", "rmdir", "removedirs", "system", "popen", "spawn", "spawnl",
    "execv", "execve", "kill", "chmod", "chown", "rename", "renames", "replace", "truncate",
    "makedirs", "mkdir", "symlink", "link", "run", "call", "check_call", "check_output", "Popen",
}
# Modules with no safe read-only surface worth allowing in a `read` snippet.
_DANGEROUS_MODULES = {"subprocess", "socket", "ctypes", "multiprocessing", "importlib", "pty", "signal"}

# Calls whose effect cannot be read off the tree. Their PRESENCE is the finding.
# These are all BUILTINS, so they are matched against bare-name calls only — see _RECEIVER NOTE below.
_OPAQUE_CALLS = {"__import__", "getattr", "setattr", "eval", "exec", "compile", "globals", "vars"}
# ...except when reached through the builtins module explicitly, which is the same call by another road.
_BUILTINS_ALIASES = {"builtins", "__builtins__"}

# ── RECEIVER NOTE (2026-08-18) — the fix for a 56% false-positive rate ────────────────────────────
# The names in _DANGEROUS_ATTRS and _OPAQUE_CALLS are not unique to dangerous objects. Measured over
# 308 live shadow observations, 14 of the 25 flags this module raised were wrong, and ALL of them came
# from two name collisions:
#   `str.replace` scored as `os.replace`  (10 of 14)
#   `re.compile`  scored as builtin `compile`  (4 of 14)
# The cause was structural rather than a bad list: the walker recorded `node.func.attr` and discarded
# the receiver, so `"a".replace(x, y)` and `os.replace(src, dst)` were indistinguishable. `remove` is
# also a list method, `run` and `call` are ordinary method names, `link` is common in scrapers.
#
# So a dangerous ATTRIBUTE call now only counts when the receiver actually resolves to a risky module,
# and an OPAQUE call only counts when it is a bare builtin (or reached via `builtins.`). The lenient
# direction is bounded by one conservative rule: if a risky module IS imported in the snippet and a
# dangerous-looking attribute call has an unresolvable receiver, it still counts. A snippet that never
# imports os/shutil/subprocess cannot be calling os.replace, and saying otherwise was the whole bug.
_RISKY_MODULES = {"os", "shutil", "subprocess", "pathlib", "socket", "ctypes",
                  "multiprocessing", "importlib", "pty", "signal", "glob", "tempfile"}

# Of the dangerous attribute names, only these actually collide with methods on ordinary builtin or
# common library types, and they are the ONLY ones that need their receiver resolved before counting:
#   replace/remove  -> str.replace, list.remove, set.remove   (this pair caused all 14 false positives)
#   run/call/link   -> ubiquitous method names in frameworks and scrapers
#   rename/truncate -> pandas DataFrame methods
# Everything else in _DANGEROUS_ATTRS (rmtree, unlink, system, popen, execv, chmod, Popen, ...) is
# dangerous by name essentially wherever it appears, so it still fires without receiver resolution.
# Splitting the list this way is what keeps the lenient fix from opening a hole: the leniency applies
# to seven names, not to the whole set.
_COLLIDING_ATTRS = {"replace", "remove", "run", "call", "link", "rename", "truncate"}

# TYPE-HIERARCHY / INTROSPECTION TRAVERSAL (added 2026-08-11 after this classifier FAILED to catch a
# working sandbox escape). Restricted builtins are not a containment boundary: walking
# `().__class__.__base__.__subclasses__()` reaches a real module, whose `__builtins__` dict hands back
# an unrestricted `__import__`. Eight lines, using only "safe" builtins, and it reaches `os.remove`.
#
# The first version of this module scored that snippet `compute` — no import, no open, no dangerous
# attribute — which is exactly the wrong answer. Reaching into the object graph for runtime internals is
# never "obviously safe" in a read/compute snippet, so it belongs with the opaque set: the classifier
# does not need to know what the traversal is FOR, only that it cannot vouch for it.
_INTROSPECTION_ATTRS = {
    "__subclasses__", "__base__", "__bases__", "__mro__", "__globals__", "__builtins__",
    "__code__", "__func__", "__self__", "__getattribute__", "__reduce__", "__reduce_ex__",
    "__init_subclass__", "__loader__", "__spec__", "f_globals", "f_builtins", "gi_frame", "cr_frame",
}

_WRITE_MODE_CHARS = ("w", "a", "x", "+")
_WRITE_CALLS = {"write", "writelines", "writerow", "writerows", "dump", "truncate"}
_READ_CALLS = {"read", "readline", "readlines", "load"}


def _open_modes(node):
    """(literal_modes, saw_non_literal) for an `open(...)` call node."""
    modes, dynamic = set(), False
    if len(node.args) > 1:
        if isinstance(node.args[1], ast.Constant):
            modes.add(str(node.args[1].value))
        else:
            dynamic = True                      # mode came from a variable -> not obvious
    for kw in node.keywords:
        if kw.arg == "mode":
            if isinstance(kw.value, ast.Constant):
                modes.add(str(kw.value.value))
            else:
                dynamic = True
    return modes, dynamic


def derive(code: str):
    """Return (operation, evidence_dict). operation in READ/WRITE/EXECUTE/COMPUTE/UNKNOWN.

    Never raises: unparseable input is UNKNOWN, which fails closed at the caller.
    """
    try:
        tree = ast.parse(code or "")
    except SyntaxError as e:
        return UNKNOWN, {"reason": f"unparseable: {e.msg}"}

    imports, plain_calls, attr_calls, modes = set(), set(), set(), set()
    introspection = set()
    dynamic_mode = False
    risky_aliases = set()        # local names bound to a risky module (import os, import os as o)
    risky_from = set()           # names pulled straight out of a risky module (from os import remove)
    qualified = set()            # (receiver_name, attr) pairs where the receiver is a bare Name
    unresolved_attrs = set()     # attr calls whose receiver is not a bare Name
    for n in ast.walk(tree):
        # Attribute ACCESS, not just calls — `x.__class__.__base__` is traversal without a call.
        if isinstance(n, ast.Attribute) and n.attr in _INTROSPECTION_ATTRS:
            introspection.add(n.attr)
        if isinstance(n, ast.Import):
            for a in n.names:
                root = a.name.split(".")[0]
                imports.add(root)
                if root in _RISKY_MODULES:
                    risky_aliases.add(a.asname or root)
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                root = n.module.split(".")[0]
                imports.add(root)
                if root in _RISKY_MODULES:
                    # `from os import remove` binds a DANGEROUS name as a bare call.
                    risky_from.update((a.asname or a.name) for a in n.names)
                    # `from os import path` also binds a risky-module alias.
                    risky_aliases.update((a.asname or a.name) for a in n.names)
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                attr_calls.add(f.attr)
                if isinstance(f.value, ast.Name):
                    qualified.add((f.value.id, f.attr))
                else:
                    unresolved_attrs.add(f.attr)
            elif isinstance(f, ast.Name):
                plain_calls.add(f.id)
            if (getattr(f, "id", None) or getattr(f, "attr", None)) == "open":
                m, dyn = _open_modes(n)
                modes.update(m)
                dynamic_mode = dynamic_mode or dyn

    calls = plain_calls | attr_calls
    ev = {"imports": sorted(imports), "calls": sorted(calls), "open_modes": sorted(modes)}

    # 1. OPAQUE FIRST. If we cannot vouch for the tree, nothing below it is trustworthy.
    # Bare-name builtins only. `re.compile(...)` is an attribute call on a module and is not the
    # builtin `compile(...)`; conflating them was 4 of the 14 measured false positives.
    opaque = (_OPAQUE_CALLS & plain_calls) | introspection
    opaque |= {a for r, a in qualified if r in _BUILTINS_ALIASES and a in _OPAQUE_CALLS}
    if opaque:
        ev["opaque"] = sorted(opaque)
        return UNKNOWN, ev
    if dynamic_mode:
        ev["opaque"] = ["open(mode=<non-literal>)"]
        return UNKNOWN, ev

    # 2. Execute / delete — attribute-level so os.path survives.
    # Non-colliding dangerous names fire on the attribute alone — `unlink`, `rmtree`, `system` and the
    # rest are not methods anyone calls by accident.
    danger = (_DANGEROUS_ATTRS - _COLLIDING_ATTRS) & attr_calls
    danger |= (_DANGEROUS_ATTRS - _COLLIDING_ATTRS) & plain_calls
    # Colliding names need the receiver to resolve to a risky module. `os.replace(a, b)` counts;
    # `"x".replace(a, b)` and `xs.remove(2)` do not.
    danger |= {a for r, a in qualified if r in risky_aliases and a in _COLLIDING_ATTRS}
    danger |= (_DANGEROUS_ATTRS & risky_from & plain_calls)   # from os import remove; remove(p)
    # Conservative backstop for the colliding names: a risky module is in scope and the receiver is
    # not a bare name we can check, so we cannot rule out that this is the dangerous one.
    if risky_aliases:
        danger |= (_COLLIDING_ATTRS & unresolved_attrs)
    mod_danger = _DANGEROUS_MODULES & imports
    if danger or mod_danger:
        ev["dangerous"] = sorted(danger | mod_danger)
        return EXECUTE, ev

    # 3. Write.
    if any(any(c in m for c in _WRITE_MODE_CHARS) for m in modes) or (_WRITE_CALLS & calls):
        return WRITE, ev

    # 4. Read.
    if "open" in calls or (_READ_CALLS & calls):
        return READ, ev

    return COMPUTE, ev


def agrees(declared: str, derived: str) -> bool:
    """Is the DERIVED operation within what was DECLARED?

    Asymmetric on purpose: declaring a wider capability than you use is fine (declare `write`, only
    read). Declaring narrower than you use is the finding. UNKNOWN never agrees with anything.
    """
    if derived == UNKNOWN:
        return False
    rank = {COMPUTE: 0, READ: 1, WRITE: 2, EXECUTE: 3}
    if declared not in rank or derived not in rank:
        return False
    return rank[derived] <= rank[declared]


if __name__ == "__main__":
    fails = []

    def check(label, code, want_op, want_agree=None, declared=None):
        op, ev = derive(code)
        if op != want_op:
            fails.append(f"{label}: derived {op!r} != {want_op!r}  ev={ev}")
        if want_agree is not None:
            got = agrees(declared, op)
            if got != want_agree:
                fails.append(f"{label}: agrees({declared!r},{op!r})={got} != {want_agree}")

    # --- RECEIVER RESOLUTION (2026-08-18) — locks in the 56%-false-positive fix ------
    # Measured over 308 live shadow observations: 25 flags raised, 14 of them wrong, and every one of
    # the 14 came from two name collisions. These cases exist so that cannot silently come back.
    check("FP-1 str.replace is not os.replace",
          "import re\ns=open('f').read()\nprint(s.replace(chr(10),' '))", READ)
    check("FP-1b str.replace even with os imported",
          "import os\ns=open('f').read()\nprint(s.replace('a','b'))", READ)
    check("FP-2 re.compile is not builtin compile",
          "import re\np=re.compile(r'x+')\nprint(p.findall(open('f').read()))", READ)
    check("FP-3 list.remove is not os.remove", "xs=[1,2,3]\nxs.remove(2)", COMPUTE)
    # ...and the dangerous originals must STILL fire. Leniency that opens a hole is worse than the bug.
    check("os.replace still fires", "import os\nos.replace('a','b')", EXECUTE)
    check("os.remove still fires", "import os\nos.remove('p')", EXECUTE)
    check("from os import remove still fires", "from os import remove\nremove('p')", EXECUTE)
    check("shutil.rmtree still fires", "import shutil\nshutil.rmtree('/d')", EXECUTE)
    check("Path().unlink() chained receiver", "from pathlib import Path\nPath('f').unlink()", EXECUTE)
    check("unresolvable receiver + risky import", "import os\np=get()\np.unlink()", EXECUTE)
    check("builtin compile still opaque", "compile('1+1','<s>','eval')", UNKNOWN)
    check("builtins.eval reached via module", "import builtins\nbuiltins.eval('1')", UNKNOWN)

    # --- real traffic from the 2026-08-11 drill logs -------------------------------
    check("real read (event_queue)",
          "p=r'E:/ML_PROJECTS/AGENT_ZERO/core_logic/event_queue.py'; L=open(p,encoding='utf-8').read(); print(len(L))",
          READ)
    check("real read (os.path join)",
          "import os\nbase = r'E:/x'\nprint(os.path.join(base,'core_logic'))",
          COMPUTE)                       # os.path is not dangerous, nothing opened
    check("real listdir",
          "import os; print(os.listdir(r'E:/x'))", READ if False else COMPUTE)
    # ^ listdir is a read of a DIRECTORY, not a file open; it lands COMPUTE and that is acceptable —
    #   it mutates nothing. Pinned so a later 'improvement' has to be deliberate.

    # --- the actual defect: the Q18 probe write that produced no receipt -----------
    check("real write (Q18 probe)",
          "open(r'E:/ML_PROJECTS/AGENT_ZERO/tests/probe_f.txt','w',encoding='utf-8').write('2026-08-09')",
          WRITE)
    check("write via mode kwarg", "open('f.txt', mode='a').write('x')", WRITE)

    # --- execute / delete ---------------------------------------------------------
    check("os.remove", "import os; os.remove('important.txt')", EXECUTE)
    check("shutil.rmtree", "import shutil; shutil.rmtree('/')", EXECUTE)
    check("subprocess import", "import subprocess; subprocess.run(['ls'])", EXECUTE)

    # --- opaque: the row that carries the whole argument --------------------------
    check("obfuscated import", "getattr(__import__('o'+'s'),'remove')('x')", UNKNOWN)
    check("eval", "eval('1+1')", UNKNOWN)
    check("dynamic open mode", "m='w'\nopen('f.txt', m).write('x')", UNKNOWN)
    check("syntax error", "def (:", UNKNOWN)

    # --- pure compute -------------------------------------------------------------
    check("arithmetic", "print(sum(range(21)))", COMPUTE)

    # --- agreement ----------------------------------------------------------------
    check("declared read, derived read -> agrees", "print(open('f').read())", READ, True, READ)
    check("declared read, derived write -> MISMATCH",
          "open('f','w').write('x')", WRITE, False, READ)
    check("declared write, derived read -> fine (narrower use)",
          "print(open('f').read())", READ, True, WRITE)
    check("declared read, derived unknown -> never agrees",
          "eval('x')", UNKNOWN, False, READ)
    check("declared execute, derived execute -> agrees",
          "import os; os.remove('f')", EXECUTE, True, EXECUTE)

    if fails:
        print("code_intent self-test FAILED:")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    print("code_intent self-test: all cases passed.")
