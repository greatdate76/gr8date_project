GR8DATE TEMPLATES — DROP-IN FIX
===============================

This pack fixes:
- Missing images/icons (rewritten to use Django {% static %} with your original paths)
- Footer/header links 404 (mapped to Django {% url %} names for your pages)
- Logo paths normalized to: newgr8/images/gr8date-logo.svg and newgr8/images/gr8date-logo-mobile.svg

Install
-------
cd ~/gr8datenew
unzip -o ~/Downloads/gr8date_templates_fixed_dropin.zip -d .

Make sure settings.py has:
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

Wire URLs
---------
Copy django_wiring/pages_urls.py over your pages/urls.py (or merge):
  - privacy, terms, about, faq, contact, login, signup, dashboard, marketing, messages, home

Copy django_wiring/pages_views.py over your pages/views.py (or merge).
Restart dev server:
python manage.py runserver 8010
