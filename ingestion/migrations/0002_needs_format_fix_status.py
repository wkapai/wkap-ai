from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rawemail",
            name="processing_status",
            field=models.CharField(
                choices=[
                    ("received", "Received"),
                    ("saved", "Saved"),
                    ("classified", "Classified"),
                    ("parsed", "Parsed"),
                    ("published", "Published"),
                    ("needs_format_fix", "Needs format fix"),
                    ("rejected", "Rejected"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="received",
                max_length=32,
            ),
        ),
    ]
