# pages/models.py
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

# ----------------------------
# Core profile models
# ----------------------------

class Profile(models.Model):
    user_id = models.IntegerField(unique=True, db_index=True)
    display_name = models.CharField(max_length=200, blank=True)
    age = models.PositiveIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True)  # keep NOT NULL; importer writes "" when empty
    primary_image = models.ImageField(upload_to="profiles/%Y/%m/%d/", blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Onboarding / approval flags ---
    # Set is_complete=True when the user finishes your profile wizard.
    # Set is_approved=True from admin when you approve/publish the profile.
    is_complete = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)

    # --- Notifications/UX state ---
    # Used to turn OFF the flashing Hot Dates flame after the user views the page
    last_seen_hotdate_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.display_name or 'User'} (#{self.user_id})"

    @property
    def is_ready(self) -> bool:
        """Profile is allowed through the app once complete AND approved."""
        return self.is_complete and self.is_approved

    # helpers
    def public_images(self):
        return self.images.filter(kind=ProfileImage.PUBLIC).order_by("position")

    def additional_images(self):
        return self.images.filter(kind=ProfileImage.ADDITIONAL).order_by("position")

    def private_images(self):
        return self.images.filter(kind=ProfileImage.PRIVATE).order_by("position")


class ProfileExtras(models.Model):
    """
    Optional legacy fields imported from CSV (not shown publicly unless you render them).
    """
    profile = models.OneToOneField(Profile, related_name="extras", on_delete=models.CASCADE)

    heading = models.CharField(max_length=200, blank=True)
    seeking = models.TextField(blank=True)
    relationship_status = models.CharField(max_length=50, blank=True)
    body_type = models.CharField(max_length=50, blank=True)
    children = models.CharField(max_length=50, blank=True)
    smoker = models.CharField(max_length=20, blank=True)
    height = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"Extras for {self.profile_id}"


class ProfileContact(models.Model):
    """
    Private contact info for a Profile. Not rendered on public pages.
    Used for email notifications, etc.
    """
    profile = models.OneToOneField(Profile, related_name="contact", on_delete=models.CASCADE)
    email = models.EmailField(blank=True)
    allow_email = models.BooleanField(default=True)
    last_notified = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Contact for Profile #{self.profile_id} – {self.email or 'no email'}"


class ProfileImage(models.Model):
    PUBLIC = "public"
    ADDITIONAL = "additional"
    PRIVATE = "private"

    IMAGE_KIND_CHOICES = [
        (PUBLIC, "Public"),
        (ADDITIONAL, "Additional"),
        (PRIVATE, "Private"),
    ]

    profile = models.ForeignKey(Profile, related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="profiles/gallery/%Y/%m/%d/")
    kind = models.CharField(max_length=20, choices=IMAGE_KIND_CHOICES, default=ADDITIONAL)
    source_url = models.URLField(blank=True)
    position = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.profile_id}-{self.kind}-{self.position}"

    class Meta:
        ordering = ["profile_id", "kind", "position"]
        indexes = [
            models.Index(fields=["profile", "kind", "position"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "kind", "image"],
                name="uniq_profile_kind_image",
            ),
            models.CheckConstraint(
                check=~models.Q(image=""),
                name="profileimage_image_not_blank",
            ),
        ]


# ----------------------------
# Leads / Marketing
# ----------------------------

class MarketingLead(models.Model):
    """
    Preview visitors who signed up with email.
    We keep them here until they fully convert (profile complete + approved).
    """
    email = models.EmailField(unique=True, db_index=True)
    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    profile = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL)

    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    converted_to_profile = models.BooleanField(default=False)
    last_contacted = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["user_id"]),
        ]

    def __str__(self):
        status = "verified" if self.email_verified else "unverified"
        return f"{self.email} ({status})"

    @property
    def has_profile(self) -> bool:
        return bool(self.profile_id)

    @property
    def status(self) -> str:
        if self.converted_to_profile:
            return "Converted"
        if self.email_verified:
            return "Verified (Preview)"
        return "Unverified"


# ----------------------------
# Blog models
# ----------------------------

User = get_user_model()

class BlogPostQuerySet(models.QuerySet):
    def published(self):
        """Return posts that are published and past their publish_at date."""
        now = timezone.now()
        return self.filter(status="published", publish_at__lte=now)


class BlogPost(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("published", "Published"),
    )

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, help_text="URL slug (auto from title).")
    excerpt = models.TextField(blank=True)
    content = models.TextField()
    category = models.CharField(max_length=80, blank=True)
    featured_image = models.ImageField(upload_to="blog/", blank=True, null=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft")
    publish_at = models.DateTimeField(default=timezone.now, help_text="When this post becomes visible.")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = BlogPostQuerySet.as_manager()

    class Meta:
        ordering = ["-publish_at"]

    def __str__(self):
        return self.title


# ----------------------------
# Social / Messaging / Hot Dates (NEW)
# ----------------------------

class MessageThread(models.Model):
    """
    Conversation between exactly two users. Ordering is normalized (lowest id = user_a).
    """
    user_a = models.ForeignKey(User, on_delete=models.CASCADE, related_name="threads_as_a")
    user_b = models.ForeignKey(User, on_delete=models.CASCADE, related_name="threads_as_b")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user_a", "user_b")
        indexes = [
            models.Index(fields=["user_a", "user_b"]),
            models.Index(fields=["updated_at"]),
        ]

    @staticmethod
    def for_users(u1, u2):
        a, b = sorted([u1.id, u2.id])
        obj, _ = MessageThread.objects.get_or_create(user_a_id=a, user_b_id=b)
        return obj

    def other(self, user):
        return self.user_b if self.user_a_id == user.id else self.user_a

    def __str__(self):
        return f"Thread<{self.user_a_id}-{self.user_b_id}>"


class Message(models.Model):
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["thread", "id"]),
            models.Index(fields=["thread", "created_at"]),
        ]

    @property
    def recipient(self):
        return self.thread.other(self.sender)

    def __str__(self):
        return f"Msg<{self.id}> from {self.sender_id}"


class Favorite(models.Model):
    """
    Who you have favourited (user -> target).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="favorites_made")   # who favourites
    target = models.ForeignKey(User, on_delete=models.CASCADE, related_name="favorited_by")   # who is favourited
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "target")
        indexes = [
            models.Index(fields=["user", "target"]),
            models.Index(fields=["target", "created_at"]),
        ]

    def __str__(self):
        return f"Fav<{self.user_id}->{self.target_id}>"


class Block(models.Model):
    """
    Prevent contact between two users (blocker blocks blocked).
    """
    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocks_made")
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocked_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("blocker", "blocked")
        indexes = [
            models.Index(fields=["blocker", "blocked"]),
        ]

    def __str__(self):
        return f"Block<{self.blocker_id} x {self.blocked_id}>"


class HotDate(models.Model):
    """
    A time-bound, broadcast-style 'date availability' post.
    The flame icon flashes when there is an active HotDate the user hasn't seen since it was last updated.
    """
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hot_dates")
    title = models.CharField(max_length=120)
    details = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["starts_at", "expires_at"]),
            models.Index(fields=["updated_at"]),
        ]

    @property
    def is_active(self):
        now = timezone.now()
        return self.starts_at <= now < self.expires_at

    def __str__(self):
        return f"HotDate<{self.title}>"

