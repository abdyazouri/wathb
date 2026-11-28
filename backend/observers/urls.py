from django.urls import path

from observers import views

app_name = "observers"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("businesses/", views.businesses, name="businesses"),
    path("activity/", views.activity, name="activity"),
    path("export.csv", views.export_csv, name="export"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("set-password/<str:uidb64>/<str:token>/", views.set_password_view, name="set-password"),
]
