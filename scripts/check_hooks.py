#!/usr/bin/env python3
"""
Catch the two ways a React hook gets called conditionally.

Both of these shipped to production in one afternoon and blanked /timesheet with
React #310 ("rendered more hooks than during the previous render"):

  1. a hook declared BELOW an early return — `if (loading) return ...` and then a
     useEffect further down. It runs on some renders and not others.
  2. a hook called inside an expression — `cond ? useThing().get(x) : 0`.

Neither is a type error, so `tsc` is silent about both and the failure only
appears as a white page. This exists because the project has no eslint;
react-hooks/rules-of-hooks does this properly and should replace it if eslint
ever lands.

Bodies are found by tracking brace depth from a component/hook declaration, so a
small component defined above a big one does not make the big one look broken.
Only guards and hooks at the body's OWN top level count — a `return` inside a
nested callback is not an early return from the component.

    python3 scripts/check_hooks.py frontend/src
"""
import re
import sys
from pathlib import Path

DECL = re.compile(
    r'^(?:export\s+)?(?:const\s+(?P<c>[A-Z]\w*|use[A-Z]\w*)\s*[:=]|'
    r'function\s+(?P<f>[A-Z]\w*|use[A-Z]\w*)\s*\()'
)
HOOK_CALL = re.compile(r'\buse[A-Z]\w*\s*\(')
GUARD = re.compile(r'^\s*(?:if\s*\([^)]*\)\s*(?:\{\s*)?return\b|return\b)')
CODE_ONLY = re.compile(r'//.*$')


def _depth_delta(line: str) -> int:
    line = CODE_ONLY.sub('', line)
    line = re.sub(r'"[^"]*"|\'[^\']*\'|`[^`]*`', '', line)
    return line.count('{') - line.count('}')


def check(path: Path):
    lines = path.read_text(errors='ignore').split('\n')
    problems = []

    i = 0
    while i < len(lines):
        if not DECL.match(lines[i]):
            i += 1
            continue
        # Walk the body, tracking depth. Body top level is depth 1.
        depth = 0
        started = False
        guard_line = None
        j = i
        while j < len(lines):
            before = depth
            depth += _depth_delta(lines[j])
            if not started and depth > 0:
                started = True
            elif started and depth <= 0:
                break

            if started and j > i and before == 1:
                stripped = lines[j].strip()
                if guard_line is None and not stripped.startswith('//'):
                    # `if (...) return x;` on one line, or a bare early `return`.
                    if GUARD.match(lines[j]):
                        guard_line = j + 1
                    # `if (...) {` opening a block that returns — the common form,
                    # and the one that blanked /timesheet. Scan just that block.
                    elif re.match(r'^\s*if\s*\(', lines[j]):
                        d2, k = 0, j
                        opened = False
                        while k < len(lines):
                            d2 += _depth_delta(lines[k])
                            if not opened and d2 > 0:
                                opened = True
                            elif opened and d2 <= 0:
                                break
                            if opened and re.match(r'^\s*return\b', lines[k]):
                                guard_line = k + 1
                                break
                            k += 1
                elif guard_line is not None and HOOK_CALL.search(lines[j]) \
                        and not stripped.startswith('//') and not stripped.startswith('*'):
                    problems.append((j + 1, f'hook below the early return on line {guard_line}',
                                     stripped[:88]))
                    break
            j += 1
        i = max(j, i + 1)

    # ── hooks inside a conditional expression ───────────────────────────────
    for n, l in enumerate(lines):
        stripped = l.strip()
        if stripped.startswith('//') or stripped.startswith('*'):
            continue
        for m in HOOK_CALL.finditer(CODE_ONLY.sub('', l)):
            before = l[:m.start()]
            if re.search(r'(\?|&&|\|\|)\s*\(?\s*$', before):
                problems.append((n + 1, 'hook inside a conditional expression', stripped[:88]))
                break
    return sorted(set(problems))


def main(argv):
    roots = [Path(p) for p in (argv[1:] or ['frontend/src'])]
    files = [f for r in roots for f in r.rglob('*.tsx')]
    bad = 0
    for f in sorted(files):
        for line, why, src in check(f):
            print(f"{f}:{line}: {why}\n    {src}")
            bad += 1
    if bad:
        print(f"\n{bad} possible rules-of-hooks violation(s) — each one a candidate white screen.")
        return 1
    print(f"checked {len(files)} .tsx files — no conditional hooks found")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
