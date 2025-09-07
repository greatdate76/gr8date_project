from django.core.management.base import BaseCommand
from django.db import transaction
from pathlib import Path
import csv

from pages.models import Profile, ProfileExtras

# Simple cleaners
def clean(v):
    if v is None: return None
    s = str(v).strip()
    return None if s.lower() in {"", "none", "null", "nan"} else s

def nz(v):  # non-null string for CharFields/TextFields
    return clean(v) or ""

INT_FIELDS = {"user_id", "age"}

class Command(BaseCommand):
    help = "Populate ProfileExtras (heading, seeking, relationship_status, body_type, children, smoker, height) from a CSV (e.g., gr8date_profiles_full_local.csv or the rebuild master)."

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Path to source CSV.")
        parser.add_argument("--fill-bio-when-empty", action="store_true",
                            help="If Profile.bio is empty, copy CSV description into it.")
        parser.add_argument("--username-col", default="username",
                            help="Optional column name for username/display name (defaults to 'username').")
        parser.add_argument("--display-name-col", default="display_name",
                            help="Optional column name for display name (defaults to 'display_name').")

    @transaction.atomic
    def handle(self, *args, **opts):
        csv_path = Path(opts["csv_file"]).expanduser()
        fill_bio = opts["fill_bio_when_empty"]
        uname_col = opts["username_col"]
        dname_col = opts["display_name_col"]

        if not csv_path.exists():
            raise SystemExit(f"CSV not found: {csv_path}")

        # Column names we’ll look for
        wanted = {
            "user_id",
            "heading",
            "seeking",
            "relationship_status",
            "body_type",
            "children",
            "smoker",
            "height",
            "description",   # for optional bio fill
            "age", "gender", "location",  # harmless if present; ignored unless needed later
            uname_col, dname_col
        }

        created = 0
        updated = 0
        bio_filled = 0
        missing_profiles = 0
        total_rows = 0

        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            hdr = [h.strip() for h in reader.fieldnames or []]
            cols = {h.lower(): h for h in hdr}  # case-insensitive

            def get(row, key):
                col = cols.get(key.lower())
                return row.get(col) if col else None

            # Warn if we’re missing core columns
            core_missing = [c for c in ["user_id"] if c.lower() not in cols]
            if core_missing:
                raise SystemExit(f"CSV missing required column(s): {core_missing}")

            for row in reader:
                total_rows += 1
                try:
                    uid_raw = get(row, "user_id")
                    if uid_raw is None: 
                        continue
                    try:
                        uid = int(float(str(uid_raw)))
                    except Exception:
                        continue

                    try:
                        profile = Profile.objects.get(user_id=uid)
                    except Profile.DoesNotExist:
                        missing_profiles += 1
                        continue

                    # Upsert extras
                    extras_defaults = {
                        "heading": nz(get(row, "heading")),
                        "seeking": nz(get(row, "seeking") or get(row, "describe_seeking") or get(row, "looking_for")),
                        "relationship_status": nz(get(row, "relationship_status")),
                        "body_type": nz(get(row, "body_type")),
                        "children": nz(get(row, "children")),
                        "smoker": nz(get(row, "smoker")),
                        "height": nz(get(row, "height")),
                    }

                    extras, made = ProfileExtras.objects.update_or_create(
                        profile=profile, defaults=extras_defaults
                    )
                    created += int(made)
                    updated += int(not made)

                    # Optionally backfill Profile.bio when empty
                    if fill_bio and not (profile.bio or "").strip():
                        desc = nz(get(row, "description"))
                        if desc:
                            profile.bio = desc
                            profile.save(update_fields=["bio"])
                            bio_filled += 1

                except Exception as e:
                    # Keep going; show a short message (could be expanded to a CSV log if needed)
                    self.stderr.write(f"[WARN] row {total_rows} (user_id={get(row,'user_id')}): {e}")

        self.stdout.write(self.style.SUCCESS(
            f"Rows read: {total_rows}; Extras created: {created}, updated: {updated}; "
            f"missing profiles in DB: {missing_profiles}; bio filled: {bio_filled}"
        ))

