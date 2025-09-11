# pages/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.http import HttpResponse
import csv

from .models import (
    Profile,
    ProfileImage,
    ProfileExtras,
    ProfileContact,
    MarketingLead,   # <-- NEW
)

# ----------------------------
# Profile & related inlines (yours, with small additions)
# ----------------------------

class ProfileImageInline(admin.TabularInline):
    model = ProfileImage
    extra = 0
    fields = ("thumb", "kind", "position", "image", "source_url")
    readonly_fields = ("thumb",)

    def thumb(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height:70px;border-radius:6px;"/>', obj.image.url)
        return "(no image)"


class ProfileExtrasInline(admin.StackedInline):
    model = ProfileExtras
    extra = 0
    max_num = 1


class ProfileContactInline(admin.StackedInline):
    model = ProfileContact
    extra = 0
    max_num = 1
    fields = ("email", "allow_email", "last_notified")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "thumb",
        "display_name",
        "age",
        "gender",
        "location",
        "contact_email",
        "has_images",
        "is_complete",          # <-- NEW
        "is_approved",          # <-- NEW
        "updated_at",
    )
    list_filter = ("gender", "is_complete", "is_approved")  # <-- NEW
    search_fields = ("display_name", "location", "bio")
    inlines = [ProfileImageInline, ProfileExtrasInline, ProfileContactInline]

    fieldsets = (
        (None, {
            "fields": ("user_id", "display_name", ("age", "gender"), "location", "bio")
        }),
        ("Primary Image", {
            "fields": ("primary_image", "thumb_large")
        }),
        ("Onboarding / Approval", {  # <-- NEW section
            "fields": ("is_complete", "is_approved"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )
    readonly_fields = ("created_at", "updated_at", "thumb_large")

    def thumb(self, obj):
        img = obj.primary_image or None
        if img:
            return format_html('<img src="{}" style="height:45px;border-radius:6px"/>', img.url)
        first = obj.images.first()
        if first and first.image:
            return format_html('<img src="{}" style="height:45px;border-radius:6px"/>', first.image.url)
        return "—"
    thumb.short_description = "Avatar"

    def thumb_large(self, obj):
        img = obj.primary_image or None
        if img:
            return format_html('<img src="{}" style="max-height:160px;border-radius:8px;border:1px solid #eee;"/>', img.url)
        first = obj.images.first()
        if first and first.image:
            return format_html('<img src="{}" style="max-height:160px;border-radius:8px;border:1px solid #eee;"/>', first.image.url)
        return "(no image)"

    def contact_email(self, obj):
        return (getattr(obj, "contact", None) and obj.contact.email) or ""
    contact_email.short_description = "Email"

    def has_images(self, obj):
        return bool(obj.primary_image or obj.images.exists())
    has_images.boolean = True


@admin.register(ProfileImage)
class ProfileImageAdmin(admin.ModelAdmin):
    list_display = ("id", "profile", "kind", "position", "small")
    list_filter = ("kind",)
    search_fields = ("profile__display_name",)

    def small(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height:45px;border-radius:6px;"/>', obj.image.url)
        return "—"
    small.short_description = "Preview"


# ----------------------------
# Marketing Leads (Preview Visitors) — NEW
# ----------------------------

@admin.register(MarketingLead)
class MarketingLeadAdmin(admin.ModelAdmin):
    """
    Shows ONLY unconverted leads by default (people who signed up/verified but
    haven't completed+been approved). Use filters/search to refine.
    """
    list_display = (
        "email",
        "email_verified",
        "created_at",
        "verified_at",
        "last_contacted",
        "user_id",
        "profile_link",
        "status_badge",
    )
    search_fields = ("email", "notes", "user_id")
    list_filter = (
        "email_verified",
        "converted_to_profile",
        ("created_at", admin.DateFieldListFilter),
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ["export_csv", "mark_contacted_now"]

    # Only show leads that have NOT converted
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(converted_to_profile=False)

    def profile_link(self, obj):
        return f"Profile #{obj.profile_id}" if obj.profile_id else "—"
    profile_link.short_description = "Profile"

    def status_badge(self, obj):
        return obj.status  # uses @property on the model
    status_badge.short_description = "Status"

    # ---- Actions ----
    def export_csv(self, request, queryset):
        headers = [
            "email",
            "email_verified",
            "created_at",
            "verified_at",
            "last_contacted",
            "user_id",
            "profile_id",
            "notes",
        ]
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=marketing_leads.csv"
        writer = csv.writer(resp)
        writer.writerow(headers)
        for o in queryset:
            writer.writerow([
                o.email,
                o.email_verified,
                o.created_at,
                o.verified_at,
                o.last_contacted,
                o.user_id,
                o.profile_id,
                o.notes,
            ])
        return resp
    export_csv.short_description = "Export selected to CSV"

    def mark_contacted_now(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(last_contacted=now)
        self.message_user(request, f"Marked {updated} lead(s) as contacted.")
    mark_contacted_now.short_description = "Mark contacted (now)"

