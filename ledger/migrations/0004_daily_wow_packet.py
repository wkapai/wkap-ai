import hashlib

import django.db.models.deletion
from django.db import migrations, models


def migrate_legacy_wows(apps, schema_editor):
    DailyWoWPacket = apps.get_model("ledger", "DailyWoWPacket")
    AgentSuggestedWoW = apps.get_model("ledger", "AgentSuggestedWoW")
    for packet in DailyWoWPacket.objects.select_related("investor", "source_email"):
        packet.format_version = "wow_packet_v1"
        packet.selected_wow_id = f"WOW-{packet.market_date}-001"
        packet.raw_email_sha256 = hashlib.sha256(packet.source_email.raw_body.encode("utf-8")).hexdigest()
        packet.save(update_fields=["format_version", "selected_wow_id", "raw_email_sha256", "updated_at"])
        AgentSuggestedWoW.objects.get_or_create(
            packet=packet,
            wow_id=packet.selected_wow_id,
            defaults={
                "item_number": 1,
                "source_refs": "Legacy single-signal WoW submission",
                "ticker_or_theme": packet.ticker_or_theme,
                "whats_worth_watching": packet.claim,
                "why_now": packet.why_worth_watching,
                "evidence_to_watch_for": packet.agent_validatable_test,
                "selected": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0001_initial"),
        ("ledger", "0003_investor_id_w_prefix"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="WoWSubmission",
            new_name="DailyWoWPacket",
        ),
        migrations.RemoveConstraint(
            model_name="dailywowpacket",
            name="unique_wow_claim_per_investor_market_date",
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="format_version",
            field=models.CharField(default="wow_packet_v1", max_length=64),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="selected_wow_id",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="user_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="closest_rejected_idea",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="why_pass",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="missing_evidence",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="raw_email_sha256",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="raw_email_github_url",
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="raw_email_commit_sha",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AlterField(
            model_name="dailywowpacket",
            name="source_email",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="wow_packets",
                to="ingestion.rawemail",
            ),
        ),
        migrations.CreateModel(
            name="ReadingLogItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("item_number", models.PositiveIntegerField()),
                ("source_title", models.CharField(blank=True, max_length=500)),
                ("source_url", models.URLField(blank=True, max_length=1000)),
                ("source_type", models.CharField(blank=True, max_length=120)),
                ("published_time", models.CharField(blank=True, max_length=120)),
                ("tickers_or_themes", models.CharField(blank=True, max_length=500)),
                ("reading_origin", models.CharField(blank=True, max_length=80)),
                ("agent_summary", models.TextField(blank=True)),
                (
                    "packet",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reading_items", to="ledger.dailywowpacket"),
                ),
            ],
            options={"ordering": ["item_number", "id"]},
        ),
        migrations.CreateModel(
            name="AgentSuggestedWoW",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("item_number", models.PositiveIntegerField()),
                ("wow_id", models.CharField(max_length=80)),
                ("source_refs", models.TextField(blank=True)),
                ("ticker_or_theme", models.CharField(blank=True, max_length=200)),
                ("whats_worth_watching", models.TextField(blank=True)),
                ("why_now", models.TextField(blank=True)),
                ("evidence_to_watch_for", models.TextField(blank=True)),
                ("selected", models.BooleanField(default=False)),
                (
                    "packet",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="suggested_wows", to="ledger.dailywowpacket"),
                ),
            ],
            options={"ordering": ["item_number", "id"]},
        ),
        migrations.AddConstraint(
            model_name="readinglogitem",
            constraint=models.UniqueConstraint(fields=("packet", "item_number"), name="unique_reading_item_per_packet"),
        ),
        migrations.AddConstraint(
            model_name="agentsuggestedwow",
            constraint=models.UniqueConstraint(fields=("packet", "wow_id"), name="unique_suggested_wow_id_per_packet"),
        ),
        migrations.RunPython(migrate_legacy_wows, migrations.RunPython.noop),
        migrations.RemoveField(model_name="dailywowpacket", name="claim"),
        migrations.RemoveField(model_name="dailywowpacket", name="agent_validatable_test"),
        migrations.RemoveField(model_name="dailywowpacket", name="why_worth_watching"),
        migrations.RemoveField(model_name="dailywowpacket", name="ticker_or_theme"),
        migrations.RemoveField(model_name="dailywowpacket", name="source_links"),
        migrations.AddConstraint(
            model_name="dailywowpacket",
            constraint=models.UniqueConstraint(fields=("investor", "market_date"), name="unique_wow_packet_per_investor_market_date"),
        ),
    ]
