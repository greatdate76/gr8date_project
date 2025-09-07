import os
from django.core.management.base import BaseCommand
from django.db import transaction
from pages.models import Profile, ProfileImage

class Command(BaseCommand):
    help = (
        "Normalize profiles:\n"
        " - If no primary_image, promote first ADDITIONAL (else PUBLIC) to primary.\n"
        " - If still none and profile has only PRIVATE (or no images), DELETE profile.\n"
        "Use --dry-run to preview changes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Don't write changes; just report.")
        parser.add_argument("--limit", type=int, default=None, help="Process at most N profiles.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        limit = opts["limit"]

        qs = Profile.objects.all().prefetch_related("images").order_by("id")
        if limit:
            qs = qs[:limit]

        promoted = 0
        deleted  = 0
        kept     = 0

        with transaction.atomic():
            for p in qs:
                has_primary = bool(p.primary_image and getattr(p.primary_image, "name", ""))
                imgs = list(p.images.all())

                additional = [im for im in imgs if im.kind == "additional" and im.image and getattr(im.image, "name", "")]
                public     = [im for im in imgs if im.kind == "public"     and im.image and getattr(im.image, "name", "")]
                private    = [im for im in imgs if im.kind == "private"    and im.image and getattr(im.image, "name", "")]

                if not has_primary:
                    candidate = (additional[:1] or public[:1])
                    if candidate:
                        im = candidate[0]
                        p.primary_image = im.image  # set file directly
                        if not dry:
                            p.save(update_fields=["primary_image", "updated_at"])
                        promoted += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"[PROMOTED] Profile {p.id} -> primary from {im.kind} ({im.id})"
                        ))
                    else:
                        # No additional/public; only private or nothing: delete
                        if not private:
                            # nothing at all
                            reason = "no images"
                        else:
                            reason = "only private images"
                        if not dry:
                            p.delete()  # cascades to images
                        deleted += 1
                        self.stdout.write(self.style.WARNING(
                            f"[DELETED] Profile {p.id} ({reason})"
                        ))
                        continue  # don't count as kept

                kept += 1

            if dry:
                self.stdout.write(self.style.NOTICE("Dry run complete; no changes were written."))
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"Summary: promoted={promoted}, deleted={deleted}, kept={kept}"
            ))
            if dry:
                transaction.set_rollback(True)

