# core/views_preview.py
from django.conf import settings
from django.shortcuts import render, redirect

def preview_lock(request):
    if not getattr(settings, "PREVIEW_LOCK_ENABLED", False):
        return redirect("/")

    error = None
    next_url = request.GET.get("next") or request.POST.get("next") or "/"

    if request.method == "POST":
        supplied = (request.POST.get("password") or "").strip()
        expected = getattr(settings, "PREVIEW_LOCK_PASSWORD", "")
        if expected and supplied == expected:
            request.session["preview_unlocked"] = True
            return redirect(next_url)
        else:
            error = "Incorrect password. Please try again."

    return render(request, "preview_lock.html", {"error": error, "next": next_url})

