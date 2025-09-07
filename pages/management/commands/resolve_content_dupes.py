from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from pathlib import Path
import hashlib, csv
from collections import defaultdict

from pages.models import Profile, ProfileImage

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
    help = (
        "Resolve cross-user content duplicates by SHA1.\n"
        "Keeps one canonical owner per image (primary owner preferred), "
        "removes same-content images from other users, and reparents primary if needed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--out-report", required=True, help="Where to write a CSV report of actions.")
        parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB.")

    def handle(self, *args, **opts):
        out_csv = Path(opts["out_report"]).expanduser()
        dry = opts["dry_run"]
        media_root = Path(settings.MEDIA_ROOT)

        # 1) Build SHA1 maps for all gallery images.
        self.stdout.write("Hashing images, please wait...")
        rows = list(
            ProfileImage.objects
            .select_related("profile")
            .values("id","profile__id","profile__user_id","image","kind","position")
        )

        # Map: sha1 -> list of dicts {row info}
        by_sha = defaultdict(list)
        # Map: path -> sha1 (to help compare with primary later)
        path_to_sha = {}

        for r in rows:
            rel = (r["image"] or "").strip()
            if not rel: 
                continue
            fpath = media_root / rel
            if not fpath.exists():
                # audit said missing=0, but be defensive
                continue
            h = path_to_sha.get(rel)
            if not h:
                h = sha1_of_file(fpath)
                if not h:
                    continue
                path_to_sha[rel] = h
            entry = dict(
                sha1=h,
                pi_id=r["id"],
                profile_id=r["profile__id"],
                user_id=r["profile__user_id"],
                image=rel,
                kind=r["kind"],
                position=r["position"],
            )
            by_sha[h].append(entry)

        # 2) Compute primary-image hashes per user (to prefer primary owner)
        user_primary_sha = {}
        prim_rows = list(Profile.objects.values("id","user_id","primary_image"))
        for pr in prim_rows:
            rel = (pr["primary_image"] or "").strip()
            if not rel:
                continue
            fpath = media_root / rel
            if not fpath.exists():
                continue
            h = path_to_sha.get(rel)
            if not h:
                h = sha1_of_file(fpath)
                if not h:
                    continue
                path_to_sha[rel] = h
            user_primary_sha[pr["user_id"]] = h

        # 3) For each SHA1 used by >1 user, decide the canonical owner and plan removals
        collisions = [(h, items) for h, items in by_sha.items()
                      if len({it["user_id"] for it in items}) > 1]

        self.stdout.write(self.style.WARNING(f"Cross-user content dupes found: {len(collisions)}"))

        actions = []  # rows for report
        removals = [] # list of (ProfileImage.id, user_id, image)
        primary_fixes = []  # (user_id, old_primary, new_primary_or_empty)

        # Helper: choose canonical owner
        def choose_owner(items_for_hash, hash_val):
            # Prefer the user who has this hash as primary
            candidates = sorted(items_for_hash, key=lambda x: (x["user_id"], x["profile_id"], x["position"]))
            primary_users = [it["user_id"] for it in candidates if user_primary_sha.get(it["user_id"]) == hash_val]
            if len(primary_users) == 1:
                return primary_users[0]
            # fallback: lowest user_id
            return min({it["user_id"] for it in candidates})

        # Build quick lookup: for user -> list of ProfileImage entries
        user_to_pis_by_sha = defaultdict(lambda: defaultdict(list))
        for h, items in by_sha.items():
            for it in items:
                user_to_pis_by_sha[it["user_id"]][h].append(it)

        # Build map of user_id -> primary path for quick adjust
        user_to_primary_path = {pr["user_id"]: (pr["primary_image"] or "").strip() for pr in prim_rows}

        @transaction.atomic
        def apply_changes():
            nonlocal removals, primary_fixes
            for h, items in collisions:
                keep_user = choose_owner(items, h)
                lose_users = sorted({it["user_id"] for it in items if it["user_id"] != keep_user})
                # plan removals for lose_users
                for lu in lose_users:
                    for it in user_to_pis_by_sha[lu][h]:
                        removals.append((it["pi_id"], lu, it["image"]))
                        if not dry:
                            try:
                                ProfileImage.objects.filter(id=it["pi_id"]).delete()
                            except Exception:
                                pass

                # If any losing user's PRIMARY equals this content, try to reassign
                for lu in lose_users:
                    prim_path = user_to_primary_path.get(lu) or ""
                    prim_sha = path_to_sha.get(prim_path)
                    if prim_sha == h:
                        # find a replacement: first PUBLIC, else ADDITIONAL, else clear
                        q = ProfileImage.objects.filter(profile__user_id=lu).order_by("kind","position")
                        new_rel = ""
                        if q.exists():
                            # Prefer PUBLIC position=0 if it exists
                            pub = q.filter(kind=ProfileImage.PUBLIC).order_by("position").first()
                            new_rel = pub.image if pub else (q.first().image or "")
                        old_rel = prim_path
                        if not dry:
                            Profile.objects.filter(user_id=lu).update(primary_image=new_rel)
                        primary_fixes.append((lu, old_rel, new_rel))

            # Write report CSV
            out_csv.parent.mkdir(parents=True, exist_ok=True)
            with out_csv.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["action","user_id","image_or_primary","detail"])
                for pi_id, uid, rel in removals:
                    w.writerow(["remove_gallery", uid, rel, f"ProfileImage#{pi_id}"])
                for (uid, old_rel, new_rel) in primary_fixes:
                    w.writerow(["fix_primary", uid, old_rel, f"new={new_rel}"])

        # Apply
        apply_changes()

        self.stdout.write(self.style.SUCCESS(
            f"Users affected (removals): {len(set(uid for _,uid,_ in removals))}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Gallery images removed: {len(removals)}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Primary fixes: {len(primary_fixes)}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Report written to: {out_csv}"
        ))
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY – no database changes were saved."))

