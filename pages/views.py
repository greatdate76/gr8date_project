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

# allauth + auth utils
from django.contrib.auth import get_user_model, login  # login kept for future use
from allauth.account.models import EmailAddress

from .models import BlogPost, Profile, MarketingLead, HotDate, Favorite, Block  # Favorite, Block included
from .permissions import can_view_private


# ----------------------------
# Helpers
# ----------------------------
def _get_id_set(session, key):
    return set(int(x) for x in session.get(key, []))


def create_profile(request):
    """Show the create profile/onboarding page (marketing → conversion)."""
    return render(request, "pages/create_your_profile.html", {
        "limited_mode": _is_limited(request),
    })


def _set_id_set(session, key, s):
    session[key] = [int(x) for x in s]


def _unique_username_for_email(email: str) -> str:
    """
    Use the email as username; if taken, append +N before the @ (legal chars).
    Ensures <=150 chars for Django's default username field.
    """
    User = get_user_model()
    email = (email or "").strip().lower()
    if not email:
        return "user"

    local, _, domain = email.partition("@")
    candidate = email[:150]
    if not User.objects.filter(username=candidate).exists():
        return candidate

    i = 1
    while True:
        alt = f"{local}+{i}@{domain}" if domain else f"{local}+{i}"
        candidate = alt[:150]
        if not User.objects.filter(username=candidate).exists():
            return candidate
        i += 1


def _visible_profiles_queryset(request):
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
    seed = request.session.get("dash_seed")
    if seed is None:
        seed = secrets.randbelow(1_000_000_000)
        request.session["dash_seed"] = seed
    return int(seed)


def _apply_shuffle(qs, request):
    if (request.GET.get("sort") or "").lower() == "latest":
        return qs.order_by("-created_at")
    seed = _get_shuffle_seed(request)
    return qs.annotate(
        sort_key=Mod(F("id") * Value(seed), Value(10000019))
    ).order_by("sort_key", "-created_at")


# ----------------------------
# Limited/Preview mode helper
# ----------------------------
def _is_limited(request) -> bool:
    """
    Limited/preview mode is ON when:
      - user is anonymous, OR
      - user exists but profile is not complete+approved.
      - EXCEPTION: superusers are never limited (dev/admin convenience).
    """
    if not request.user.is_authenticated:
        return True
    if getattr(request.user, "is_superuser", False):
        return False  # superusers bypass limited/preview mode
    try:
        p = Profile.objects.get(user_id=request.user.id)
        return not (p.is_complete and p.is_approved)
    except Profile.DoesNotExist:
        return True


# ----------------------------
# Core Pages
# ----------------------------
def index(request):
    return render(request, "pages/index.html")


def marketing(request):
    """
    Marketing dashboard: reuse the same grid as /dashboard/ but
    always render in limited/preview mode (blur/disabled actions).
    """
    profiles = _apply_shuffle(_visible_profiles_queryset(request), request)
    paginator = Paginator(profiles, 12)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "pages/dashboard.html",  # reuse the dashboard template for consistent UI
        {
            "page_obj": page_obj,
            "q": "",
            "search_params": {"location": "", "age_min": "", "age_max": "", "gender": ""},
            "is_superuser": request.user.is_authenticated and request.user.is_superuser,
            "limited_mode": True,  # force preview mode here
        },
    )


def messages_page(request):
    return render(request, "pages/messages.html")


def login_page(request):
    # Template-only; actual login handled by auth_views.LoginView at /login/
    return render(request, "pages/login.html")


# NEW: Post-login decision view
@login_required
def post_login(request):
    """
    Decide where to send a user right after login.
    - Superusers -> dashboard
    - Ready profile -> dashboard
    - Otherwise -> marketing (preview)
    """
    if getattr(request.user, "is_superuser", False):
        return redirect("pages:dashboard")

    try:
        p = Profile.objects.get(user_id=request.user.id)
        is_ready = p.is_complete and p.is_approved
    except Profile.DoesNotExist:
        is_ready = False

    if is_ready:
        return redirect("pages:dashboard")
    return redirect("pages:marketing")


# Headless-allauth signup (uses your existing signup.html)
def signup(request):
    """
    GET  -> render your approved signup template.
    POST -> validate terms, create/find user by email, ensure EmailAddress,
            send confirmation, then render a 'check inbox' page.
    """
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        terms_ok = bool(request.POST.get("terms-agree"))

        if not email:
            return render(
                request, "pages/signup.html",
                {"error": "Please enter a valid email address.", "email": email},
                status=400,
            )
        if not terms_ok:
            return render(
                request, "pages/signup.html",
                {"error": "You must confirm you are over 18 and agree to the Terms & Privacy.", "email": email},
                status=400,
            )

        User = get_user_model()
        user = User.objects.filter(email=email).first()
        if not user:
            user = User(email=email, username=_unique_username_for_email(email))
            user.set_unusable_password()
            user.save()

        # Ensure EmailAddress exists & is primary
        email_address, _ = EmailAddress.objects.update_or_create(
            user=user,
            email=email,
            defaults={"primary": True, "verified": False},
        )

        # Send allauth confirmation email
        email_address.send_confirmation(request, signup=True)

        # Track as marketing lead
        MarketingLead.objects.update_or_create(
            email=email,
            defaults={"user_id": user.id, "email_verified": False},
        )

        return render(request, "pages/signup_check_inbox.html", {"email": email})

    return render(request, "pages/signup.html")


def about_page(request):
    return render(request, "pages/aboutus.html")


def privacy_page(request):
    return render(request, "pages/privacy.html")


def terms_page(request):
    return render(request, "pages/terms.html")


def contact_page(request):
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
            "limited_mode": _is_limited(request),
        },
    )


def profile_detail(request, pk):
    profile = get_object_or_404(Profile.objects.prefetch_related("images"), pk=pk)

    # The auth.User who owns this profile (for favorites/blocks/DMs)
    User = get_user_model()
    profile_user = User.objects.filter(pk=profile.user_id).first()

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
    thumbs = _dedup_thumbs(profile, photos_public, photos_additional)

    allow_private = can_view_private(request.user, profile)

    # DB-driven favourite / block flags (for icon colours)
    is_favorited = False
    is_blocked = False
    if request.user.is_authenticated and profile_user:
        is_favorited = Favorite.objects.filter(user=request.user, target=profile_user).exists()
        is_blocked = Block.objects.filter(blocker=request.user, blocked=profile_user).exists()

    return render(
        request,
        "pages/profile.html",
        {
            "profile": profile,
            "profile_user": profile_user,   # for quick DM
            "photos_public": photos_public,
            "photos_additional": photos_additional,
            "photos_private": photos_private,
            "thumbs": thumbs,
            "allow_private": allow_private,
            "is_favorited": is_favorited,   # drives red heart
            "is_blocked": is_blocked,       # drives red block icon
            "prev_url": prev_url,
            "next_url": next_url,
            "q": "",
            "search_params": {"location": "", "age_min": "", "age_max": "", "gender": ""},
            "is_superuser": request.user.is_authenticated and request.user.is_superuser,
            "limited_mode": _is_limited(request),
        },
    )


@require_POST
@login_required
def toggle_favorite(request, pk):
    """
    Toggle Favourite in the database (Favorite.user -> Favorite.target),
    so Matches reflects reality. Keeps the redirect & messages UX.
    """
    profile = get_object_or_404(Profile, pk=pk)
    target_user_id = profile.user_id  # Profile points to auth User id
    User = get_user_model()
    target = get_object_or_404(User, pk=target_user_id)

    fav, created = Favorite.objects.get_or_create(user=request.user, target=target)
    if created:
        dj_messages.success(request, f"Added {profile.display_name or target.username} to favourites.")
    else:
        fav.delete()
        dj_messages.info(request, f"Removed {profile.display_name or target.username} from favourites.")
    return redirect("pages:profile_detail", pk=pk)


@require_POST
@login_required
def block_profile(request, pk):
    """
    Toggle Block in the database (Block.blocker -> Block.blocked),
    so Matches and filtering can rely on DB state.
    """
    profile = get_object_or_404(Profile, pk=pk)
    blocked_user_id = profile.user_id
    User = get_user_model()
    blocked = get_object_or_404(User, pk=blocked_user_id)

    obj, created = Block.objects.get_or_create(blocker=request.user, blocked=blocked)
    if created:
        dj_messages.success(
            request,
            f"Blocked {profile.display_name or blocked.username}. You won't see them in the dashboard."
        )
    else:
        obj.delete()
        dj_messages.info(request, f"Unblocked {profile.display_name or blocked.username}.")
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


@login_required
def my_profile_edit(request):
    """
    Edit the logged-in user's profile.
    """
    profile = get_object_or_404(Profile, user_id=request.user.id)

    if request.method == 'POST':
        profile.display_name = request.POST.get('display_name', profile.display_name)
        profile.bio = request.POST.get('bio', profile.bio)
        profile.location = request.POST.get('location', profile.location)
        # Add other fields as necessary
        profile.save()
        dj_messages.success(request, "Profile updated successfully.")
        return redirect('pages:my_profile')
     
    return render(request, "pages/my-profile-edit.html", {"profile": profile})


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

@login_required
def hot_dates_list(request):
    """
    Dedicated page to list active & upcoming Hot Dates.
    Viewing this page stamps Profile.last_seen_hotdate_at
    so the flashing flame badge stops until a newer Hot Date appears.
    """
    now = timezone.now()
    active = HotDate.objects.filter(starts_at__lte=now, expires_at__gt=now).order_by("starts_at")
    upcoming = HotDate.objects.filter(starts_at__gt=now).order_by("starts_at")[:20]

    prof = Profile.objects.filter(user_id=request.user.id).first()
    if prof:
        prof.last_seen_hotdate_at = timezone.now()
        prof.save(update_fields=["last_seen_hotdate_at"])

    return render(request, "pages/hot_dates.html", {"active": active, "upcoming": upcoming})

@login_required
def matches_page(request):
    """
    Shows:
    - My favorites
    - Who favorited me
    - Who I have blocked
    """
    my_favs = Favorite.objects.filter(user=request.user).select_related("target").order_by("-created_at")
    fav_me = Favorite.objects.filter(target=request.user).select_related("user").order_by("-created_at")
    my_blocks = Block.objects.filter(blocker=request.user).select_related("blocked").order_by("-created_at")

    return render(request, "pages/matches.html", {
        "my_favs": my_favs,
        "fav_me": fav_me,
        "my_blocks": my_blocks,
    })

