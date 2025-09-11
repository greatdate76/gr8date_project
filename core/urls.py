# core/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.contrib.auth import views as auth_views  # <-- add
from core.views_preview import preview_lock
from core.views_health import healthz
from allauth.account.views import confirm_email as allauth_confirm_email

urlpatterns = [
    path("admin/", admin.site.urls),
    path("_preview-lock/", preview_lock, name="preview_lock"),
    path("healthz/", healthz, name="healthz"),

    # Allauth confirm endpoint (keep exposed so email links work)
    path("verify-email/<str:key>/", allauth_confirm_email, name="account_confirm_email"),

    # ---- Login route (named 'login') ----
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="pages/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),

    # App URLs
    path("", include(("pages.urls", "pages"), namespace="pages")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

