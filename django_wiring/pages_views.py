from django.shortcuts import render
from django.core.paginator import Paginator
from .models import Profile

def index(request):
    return render(request, "pages/index.html")

def dashboard(request):
    qs = Profile.objects.exclude(primary_image='').exclude(primary_image__isnull=True).order_by('-updated_at', '-created_at')
    paginator = Paginator(qs, 12)
    page_obj = paginator.get_page(request.GET.get('page') or 1)
    return render(request, "pages/dashboard.html", {"page_obj": page_obj, "total_profiles": paginator.count})

def marketing(request):
    total = Profile.objects.count()
    with_images = Profile.objects.exclude(primary_image='').exclude(primary_image__isnull=True).count()
    return render(request, "pages/marketing.html", {"total": total, "with_images": with_images})

def messages(request):
    return render(request, "pages/messages.html")

def login_page(request):   return render(request, "pages/login.html")
def signup_page(request):  return render(request, "pages/signup.html")
def about_page(request):   return render(request, "pages/aboutus.html")
def privacy_page(request): return render(request, "pages/privacy.html")
def terms_page(request):   return render(request, "pages/terms.html")
def contact_page(request): return render(request, "pages/contactus.html")
def faq_page(request):     return render(request, "pages/faq.html")
