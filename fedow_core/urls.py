from django.urls import path, include
from fedow_core.views import TransactionAPI
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

router.register(r'transaction', TransactionAPI, basename='transaction')

urlpatterns = [
    path('', include(router.urls)),
]
