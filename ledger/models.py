from django.conf import settings
from django.db import models

from ledger.wow_contract import clean_packet_text, public_wow_id


class Investor(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        BLOCKED = "blocked", "Blocked"

    investor_id = models.CharField(max_length=5, unique=True, db_index=True)
    email_private = models.EmailField(unique=True)
    display_name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["investor_id"]

    def __str__(self) -> str:
        return self.investor_id

    @property
    def public_label(self) -> str:
        if self.display_name:
            return self.display_name
        return self.investor_id


class ArtifactProofFields(models.Model):
    canonical_url = models.URLField(max_length=1000, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    github_file_url = models.URLField(max_length=1000, blank=True)
    github_commit_sha = models.CharField(max_length=80, blank=True)
    manifest_url = models.URLField(max_length=1000, blank=True)
    ots_status = models.CharField(max_length=64, blank=True, default="not_started")
    ots_proof_url = models.URLField(max_length=1000, blank=True)

    class Meta:
        abstract = True

    @property
    def opentimestamp_target_url(self) -> str:
        base = settings.WKAP_LEDGER_GITHUB_BASE_URL.rstrip("/")
        if not base or not self.id:
            return ""
        entity_type = "radar" if isinstance(self, RadarIssue) else "wow"
        return f"{base}/timestamps/{entity_type}-{self.id}.json"


class RadarIssue(ArtifactProofFields):
    market_date = models.DateField(unique=True)
    title = models.CharField(max_length=500)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)
    receipt_email_sent_at = models.DateTimeField(null=True, blank=True)
    receipt_email_message_id = models.CharField(max_length=255, blank=True)
    receipt_email_error = models.TextField(blank=True)
    source_email = models.ForeignKey("ingestion.RawEmail", on_delete=models.PROTECT, related_name="radar_issues")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-market_date", "-id"]

    def __str__(self) -> str:
        return f"Radar {self.market_date}: {self.title}"


class DailyWoWPacket(ArtifactProofFields):
    investor = models.ForeignKey(Investor, on_delete=models.PROTECT, related_name="wows")
    market_date = models.DateField()
    format_version = models.CharField(max_length=64, default="wow_packet_v1")
    packet_id = models.CharField(max_length=120, blank=True, db_index=True)
    author_id = models.CharField(max_length=120, blank=True, db_index=True)
    packet_spec_version = models.CharField(max_length=64, blank=True, default="")
    packet_spec_url = models.URLField(max_length=1000, blank=True)
    skill_version = models.CharField(max_length=64, blank=True, default="")
    skill_url = models.URLField(max_length=1000, blank=True)
    selected_wow_id = models.CharField(max_length=80, blank=True)
    reason_for_selection = models.TextField(blank=True)
    closest_rejected_idea = models.TextField(blank=True)
    why_pass = models.TextField(blank=True)
    missing_evidence = models.TextField(blank=True)
    human_title = models.CharField(max_length=500, blank=True)
    human_summary = models.TextField(blank=True)
    raw_packet_json = models.JSONField(default=dict, blank=True)
    agent_facts_json = models.JSONField(default=dict, blank=True)
    validation_results_json = models.JSONField(default=dict, blank=True)
    wow_items_json = models.JSONField(default=list, blank=True)
    wow_count = models.PositiveIntegerField(default=0)
    scoreable_count = models.PositiveIntegerField(default=0)
    trackable_count = models.PositiveIntegerField(default=0)
    thesis_count = models.PositiveIntegerField(default=0)
    candidate_count = models.PositiveIntegerField(default=0)
    status_update_count = models.PositiveIntegerField(default=0)
    public_status = models.CharField(max_length=80, blank=True, default="published_on_wkap")
    raw_email_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    raw_email_github_url = models.URLField(max_length=1000, blank=True)
    raw_email_commit_sha = models.CharField(max_length=80, blank=True)
    receipt_email_sent_at = models.DateTimeField(null=True, blank=True)
    receipt_email_message_id = models.CharField(max_length=255, blank=True)
    receipt_email_error = models.TextField(blank=True)
    source_email = models.ForeignKey("ingestion.RawEmail", on_delete=models.PROTECT, related_name="wow_packets")
    submitted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-market_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["investor", "market_date"],
                name="unique_wow_packet_per_investor_market_date",
            )
        ]

    def __str__(self) -> str:
        return f"WoW {self.investor.investor_id} {self.market_date}"

    @property
    def public_selected_wow_id(self) -> str:
        return public_wow_id(self.investor.investor_id, self.selected_wow_id)


class ReadingLogItem(models.Model):
    packet = models.ForeignKey(DailyWoWPacket, on_delete=models.CASCADE, related_name="reading_items")
    item_number = models.PositiveIntegerField()
    source_title = models.CharField(max_length=500, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    source_type = models.CharField(max_length=120, blank=True)
    published_time = models.CharField(max_length=120, blank=True)
    tickers_or_themes = models.CharField(max_length=500, blank=True)
    reading_origin = models.CharField(max_length=80, blank=True)
    agent_summary = models.TextField(blank=True)

    class Meta:
        ordering = ["item_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["packet", "item_number"], name="unique_reading_item_per_packet")
        ]

    def __str__(self) -> str:
        return f"Reading Item {self.item_number} for {self.packet_id}"


class AgentSuggestedWoW(models.Model):
    packet = models.ForeignKey(DailyWoWPacket, on_delete=models.CASCADE, related_name="suggested_wows")
    item_number = models.PositiveIntegerField()
    wow_id = models.CharField(max_length=80)
    source_refs = models.TextField(blank=True)
    ticker_or_theme = models.CharField(max_length=200, blank=True)
    whats_worth_watching = models.TextField(blank=True)
    why_now = models.TextField(blank=True)
    evidence_to_watch_for = models.TextField(blank=True)
    selected = models.BooleanField(default=False)

    class Meta:
        ordering = ["item_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["packet", "wow_id"], name="unique_suggested_wow_id_per_packet")
        ]

    def __str__(self) -> str:
        return f"{self.wow_id} for {self.packet_id}"

    @property
    def public_wow_id(self) -> str:
        return public_wow_id(self.packet.investor.investor_id, self.wow_id)

    @property
    def public_evidence_to_watch_for(self) -> str:
        return clean_packet_text(self.evidence_to_watch_for)


class LedgerEvent(models.Model):
    class Status(models.TextChoices):
        STARTED = "started", "Started"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"
        SKIPPED = "skipped", "Skipped"

    event_name = models.CharField(max_length=120, db_index=True)
    entity_type = models.CharField(max_length=64, blank=True, db_index=True)
    entity_id = models.CharField(max_length=64, blank=True, db_index=True)
    run_id = models.UUIDField(db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    environment = models.CharField(max_length=64, blank=True)
    gmail_message_id = models.CharField(max_length=255, blank=True, db_index=True)
    sender_email = models.EmailField(blank=True)
    investor_id = models.CharField(max_length=5, blank=True, db_index=True)
    market_date = models.DateField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    canonical_url = models.URLField(max_length=1000, blank=True)
    github_file_url = models.URLField(max_length=1000, blank=True)
    github_commit_sha = models.CharField(max_length=80, blank=True)
    ots_status = models.CharField(max_length=64, blank=True)
    error_code = models.CharField(max_length=120, blank=True)
    error_message = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]

    def __str__(self) -> str:
        return f"{self.event_name} {self.status}"
