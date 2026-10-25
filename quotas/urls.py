from django.urls import path

from quotas import views

urlpatterns = [
    path("requests/", views.QuotaRequestListCreateView.as_view(), name="request-list"),
    path("requests/<int:pk>/", views.QuotaRequestDetailView.as_view(), name="request-detail"),
    path("requests/<int:pk>/decisions/", views.DecisionCreateView.as_view(), name="request-decide"),
    path("quotas/<int:period_id>/", views.QuotaSummaryView.as_view(), name="quota-summary"),
]
