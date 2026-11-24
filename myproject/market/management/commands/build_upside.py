"""Build the top-upside snapshot now, in the foreground, and print what it took.

    python manage.py build_upside                 # 2,000 stocks, saved for the page
    python manage.py build_upside --size 200 --workers 8 --no-save
"""
import time

from django.core.management.base import BaseCommand

from market import upside


class Command(BaseCommand):
    help = "Fetch analyst targets for the largest US stocks and save the top-upside snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--size", type=int, default=upside.UNIVERSE_SIZE)
        parser.add_argument("--workers", type=int, default=upside.WORKERS)
        parser.add_argument("--no-save", action="store_true")

    def handle(self, size, workers, no_save, **_):
        t0 = time.perf_counter()
        snap = upside.build(size=size, workers=workers)
        with_targets = sum(1 for r in snap["rows"] if r.get("target_mean"))
        self.stdout.write(
            f"stocks={snap['universe']} with_targets={with_targets} failed={snap['failed']} "
            f"workers={workers} screen_s={snap['screen_seconds']} total_s={time.perf_counter() - t0:.1f}")
        if not no_save:
            upside.save(snap)
            self.stdout.write(f"saved to {upside.data_dir() / 'current.json'}")
