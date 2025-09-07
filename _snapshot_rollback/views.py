from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse

# Import your models
# Adjust these to match your actual app structure
from .models import Profile, BlogPost


# ---------- Helpers for resolving images and fields ----------

IMG_PRIMARY_CANDIDATES = [
    "primary_image", "primary_photo", "photo", "image", "avatar",
    "primary_image_url", "photo_url", "image_url", "avatar_url",
]

GALLERY_LIST_CANDIDATES = [
    "gallery_images", "gallery", "images", "photos", "gallery_image_urls"
]

GALLERY_INDEXED_PREFIXES = ["image", "img", "photo", "gallery_image"]


def _string_or_none(val):
    if not val:
        return None
    s = str(val).strip()
    return s or None


def _url_from_field(obj, field_name):
    if not hasattr(obj, field_name):
        return None
    value = getattr(obj, field_name)
    if value is None:
        return None

    # If Image/File field
    if hasattr(value, "url"):
        try:
            return _string_or_none(value.url)
        except Exception:
            pass

    return _string_or_none(value)


def resolve_primary_image_url(profile):
    for name in IMG_PRIMARY_CANDIDATES:
        url = _url_from_field(profile, name)
        if url:
            return url
    gallery = resolve_gallery_urls(profile)
    if gallery:
        return gallery[0]
    return None


def resolve_gallery_urls(profile, max_items=8):
    urls = []

    # 1) Gallery list fields
    for fname in GALLERY_LIST_CANDIDATES:
        if hasattr(profile, fname):
            val = getattr(profile, fname)
            if isinstance(val, (list, tuple)):
                for item in val:
                    s = _string_or_none(getattr(item, "url", item))
                    if s:
                        urls.append(s)
            else:
                s = _string_or_none(val)
                if s and ("," in s):
                    urls.extend([piece.strip() for piece in s.split(",") if piece.strip()])

    # 2) Indexed fields like image1 .. image10
    for prefix in GALLERY_INDEXED_PREFIXES:
        for i in range(1, 11):
            url = _url_from_field(profile, f"{prefix}{i}")
            if url:
                urls.append(url)

    seen, uniq = set(), []
    for u in urls:
        if u not in seen:
            uniq.append(u)
            seen.add(u)
    return uniq[:max_items]


def resolve_display_name(profile):
    for name in ("display_name", "username", "name", "title"):
        if hasattr(profile, name):
            val = _string_or_none(getattr(profile, name))
            if val:
                return val
    return f"Member #{getattr(profile, 'id', '')}".strip()


def resolve_location(profile):
    for name in ("location", "city", "region", "state", "country"):
        if hasattr(profile, name):
            val = _string_or_none(getattr(profile, name))
            if val:
                return val
    return None


# ------------------------- Views -------------------------

def index(request):
    return render(request, "pages/index.html")


def dashboard(request):
    q = request.GET.get("q", "").strip()
    qs = Profile.objects.all()

    if q:
        qs = qs.filter(
            Q(display_name__icontains=q)
            | Q(username__icontains=q)
            | Q(name__icontains=q)
            | Q(city__icontains=q)
            | Q(location__icontains=q)
            | Q(tagline__icontains=q)
        )

    items = []
    for p in qs:
        items.append({
            "id": p.id,
            "display_name": resolve_display_name(p),
            "age": getattr(p, "age", None),
            "location": resolve_location(p),
            "primary_image_url": resolve_primary_image_url(p),
            "tagline": _string_or_none(getattr(p, "tagline", "")),
        })

    paginator = Paginator(items, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "pages/dashboard.html", {"page_obj": page_obj})


def profile_detail(request, pk):
    profile = get_object_or_404(Profile, pk=pk)

    profile_ctx = {
        "id": profile.id,
        "display_name": resolve_display_name(profile),
        "age": getattr(profile, "age", None),
        "location": resolve_location(profile),
        "primary_image_url": resolve_primary_image_url(profile),
        "gallery_image_urls": resolve_gallery_urls(profile),
        "tags": getattr(profile, "tags", []) or [],
        "about": _string_or_none(getattr(profile, "about", "")),
        "expectations": _string_or_none(getattr(profile, "expectations", "")),
        "extras": _string_or_none(getattr(profile, "extras", "")),
    }

    return render(request, "pages/profile.html", {"profile": profile_ctx})


# --------------------- Static-like pages ---------------------

def marketing(request):        return render(request, "pages/marketing.html")
def messages(request):         return render(request, "pages/messages.html")
def login_page(request):       return render(request, "pages/login.html")
def signup_page(request):      return render(request, "pages/signup.html")
def about_page(request):       return render(request, "pages/aboutus.html")
def privacy_page(request):     return render(request, "pages/privacy.html")
def terms_page(request):       return render(request, "pages/terms.html")
def contact_page(request):     return render(request, "pages/contact.html")
def faq_page(request):         return render(request, "pages/faq.html")

def request_private_access(request, pk):
    return render(request, "pages/messages.html")

def block_profile(request, pk):
    return render(request, "pages/messages.html")

def logout_view(request):
    return render(request, "pages/index.html")

def my_profile(request):
    return render(request, "pages/my_profile.html")

def my_profile_edit(request):
    return render(request, "pages/my_profile_edit.html")

def hot_dates(request):
    return render(request, "pages/hot_dates.html")


# --------------------- Blog views ---------------------

def blog_list(request):
    posts = BlogPost.objects.order_by("-created_at")
    return render(request, "pages/blog_list.html", {"posts": posts})

def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug)
    # Optional: fetch a few recent posts for a sidebar
    recent = BlogPost.objects.exclude(pk=post.pk).order_by("-created_at")[:5]
    return render(request, "pages/blog_detail.html", {"post": post, "recent": recent})
