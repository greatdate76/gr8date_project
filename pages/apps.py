from django.apps import AppConfig

class PagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pages"

    def ready(self):
        # Ensure signals are registered at startup
        import pages.signals  # noqa: F401

