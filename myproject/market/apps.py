import logging
import threading
import time
import urllib.request

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class MarketConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'market'

    def ready(self):
        # Don't run during migrations or management commands
        import sys
        if 'runserver' not in sys.argv and 'gunicorn' not in ' '.join(sys.argv):
            # Still warm on gunicorn (production)
            pass

        thread = threading.Thread(target=self._warm_cache, daemon=True)
        thread.start()

    @staticmethod
    def _warm_cache():
        # Wait for gunicorn/Django to fully finish booting
        time.sleep(20)

        base = "http://127.0.0.1:8000"
        urls = [
            "/api/indices/",   # heaviest — world indices (Yahoo Finance batch)
            "/api/crypto/",    # CoinGecko
            "/api/news/",      # parallel news fetch
            "/mag7/",          # Magnificent 7
            "/etfs/",          # ETF batch
            "/ipo/",           # Finnhub IPO
        ]

        logger.info("[WARMUP] Cache warming started...")

        for url in urls:
            try:
                req = urllib.request.Request(
                    base + url,
                    headers={"User-Agent": "CacheWarmer/1.0"}
                )
                urllib.request.urlopen(req, timeout=120)
                logger.info(f"[WARMUP] ✓ {url}")
            except Exception as e:
                logger.warning(f"[WARMUP] ✗ {url} — {e}")

        logger.info("[WARMUP] Complete — all endpoints cached!")