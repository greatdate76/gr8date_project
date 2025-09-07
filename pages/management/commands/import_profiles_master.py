from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from pathlib import Path
import csv

from pages.models import Profile, ProfileImage

def clean_val(v):
    if v is None: return None
    s = str(v).strip()
    return None if s.lower() in {"", "none", "null", "nan"} else s

def clean_text(v):
    s = clean_val(v)
    return s if s is not None else ""

def to_int(v):
    s = clean_val(v)
    if s is None: return None
    try: return int(float(s))
    except Exception: return None

def split_paths(cell):
    """CSV stores multi-images as ';' separated (commas tolerated)."""
    s = clean_val(cell)
    if not s: return []
    return [part.strip() for part in str(s).replace(",", ";").split(";") if part.strip()]

def rel_media(path_str):
    """'media/profiles/user_1602/x.jpg' or '/media/profiles/...' -> 'profiles/user_1602/x.jpg'"""
    if not path_str: return None
    p = str(path_str).lstrip("/")
    if p.startswith("media/"): p = p[len("media/"):]
    return p

def file_exists_under_media(path_rel):
    return bool(path_rel) and (Path(settings.MEDIA_ROOT) / path_rel).exists()

class Command(BaseCommand):
    help = "Import master CSV (local media paths) into Profile + ProfileImage."

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Path to CSV with media paths")
        parser.add_argument("--clear-images", action="store_true", help="Clear existing gallery before re-adding")
        parser.add_argument("--no-text", action="store_true", help="Skip text fields (only images)")

    @transaction.atomic
    def handle(self, *args, **opts):
        path = opts["csv_file"]
        clear_images = opts["clear_images"]
        no_text = opts["no_text"]

        created_profiles = updated_profiles = created_images = skipped_files = 0

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = to_int(row.get("user_id"))
                if uid is None: continue

                defaults = {}
                if not no_text:
                    defaults.update({
                        "display_name": clean_text(row.get("username")) or clean_text(row.get("display_name")),
                        "age": to_int(row.get("age")),
                        "gender": clean_text(row.get("gender")),
                        "location": clean_text(row.get("location")),
                        "bio": clean_text(row.get("description")) or clean_text(row.get("bio")),
                    })

                profile, made = Profile.objects.update_or_create(user_id=uid, defaults=defaults)
                created_profiles += int(made); updated_profiles += int(not made)

                if clear_images and not made:
                    ProfileImage.objects.filter(profile=profile).delete()

                # --- primary image: take FIRST of possibly many in profile_image ---
                profile_list = split_paths(row.get("profile_image"))
                primary_rel = rel_media(profile_list[0]) if profile_list else None
                if primary_rel and file_exists_under_media(primary_rel):
                    if not profile.primary_image or profile.primary_image.name != primary_rel:
                        profile.primary_image.name = primary_rel
                        profile.save(update_fields=["primary_image"])
                    if not ProfileImage.objects.filter(
                        profile=profile, kind=ProfileImage.PUBLIC, position=0, image=primary_rel
                    ).exists():
                        ProfileImage.objects.create(
                            profile=profile,
                            kind=ProfileImage.PUBLIC,
                            position=0,
                            image=primary_rel,
                            source_url="",
                        )
                        created_images += 1
                elif primary_rel:
                    # bad path (likely because it contained ';...' originally)
                    skipped_files += 1

                # --- additional images: leftovers from profile_image + additional_images column ---
                addl_sources = (profile_list[1:] if profile_list else []) + split_paths(row.get("additional_images"))
                pos = 1
                for pth in addl_sources:
                    rel = rel_media(pth)
                    if not rel or not file_exists_under_media(rel):
                        skipped_files += 1
                        continue
                    if not ProfileImage.objects.filter(profile=profile, kind=ProfileImage.ADDITIONAL, image=rel).exists():
                        ProfileImage.objects.create(
                            profile=profile,
                            kind=ProfileImage.ADDITIONAL,
                            position=pos,
                            image=rel,
                            source_url="",
                        )
                        created_images += 1
                    pos += 1

                # --- private images (unchanged) ---
                pos = 1
                for pth in split_paths(row.get("private_images")):
                    rel = rel_media(pth)
                    if not rel or not file_exists_under_media(rel):
                        skipped_files += 1
                        continue
                    if not ProfileImage.objects.filter(profile=profile, kind=ProfileImage.PRIVATE, image=rel).exists():
                        ProfileImage.objects.create(
                            profile=profile,
                            kind=ProfileImage.PRIVATE,
                            position=pos,
                            image=rel,
                            source_url="",
                        )
                        created_images += 1
                    pos += 1

        self.stdout.write(self.style.SUCCESS(
            f"Profiles created: {created_profiles}, updated: {updated_profiles}; "
            f"images created: {created_images}; skipped missing files: {skipped_files}"
        ))
