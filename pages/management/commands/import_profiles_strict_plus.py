import csv, os, re
from urllib.parse import urlparse, urlunparse, quote
import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify
from pages.models import Profile, ProfileImage

HDRS = {"User-Agent": "Mozilla/5.0"}

def split_urls(cell):
    if not cell or not isinstance(cell, str):
        return []
    return [p for p in re.split(r'[\s,;|]+', cell.strip()) if p.lower().startswith('http')]

def normalize_url(u):
    try:
        parts = list(urlparse(u))
        parts[2] = quote(parts[2])
        parts[4] = quote(parts[4], safe="=&")
        return urlunparse(parts)
    except Exception:
        return u

def ensure_ext_candidates(url):
    if '.' in urlparse(url).path.split('/')[-1]:
        return [url]
    return [url + ext for ext in ('.jpg', '.jpeg', '.png')]

def filename_from_url(url, prefix='img'):
    path = urlparse(url).path
    name = os.path.basename(path) or f"{prefix}.jpg"
    if '.' not in name:
        name += '.jpg'
    base, ext = os.path.splitext(name)
    return slugify(base) + ext.lower()

def http_get(url, timeout=10):
    return requests.get(url, stream=True, timeout=timeout, headers=HDRS)

def download_to_content(url, timeout=10, max_bytes=10*1024*1024, retries=1):
    last_err = None
    for _ in range(retries + 1):
        try:
            r = http_get(url, timeout=timeout)
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
        except Exception as e:
            last_err = e
    raise last_err

class Command(BaseCommand):
    help = "Strict import with URL normalization, extension fallbacks, retry, per-row commit"

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--start', type=int, default=0)

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

            pubs = [normalize_url(u) for u in split_urls(row.get('images'))]
            adds = [normalize_url(u) for u in split_urls(row.get('additional_images'))]
            privs = [normalize_url(u) for u in split_urls(row.get('private_images'))]
            candidates_raw = pubs + adds + privs

            if not candidates_raw:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"[{i}] skipped — no image URLs"))
                continue

            downloaded = []
            primary_tuple = None

            for pos, raw in enumerate(candidates_raw):
                for cand in ensure_ext_candidates(raw):
                    try:
                        content = download_to_content(cand, timeout=10, retries=1)
                        fname = filename_from_url(cand, prefix=f"{uid}_img_{pos}")
                        if primary_tuple is None:
                            primary_tuple = (fname, content, cand)
                        downloaded.append((fname, content, cand))
                        break
                    except Exception:
                        continue

            if not downloaded:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"[{i}] skipped — all image downloads failed"))
                continue

            try:
                with transaction.atomic():
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

                    if not dry and primary_tuple and not prof.primary_image:
                        prof.primary_image.save(primary_tuple[0], primary_tuple[1], save=True)
                        saved += 1

                    if not dry:
                        for idx2, (fname, content, url) in enumerate(downloaded):
                            try:
                                kind = ProfileImage.PUBLIC if url in pubs else (ProfileImage.ADDITIONAL if url in adds else ProfileImage.PRIVATE)
                                ProfileImage.objects.create(
                                    profile=prof, image=content, kind=kind, source_url=url, position=idx2
                                )
                                saved += 1
                            except Exception as e:
                                self.stdout.write(self.style.WARNING(f"[{i}] gallery save fail {url} {e}"))
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Interrupted. Partial work kept."))
                break
            except Exception as e:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"[{i}] row error {e}"))
                continue

        self.stdout.write(self.style.SUCCESS(f"Created:{created} Updated:{updated} Images:{saved} Skipped:{skipped}"))
        if dry:
            self.stdout.write(self.style.WARNING("dry-run"))
