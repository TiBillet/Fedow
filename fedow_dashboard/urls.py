from django.urls import path, include
from .views import index
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

# router.register(r'', IndexRESThtmx, basename='index')

urlpatterns = [
    path('', index, name='index'),
]
