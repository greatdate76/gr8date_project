# pages/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import Profile, ProfileImage, ProfileExtras, ProfileContact

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
    list_display = ("id", "thumb", "display_name", "age", "gender", "location", "contact_email", "has_images", "updated_at")
    list_filter = ("gender",)
    search_fields = ("display_name", "location", "bio")
    inlines = [ProfileImageInline, ProfileExtrasInline, ProfileContactInline]
    readonly_fields = ("thumb_large",)

    fieldsets = (
        (None, {
            "fields": ("user_id", "display_name", ("age","gender"), "location", "bio")
        }),
        ("Primary Image", {
            "fields": ("primary_image", "thumb_large")
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
        return obj.primary_image or obj.images.exists()
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

