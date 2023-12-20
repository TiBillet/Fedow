from django.urls import path, include
import fedow_dashboard.views as dashboard_views
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

urlpatterns = [
    path('place/<uuid:pk>/', dashboard_views.place_view, name='place'),
    path('asset/<uuid:pk>/', dashboard_views.asset_view, name='asset'),
    path('', dashboard_views.index, name='index'),
]
