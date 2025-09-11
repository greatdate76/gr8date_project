# core/middleware_onboarding.py
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from pages.models import Profile

class OnboardingAccessMiddleware:
    """
    If a user is authenticated but NOT approved yet, they are only allowed to visit
    a small set of pages (edit profile, logout, legal, etc.). All other pages
    redirect to the profile edit page with a notice.
    """
    def __init__(self, get_response):
        self.get_response = get_response

        # URL prefixes that are ALWAYS allowed
        self.ALLOW_PREFIXES = (
            "/admin/",
            "/static/",
            "/media/",
            "/healthz/",
            "/accounts/",        # allauth endpoints if any
        )
        # Named routes or paths we allow for unapproved users
        self.ALLOW_PATHS = {
            "/",                         # index
            "/login/",
            "/logout/",
            "/signup/",
            "/marketing/",
            "/about-us/",
            "/privacy/",
            "/terms/",
            "/faq/",
            "/contact/",
            "/my-profile/",
            "/my-profile-edit/",
        }

    def __call__(self, request):
        user = getattr(request, "user", None)
        path = request.path

        # Let anonymous users and allowed prefixes pass through.
        if not (user and user.is_authenticated):
            return self.get_response(request)
        if any(path.startswith(p) for p in self.ALLOW_PREFIXES):
            return self.get_response(request)
        if path in self.ALLOW_PATHS:
            return self.get_response(request)

        # Staff can go anywhere.
        if user.is_staff or user.is_superuser:
            return self.get_response(request)

        # Check profile approval
        profile = Profile.objects.filter(user_id=user.id).only("is_approved", "is_complete").first()
        if profile and not profile.is_approved:
            # Gate everything else
            messages.info(request, "Your account is awaiting approval. You can update your profile while you wait.")
            return redirect(reverse("pages:my_profile_edit"))

        return self.get_response(request)

