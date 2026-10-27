from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("accounts.urls")),
    path("api/v1/", include("quotas.urls")),
]

handler404 = "utils.errors.not_found_view"
handler500 = "utils.errors.server_error_view"
