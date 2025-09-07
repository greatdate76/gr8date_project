from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("marketing/", views.marketing, name="marketing"),
    path("messages/", views.messages, name="messages"),
    path("login/", views.login_page, name="login"),
    path("signup/", views.signup_page, name="signup"),
    path("about/", views.about_page, name="about"),
    path("privacy/", views.privacy_page, name="privacy"),
    path("terms/", views.terms_page, name="terms"),
    path("contact/", views.contact_page, name="contact"),
    path("faq/", views.faq_page, name="faq"),
]
