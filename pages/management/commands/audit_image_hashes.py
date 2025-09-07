from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
import hashlib, csv
from collections import defaultdict

from pages.models import ProfileImage, Profile

def sha1_of_file(p: Path, chunk=1024*1024):
    try:
        h = hashlib.sha1()
        with p.open('rb') as f:
            while True:
                b = f.read(chunk)
                if not b: break
                h.update(b)
        return h.hexdigest()
    except Exception:
        return None

class Command(BaseCommand):
    help = "Audit image CONTENT duplicates within a user and across users (by SHA1). Writes CSV reports."

    def add_arguments(self, parser):
        parser.add_argument("--out-dir", required=True, help="Directory to write reports")

    def handle(self, *args, **opts):
        out_dir = Path(opts["out_dir"]).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)

        media_root = Path(settings.MEDIA_ROOT)
        rows = list(ProfileImage.objects.select_related("profile").values(
            "profile__user_id", "kind", "position", "image"
        ))

        # Build hashes
        by_user_hash = defaultdict(lambda: defaultdict(list))  # uid -> sha1 -> [paths]
        hash_to_users = defaultdict(set)                      # sha1 -> set(uids)
        missing = []

        for r in rows:
            uid = r["profile__user_id"]
            rel = (r["image"] or "").strip()
            if not rel:
                continue
            p = (media_root / rel)
            if not p.exists():
                missing.append((uid, rel))
                continue
            h = sha1_of_file(p)
            if not h:
                missing.append((uid, rel))
                continue
            by_user_hash[uid][h].append(rel)
            hash_to_users[h].add(uid)

        # Within-user duplicate report
        with (out_dir / "within_user_content_dupes.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["user_id","sha1","count","paths"])
            total = 0
            for uid, mp in by_user_hash.items():
                for h, paths in mp.items():
                    if len(paths) > 1:
                        total += 1
                        w.writerow([uid, h, len(paths), ";".join(sorted(set(paths)))])
        self.stdout.write(self.style.SUCCESS("Wrote within_user_content_dupes.csv"))

        # Cross-user duplicate report
        with (out_dir / "cross_user_content_dupes.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["sha1","user_ids"])
            total = 0
            for h, uids in hash_to_users.items():
                if len(uids) > 1:
                    total += 1
                    w.writerow([h, ";".join(str(u) for u in sorted(uids))])
        self.stdout.write(self.style.SUCCESS("Wrote cross_user_content_dupes.csv"))

        # Missing/failed files
        with (out_dir / "missing_or_unreadable.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["user_id","image"])
            for uid, rel in missing:
                w.writerow([uid, rel])
        self.stdout.write(self.style.SUCCESS("Wrote missing_or_unreadable.csv"))

        # Console summary
        cu = sum(1 for h,u in hash_to_users.items() if len(u)>1)
        wu = sum(1 for uid, mp in by_user_hash.items() for h,paths in mp.items() if len(paths)>1)
        self.stdout.write(self.style.SUCCESS(
            f"Summary: cross-user content dupes={cu}, within-user content dupes={wu}, missing={len(missing)}"
        ))

