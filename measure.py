"""Time one GET per dashboard endpoint (first call = cold cache, unless warm-up ran).

Usage: python measure.py [BASE_URL]      default BASE_URL = http://127.0.0.1:8000
"""
import sys
import time

import requests

ENDPOINTS = ["/healthz", "/", "/api/indices/", "/api/crypto/", "/api/news/", "/mag7/", "/etfs/", "/ipo/"]


def main(base: str) -> None:
    print(f"base={base}")
    for ep in ENDPOINTS:
        t0 = time.perf_counter()
        try:
            r = requests.get(base + ep, timeout=120)
            print(f"{time.perf_counter() - t0:7.3f}s  {r.status_code}  {ep}")
        except requests.RequestException as exc:
            print(f"{time.perf_counter() - t0:7.3f}s  ERROR  {ep}  {exc}")


if __name__ == "__main__":
    main(sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000")
