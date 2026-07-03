from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0005_wow_receipt_email"),
    ]

    operations = [
        migrations.AlterField(
            model_name="radarissue",
            name="title",
            field=models.CharField(max_length=500),
        ),
    ]
