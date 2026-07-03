# Generated for WKAP V0.

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="RawEmail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("gmail_message_id", models.CharField(max_length=255, unique=True)),
                ("sender_email", models.EmailField(max_length=254)),
                ("subject", models.CharField(blank=True, max_length=500)),
                ("raw_body", models.TextField()),
                ("received_at", models.DateTimeField()),
                (
                    "classification",
                    models.CharField(
                        choices=[
                            ("unclassified", "Unclassified"),
                            ("radar", "Radar Feed"),
                            ("wow", "WoW"),
                            ("unknown", "Unknown"),
                            ("spam", "Spam"),
                            ("error", "Error"),
                        ],
                        db_index=True,
                        default="unclassified",
                        max_length=32,
                    ),
                ),
                (
                    "processing_status",
                    models.CharField(
                        choices=[
                            ("received", "Received"),
                            ("saved", "Saved"),
                            ("classified", "Classified"),
                            ("parsed", "Parsed"),
                            ("published", "Published"),
                            ("rejected", "Rejected"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="received",
                        max_length=32,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-received_at", "-id"]},
        ),
    ]
