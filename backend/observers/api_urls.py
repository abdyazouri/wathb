from django.urls import path

from observers import api

urlpatterns = [
    path("", api.ObserverListCreateView.as_view(), name="admin-observers"),
    path("<int:pk>/", api.ObserverDetailView.as_view(), name="admin-observer-detail"),
    path("<int:pk>/link/", api.ObserverLinkView.as_view(), name="admin-observer-link"),
]
