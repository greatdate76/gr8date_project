from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .api import (  # <-- appended import for API endpoints
    ThreadsListAPIView,
    ThreadMessagesAPIView,
    BlockToggleAPIView,
    NotificationsSummaryAPIView,
)

app_name = "pages"

urlpatterns = [
    path("", views.index, name="index"),  # Homepage view
    path('profile/edit/', views.my_profile_edit, name='my_profile_edit'),  # Edit profile page
    path('profile/<int:pk>/', views.profile_detail, name='profile'),
    path("create-profile/", views.create_profile, name="create_profile"),  # Profile creation

    # Marketing landing/dashboard (redirect target after email confirm)
    path("marketing/", views.marketing, name="marketing"),  # Marketing page route
    path("dashboard/", views.dashboard, name="dashboard"),
    # CHANGED: hot-dates now uses the dedicated view
    path("hot-dates/", views.hot_dates_list, name="hot_dates"),

    # NEW: matches hub page
    path("matches/", views.matches_page, name="matches"),

    path("blog/", views.blog_list, name="blog_list"),
    path("blog/<slug:slug>/", views.blog_detail, name="blog_detail"),

    path("profiles/<int:pk>/", views.profile_detail, name="profile_detail"),
    path("my-profile/", views.my_profile, name="my_profile"),
    path("my-profile-edit/", views.my_profile_edit, name="my_profile_edit"),

    # Auth / account
    path("login/", auth_views.LoginView.as_view(template_name="pages/login.html"), name="login"),
    path("signup/", views.signup, name="signup"),  # <<< change (was views.signup_page)
    path("logout/", views.logout_view, name="logout"),
    path("post-login/", views.post_login, name="post_login"),

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

    # --------------------------
    # API endpoints (appended)
    # --------------------------
    path("api/messages/threads/", ThreadsListAPIView.as_view(), name="api_threads"),
    path("api/messages/thread/<str:username>/", ThreadMessagesAPIView.as_view(), name="api_thread_messages"),
    path("api/block/<int:user_id>/toggle/", BlockToggleAPIView.as_view(), name="api_block_toggle"),
    path("api/notifications/summary/", NotificationsSummaryAPIView.as_view(), name="notifications_summary"),
]

