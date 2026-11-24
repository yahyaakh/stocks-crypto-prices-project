import logging
import os
import tempfile
import threading
import time
import urllib.request

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)

WARMUP_PATHS = ["/api/indices/", "/api/crypto/", "/api/news/", "/mag7/", "/etfs/", "/ipo/", "/upside/", "/"]


class MarketConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "market"

    def ready(self):
        _isolate_yfinance_cache()
        # Opt-in only (CACHE_WARMUP=1), so tests, collectstatic and migrate never start it.
        # Caveat: LocMemCache is per process, so with N gunicorn workers this warms only
        # whichever worker answers each request. A shared cache (Redis) would fix that.
        if os.environ.get("CACHE_WARMUP") == "1":
            threading.Thread(target=_warm_cache, daemon=True, name="cache-warmup").start()


def _isolate_yfinance_cache():
    """yfinance keeps SQLite caches (timezones, cookies) in one shared directory. With several
    gunicorn worker processes, concurrent requests then fail with `peewee.OperationalError:
    database is locked`. Each process gets a per-PID directory, so no two processes ever share
    a cache file. Called from ready() (runserver, tests) and, because gunicorn preloads the app
    in the master, again in every worker from gunicorn.conf.py's post_fork hook."""
    import yfinance as yf

    path = os.path.join(tempfile.gettempdir(), f"py-yfinance-{os.getpid()}")
    os.makedirs(path, exist_ok=True)
    yf.set_tz_cache_location(path)


def _warm_cache():
    base = os.environ.get("CACHE_WARMUP_URL", "http://127.0.0.1:8000")
    delay_s = float(os.environ.get("CACHE_WARMUP_DELAY_S", "20"))
    host = settings.ALLOWED_HOSTS[0]  # Host header must pass ALLOWED_HOSTS validation
    time.sleep(delay_s)  # let the server finish binding before we call it

    logger.info("cache warmup start base=%s", base)
    for path in WARMUP_PATHS:
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(base + path, headers={"User-Agent": "CacheWarmer/1.0", "Host": host})
            with urllib.request.urlopen(req, timeout=120) as resp:
                status = resp.status
            logger.info("cache warmup path=%s status=%s ms=%.0f", path, status, (time.perf_counter() - t0) * 1e3)
        except Exception as exc:
            logger.warning("cache warmup failed path=%s err=%s", path, exc)
    logger.info("cache warmup done")
