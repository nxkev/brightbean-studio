from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("accounts/", views.list_accounts, name="accounts"),
    path("media/upload/", views.upload_media, name="upload_media"),
    path("posts/", views.posts, name="posts"),
    path("posts/<uuid:post_id>/", views.post_detail, name="post_detail"),
    path("posts/<uuid:post_id>/retry/", views.retry_post, name="retry_post"),
]
