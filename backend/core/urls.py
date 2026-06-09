"""Маршруты приложения core: публичные страницы (Ф7), API (Ф6), healthcheck."""

from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("map/", views.map_page, name="map"),
    path("rankings/", views.rankings, name="rankings"),
    path("typology/", views.typology, name="typology"),
    path("compare/", views.compare, name="compare"),
    path("regions/", views.regions, name="regions"),
    path("regions/<str:okato>/", views.region_dashboard_page, name="region-dashboard-page"),
    path("methodology/", views.methodology, name="methodology"),
    path("data/", views.data_page, name="data"),
    path("help/", views.help_page, name="help"),
    path("feedback/", views.feedback, name="feedback"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            extra_context={
                "active": "login",
                "breadcrumbs": [
                    {"title": "Главная", "url": reverse_lazy("home")},
                    {"title": "Вход"},
                ],
            },
        ),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("healthz/", views.healthz, name="healthz"),
    path("api/", include("core.api.urls")),
]
