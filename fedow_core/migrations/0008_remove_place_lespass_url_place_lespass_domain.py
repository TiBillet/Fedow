# Generated by Django 4.2.8 on 2024-03-30 11:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fedow_core', '0007_alter_checkoutstripe_checkout_session_id_stripe_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='place',
            name='lespass_url',
        ),
        migrations.AddField(
            model_name='place',
            name='lespass_domain',
            field=models.CharField(blank=True, editable=False, max_length=100, null=True),
        ),
    ]
