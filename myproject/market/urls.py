from django.contrib import admin
from django.urls import path

from .views import home, stocks_page, stock_detail, price_target, stock_news, stocks_ipo

from . import views


urlpatterns = [


    # we use the name so we can access urls dynamically in our views and templates
    # in templates we use the href = { % url = 'stocks' %  }
    path("", home, name="home"),
    path("mag7/", views.magnificent7_view, name="mag7"),
    path("etfs/", views.etf, name="etf"),
    path("stocks/", stocks_page, name="stocks"),
    path("info/", stock_detail, name="info"),
    path("target/", price_target, name="target"),
    path("stocknews/", stock_news, name="stocknews"),
    path("ipo/", stocks_ipo, name="stocks_ipo"),
    path('api/crypto/', views.api_crypto, name='api_crypto'),
    path('api/news/', views.api_news, name='api_news'),

path('api/get-price/', views.api_get_stock_price, name='api_get_price'),

# URL ROUTING: Live Watchlist Route
# Maps the user-friendly URL "domain.com/live/" to our React integration view.
#
# EXPLANATION:
# The argument 'name="Live"' is crucial for decoupling the URL path from the code.
# It allows us to use dynamic reverse-lookup tags like {% url 'Live' %} in our templates (base.html).
# If we decide to change the URL to "/dashboard/" later, we only change it here, 
# and the entire navigation system updates automatically without breaking links.
path("live/", views.live_watch_view, name="Live"),

    path('api/indices/', views.api_world_indices, name='api_indices'),



]

