from django.core.management.base import BaseCommand
import csv
from pages.models import Profile  # adjust if your model lives elsewhere

class Command(BaseCommand):
    help = "Import profiles from gr8date_profiles_with_images.csv"

    def add_arguments(self, parser):
        parser.add_argument("csv_file", type=str, help="Path to CSV file")

    def handle(self, *args, **options):
        csv_file = options["csv_file"]
        created = 0
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                profile, made = Profile.objects.get_or_create(
                    user_id=row.get("user_id"),
                    defaults={
                        "username": row.get("username"),
                        "age": row.get("age") or None,
                        "location": row.get("location"),
                        "heading": row.get("heading"),
                        "description": row.get("description"),
                        "seeking": row.get("seeking"),
                        "relationship_status": row.get("relationship_status"),
                        "body_type": row.get("body_type"),
                        "children": row.get("children"),
                        "smoker": row.get("smoker"),
                        "drinker": row.get("drinker"),
                        "profile_image": row.get("profile_image"),
                        "additional_images": row.get("additional_images"),
                        "private_images": row.get("private_images"),
                    },
                )
                if made:
                    created += 1
        self.stdout.write(self.style.SUCCESS(f"Imported {created} profiles."))

