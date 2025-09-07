from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, F, Value
from django.db.models.functions import Mod
from django.contrib import messages as dj_messages
from django.views.decorators.http import require_POST
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail, BadHeaderError
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import get_template
from django.template import TemplateDoesNotExist
from django.urls import reverse
import secrets

from .models import BlogPost, Profile
from .permissions import can_view_private


# ----------------------------
# Helpers for session-backed favorites/blocks
# ----------------------------
def _get_id_set(session, key):
    return set(int(x) for x in session.get(key, []))


def _set_id_set(session, key, s):
    session[key] = [int(x) for x in s]


def _visible_profiles_queryset(request):
    """
    Same visibility as dashboard:
    - has a real primary image OR at least one public/additional gallery image
    - excludes session-blocked users
    - newest first (baseline; may be re-ordered by shuffle)
    """
    blocked_ids = _get_id_set(request.session, "blocked_profiles")
    return (
        Profile.objects
        .filter(
            Q(primary_image__isnull=False) & ~Q(primary_image="")
            | Q(images__kind__in=["public", "additional"])
        )
        .exclude(pk__in=blocked_ids)
        .distinct()
        .prefetch_related("images")
        .order_by("-created_at")
    )


def _dedup_thumbs(profile, photos_public, photos_additional):
    """
    Build a de-duped list for the 'Photos' grid:
    - excludes the primary image (avatar)
    - removes exact duplicates (by file name)
    - preserves original ordering
    """
    primary_name = ""
    if getattr(profile, "primary_image", None) and getattr(profile.primary_image, "name", ""):
        primary_name = profile.primary_image.name.strip()

    seen = set()
    out = []
    for qs in (photos_public, photos_additional):
        for ph in qs:
            name = getattr(getattr(ph, "image", None), "name", "") or ""
            if not name or name == primary_name:
                continue
            if name in seen:
                continue
            seen.add(name)
            out.append(ph)
    return out


# ----------------------------
# Shuffle helpers (per-login seed)
# ----------------------------
def _get_shuffle_seed(request) -> int:
    """
    Keep order stable while browsing; rotate on each login via pages/signals.py.
    If missing (e.g., anonymous user), create a seed so refresh shuffles too.
    """
    seed = request.session.get("dash_seed")
    if seed is None:
        seed = secrets.randbelow(1_000_000_000)
        request.session["dash_seed"] = seed
    return int(seed)


def _apply_shuffle(qs, request):
    """
    Default: pseudo-random order based on session seed.
    Optional: ?sort=latest forces newest-first.
    """
    if (request.GET.get("sort") or "").lower() == "latest":
        return qs.order_by("-created_at")

    seed = _get_shuffle_seed(request)
    # Deterministic pseudo-random order: (id * seed) % big_prime
    return qs.annotate(
        sort_key=Mod(F("id") * Value(seed), Value(10000019))
    ).order_by("sort_key", "-created_at")


# ----------------------------
# Core Pages
# ----------------------------
def index(request):
    return render(request, "pages/index.html")


def marketing(request):
    return render(request, "pages/marketing.html")


def messages_page(request):
    return render(request, "pages/messages.html")


def login_page(request):
    # Template-only; actual login handled by auth_views.LoginView at /login/
    return render(request, "pages/login.html")


def signup_page(request):
    return render(request, "pages/signup.html")


def about_page(request):
    return render(request, "pages/aboutus.html")


def privacy_page(request):
    return render(request, "pages/privacy.html")


def terms_page(request):
    return render(request, "pages/terms.html")


def contact_page(request):
    """
    Hybrid contact: shows mailto AND a site form fallback.
    Configure SUPPORT_EMAIL or DEFAULT_FROM_EMAIL in settings.
    """
    initial = {}
    if request.user.is_authenticated:
        initial["name"] = (request.user.get_full_name() or request.user.get_username() or "").strip()
        initial["email"] = getattr(request.user, "email", "") or ""

    try:
        from .forms import ContactForm
    except Exception:
        ContactForm = None

    if ContactForm:
        if request.method == "POST":
            form = ContactForm(request.POST)
            if form.is_valid():
                name = form.cleaned_data["name"].strip()
                email = form.cleaned_data["email"].strip()
                message = form.cleaned_data["message"].strip()

                subject = f"[GR8DATE Contact] from {name}"
                body = f"From: {name} <{email}>\n\nMessage:\n{message}"
                to_email = getattr(settings, "SUPPORT_EMAIL", None) or getattr(settings, "DEFAULT_FROM_EMAIL", None)

                if not to_email:
                    dj_messages.error(request, "Contact form is not yet configured (no SUPPORT_EMAIL/DEFAULT_FROM_EMAIL).")
                    return render(request, "pages/contactus.html", {"form": form})

                try:
                    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL or email, [to_email])
                    dj_messages.success(request, "Thanks! Your message has been sent.")
                    return redirect("pages:contact")
                except BadHeaderError:
                    dj_messages.error(request, "Invalid email header. Please try again or use the email link.")
        else:
            form = ContactForm(initial=initial)
        return render(request, "pages/contactus.html", {"form": form})

    return render(request, "pages/contactus.html")


def faq_page(request):
    return render(request, "pages/faq.html")


# ----------------------------
# Dashboard + Profiles (public browsing)
# ----------------------------
def dashboard(request):
    """
    Show only profiles that have a usable image:
      - a real primary_image file, OR
      - at least one PUBLIC or ADDITIONAL gallery image
    Exclude any user-blocked profiles (session-based).
    Shuffle order per-login by default.
    """
    profiles = _apply_shuffle(_visible_profiles_queryset(request), request)

    # simple filters from the search modal
    q = request.GET.get("q", "").strip()
    location = request.GET.get("location", "").strip()
    age_min = request.GET.get("age_min", "").strip()
    age_max = request.GET.get("age_max", "").strip()
    gender = request.GET.get("gender", "").strip()

    if q:
        profiles = profiles.filter(Q(display_name__icontains=q) | Q(bio__icontains=q) | Q(location__icontains=q))
    if location:
        profiles = profiles.filter(location__icontains=location)
    if age_min.isdigit():
        profiles = profiles.filter(age__gte=int(age_min))
    if age_max.isdigit():
        profiles = profiles.filter(age__lte=int(age_max))
    if request.user.is_authenticated and request.user.is_superuser and gender:
        profiles = profiles.filter(gender__iexact=gender)

    paginator = Paginator(profiles, 12)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "pages/dashboard.html",
        {
            "page_obj": page_obj,
            "q": q,
            "search_params": {
                "location": location,
                "age_min": age_min,
                "age_max": age_max,
                "gender": gender,
            },
            "is_superuser": request.user.is_authenticated and request.user.is_superuser,
        },
    )


def profile_detail(request, pk):
    """
    Profile page with robust fallbacks and separated photo kinds.
    Prev/Next links are computed from the same visibility rules + shuffle as dashboard.
    """
    profile = get_object_or_404(Profile.objects.prefetch_related("images"), pk=pk)

    # Compute Prev/Next from the same (shuffled) visible queryset
    visible_qs = _apply_shuffle(_visible_profiles_queryset(request), request)
    id_list = list(visible_qs.values_list("pk", flat=True))
    prev_url = next_url = None
    try:
        idx = id_list.index(profile.pk)
        if idx > 0:
            prev_url = reverse("pages:profile_detail", args=[id_list[idx - 1]])
        if idx < len(id_list) - 1:
            next_url = reverse("pages:profile_detail", args=[id_list[idx + 1]])
    except ValueError:
        pass

    photos_public = profile.images.filter(kind__iexact="public")
    photos_additional = profile.images.filter(kind__iexact="additional")
    photos_private = profile.images.filter(kind__iexact="private")

    # Build de-duped list for Photos grid (no avatar duplicates)
    thumbs = _dedup_thumbs(profile, photos_public, photos_additional)

    allow_private = can_view_private(request.user, profile)

    fav_ids = _get_id_set(request.session, "favorite_profiles")
    blocked_ids = _get_id_set(request.session, "blocked_profiles")

    return render(
        request,
        "pages/profile.html",
        {
            "profile": profile,
            "photos_public": photos_public,
            "photos_additional": photos_additional,
            "photos_private": photos_private,
            "thumbs": thumbs,  # used by template Photos grid
            "allow_private": allow_private,
            "is_favorited": profile.pk in fav_ids,
            "is_blocked": profile.pk in blocked_ids,
            "prev_url": prev_url,
            "next_url": next_url,
            "q": "",
            "search_params": {"location": "", "age_min": "", "age_max": "", "gender": ""},
            "is_superuser": request.user.is_authenticated and request.user.is_superuser,
        },
    )


@require_POST
@login_required
def toggle_favorite(request, pk):
    """Session-based favorite toggle (placeholder UI behavior)."""
    profile = get_object_or_404(Profile, pk=pk)
    favs = _get_id_set(request.session, "favorite_profiles")
    if pk in favs:
        favs.remove(pk)
        dj_messages.info(request, f"Removed {profile.display_name} from favourites.")
    else:
        favs.add(pk)
        dj_messages.success(request, f"Added {profile.display_name} to favourites.")
    _set_id_set(request.session, "favorite_profiles", favs)
    request.session.modified = True
    return redirect("pages:profile_detail", pk=pk)


@require_POST
@login_required
def block_profile(request, pk):
    """
    Session-based block (placeholder). Blocks hide the profile on dashboard and
    indicate state on profile page. Unblock if already blocked.
    """
    profile = get_object_or_404(Profile, pk=pk)
    blocked = _get_id_set(request.session, "blocked_profiles")

    if pk in blocked:
        blocked.remove(pk)
        dj_messages.info(request, f"Unblocked {profile.display_name}.")
    else:
        blocked.add(pk)
        dj_messages.success(request, f"Blocked {profile.display_name}. You won't see them in the dashboard.")
    _set_id_set(request.session, "blocked_profiles", blocked)
    request.session.modified = True
    return redirect("pages:profile_detail", pk=pk)


@require_POST
def request_private_access(request, pk):
    profile = get_object_or_404(Profile, pk=pk)
    # TODO: implement PrivateAccessRequest + email the owner
    dj_messages.success(request, f"Request sent to view {profile.display_name}'s private photos.")
    return redirect("pages:profile_detail", pk=profile.pk)


# ----------------------------
# My Profile (logged-in user)
# ----------------------------
@login_required
def my_profile(request):
    """
    Shows the logged-in user's own profile using templates/pages/profile.html.
    """
    profile, created = Profile.objects.get_or_create(
        user_id=request.user.id,
        defaults={
            "display_name": request.user.get_username() or "Member",
            "bio": "",
        },
    )
    if created:
        dj_messages.info(request, "We created a starter profile for you. Update your details when ready.")

    photos_public = profile.images.filter(kind__iexact="public")
    photos_additional = profile.images.filter(kind__iexact="additional")
    photos_private = profile.images.filter(kind__iexact="private")
    thumbs = _dedup_thumbs(profile, photos_public, photos_additional)

    allow_private = can_view_private(request.user, profile)

    context = {
        "profile": profile,
        "photos_public": photos_public,
        "photos_additional": photos_additional,
        "photos_private": photos_private,
        "thumbs": thumbs,
        "allow_private": allow_private,
        "q": "",
        "search_params": {"location": "", "age_min": "", "age_max": "", "gender": ""},
        "is_superuser": request.user.is_authenticated and request.user.is_superuser,
        "is_favorited": False,
        "is_blocked": False,
    }
    return render(request, "pages/profile.html", context)


def my_profile_edit(request):
    """
    Renders pages/my-profile-edit.html if it exists; otherwise shows a placeholder
    so the route always resolves.
    """
    try:
        get_template("pages/my-profile-edit.html")
        return render(request, "pages/my-profile-edit.html", {})
    except TemplateDoesNotExist:
        return HttpResponse("<h1>Edit My Profile</h1><p>Template not created yet.</p>")


# ----------------------------
# Logout — confirm in-page, POST, always to Home
# ----------------------------
@require_POST
def logout_view(request):
    logout(request)
    return redirect(reverse("pages:index"))


# ----------------------------
# Blog
# ----------------------------
def blog_list(request):
    qs = (
        BlogPost.objects
        .filter(status__iexact="published", publish_at__lte=timezone.now())
        .order_by("-publish_at")
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) |
            Q(content__icontains=q) |
            Q(category__icontains=q)
        )

    paginator = Paginator(qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "pages/blog_list.html",
        {"page_obj": page_obj, "posts": page_obj.object_list, "q": q},
    )


def blog_detail(request, slug):
    post = get_object_or_404(
        BlogPost,
        slug=slug,
        status="published",
        publish_at__lte=timezone.now()
    )
    return render(request, "pages/blog_detail.html", {"post": post})

