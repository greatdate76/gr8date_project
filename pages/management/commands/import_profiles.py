import csv, os, re
from urllib.parse import urlparse
import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify
from pages.models import Profile, ProfileImage

def split_urls(cell):
    if not cell or not isinstance(cell, str):
        return []
    return [p for p in re.split(r'[\s,;|]+', cell.strip()) if p.lower().startswith('http')]

def filename_from_url(url, prefix='img'):
    path = urlparse(url).path
    name = os.path.basename(path) or f"{prefix}.jpg"
    if '.' not in name:
        name += '.jpg'
    base, ext = os.path.splitext(name)
    return slugify(base) + ext.lower()

def download_to_content(url, timeout=20, max_bytes=10485760):
    r = requests.get(url, stream=True, timeout=timeout)
    r.raise_for_status()
    total = 0
    chunks = []
    for chunk in r.iter_content(8192):
        if chunk:
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("too_large")
            chunks.append(chunk)
    return ContentFile(b"".join(chunks))

class Command(BaseCommand):
    help = "Import profiles and images from CSV"

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--start', type=int, default=0)

    @transaction.atomic
    def handle(self, *args, **opts):
        csv_path = opts['csv_path']
        dry = opts['dry_run']
        limit = opts['limit']
        start = opts['start']
        if not os.path.exists(csv_path):
            raise CommandError(f"CSV not found: {csv_path}")
        with open(csv_path, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        if start:
            rows = rows[start:]
        if limit is not None:
            rows = rows[:limit]
        created = updated = saved = skipped = 0
        for i, row in enumerate(rows, 1):
            try:
                uid_raw = row.get('user_id') or row.get('uid') or row.get('id')
                uid = int(float(uid_raw))
            except Exception:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"[{i}] invalid user_id"))
                continue
            name = row.get('display_name') or row.get('nickname') or ''
            bio = row.get('bio') or row.get('description') or ''
            gender = row.get('gender') or ''
            age = None
            try:
                age = int(row.get('age')) if row.get('age') else None
            except Exception:
                age = None
            location = row.get('location') or row.get('location_x') or ''
            pubs = split_urls(row.get('images'))
            adds = split_urls(row.get('additional_images'))
            privs = split_urls(row.get('private_images'))
            prof, was_created = Profile.objects.get_or_create(user_id=uid, defaults=dict(
                display_name=name, bio=bio, gender=gender, age=age, location=location
            ))
            if was_created:
                created += 1
            else:
                changed = False
                for f, v in dict(display_name=name, bio=bio, gender=gender, age=age, location=location).items():
                    if v and getattr(prof, f) != v:
                        setattr(prof, f, v)
                        changed = True
                if changed and not dry:
                    prof.save()
                updated += 1
            if pubs and not dry and not prof.primary_image:
                url = pubs[0]
                try:
                    content = download_to_content(url)
                    fname = filename_from_url(url, prefix=f"{prof.user_id}_primary")
                    prof.primary_image.save(fname, content, save=True)
                    saved += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"[{i}] primary fail {url} {e}"))
            def write_gallery(urls, kind):
                nonlocal saved
                for pos, url in enumerate(urls):
                    try:
                        content = download_to_content(url)
                        fname = filename_from_url(url, prefix=f"{prof.user_id}_{kind}_{pos}")
                        ProfileImage.objects.create(profile=prof, image=content, kind=kind, source_url=url, position=pos)
                        saved += 1
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"[{i}] gallery fail {kind} {url} {e}"))
            if not dry:
                write_gallery(pubs, ProfileImage.PUBLIC)
                write_gallery(adds, ProfileImage.ADDITIONAL)
                write_gallery(privs, ProfileImage.PRIVATE)
        self.stdout.write(self.style.SUCCESS(f"Created:{created} Updated:{updated} Images:{saved} Skipped:{skipped}"))
        if dry:
            self.stdout.write(self.style.WARNING("dry-run"))