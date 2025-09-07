# pages/management/commands/fix_images.py
from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
import hashlib

from pages.models import Profile, ProfileImage as PI

def sha1_for(rel_path):
    """Return SHA-1 of MEDIA_ROOT/rel_path, or None if file is missing."""
    if not rel_path:
        return None
    p = Path(settings.MEDIA_ROOT) / rel_path
    if not p.exists() or not p.is_file():
        return None
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

class Command(BaseCommand):
    help = (
        "Fix image duplicates for each user.\n"
        "• Always remove ADDITIONAL images that are exact duplicates of the user's primary/avatar image.\n"
        "• With --drop-any-dupes, also remove ANY exact duplicates within a user's gallery "
        "(keeps first by priority: PUBLIC > ADDITIONAL > PRIVATE).\n"
        "• Renumbers positions after changes (PUBLIC keeps 0; ADDITIONAL/PRIVATE start at 1)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--drop-any-dupes",
            action="store_true",
            help="Also remove any duplicate images within the same user (by exact file hash); "
                 "not just duplicates of the primary/avatar image.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without modifying the database.",
        )

    def handle(self, *args, **opts):
        drop_any = opts["drop_any_dupes"]
        dry = opts["dry_run"]

        total_users = 0
        removed_primary_dupes = 0
        removed_other_dupes = 0
        renumbered = 0

        for prof in Profile.objects.all().iterator():
            total_users += 1

            # Primary/avatar hash (from Profile.primary_image)
            primary_rel = (prof.primary_image.name or "").strip()
            primary_h = sha1_for(primary_rel) if primary_rel else None

            # Fetch gallery lists once
            pub_qs  = list(prof.images.filter(kind=PI.PUBLIC).order_by("position"))
            add_qs  = list(prof.images.filter(kind=PI.ADDITIONAL).order_by("position"))
            priv_qs = list(prof.images.filter(kind=PI.PRIVATE).order_by("position"))

            # 1) Remove ADDITIONAL duplicates of primary/avatar
            if primary_h:
                for img in list(add_qs):
                    h = sha1_for((img.image.name or "").strip())
                    if h and h == primary_h:
                        removed_primary_dupes += 1
                        if not dry:
                            img.delete()
                        add_qs.remove(img)

            # 2) Optionally remove ANY duplicates across the user's gallery
            if drop_any:
                # Keep first occurrence by priority: PUBLIC > ADDITIONAL > PRIVATE
                seen = {}

                def mark_or_remove(lst):
                    nonlocal removed_other_dupes
                    for img in list(lst):
                        rel = (img.image.name or "").strip()
                        h = sha1_for(rel)
                        key = ("H", h) if h else ("P", rel)  # fallback to path when file missing
                        if key in seen:
                            removed_other_dupes += 1
                            if not dry:
                                img.delete()
                            lst.remove(img)
                        else:
                            seen[key] = True

                mark_or_remove(pub_qs)
                mark_or_remove(add_qs)
                mark_or_remove(priv_qs)

            # 3) Renumber positions (PUBLIC keeps 0; others 1..n)
            changed = False
            if pub_qs:
                if pub_qs[0].position != 0:
                    changed = True
                    if not dry:
                        pub_qs[0].position = 0
                        pub_qs[0].save(update_fields=["position"])
                for i, img in enumerate(pub_qs[1:], start=1):
                    if img.position != i:
                        changed = True
                        if not dry:
                            img.position = i
                            img.save(update_fields=["position"])

            for i, img in enumerate(add_qs, start=1):
                if img.position != i:
                    changed = True
                    if not dry:
                        img.position = i
                        img.save(update_fields=["position"])

            for i, img in enumerate(priv_qs, start=1):
                if img.position != i:
                    changed = True
                    if not dry:
                        img.position = i
                        img.save(update_fields=["position"])

            if changed:
                renumbered += 1

        self.stdout.write(self.style.SUCCESS(
            f"Users processed: {total_users}\n"
            f"Removed ADDITIONAL duplicates of primary: {removed_primary_dupes}\n"
            f"{'Removed other exact duplicates: ' + str(removed_other_dupes) if drop_any else 'Removed other exact duplicates: 0'}\n"
            f"Users with positions renumbered: {renumbered}\n"
            f"{'(dry run: no changes were written)' if dry else ''}"
        ))

