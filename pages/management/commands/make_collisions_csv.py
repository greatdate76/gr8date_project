from django.core.management.base import BaseCommand
from django.db.models import F
from pathlib import Path
import csv

from pages.models import Profile, ProfileImage

def clean(s): return (s or "").strip()

class Command(BaseCommand):
    help = "Scan DB for images assigned to multiple users and write cross_user_collisions.csv"

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="Path to write cross_user_collisions.csv")
        parser.add_argument("--master-csv", help="Optional master CSV to help choose an owner (e.g. rebuild_master.csv)")

    def handle(self, *args, **opts):
        out_path = Path(opts["out"]).expanduser()
        master_csv = opts.get("master_csv")
        master_map = {}  # image -> set(user_id)

        # Optional: load master CSV to suggest owner_choice
        if master_csv:
            mp = Path(master_csv).expanduser()
            if mp.exists():
                with mp.open(newline="", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        uid = clean(row.get("user_id"))
                        if not uid.isdigit():
                            continue
                        uid = int(uid)
                        for col in ("profile_image", "additional_images", "private_images"):
                            val = clean(row.get(col))
                            if not val:
                                continue
                            for p in [x.strip() for x in val.replace(",", ";").split(";") if x.strip()]:
                                master_map.setdefault(p, set()).add(uid)
                self.stdout.write(self.style.NOTICE(f"Loaded master hints from {mp}"))
            else:
                self.stdout.write(self.style.WARNING(f"Master CSV not found: {mp} (continuing without)"))

        # Build image -> set(users) from DB
        rows = (
            ProfileImage.objects
            .select_related("profile")
            .values(img=F("image"), uid=F("profile__user_id"))
        )

        img_to_users = {}
        for r in rows:
            img = clean(r["img"])
            uid = int(r["uid"])
            if not img:
                continue
            img_to_users.setdefault(img, set()).add(uid)

        collisions = [(img, sorted(uids)) for img, uids in img_to_users.items() if len(uids) > 1]
        collisions.sort(key=lambda t: (t[0].split("/")[-1].lower(), t[0]))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["image", "user_ids", "owner_choice", "reason"])
            for img, uids in collisions:
                owner = ""
                reason = ""
                # Try to pick an owner if master hints say only one user referenced this image
                if img in master_map and len(master_map[img]) == 1:
                    owner = str(next(iter(master_map[img])))
                    reason = "master_csv"
                else:
                    # Leave blank; resolver will fall back (e.g., smallest user_id)
                    owner = ""
                    reason = "tie_or_unknown"
                w.writerow([img, ";".join(str(u) for u in uids), owner, reason])

        self.stdout.write(self.style.SUCCESS(
            f"Wrote collisions: {out_path} (total {len(collisions)})"
        ))

