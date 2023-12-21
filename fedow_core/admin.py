from django.contrib import admin

from fedow_core.models import Federation

# Register your models here.
@admin.register(Federation)
class FederationAdmin(admin.ModelAdmin):
    pass

