# core/views_health.py
from django.http import HttpResponse

def healthz(request):
    return HttpResponse("ok", content_type="text/plain")

