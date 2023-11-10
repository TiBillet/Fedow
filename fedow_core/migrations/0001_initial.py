# Generated by Django 4.2 on 2023-11-10 16:27

from django.conf import settings
import django.contrib.auth.models
import django.contrib.auth.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import stdimage.models
import stdimage.validators
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='FedowUser',
            fields=[
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('email', models.EmailField(db_index=True, max_length=100, unique=True)),
                ('stripe_customer_id', models.CharField(blank=True, max_length=21, null=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'abstract': False,
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Asset',
            fields=[
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100, unique=True)),
                ('currency_code', models.CharField(max_length=3)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('last_update', models.DateTimeField(auto_now=True, verbose_name="Dernière modification des informations de l'asset")),
                ('img', stdimage.models.JPEGField(blank=True, force_min_size=False, null=True, upload_to='assets/', validators=[stdimage.validators.MinSizeValidator(480, 480), stdimage.validators.MaxSizeValidator(1920, 1920)], variations={'crop': (150, 150, True), 'med': (480, 480), 'thumbnail': (150, 150)}, verbose_name='logo')),
                ('comment', models.TextField(blank=True, null=True)),
                ('category', models.CharField(choices=[('TLF', 'Fiduciary local token'), ('TNF', 'Token local non fiduciaire'), ('FED', 'Fiduciary and federated token on stripe'), ('SUB', 'Membership or subscription')], max_length=3)),
                ('id_price_stripe', models.CharField(blank=True, editable=False, max_length=30, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Card',
            fields=[
                ('uuid', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('first_tag_id', models.CharField(db_index=True, max_length=8, unique=True)),
                ('complete_tag_id_uuid', models.UUIDField(blank=True, null=True)),
                ('qrcode_uuid', models.UUIDField(unique=True)),
                ('number_printed', models.CharField(db_index=True, max_length=8, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='CheckoutStripe',
            fields=[
                ('uuid', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('datetime', models.DateTimeField(auto_now_add=True)),
                ('checkout_session_id_stripe', models.CharField(max_length=80, unique=True)),
                ('status', models.CharField(choices=[('O', 'En attente de paiement'), ('E', 'Expiré'), ('P', 'Payé'), ('W', 'Wallet primaire chargé'), ('V', 'Wallet user chargé'), ('C', 'Annulée')], default='O', max_length=1, verbose_name='Statut de la commande')),
                ('metadata', models.CharField(editable=False, max_length=500)),
                ('asset', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='checkout_stripe', to='fedow_core.asset')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='checkout_stripe', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Wallet',
            fields=[
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(blank=True, max_length=100, null=True)),
                ('private_pem', models.CharField(editable=False, max_length=2048)),
                ('public_pem', models.CharField(editable=False, max_length=512)),
                ('ip', models.GenericIPAddressField(default='0.0.0.0', verbose_name='Ip source')),
            ],
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('hash', models.CharField(editable=False, max_length=64, unique=True)),
                ('ip', models.GenericIPAddressField(verbose_name='Ip source')),
                ('datetime', models.DateTimeField()),
                ('amount', models.PositiveIntegerField()),
                ('comment', models.TextField(blank=True, null=True)),
                ('subscription_start_datetime', models.DateTimeField(blank=True, null=True)),
                ('action', models.CharField(choices=[('F', 'Premier bloc'), ('S', "Vente d'article"), ('C', 'Creation monétaire'), ('R', 'Recharge'), ('T', 'Transfert'), ('B', 'Abonnement ou adhésion')], default='S', max_length=1)),
                ('asset', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transactions', to='fedow_core.asset')),
                ('card', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='transactions', to='fedow_core.card')),
                ('checkout_stripe', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='checkout_stripe', to='fedow_core.checkoutstripe')),
                ('previous_transaction', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='next_transaction', to='fedow_core.transaction')),
                ('primary_card', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='associated_primarycard_transactions', to='fedow_core.card')),
                ('receiver', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transactions_received', to='fedow_core.wallet')),
                ('sender', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transactions_sent', to='fedow_core.wallet')),
            ],
            options={
                'ordering': ['-datetime'],
            },
        ),
        migrations.CreateModel(
            name='Place',
            fields=[
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100, unique=True)),
                ('stripe_connect_account', models.CharField(blank=True, editable=False, max_length=21, null=True)),
                ('stripe_connect_valid', models.BooleanField(default=False)),
                ('cashless_server_ip', models.GenericIPAddressField(blank=True, editable=False, null=True)),
                ('cashless_server_url', models.URLField(blank=True, editable=False, null=True)),
                ('cashless_rsa_pub_key', models.CharField(blank=True, editable=False, help_text='Public rsa Key of cashless server for signature.', max_length=512, null=True)),
                ('cashless_admin_apikey', models.CharField(blank=True, editable=False, help_text='Encrypted API key of cashless server admin.', max_length=256, null=True)),
                ('logo', stdimage.models.JPEGField(blank=True, force_min_size=False, null=True, upload_to='images/', validators=[stdimage.validators.MinSizeValidator(720, 720), stdimage.validators.MaxSizeValidator(1920, 1920)], variations={'crop': (480, 270, True), 'hdr': (720, 720), 'med': (480, 480), 'thumbnail': (150, 90)}, verbose_name='logo')),
                ('admins', models.ManyToManyField(related_name='admin_places', to=settings.AUTH_USER_MODEL)),
                ('wallet', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='place', to='fedow_core.wallet')),
            ],
        ),
        migrations.CreateModel(
            name='Origin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('generation', models.IntegerField()),
                ('img', stdimage.models.JPEGField(blank=True, force_min_size=False, null=True, upload_to='images/', validators=[stdimage.validators.MinSizeValidator(720, 720), stdimage.validators.MaxSizeValidator(1920, 1920)], variations={'crop': (480, 270, True), 'hdr': (720, 720), 'med': (480, 480), 'thumbnail': (150, 90)}, verbose_name='img')),
                ('place', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='origins', to='fedow_core.place')),
            ],
        ),
        migrations.CreateModel(
            name='Federation',
            fields=[
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100, unique=True)),
                ('places', models.ManyToManyField(related_name='federations', to='fedow_core.place')),
            ],
        ),
        migrations.CreateModel(
            name='Configuration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('domain', models.URLField()),
                ('stripe_endpoint_secret_enc', models.CharField(blank=True, editable=False, max_length=100, null=True)),
                ('primary_wallet', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='primary', to='fedow_core.wallet')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='card',
            name='origin',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cards', to='fedow_core.origin'),
        ),
        migrations.AddField(
            model_name='card',
            name='primary_places',
            field=models.ManyToManyField(related_name='primary_cards', to='fedow_core.place'),
        ),
        migrations.AddField(
            model_name='card',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cards', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='card',
            name='wallet_ephemere',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='card_ephemere', to='fedow_core.wallet'),
        ),
        migrations.AddField(
            model_name='asset',
            name='origin',
            field=models.ForeignKey(editable=False, help_text="Lieu ou configuration d'origine", on_delete=django.db.models.deletion.PROTECT, related_name='assets_created', to='fedow_core.wallet'),
        ),
        migrations.AddField(
            model_name='fedowuser',
            name='wallet',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='user', to='fedow_core.wallet'),
        ),
        migrations.CreateModel(
            name='Token',
            fields=[
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('value', models.PositiveIntegerField(default=0, help_text='Valeur, en centimes.')),
                ('asset', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tokens', to='fedow_core.asset')),
                ('wallet', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tokens', to='fedow_core.wallet')),
            ],
            options={
                'unique_together': {('wallet', 'asset')},
            },
        ),
        migrations.CreateModel(
            name='OrganizationAPIKey',
            fields=[
                ('id', models.CharField(editable=False, max_length=150, primary_key=True, serialize=False, unique=True)),
                ('prefix', models.CharField(editable=False, max_length=8, unique=True)),
                ('hashed_key', models.CharField(editable=False, max_length=150)),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('name', models.CharField(default=None, help_text='A free-form name for the API key. Need not be unique. 50 characters max.', max_length=50)),
                ('revoked', models.BooleanField(blank=True, default=False, help_text='If the API key is revoked, clients cannot use it anymore. (This cannot be undone.)')),
                ('expiry_date', models.DateTimeField(blank=True, help_text='Once API key expires, clients cannot use it anymore.', null=True, verbose_name='Expires')),
                ('place', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_keys', to='fedow_core.place')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_keys', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'API key',
                'verbose_name_plural': 'API keys',
                'ordering': ('-created',),
                'unique_together': {('place', 'user')},
            },
        ),
        migrations.AddConstraint(
            model_name='asset',
            constraint=models.UniqueConstraint(condition=models.Q(('category', 'FED')), fields=('category',), name='unique_stripe_primary_asset'),
        ),
    ]
