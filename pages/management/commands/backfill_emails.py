from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from pathlib import Path
import csv

from pages.models import Profile, ProfileContact

User = get_user_model()

class Command(BaseCommand):
    help = "Backfill ProfileContact.email from auth_user or a CSV (user_id,email)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-auth",
            action="store_true",
            help="Populate emails from Django auth User table (User.id == Profile.user_id)."
        )
        parser.add_argument(
            "--csv",
            type=str,
            help="Optional CSV path with columns user_id,email to import."
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing non-empty emails in ProfileContact."
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        overwrite = opts["overwrite"]
        from_auth = opts["from_auth"]
        csv_path = opts.get("csv")

        created = 0
        updated = 0
        skipped = 0

        def set_email(profile: Profile, email: str):
            nonlocal created, updated, skipped
            email = (email or "").strip()
            if not email:
                skipped += 1
                return
            contact, made = ProfileContact.objects.get_or_create(profile=profile, defaults={"email": email})
            if made:
                created += 1
                return
            # existing
            if contact.email and not overwrite:
                skipped += 1
                return
            contact.email = email
            contact.save(update_fields=["email"])
            updated += 1

        if from_auth:
            # Match Profile.user_id to User.id
            users_by_id = {u.id: u for u in User.objects.all()}
            for p in Profile.objects.all():
                u = users_by_id.get(p.user_id)
                if not u:
                    skipped += 1
                    continue
                set_email(p, getattr(u, "email", "") or "")

        if csv_path:
            path = Path(csv_path).expanduser()
            if not path.exists():
                raise SystemExit(f"CSV not found: {path}")
            with path.open(newline="", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    uid = row.get("user_id")
                    email = row.get("email") or row.get("Email") or row.get("EMAIL")
                    try:
                        uid = int(float(uid))
                    except Exception:
                        continue
                    try:
                        p = Profile.objects.get(user_id=uid)
                    except Profile.DoesNotExist:
                        skipped += 1
                        continue
                    set_email(p, email or "")

        self.stdout.write(self.style.SUCCESS(
            f"Done. created={created}, updated={updated}, skipped={skipped}"
        ))

