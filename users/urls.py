from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("register/", views.register, name="register"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("profile/", views.profile_view, name="profile"),
    path("contact/", views.contact, name="contact"),

    # Login/logout
    path("login/", views.PrettyLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),

    # Password change
    path(
        "password-change/",
        auth_views.PasswordChangeView.as_view(template_name="users/password_change_form.html"),
        name="password_change",
    ),
    path(
        "password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="users/password_change_done.html"),
        name="password_change_done",
    ),
]
