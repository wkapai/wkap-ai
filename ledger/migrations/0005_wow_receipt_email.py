from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0004_daily_wow_packet"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailywowpacket",
            name="receipt_email_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="receipt_email_message_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="receipt_email_error",
            field=models.TextField(blank=True),
        ),
    ]
