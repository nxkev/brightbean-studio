from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("accept-terms/", views.accept_terms, name="accept_terms"),
    path("settings/", views.account_settings, name="settings"),
    path("logout/", views.logout_view, name="logout"),
]
