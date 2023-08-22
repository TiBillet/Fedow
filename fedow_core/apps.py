from django.apps import AppConfig


class FedowCoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fedow_core'
    def ready(self):
        import fedow_core.signals
