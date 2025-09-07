import csv
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from pages.models import Profile, ProfileImage

# Supported delimiters in your CSV image columns
DELIMS = [",", "|", ";"]

def split_urls(value: str):
    """Split a delimited string of URLs into a clean list."""
    if not value:
        return []
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return []
    parts = [s]
    for d in DELIMS:
        if d in s:
            parts = [p.strip() for p in s.split(d)]
            break
    clean = []
    for p in parts:
        if not p:
            continue
        if p.startswith("http://") or p.startswith("https://"):
            clean.append(p)
    return clean

def safe_int(v, default=None):
    try:
        if v in ("", None):
            return default
        return int(float(v))  # accepts "23.0"
    except Exception:
        return default

def filename_from_url(url, fallback="image.jpg"):
    try:
        name = os.path.basename(urlparse(url).path) or fallback
        name = name.split("?")[0].split("#")[0]
        if "." not in name:
            name += ".jpg"
        return name
    except Exception:
        return fallback

def fetch_image_bytes(url, timeout=15):
    resp = requests.get(url, timeout=timeout, stream=True)
    resp.raise_for_status()
    data = resp.content
    if len(data) < 500:  # tiny/invalid
        raise ValueError(f"Image too small: {url}")
    return data

class Command(BaseCommand):
    help = "Import profiles from CSV into Profile + ProfileImage. Skips rows with no public/additional images."

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="Path to CSV file")
        parser.add_argument("--limit", type=int, default=None, help="Optional limit")
        parser.add_argument("--offset", type=int, default=0, help="Optional offset (skip first N rows)")
        parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write to DB")
        parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout for image downloads (sec)")

    def handle(self, *args, **opts):
        csv_path = opts["csv"]
        limit = opts["limit"]
        offset = opts["offset"]
        dry_run = opts["dry_run"]
        timeout = int(opts["timeout"])

        if not os.path.exists(csv_path):
            raise CommandError(f"CSV not found: {csv_path}")

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        total = len(rows)
        start = offset
        end = min(offset + limit, total) if limit is not None else total

        self.stdout.write(self.style.NOTICE(f"Processing rows {start}..{end-1} of {total}"))

        # Expected columns (based on your file preview)
        col_user_id = "user_id"
        col_display = "display_name"
        col_age = "age"
        col_gender = "gender"
        col_bio = "bio"
        col_desc = "description"      # fallback if bio missing
        col_location = "location_x"
        col_public = "images"
        col_additional = "additional_images"
        col_private = "private_images"

        present_cols = rows[0].keys() if rows else []
        for c in [col_user_id, col_public, col_additional, col_private]:
            if c not in present_cols:
                raise CommandError(f"Missing expected column '{c}'. Present: {list(present_cols)}")

        created_profiles = 0
        updated_profiles = 0
        created_images = 0
        skipped_no_images = 0

        def create_images_for(profile, urls, kind, display_name, user_id):
            nonlocal created_images
            pos = 0
            base = slugify(display_name) or f"user-{user_id}"
            for u in urls:
                try:
                    data = fetch_image_bytes(u, timeout=timeout)
                except Exception:
                    # Skip bad/timeout images but keep going
                    continue
                fname = filename_from_url(u, fallback=f"{base}-{kind}-{pos}.jpg")
                # unique-ish name
                name = f"{base}-{kind}-{pos}-{int(time.time()*1000)%100000}.{fname.split('.')[-1]}"
                obj = ProfileImage(profile=profile, kind=kind, position=pos)
                obj.image.save(name, ContentFile(data), save=True)
                created_images += 1
                pos += 1

        for i in range(start, end):
            row = rows[i]

            public_urls = split_urls(row.get(col_public))
            add_urls = split_urls(row.get(col_additional))
            private_urls = split_urls(row.get(col_private))

            # Your rule: skip rows with no public/additional images
            if not public_urls and not add_urls:
                skipped_no_images += 1
                if dry_run:
                    self.stdout.write(f"[{i}] skip (no images) uid={row.get(col_user_id)}")
                continue

            user_id = safe_int(row.get(col_user_id))
            if user_id is None:
                skipped_no_images += 1
                if dry_run:
                    self.stdout.write(f"[{i}] skip (no user_id)")
                continue

            display_name = (row.get(col_display) or "").strip() or f"Member_{user_id}"
            age = safe_int(row.get(col_age))
            gender = (row.get(col_gender) or "").strip()
            location = (row.get(col_location) or "").strip()
            bio = (row.get(col_bio) or "").strip() or (row.get(col_desc) or "").strip()

            if dry_run:
                status = "IMPORT"
                self.stdout.write(f"[{i}] {status} uid={user_id} name={display_name} "
                                  f"pub={len(public_urls)} add={len(add_urls)} priv={len(private_urls)}")
                continue

            with transaction.atomic():
                prof, created = Profile.objects.get_or_create(
                    user_id=user_id,
                    defaults={
                        "display_name": display_name,
                        "age": age,
                        "gender": gender,
                        "location": location,
                        "bio": bio,
                    },
                )
                if created:
                    created_profiles += 1
                else:
                    changed = False
                    if display_name and prof.display_name != display_name:
                        prof.display_name = display_name; changed = True
                    if age is not None and prof.age != age:
                        prof.age = age; changed = True
                    if gender and prof.gender != gender:
                        prof.gender = gender; changed = True
                    if location and prof.location != location:
                        prof.location = location; changed = True
                    if bio and prof.bio != bio:
                        prof.bio = bio; changed = True
                    if changed:
                        prof.save(update_fields=["display_name","age","gender","location","bio"])
                        updated_profiles += 1

                # Create images
                create_images_for(prof, public_urls, ProfileImage.PUBLIC, display_name, user_id)
                create_images_for(prof, add_urls, ProfileImage.ADDITIONAL, display_name, user_id)
                create_images_for(prof, private_urls, ProfileImage.PRIVATE, display_name, user_id)

                # Ensure primary_image is set (first public, else first additional)
                if not prof.primary_image:
                    first_public = prof.images.filter(kind=ProfileImage.PUBLIC).order_by("position","id").first()
                    first_add = prof.images.filter(kind=ProfileImage.ADDITIONAL).order_by("position","id").first()
                    first = first_public or first_add
                    if first:
                        # Read the stored file and copy bytes into primary_image (works across storages)
                        first.image.open("rb")
                        data = first.image.read()
                        first.image.close()
                        ext = os.path.splitext(first.image.name)[1] or ".jpg"
                        prof.primary_image.save(f"primary-{prof.user_id}{ext}", ContentFile(data), save=True)

        # Summary
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN finished. Would skip(no images): {skipped_no_images}"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Done. Profiles created: {created_profiles}, updated: {updated_profiles}, "
                f"images created: {created_images}, skipped(no images): {skipped_no_images}"
            ))

