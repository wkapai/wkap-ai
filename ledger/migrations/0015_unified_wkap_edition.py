from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0014_creative_edition"),
    ]

    operations = [
        migrations.AddField(
            model_name="radarissue",
            name="edition_version",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="cover_image_source_url",
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="cover_image_extension",
            field=models.CharField(blank=True, max_length=12),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="cover_image_media_type",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="cover_image_size_bytes",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="cover_image_sha256",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="cover_logo_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="radarissue",
            name="challenge_invitation",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="creativeedition",
            name="article_sha256",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="creativeedition",
            name="article_word_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="creativeedition",
            name="cover_logo_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="creativeedition",
            name="edition_json_github_url",
            field=models.URLField(blank=True, max_length=1000),
        ),
    ]
