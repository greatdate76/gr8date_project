import shutil
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = "Copy seed_media/* into MEDIA_ROOT (skips if seed_media missing)."

    def handle(self, *args, **opts):
        base = Path(settings.BASE_DIR)
        src = base / "seed_media"
        dst = Path(settings.MEDIA_ROOT)

        if not src.exists():
            self.stdout.write("No seed_media directory; skipping.")
            return

        dst.mkdir(parents=True, exist_ok=True)

        copied = 0
        for p in src.rglob("*"):
            if p.is_file():
                rel = p.relative_to(src)
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(p, target)
                    self.stdout.write(f"Copied {rel}")
                    copied += 1
        self.stdout.write(self.style.SUCCESS(f"Seed media copy complete. Files copied: {copied}"))
