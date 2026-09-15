"""Scratch settings: the real app against a throwaway Postgres.

Only for the *_test.py scripts. The app container points at PRODUCTION, so a
test must never run under its default settings. Not imported by anything the
app ships.
"""
from timeserver.settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "scratch",
        "USER": "scratch",
        "PASSWORD": "scratch",
        "HOST": "tt_scratch_pg",
        "PORT": "5432",
    }
}
