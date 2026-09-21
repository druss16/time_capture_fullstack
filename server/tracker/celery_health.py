"""Does every scheduled task exist on the worker?

tasks_mail.py went four months sending five-minute messages into a worker
that had never imported it — autodiscover_tasks() only walks each app's
`tasks` module, so the task names were not in the registry and every message
was discarded as unregistered. Nothing surfaced it: beat logged a successful
send, the enqueueing web process had the module imported so .delay() returned
cleanly, and the fields that would have shown a problem are written by the
task itself.

The mismatch is cheap to detect, so detect it — at worker startup, and in CI.
"""
import ast
import logging
import os
import warnings

logger = logging.getLogger(__name__)


def scheduled_task_names(app):
    """
    Task names the schedule will send, by where they are scheduled.

    Two sources, because both can fire: the PeriodicTask table is the live
    schedule under DatabaseScheduler, and app.conf.beat_schedule is what the
    code declares. A name in either one must be runnable.

    The database is consulted only if it answers — this runs in CI, where
    there is no database, and a missing one must not mask the check of the
    declared schedule.
    """
    sources = {}

    for entry in (app.conf.beat_schedule or {}).values():
        task = entry.get('task') if isinstance(entry, dict) else getattr(entry, 'task', None)
        if task:
            sources.setdefault(task, set()).add('celery_app.py')

    try:
        from django_celery_beat.models import PeriodicTask
        for task in PeriodicTask.objects.filter(enabled=True).values_list('task', flat=True):
            if task:
                sources.setdefault(task, set()).add('PeriodicTask')
    except Exception as exc:  # no database, app not installed, table absent
        logger.debug(f"[BEAT-CHECK] Skipping PeriodicTask rows: {exc}")

    return sources


def unregistered_scheduled_tasks(app):
    """
    {task name: sorted sources} for scheduled tasks this process cannot run.

    import_default_modules() forces the autodiscovery this is here to audit,
    so the registry read afterwards is the one a worker would use.
    """
    scheduled = scheduled_task_names(app)
    app.loader.import_default_modules()
    registered = set(app.tasks)
    return {
        name: sorted(sources)
        for name, sources in sorted(scheduled.items())
        if name not in registered
    }


# ---------------------------------------------------------------------------
# The other direction: declared but unrunnable
# ---------------------------------------------------------------------------
#
# `unregistered_scheduled_tasks` computes (scheduled - registered), which only
# sees a task that IS scheduled. It cannot see the opposite failure, and that
# one has now happened twice:
#
#   sync_clio_full carried a "runs on the scheduled sweep" docstring for a
#   month while being scheduled nowhere and registered nowhere. There was no
#   schedule entry to compare against, so the check above had nothing to say.
#
# What both failures share is the cause: @shared_task in a module that
# autodiscover_tasks() never walks, because it only walks each app's `tasks`
# module. The task then exists, imports fine, and `.delay()` from the web
# process returns cleanly — the web process imported the module itself — while
# the worker discards every message as unregistered.
#
# So audit the declarations directly. A @shared_task that is not in the
# registry cannot run, whether or not anything schedules it yet.

TASK_DECORATORS = {'shared_task', 'task'}
SKIP_DIRS = {'migrations', '__pycache__', 'node_modules', '.git'}


def _task_name_from_node(node, module_path):
    """
    The name Celery would register this function under, or None.

    Celery defaults to "<module>.<function>" when `name=` is omitted, so that
    is what an omitted name is compared against.
    """
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        func = call.func if call else decorator
        attr = getattr(func, 'id', None) or getattr(func, 'attr', None)
        if attr not in TASK_DECORATORS:
            continue
        if call:
            for keyword in call.keywords:
                if keyword.arg == 'name' and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
        return f'{module_path}.{node.name}'
    return None


def _tracker_package_dir():
    """
    Absolute path to the tracker package, resolved from the module itself.

    NOT a relative "tracker" against the cwd. os.walk() on a path that does not
    exist yields nothing and raises nothing, so a cwd-relative default would
    make this check report a clean tree from any other directory — passing
    loudly while auditing zero files. A check that cannot fail is worse than no
    check, because it is believed.
    """
    import tracker
    return os.path.dirname(os.path.abspath(tracker.__file__))


def declared_task_names(package_dir=None):
    """
    {task name: "path:line"} for every @shared_task in the source tree.

    Parsed with ast rather than imported: importing every module to find its
    tasks would itself perform the registration this is trying to audit, and
    would report everything as healthy.
    """
    package_dir = package_dir or _tracker_package_dir()
    if not os.path.isdir(package_dir):
        raise RuntimeError(
            f'Cannot audit Celery tasks: {package_dir!r} is not a directory.'
        )

    declared = {}
    for root, dirs, files in os.walk(package_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in files:
            if not filename.endswith('.py'):
                continue
            path = os.path.join(root, filename)
            try:
                # Parsing raises SyntaxWarning for things like an invalid
                # escape in an unrelated file's regex. That is real, but it is
                # not this check's business to report, and an unattributed
                # "<unknown>:35" line in CI output is pure noise beside a
                # finding someone has to act on.
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    tree = ast.parse(open(path, encoding='utf-8').read())
            except (OSError, SyntaxError) as exc:
                logger.debug(f'[BEAT-CHECK] Skipping {path}: {exc}')
                continue
            rel = os.path.relpath(path, os.path.dirname(package_dir))
            module_path = rel[:-3].replace(os.sep, '.')
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                name = _task_name_from_node(node, module_path)
                if name:
                    declared[name] = f'{rel}:{node.lineno}'
    return declared


def unregistered_declared_tasks(app, package_dir=None):
    """
    {task name: "path:line"} for tasks that exist in the source but cannot run.

    Each one is a trap: it will import, it will accept .delay() from the web
    process, and the worker will discard the message.
    """
    declared = declared_task_names(package_dir)
    app.loader.import_default_modules()
    registered = set(app.tasks)
    return {
        name: where
        for name, where in sorted(declared.items())
        if name not in registered
    }
