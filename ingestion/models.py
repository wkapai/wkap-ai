from django.db import models


class RawEmail(models.Model):
    class Classification(models.TextChoices):
        UNCLASSIFIED = "unclassified", "Unclassified"
        RADAR = "radar", "Radar Feed"
        WOW = "wow", "WoW"
        UNKNOWN = "unknown", "Unknown"
        SPAM = "spam", "Spam"
        ERROR = "error", "Error"

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Received"
        SAVED = "saved", "Saved"
        CLASSIFIED = "classified", "Classified"
        PARSED = "parsed", "Parsed"
        PUBLISHED = "published", "Published"
        NEEDS_FORMAT_FIX = "needs_format_fix", "Needs format fix"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    gmail_message_id = models.CharField(max_length=255, unique=True)
    sender_email = models.EmailField()
    subject = models.CharField(max_length=500, blank=True)
    raw_body = models.TextField()
    received_at = models.DateTimeField()
    classification = models.CharField(
        max_length=32,
        choices=Classification.choices,
        default=Classification.UNCLASSIFIED,
        db_index=True,
    )
    processing_status = models.CharField(
        max_length=32,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at", "-id"]

    def __str__(self) -> str:
        return f"{self.gmail_message_id} ({self.classification})"
