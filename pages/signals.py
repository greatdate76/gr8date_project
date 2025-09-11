# pages/signals.py
from django.conf import settings
from django.core.mail import send_mail, BadHeaderError
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from .models import Message, Favorite

DEFAULT_FROM = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@example.com")
SITE_BASE_URL = getattr(settings, "SITE_BASE_URL", "http://127.0.0.1:8000")

def _safe_send(subject: str, body: str, to_email: str):
    if not to_email:
        return
    try:
        send_mail(subject, body, DEFAULT_FROM, [to_email], fail_silently=True)
    except BadHeaderError:
        pass

@receiver(post_save, sender=Message)
def email_on_new_message(sender, instance: Message, created, **kwargs):
    if not created:
        return
    recipient = instance.recipient
    to_email = getattr(recipient, "email", None)
    if not to_email:
        return
    try:
        path = reverse("messages_inbox")  # change if your inbox URL name differs
    except Exception:
        path = "/"
    subject = "You’ve got a new message on GR8DATE"
    body = (
        f"Hi {getattr(recipient, 'first_name', '') or recipient.username},\n\n"
        f"You’ve received a new message. Sign in to reply:\n{SITE_BASE_URL}{path}\n\n— GR8DATE"
    )
    _safe_send(subject, body, to_email)

@receiver(post_save, sender=Favorite)
def email_on_favorited(sender, instance: Favorite, created, **kwargs):
    if not created:
        return
    target = instance.target
    to_email = getattr(target, "email", None)
    if not to_email:
        return
    try:
        path = reverse("matches")  # change if your matches URL name differs
    except Exception:
        path = "/"
    subject = "Someone favourited your profile on GR8DATE"
    body = (
        f"Hi {getattr(target, 'first_name', '') or target.username},\n\n"
        f"Good news—someone just favourited your profile. Check it out:\n{SITE_BASE_URL}{path}\n\n— GR8DATE"
    )
    _safe_send(subject, body, to_email)

