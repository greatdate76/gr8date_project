# core/middleware.py
from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings

class PreviewLockMiddleware:
    """
    Locks down the whole site behind a preview password if enabled by env.
    - Controlled with PREVIEW_LOCK_ENABLED and PREVIEW_LOCK_PASSWORD
    - Uses session 'preview_unlocked'
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "PREVIEW_LOCK_ENABLED", False):
            return self.get_response(request)

        if request.session.get("preview_unlocked", False):
            return self.get_response(request)

        path = request.path or "/"

        # Exclude static/admin/preview-lock
        for prefix in getattr(settings, "PREVIEW_LOCK_EXCLUDE_PATHS", []):
            if prefix and path.startswith(prefix):
                return self.get_response(request)

        lock_url = reverse("preview_lock")
        if path != lock_url:
            return redirect(f"{lock_url}?next={path}")

        return self.get_response(request)

