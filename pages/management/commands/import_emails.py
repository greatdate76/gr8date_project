# pages/management/commands/import_emails.py
from pathlib import Path
import csv

from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from pages.models import Profile, ProfileContact


class Command(BaseCommand):
    help = "Import/update profile contact emails from a CSV (maps by user_id)."

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to CSV (e.g. user_profiles_export.csv)",
        )
        parser.add_argument(
            "--id-col",
            default="user_id",
            help="Column name for user id (default: user_id)",
        )
        parser.add_argument(
            "--email-col",
            default="user_email",
            help="Column name for email (default: user_email)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report only; do not write changes.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        csv_path = Path(opts["csv_file"]).expanduser()
        id_col = opts["id_col"]
        email_col = opts["email_col"]
        dry_run = opts["dry_run"]

        if not csv_path.exists():
            raise SystemExit(f"CSV not found: {csv_path}")

        # Counters
        total_rows = 0
        updated = 0
        created = 0
        unchanged = 0
        invalid_email = 0
        missing_id = 0
        missing_profile = 0
        blank_email = 0
        duplicate_rows_skipped = 0

        seen_ids = set()

        with csv_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            cols = [c.strip() for c in reader.fieldnames or []]
            if id_col not in cols or email_col not in cols:
                raise SystemExit(
                    f"CSV must include columns '{id_col}' and '{email_col}'. Found: {cols}"
                )

            for row in reader:
                total_rows += 1
                raw_id = (row.get(id_col) or "").strip()
                raw_email = (row.get(email_col) or "").strip()

                if not raw_id:
                    missing_id += 1
                    continue

                # keep first occurrence if CSV has dup user_id rows
                if raw_id in seen_ids:
                    duplicate_rows_skipped += 1
                    continue
                seen_ids.add(raw_id)

                # parse user_id int
                try:
                    uid = int(float(raw_id))
                except Exception:
                    missing_id += 1
                    continue

                # email checks
                if not raw_email:
                    blank_email += 1
                    continue
                try:
                    validate_email(raw_email)
                except ValidationError:
                    invalid_email += 1
                    continue

                # find profile
                try:
                    profile = Profile.objects.get(user_id=uid)
                except Profile.DoesNotExist:
                    missing_profile += 1
                    continue

                # upsert ProfileContact
                pc, made = ProfileContact.objects.get_or_create(
                    profile=profile,
                    defaults={"email": raw_email},
                )

                if made:
                    if dry_run:
                        created += 1  # simulated
                    else:
                        created += 1
                    continue

                # existing row
                if pc.email == raw_email:
                    unchanged += 1
                else:
                    if dry_run:
                        updated += 1  # simulated
                    else:
                        pc.email = raw_email
                        pc.save(update_fields=["email"])
                        updated += 1

        if dry_run:
            # rollback everything in a dry-run
            transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("=== IMPORT EMAILS SUMMARY ==="))
        self.stdout.write(f"CSV: {csv_path}")
        self.stdout.write(f"Rows read: {total_rows}")
        self.stdout.write(f"Unique user_ids processed: {len(seen_ids)}")
        self.stdout.write(f"Created contact rows: {created}")
        self.stdout.write(f"Updated emails: {updated}")
        self.stdout.write(f"Unchanged: {unchanged}")
        self.stdout.write(f"Skipped blank emails: {blank_email}")
        self.stdout.write(f"Invalid emails: {invalid_email}")
        self.stdout.write(f"Missing user_id: {missing_id}")
        self.stdout.write(f"Missing Profile in DB: {missing_profile}")
        self.stdout.write(f"Duplicate CSV rows skipped: {duplicate_rows_skipped}")
        self.stdout.write(self.style.NOTICE(f"Dry-run: {dry_run}"))

