from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0003_alter_rawemail_classification"),
        ("ledger", "0013_clean_wow_investor_identity_json"),
    ]

    operations = [
        migrations.CreateModel(
            name="CreativeEdition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("canonical_url", models.URLField(blank=True, max_length=1000)),
                ("content_sha256", models.CharField(blank=True, db_index=True, max_length=64)),
                ("github_file_url", models.URLField(blank=True, max_length=1000)),
                ("github_commit_sha", models.CharField(blank=True, max_length=80)),
                ("manifest_url", models.URLField(blank=True, max_length=1000)),
                ("ots_status", models.CharField(blank=True, default="not_started", max_length=64)),
                ("ots_proof_url", models.URLField(blank=True, max_length=1000)),
                ("market_date", models.DateField(db_index=True)),
                ("edition_version", models.PositiveIntegerField(default=1)),
                ("format_version", models.CharField(default="creative_edition_v1", max_length=64)),
                ("title", models.CharField(max_length=500)),
                ("article_url", models.URLField(max_length=1000)),
                ("image_source_url", models.URLField(max_length=1000)),
                ("image_extension", models.CharField(max_length=12)),
                ("image_media_type", models.CharField(max_length=80)),
                ("image_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("image_sha256", models.CharField(db_index=True, max_length=64)),
                ("image_github_url", models.URLField(blank=True, max_length=1000)),
                ("journal_json", models.JSONField(default=dict)),
                ("journal_sha256", models.CharField(db_index=True, max_length=64)),
                ("creator_human", models.CharField(max_length=300)),
                ("creator_ai", models.CharField(max_length=300)),
                ("publisher", models.CharField(default="WKAP.ai", max_length=200)),
                ("ots_proof_version", models.PositiveIntegerField(default=0)),
                ("bitcoin_verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source_email",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="creative_editions",
                        to="ingestion.rawemail",
                    ),
                ),
            ],
            options={"ordering": ["-market_date", "-edition_version", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="creativeedition",
            constraint=models.UniqueConstraint(
                fields=("market_date", "edition_version"),
                name="unique_creative_edition_date_version",
            ),
        ),
    ]
