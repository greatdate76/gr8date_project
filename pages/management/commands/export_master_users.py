# pages/management/commands/export_master_users.py
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Prefetch

from pages.models import Profile, ProfileImage


def _join_paths(qs: Iterable[ProfileImage]) -> str:
    """Join image field names into a single ';' separated string, no blanks, stable order."""
    parts = []
    for img in qs:
        name = (img.image.name or "").strip()
        if name and name not in parts:
            parts.append(name)
    return ";".join(parts)


class Command(BaseCommand):
    help = "Export a master CSV of current profiles + image paths + bio."

    def add_arguments(self, parser):
        parser.add_argument(
            "out_csv",
            nargs="?",
            help="Output CSV path (default: ~/Downloads/gr8_master_users.csv)",
        )
        parser.add_argument(
            "--only-with-images",
            action="store_true",
            help="Export only profiles that have at least one image (primary/public/additional/private).",
        )
        parser.add_argument(
            "--absolute",
            action="store_true",
            help="Write absolute file paths (joined with MEDIA_ROOT) instead of relative media paths.",
        )

    def handle(self, *args, **opts):
        out_csv = Path(
            opts["out_csv"] or (Path.home() / "Downloads" / "gr8_master_users.csv")
        ).expanduser()
        only_with_images = bool(opts.get("only_with_images"))
        absolute = bool(opts.get("absolute"))

        # Prefetch images once, keep DB hits small
        images_qs = ProfileImage.objects.order_by("kind", "position", "id")
        profiles = (
            Profile.objects
            .prefetch_related(Prefetch("images", queryset=images_qs))
            .order_by("id")
        )

        # Filter if requested
        if only_with_images:
            profiles = [
                p for p in profiles
                if (
                    (p.primary_image and (p.primary_image.name or "").strip())
                    or p.images.exists()
                )
            ]

        out_csv.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "user_id",
            "display_name",
            "age",
            "gender",
            "location",
            "bio",
            "primary_image",
            "public_images",
            "additional_images",
            "private_images",
            "public_count",
            "additional_count",
            "private_count",
            "created_at",
            "updated_at",
        ]

        def to_abs(path_str: str) -> str:
            if not path_str:
                return ""
            if path_str.startswith("http://") or path_str.startswith("https://"):
                return path_str
            p = Path(path_str)
            # Django ImageField usually stores path relative to MEDIA_ROOT
            if p.is_absolute():
                return str(p)
            return str(Path(settings.MEDIA_ROOT) / p)

        with out_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()

            for p in profiles:
                public = [img for img in p.images.all() if img.kind == ProfileImage.PUBLIC]
                addl   = [img for img in p.images.all() if img.kind == ProfileImage.ADDITIONAL]
                priv   = [img for img in p.images.all() if img.kind == ProfileImage.PRIVATE]

                primary = (p.primary_image.name or "").strip() if p.primary_image else ""

                public_s = _join_paths(public)
                addl_s   = _join_paths(addl)
                priv_s   = _join_paths(priv)

                if absolute:
                    primary = to_abs(primary)
                    public_s = ";".join(to_abs(x) for x in public_s.split(";") if x)
                    addl_s   = ";".join(to_abs(x) for x in addl_s.split(";") if x)
                    priv_s   = ";".join(to_abs(x) for x in priv_s.split(";") if x)

                row = {
                    "user_id": p.user_id,
                    "display_name": p.display_name or "",
                    "age": p.age or "",
                    "gender": p.gender or "",
                    "location": p.location or "",
                    "bio": p.bio or "",
                    "primary_image": primary,
                    "public_images": public_s,
                    "additional_images": addl_s,
                    "private_images": priv_s,
                    "public_count": len(public),
                    "additional_count": len(addl),
                    "private_count": len(priv),
                    "created_at": p.created_at.isoformat() if p.created_at else "",
                    "updated_at": p.updated_at.isoformat() if p.updated_at else "",
                }
                w.writerow(row)

        self.stdout.write(self.style.SUCCESS(f"Exported → {out_csv}"))

