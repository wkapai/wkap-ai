# Generated for WKAP V0.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("ingestion", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Contributor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cid", models.CharField(db_index=True, max_length=5, unique=True)),
                ("email_private", models.EmailField(max_length=254, unique=True)),
                ("display_name", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(choices=[("active", "Active"), ("blocked", "Blocked")], default="active", max_length=32),
                ),
            ],
            options={"ordering": ["cid"]},
        ),
        migrations.CreateModel(
            name="LedgerEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_name", models.CharField(db_index=True, max_length=120)),
                ("entity_type", models.CharField(blank=True, db_index=True, max_length=64)),
                ("entity_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("run_id", models.UUIDField(db_index=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("started", "Started"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("rejected", "Rejected"),
                            ("skipped", "Skipped"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("timestamp", models.DateTimeField(auto_now_add=True)),
                ("environment", models.CharField(blank=True, max_length=64)),
                ("gmail_message_id", models.CharField(blank=True, db_index=True, max_length=255)),
                ("sender_email", models.EmailField(blank=True, max_length=254)),
                ("cid", models.CharField(blank=True, db_index=True, max_length=5)),
                ("market_date", models.DateField(blank=True, null=True)),
                ("content_hash", models.CharField(blank=True, max_length=64)),
                ("canonical_url", models.URLField(blank=True, max_length=1000)),
                ("github_file_url", models.URLField(blank=True, max_length=1000)),
                ("github_commit_sha", models.CharField(blank=True, max_length=80)),
                ("ots_status", models.CharField(blank=True, max_length=64)),
                ("error_code", models.CharField(blank=True, max_length=120)),
                ("error_message", models.TextField(blank=True)),
                ("details", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["-timestamp", "-id"]},
        ),
        migrations.CreateModel(
            name="RadarIssue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("canonical_url", models.URLField(blank=True, max_length=1000)),
                ("content_sha256", models.CharField(blank=True, db_index=True, max_length=64)),
                ("github_file_url", models.URLField(blank=True, max_length=1000)),
                ("github_commit_sha", models.CharField(blank=True, max_length=80)),
                ("manifest_url", models.URLField(blank=True, max_length=1000)),
                ("ots_status", models.CharField(blank=True, default="not_started", max_length=64)),
                ("ots_proof_url", models.URLField(blank=True, max_length=1000)),
                ("market_date", models.DateField(unique=True)),
                ("title", models.CharField(max_length=240)),
                ("body_text", models.TextField()),
                ("body_html", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source_email",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="radar_issues",
                        to="ingestion.rawemail",
                    ),
                ),
            ],
            options={"ordering": ["-market_date", "-id"]},
        ),
        migrations.CreateModel(
            name="WoWSubmission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("canonical_url", models.URLField(blank=True, max_length=1000)),
                ("content_sha256", models.CharField(blank=True, db_index=True, max_length=64)),
                ("github_file_url", models.URLField(blank=True, max_length=1000)),
                ("github_commit_sha", models.CharField(blank=True, max_length=80)),
                ("manifest_url", models.URLField(blank=True, max_length=1000)),
                ("ots_status", models.CharField(blank=True, default="not_started", max_length=64)),
                ("ots_proof_url", models.URLField(blank=True, max_length=1000)),
                ("market_date", models.DateField()),
                ("claim", models.TextField()),
                ("agent_validatable_test", models.TextField()),
                ("why_worth_watching", models.TextField()),
                ("ticker_or_theme", models.CharField(max_length=200)),
                ("source_links", models.JSONField(blank=True, default=list)),
                ("submitted_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "contributor",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="wows", to="ledger.contributor"),
                ),
                (
                    "source_email",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="wow_submissions",
                        to="ingestion.rawemail",
                    ),
                ),
            ],
            options={
                "ordering": ["-market_date", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("contributor", "market_date", "claim"),
                        name="unique_wow_claim_per_contributor_market_date",
                    )
                ],
            },
        ),
    ]
