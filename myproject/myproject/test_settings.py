"""Settings for the test suite: no real secrets or API keys, nothing leaves the machine."""
import os

os.environ.setdefault("SECRET_KEY", "test-only-not-secret")
os.environ["FINNHUB_API_KEY"] = ""
os.environ["SEC_USER_AGENT"] = ""
os.environ["GOATCOUNTER_CODE"] = ""

from .settings import *  # noqa: E402,F401,F403

ALLOWED_HOSTS = ["testserver"]
# Hashed-manifest storage needs collectstatic to have run; tests render templates without it.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
