"""Маршруты приложения core: публичные страницы (Ф7), API (Ф6), healthcheck."""

from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from django.utils.translation import gettext_lazy as _

from . import cabinet, views

urlpatterns = [
    path("", views.home, name="home"),
    path("map/", views.map_page, name="map"),
    path("explore/", views.explore_page, name="explore"),
    path("views/<str:token>/", views.public_saved_view, name="public_saved_view"),
    path("rankings/", views.rankings, name="rankings"),
    path("index-lab/", views.index_lab_page, name="index_lab"),
    path("convergence/", views.convergence_page, name="convergence"),
    path("rankings/stability/", views.rank_stability_page, name="rank_stability_page"),
    path("typology/", views.typology, name="typology"),
    path("compare/", views.compare, name="compare"),
    path("regions/", views.regions, name="regions"),
    path("regions/<str:okato>/", views.region_dashboard_page, name="region-dashboard-page"),
    path("regions/<str:okato>/export/", views.export_region, name="export_region"),
    path("methodology/", views.methodology, name="methodology"),
    path("data/", views.data_page, name="data"),
    path("data/quality/", views.data_quality_page, name="data_quality_page"),
    path("dispersion/", views.dispersion_page, name="dispersion_page"),
    path("anomalies/", views.anomalies_page, name="anomalies_page"),
    path("correlations/", views.correlations_page, name="correlations_page"),
    path("help/", views.help_page, name="help"),
    path("feedback/", views.feedback, name="feedback"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            extra_context={
                "active": "login",
                "breadcrumbs": [
                    {"title": _("Главная"), "url": reverse_lazy("home")},
                    {"title": _("Вход")},
                ],
            },
        ),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("account/", cabinet.overview, name="account"),
    path("account/profile/", cabinet.profile_edit, name="account_profile"),
    path("account/views/", cabinet.saved_views, name="account_views"),
    path("account/views/<int:pk>/open/", cabinet.saved_view_open, name="account_view_open"),
    path("account/views/<int:pk>/share/", cabinet.saved_view_share, name="account_view_share"),
    path("account/views/<int:pk>/delete/", cabinet.saved_view_delete, name="account_view_delete"),
    path("account/exports/", cabinet.export_history, name="account_exports"),
    path("account/favorites/", cabinet.favorites_list, name="account_favorites"),
    path("account/favorites/toggle/", cabinet.favorite_toggle, name="favorite_toggle"),
    path("account/activity/", cabinet.activity_feed, name="account_activity"),
    path("account/settings/", cabinet.settings_edit, name="account_settings"),
    path("account/comparisons/", cabinet.comparison_sets, name="account_comparisons"),
    path("account/comparisons/save/", cabinet.comparison_save, name="comparison_save"),
    path(
        "account/comparisons/<int:pk>/open/",
        cabinet.comparison_open,
        name="comparison_open",
    ),
    path(
        "account/comparisons/<int:pk>/delete/",
        cabinet.comparison_delete,
        name="comparison_delete",
    ),
    path(
        "account/password/",
        auth_views.PasswordChangeView.as_view(
            template_name="account/password.html",
            success_url=reverse_lazy("account_password_done"),
            extra_context={
                "active": "account",
                "cabinet_tab": "password",
                "breadcrumbs": [
                    {"title": _("Главная"), "url": reverse_lazy("home")},
                    {"title": _("Личный кабинет"), "url": reverse_lazy("account")},
                    {"title": _("Смена пароля"), "url": None},
                ],
            },
        ),
        name="account_password",
    ),
    path(
        "account/password/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="account/password_done.html",
            extra_context={
                "active": "account",
                "cabinet_tab": "password",
                "breadcrumbs": [
                    {"title": _("Главная"), "url": reverse_lazy("home")},
                    {"title": _("Личный кабинет"), "url": reverse_lazy("account")},
                    {"title": _("Смена пароля"), "url": None},
                ],
            },
        ),
        name="account_password_done",
    ),
    path("healthz/", views.healthz, name="healthz"),
    path("api/", include("core.api.urls")),
]
