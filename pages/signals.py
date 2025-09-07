from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
import secrets

@receiver(user_logged_in)
def reset_dashboard_seed(sender, request, user, **kwargs):
    if request is not None:
        request.session["dash_seed"] = secrets.randbelow(1_000_000_000)

