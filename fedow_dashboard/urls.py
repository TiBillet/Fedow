from django.urls import path, include
import fedow_dashboard.views as dashboard_views
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'place', dashboard_views.PlaceAPI, basename='place')

urlpatterns = [
    path('dashboard/', include(router.urls)),
    path('', dashboard_views.index, name='index'),
]
