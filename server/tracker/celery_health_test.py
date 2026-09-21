"""
Tests for the Celery task audit.

This check exists because the same bug has now landed three times — a
@shared_task in a module autodiscover_tasks() does not walk, so the worker
never registers it. tasks_mail.py cost four months of discarded mail syncs;
sync_clio_full spent a month advertising a schedule that did not exist; and
the audit added alongside these tests found a third (cch_axcess) already
sitting in the tree.

So the thing under test is a safety net, and the failure mode that matters
most is the one where a safety net reports success without having looked at
anything. Hence the emphasis below on: does it actually find files, from any
working directory, and does it still fail when it should.

DATABASE-FREE — these run via `manage.py shell`, which in this deployment is
wired to the live production database.

    python manage.py shell -c "import tracker.celery_health_test"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = _skipped = 0


def _raises(fn):
    """True when fn() raises — used to assert a check fails loudly."""
    try:
        fn()
    except Exception:
        return True
    return False


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


try:
    import ast
    import tempfile

    from tracker.celery_health import (
        _task_name_from_node,
        declared_task_names,
        unregistered_declared_tasks,
        unregistered_scheduled_tasks,
    )
    from celery_app import app
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("Celery health:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    def name_of(src, module='tracker.somewhere'):
        node = ast.parse(src).body[0]
        return _task_name_from_node(node, module)

    print("Celery health — reading a task's registered name:")
    check("explicit name= wins",
          name_of("@shared_task(name='tracker.foo')\ndef f(): pass") == 'tracker.foo')
    check("bare decorator falls back to module.function",
          name_of("@shared_task\ndef f(): pass") == 'tracker.somewhere.f')
    check("decorator with other kwargs but no name still falls back",
          name_of("@shared_task(bind=True, max_retries=2)\ndef f(): pass")
          == 'tracker.somewhere.f')
    check("dotted form (celery.shared_task) is recognised",
          name_of("@celery.shared_task(name='tracker.bar')\ndef f(): pass")
          == 'tracker.bar')
    check("app.task form is recognised",
          name_of("@app.task(name='tracker.baz')\ndef f(): pass") == 'tracker.baz')
    check("an ordinary decorated function is not a task",
          name_of("@login_required\ndef f(): pass") is None)
    check("an undecorated function is not a task",
          name_of("def f(): pass") is None)
    check("a task among other decorators is still found",
          name_of("@login_required\n@shared_task(name='tracker.qux')\ndef f(): pass")
          == 'tracker.qux')

    print("\nCelery health — the audit must actually look at files:")
    declared = declared_task_names()
    # The exact number will drift; what must never happen is zero. os.walk on a
    # missing path yields nothing and raises nothing, so "found none" is what a
    # silently broken audit looks like.
    check("finds a substantial number of declarations", len(declared) > 20)
    check("finds tasks defined in tracker/tasks.py itself",
          any(v.startswith('tracker/tasks.py') for v in declared.values()))
    check("finds tasks defined OUTSIDE tasks.py (the whole point)",
          any(not v.startswith('tracker/tasks.py') for v in declared.values()))
    check("every entry carries a path:line",
          all(':' in v and v.rsplit(':', 1)[1].isdigit() for v in declared.values()))

    # Independent of cwd: CI runs it from server/, a developer may not.
    _cwd = os.getcwd()
    try:
        os.chdir(tempfile.gettempdir())
        from_elsewhere = declared_task_names()
    finally:
        os.chdir(_cwd)
    check("finds the same declarations from an unrelated cwd",
          from_elsewhere == declared)

    check("a missing package dir raises rather than reporting a clean tree",
          _raises(lambda: declared_task_names('/nonexistent/path/xyz')))

    print("\nCelery health — migrations are excluded:")
    check("no migration file is audited",
          not any('/migrations/' in v for v in declared.values()))

    print("\nCelery health — the tree is currently clean:")
    check("no scheduled task is unregistered", unregistered_scheduled_tasks(app) == {})
    check("no declared task is unregistered", unregistered_declared_tasks(app) == {})

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
