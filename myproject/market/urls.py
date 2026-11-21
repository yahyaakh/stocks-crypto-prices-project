from django.urls import path

from . import views

# Route names let templates use {% url 'name' %} instead of hard-coded paths.
urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    # HTML pages
    path("", views.home, name="home"),
    path("mag7/", views.magnificent7_view, name="mag7"),
    path("etfs/", views.etf, name="etf"),
    path("stocks/", views.stocks_page, name="stocks"),
    path("info/", views.stock_detail, name="info"),
    path("target/", views.price_target, name="target"),
    path("stocknews/", views.stock_news, name="stocknews"),
    path("ipo/", views.stocks_ipo, name="stocks_ipo"),
    path("live/", views.live_watch_view, name="Live"),
    # React Router owns everything under /live/ (e.g. /live/stock/MSFT): serve the same shell.
    path("live/<path:rest>", views.live_watch_view),
    # JSON API
    path("api/indices/", views.api_world_indices, name="api_indices"),
    path("api/crypto/", views.api_crypto, name="api_crypto"),
    path("api/news/", views.api_news, name="api_news"),
    path("api/get-price/", views.api_get_stock_price, name="api_get_price"),
    path("api/stocks/<str:symbol>/overview/", views.stock_overview_api, name="stock_overview_api"),
    path("api/stocks/<str:symbol>/ratings/", views.analyst_ratings_api, name="analyst_ratings_api"),
    path("api/stocks/<str:symbol>/history/", views.stock_price_history_api, name="stock_history_api"),
    path("api/stocks/<str:symbol>/news/", views.api_company_news, name="api_company_news"),
    path("api/stocks/<str:symbol>/recommendation-trend/", views.api_recommendation_trend,
         name="api_recommendation_trend"),
]
