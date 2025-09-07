from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = "pages"

urlpatterns = [
    path("", views.index, name="index"),
    path("", views.index, name="home"),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("hot-dates/", views.dashboard, name="hot_dates"),

    path("blog/", views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),

    path("profiles/<int:pk>/", views.profile_detail, name="profile_detail"),
    path("my-profile/", views.my_profile, name="my_profile"),
    path("my-profile-edit/", views.my_profile_edit, name="my_profile_edit"),

    # Auth / account
    # Use Django's real login view so front-end login creates a valid session
    path("login/", auth_views.LoginView.as_view(template_name="pages/login.html"), name="login"),
    path("signup/", views.signup_page, name="signup"),
    path("logout/", views.logout_view, name="logout"),

    # Footer/info pages
    path("about-us/", views.about_page, name="about"),
    path("privacy/", views.privacy_page, name="privacy"),
    path("terms/", views.terms_page, name="terms"),
    path("faq/", views.faq_page, name="faq"),
    path("contact/", views.contact_page, name="contact"),

    # Messages
    path("messages/", views.messages_page, name="messages"),

    # Actions
    path("toggle-favorite/<int:pk>/", views.toggle_favorite, name="toggle_favorite"),
    path("block-profile/<int:pk>/", views.block_profile, name="block_profile"),
    path("request-private-access/<int:pk>/", views.request_private_access, name="request_private_access"),
]

