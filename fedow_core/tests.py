from django.test import TestCase
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from fedow_core.models import Configuration
from fedow_core.views import HelloWorld


# Create your tests here.


class APITestCase(TestCase):
    # def setUp(self):
    #     Animal.objects.create(name="lion", sound="roar")
    #     Animal.objects.create(name="cat", sound="meow")

    def test_helloworld(self):
        hello_world = HelloWorld()
        response = hello_world.list(None)

        assert response.status_code == 200
        assert response.data == {'message': 'Hello world!'}
        assert issubclass(HelloWorld, viewsets.ViewSet)
        permissions = hello_world.get_permissions()
        assert len(permissions) == 1
        assert isinstance(hello_world.get_permissions()[0], AllowAny)


class ModelsTest(TestCase):
    # def setUp(self):
    #     Configuration.objects.create(
    #         stripe_mode_test=True,
    #         stripe_test_api_key=None,
    #         stripe_api_key='prout')

    def test_both_api_keys_none(self):
        # config = Configuration.get_solo()
        config = Configuration(stripe_mode_test=True, stripe_test_api_key=None, stripe_api_key=None)

        assert config.get_stripe_api() is None
