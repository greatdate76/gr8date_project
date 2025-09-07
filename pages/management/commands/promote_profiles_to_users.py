from contextlib import nullcontext
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, ForeignKey, OneToOneField
from django.utils.text import slugify
from pages.models import Profile

# Optional: django-allauth support
try:
    from allauth.account.models import EmailAddress
except Exception:
    EmailAddress = None

class Command(BaseCommand):
    help = "Create/link Users for Profiles (fixes orphaned user_id), with optional activation + email verification."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would happen without writing to the DB.")
        parser.add_argument("--activate", action="store_true",
                            help="Create users as is_active=True (default is False).")
        parser.add_argument("--password", type=str, default="",
                            help="Set this password for all created users (else set unusable).")
        parser.add_argument("--verify-emails", action="store_true",
                            help="Mark user emails as verified (uses django-allauth if available).")
        parser.add_argument("--limit", type=int, default=0,
                            help="Only process the first N profiles (for testing).")

    def handle(self, *args, **opts):
        User = get_user_model()
        dry_run = opts["dry_run"]
        activate = opts["activate"]
        password = opts["password"]
        verify_emails = opts["verify_emails"]
        limit = opts["limit"]

        fields = {f.name: f for f in Profile._meta.get_fields()}
        has_user_rel = "user" in fields and isinstance(fields["user"], (ForeignKey, OneToOneField))
        has_user_id  = "user_id" in fields

        if not has_user_rel and not has_user_id:
            raise CommandError("Profile has neither a 'user' relation nor a 'user_id' field.")

        existing_ids = set(User.objects.values_list("id", flat=True))

        # Profiles needing work: missing link OR orphaned user_id
        if has_user_rel:
            base_qs = Profile.objects.filter(user__isnull=True)
        else:
            base_qs = Profile.objects.filter(Q(user_id__isnull=True) | Q(user_id__in=[0, -1]))
            orphan_qs = Profile.objects.exclude(user_id__isnull=True).exclude(user_id__in=existing_ids)
            base_qs = base_qs.union(orphan_qs)

        total_missing = base_qs.count()
        qs = base_qs.order_by("pk")
        if limit and limit > 0:
            qs = qs[:limit]

        self.stdout.write(self.style.NOTICE(
            f"Profiles needing a user: {total_missing} (processing {qs.count()})"
        ))

        existing_usernames = set(User.objects.values_list("username", flat=True))
        unique_email_required = getattr(User._meta.get_field("email"), "unique", False)
        existing_emails = set(User.objects.values_list("email", flat=True)) if unique_email_required else set()

        def unique_username(base: str) -> str:
            base = slugify(base or "member") or "member"
            max_len = User._meta.get_field("username").max_length
            base = base[: max_len - 6]
            candidate = base
            i = 1
            while candidate in existing_usernames:
                suffix = f"-{i}"
                candidate = (base[: max_len - len(suffix)]) + suffix
                i += 1
            existing_usernames.add(candidate)
            return candidate

        def unique_email_stub(username: str) -> str:
            email = f"{username}@example.invalid"  # non-routable TLD
            if unique_email_required:
                base = username
                i = 1
                while email in existing_emails:
                    email = f"{base}-{i}@example.invalid"
                    i += 1
                existing_emails.add(email)
            return email

        def base_name(p: Profile) -> str:
            for attr in ("username", "display_name", "name", "heading"):
                if hasattr(p, attr):
                    val = getattr(p, attr) or ""
                    if val.strip():
                        return val
            return f"profile-{p.pk}"

        def mark_verified(u, profile=None):
            """
            Mark the user's email as verified.
            If django-allauth is installed, create/update EmailAddress.
            Also tries common boolean flags on User/Profile if present.
            """
            if not u.email:
                return
            if EmailAddress:
                # Ensure a single primary, verified EmailAddress exists
                ea, created = EmailAddress.objects.get_or_create(user=u, email=u.email, defaults={"verified": True, "primary": True})
                if not created:
                    changed = False
                    if not ea.verified:
                        ea.verified = True; changed = True
                    if not ea.primary:
                        # Demote other primaries for this user
                        EmailAddress.objects.filter(user=u, primary=True).exclude(pk=ea.pk).update(primary=False)
                        ea.primary = True; changed = True
                    if changed:
                        ea.save(update_fields=["verified", "primary"])
            # Common custom flags
            for flag in ("email_verified", "is_email_verified", "email_confirmed", "is_email_confirmed"):
                if hasattr(u, flag):
                    setattr(u, flag, True); u.save(update_fields=[flag])
                if profile is not None and hasattr(profile, flag):
                    setattr(profile, flag, True); profile.save(update_fields=[flag])

        created = 0
        skipped = 0
        examples = []

        ctx = transaction.atomic() if not dry_run else nullcontext()
        with ctx:
            for p in qs.iterator(chunk_size=1000):
                try:
                    # If already points to a real user, keep it
                    if has_user_rel and getattr(p, "user_id", None) in existing_ids:
                        continue
                    if has_user_id and (p.user_id in existing_ids):
                        continue

                    username = unique_username(base_name(p))
                    email = unique_email_stub(username)

                    if dry_run:
                        created += 1
                        if len(examples) < 10:
                            examples.append((p.pk, "dry-run", username, email))
                        continue

                    u = User(username=username, email=email, is_active=activate)
                    if password:
                        u.set_password(password)
                    else:
                        u.set_unusable_password()
                    u.save()

                    if has_user_rel:
                        p.user = u
                        p.save(update_fields=["user"])
                    else:
                        p.user_id = u.pk
                        p.save(update_fields=["user_id"])

                    if verify_emails:
                        mark_verified(u, profile=p)

                    existing_ids.add(u.pk)
                    created += 1
                    if len(examples) < 10:
                        examples.append((p.pk, u.pk, username, email))
                except Exception as e:
                    skipped += 1
                    self.stderr.write(f"Skipped profile id={p.pk}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Created {created} users; skipped {skipped}."))
        if examples:
            self.stdout.write("Examples (up to 10):")
            for row in examples:
                self.stdout.write(f"  Profile#{row[0]} -> User#{row[1]}  username={row[2]}  email={row[3]}")
