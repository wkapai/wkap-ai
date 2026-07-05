from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0008_rename_user_note_reason_for_selection"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailywowpacket",
            name="agent_facts_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="author_id",
            field=models.CharField(blank=True, db_index=True, max_length=120),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="candidate_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="human_summary",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="human_title",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="packet_id",
            field=models.CharField(blank=True, db_index=True, max_length=120),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="packet_spec_url",
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="packet_spec_version",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="public_status",
            field=models.CharField(blank=True, default="published_on_wkap", max_length=80),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="raw_packet_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="scoreable_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="skill_url",
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="skill_version",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="status_update_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="thesis_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="trackable_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="validation_results_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="wow_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="dailywowpacket",
            name="wow_items_json",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
