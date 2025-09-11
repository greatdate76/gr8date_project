# pages/apps.py
from django.apps import AppConfig

class PagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pages"

    def ready(self):
        # Auto-register email signals
        from . import signals  # noqa: F401

