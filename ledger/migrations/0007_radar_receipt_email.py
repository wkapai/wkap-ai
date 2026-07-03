from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0006_radar_title_500"),
    ]

    operations = [
        migrations.AddField(
            model_name="radarissue",
            name="receipt_email_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="receipt_email_message_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="receipt_email_error",
            field=models.TextField(blank=True),
        ),
    ]
