from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Contributor",
            new_name="Investor",
        ),
        migrations.RenameField(
            model_name="investor",
            old_name="cid",
            new_name="investor_id",
        ),
        migrations.AlterModelOptions(
            name="investor",
            options={"ordering": ["investor_id"]},
        ),
        migrations.RenameField(
            model_name="ledgerevent",
            old_name="cid",
            new_name="investor_id",
        ),
        migrations.RemoveConstraint(
            model_name="wowsubmission",
            name="unique_wow_claim_per_contributor_market_date",
        ),
        migrations.RenameField(
            model_name="wowsubmission",
            old_name="contributor",
            new_name="investor",
        ),
        migrations.AddConstraint(
            model_name="wowsubmission",
            constraint=models.UniqueConstraint(
                fields=("investor", "market_date", "claim"),
                name="unique_wow_claim_per_investor_market_date",
            ),
        ),
    ]
