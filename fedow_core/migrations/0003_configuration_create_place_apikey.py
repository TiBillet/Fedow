# Generated by Django 4.2.8 on 2024-02-16 16:40

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('fedow_core', '0002_createplaceapikey_alter_asset_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuration',
            name='create_place_apikey',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='configuration', to='fedow_core.createplaceapikey'),
        ),
    ]