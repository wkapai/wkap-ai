from django.db import migrations


def forwards(apps, schema_editor):
    Investor = apps.get_model("ledger", "Investor")
    WoWSubmission = apps.get_model("ledger", "WoWSubmission")
    LedgerEvent = apps.get_model("ledger", "LedgerEvent")

    id_map = {}
    for investor in Investor.objects.all():
        old_id = investor.investor_id
        if old_id.startswith("c") and old_id[1:].isdigit():
            new_id = f"w{old_id[1:]}"
            id_map[old_id] = new_id
            investor.investor_id = new_id
            investor.save(update_fields=["investor_id"])

    for old_id, new_id in id_map.items():
        LedgerEvent.objects.filter(investor_id=old_id).update(investor_id=new_id)

    for submission in WoWSubmission.objects.all():
        changed = False
        for field in ("canonical_url", "github_file_url"):
            value = getattr(submission, field)
            if value:
                updated = _replace_investor_id_urls(value, id_map)
                if updated != value:
                    setattr(submission, field, updated)
                    changed = True
        if changed:
            submission.save(update_fields=["canonical_url", "github_file_url", "updated_at"])


def backwards(apps, schema_editor):
    Investor = apps.get_model("ledger", "Investor")
    WoWSubmission = apps.get_model("ledger", "WoWSubmission")
    LedgerEvent = apps.get_model("ledger", "LedgerEvent")

    id_map = {}
    for investor in Investor.objects.all():
        old_id = investor.investor_id
        if old_id.startswith("w") and old_id[1:].isdigit():
            new_id = f"c{old_id[1:]}"
            id_map[old_id] = new_id
            investor.investor_id = new_id
            investor.save(update_fields=["investor_id"])

    for old_id, new_id in id_map.items():
        LedgerEvent.objects.filter(investor_id=old_id).update(investor_id=new_id)

    for submission in WoWSubmission.objects.all():
        changed = False
        for field in ("canonical_url", "github_file_url"):
            value = getattr(submission, field)
            if value:
                updated = _replace_investor_id_urls(value, id_map)
                if updated != value:
                    setattr(submission, field, updated)
                    changed = True
        if changed:
            submission.save(update_fields=["canonical_url", "github_file_url", "updated_at"])


def _replace_investor_id_urls(value: str, id_map: dict[str, str]) -> str:
    updated = value
    for old_id, new_id in id_map.items():
        updated = updated.replace(f"/investors/{old_id}/", f"/investors/{new_id}/")
        updated = updated.replace(f"wow-{old_id}-", f"wow-{new_id}-")
    return updated


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0002_investor_rename"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
