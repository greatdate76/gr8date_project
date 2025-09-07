from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from pathlib import Path
import csv
from collections import defaultdict

from pages.models import Profile, ProfileImage

def clean(s):
    return (s or "").strip()

class Command(BaseCommand):
    help = "Resolve cross-user image collisions using cross_user_collisions.csv + source hints."

    def add_arguments(self, parser):
        parser.add_argument(
            "--collisions",
            required=True,
            help="Path to cross_user_collisions.csv produced by the audit.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing.",
        )

    def handle(self, *args, **opts):
        collisions_csv = Path(opts["collisions"]).expanduser()
        dry = opts["dry_run"]

        if not collisions_csv.exists():
            raise SystemExit(f"File not found: {collisions_csv}")

        # collisions file expected columns: image, user_ids, owner_choice, reason
        # (owner_choice & reason were written by the audit script; if absent we’ll fallback)
        rows = []
        with open(collisions_csv, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                rows.append(row)

        removed = 0
        fixed_avatar = 0
        processed_files = 0

        @transaction.atomic
        def apply_changes():
            nonlocal removed, fixed_avatar, processed_files
            for row in rows:
                img = clean(row.get("image"))
                if not img:
                    continue
                processed_files += 1

                # Decide owner
                owner = clean(row.get("owner_choice"))
                if not owner:
                    # Fallback: if the row lists candidate user_ids like "123;456"
                    # choose the smallest as a stable tie-break.
                    cand = [u.strip() for u in (row.get("user_ids") or "").replace(",", ";").split(";") if u.strip().isdigit()]
                    owner = cand and min(cand, key=int) or None
                if not owner or not owner.isdigit():
                    continue
                owner_uid = int(owner)

                # All profiles currently holding this image:
                holders = list(
                    ProfileImage.objects.select_related("profile")
                    .filter(image=img)
                    .values("id", "profile_id", "profile__user_id", "kind", "position", "image")
                )

                # Remove from any profile whose user_id != owner
                for h in holders:
                    if h["profile__user_id"] != owner_uid:
                        if not dry:
                            ProfileImage.objects.filter(id=h["id"]).delete()
                        removed += 1

                # Ensure the owner still has it; if it was removed entirely, nothing to do
                owner_has = ProfileImage.objects.filter(
                    profile__user_id=owner_uid, image=img
                ).exists()

                # If the owner's avatar equals this image for someone else, fix avatars later.
                # Now repair avatars for users who LOST their primary due to removals:
                lost_avatar_profiles = (
                    Profile.objects.filter(primary_image=img)
                    .exclude(user_id=owner_uid)
                    .values_list("id", flat=True)
                )
                for pid in lost_avatar_profiles:
                    p = Profile.objects.get(id=pid)
                    # pick first remaining public/additional
                    pick = (
                        p.images.filter(kind__in=[ProfileImage.PUBLIC, ProfileImage.ADDITIONAL])
                        .order_by("kind", "position")
                        .first()
                    )
                    if pick:
                        if not dry:
                            p.primary_image.name = pick.image.name
                            p.save(update_fields=["primary_image"])
                        fixed_avatar += 1
                    else:
                        # no gallery left; blank avatar
                        if not dry:
                            p.primary_image = ""
                            p.save(update_fields=["primary_image"])
                        fixed_avatar += 1

        if dry:
            self.stdout.write(self.style.WARNING("DRY-RUN: No DB writes will be made."))
            apply_changes()
        else:
            apply_changes()

        self.stdout.write(self.style.SUCCESS(
            f"Processed files: {processed_files}\n"
            f"Removed wrong-owner duplicates: {removed}\n"
            f"Profiles with avatar repaired: {fixed_avatar}"
        ))

