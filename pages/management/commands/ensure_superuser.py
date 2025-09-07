import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Ensure one or more superusers exist using env vars. Idempotent."

    def handle(self, *args, **options):
        User = get_user_model()

        # Back-compat single-user envs (optional)
        users = []
        if os.getenv("DJANGO_SUPERUSER_USERNAME"):
            users.append({
                "username": os.getenv("DJANGO_SUPERUSER_USERNAME"),
                "email": os.getenv("DJANGO_SUPERUSER_EMAIL", ""),
                "password": os.getenv("DJANGO_SUPERUSER_PASSWORD"),
            })

        # Numbered users: DJANGO_SUPERUSER1_*, DJANGO_SUPERUSER2_*, ...
        i = 1
        while True:
            uname = os.getenv(f"DJANGO_SUPERUSER{i}_USERNAME")
            if not uname:
                break
            users.append({
                "username": uname,
                "email": os.getenv(f"DJANGO_SUPERUSER{i}_EMAIL", ""),
                "password": os.getenv(f"DJANGO_SUPERUSER{i}_PASSWORD"),
            })
            i += 1

        if not users:
            self.stdout.write(self.style.WARNING(
                "No DJANGO_SUPERUSER* env vars set; skipping ensure_superuser."
            ))
            return

        for u in users:
            username = (u.get("username") or "").strip()
            password = (u.get("password") or "").strip()
            email = (u.get("email") or "").strip()

            if not username or not password:
                self.stdout.write(self.style.WARNING(
                    f"Skipping: username/password missing for one entry ({u})."
                ))
                continue

            if User.objects.filter(username=username).exists():
                self.stdout.write(self.style.SUCCESS(
                    f"Superuser '{username}' already exists — OK."
                ))
                continue

            try:
                User.objects.create_superuser(username=username, email=email, password=password)
                self.stdout.write(self.style.SUCCESS(
                    f"Superuser '{username}' created."
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"Failed to create superuser '{username}': {e}"
                ))
                raise

