# Generated by Django 4.2 on 2024-09-05 10:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fedow_core', '0011_alter_organizationapikey_unique_together'),
    ]

    operations = [
        migrations.AddField(
            model_name='asset',
            name='archive',
            field=models.BooleanField(default=False),
        ),
    ]
