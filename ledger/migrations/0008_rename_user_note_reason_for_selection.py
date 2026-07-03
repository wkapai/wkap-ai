from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0007_radar_receipt_email"),
    ]

    operations = [
        migrations.RenameField(
            model_name="dailywowpacket",
            old_name="user_note",
            new_name="reason_for_selection",
        ),
    ]
