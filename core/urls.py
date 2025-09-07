# core/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core.views_preview import preview_lock
from core.views_health import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("_preview-lock/", preview_lock, name="preview_lock"),
    path("healthz/", healthz, name="healthz"),   # health check endpoint
    path("", include(("pages.urls", "pages"), namespace="pages")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

