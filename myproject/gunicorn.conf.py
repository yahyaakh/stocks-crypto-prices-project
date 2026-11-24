"""Gunicorn settings, read automatically from the working directory (/app/myproject in the image).

preload_app: Django, pandas and yfinance are imported once in the master and the workers are
forked from it. Under the hosted 0.25 vCPU, two workers importing them separately took
~9-11 s to serve the first request; preloading brought that to ~4.5-5.4 s (local runs with
`docker run --cpus 0.25 --memory 512m`, 2026-11-24).
"""


preload_app = True


def post_fork(server, worker):
    # Django's AppConfig.ready() ran once, in the master, so every worker would inherit the
    # master's yfinance cache directory and the workers would share one SQLite file again
    # ("database is locked"). Point each worker at its own directory after the fork.
    from market.apps import _isolate_yfinance_cache

    _isolate_yfinance_cache()
