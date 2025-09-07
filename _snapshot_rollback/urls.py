from django.urls import path
from . import views

app_name = "pages"

urlpatterns = [
    path("", views.index, name="index"),   # root: /  -> 'pages:index'
    path("", views.index, name="home"),    # alias:   -> 'pages:home'
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profiles/<int:pk>/", views.profile_detail, name="profile_detail"),
    path("profiles/<int:pk>/request-private/", views.request_private_access, name="request_private_access"),
    path("profiles/<int:pk>/block/", views.block_profile, name="block_profile"),
    path("marketing/", views.marketing, name="marketing"),
    path("messages/", views.messages, name="messages"),
    path("login/", views.login_page, name="login"),
    path("signup/", views.signup_page, name="signup"),
    path("about/", views.about_page, name="about"),
    path("privacy/", views.privacy_page, name="privacy"),
    path("terms/", views.terms_page, name="terms"),
    path("contact/", views.contact_page, name="contact"),
    path("faq/", views.faq_page, name="faq"),
    path("logout/", views.logout_view, name="logout"),
    path("my-profile/", views.my_profile, name="my_profile"),
    path("my-profile/edit/", views.my_profile_edit, name="my_profile_edit"),
    path("hot-dates/", views.hot_dates, name="hot_dates"),
    path("blog/", views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),
]

