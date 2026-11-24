from django.conf import settings


def analytics(request):
    """The GoatCounter site code for base.html; empty when analytics is off."""
    return {"goatcounter_code": settings.GOATCOUNTER_CODE}
