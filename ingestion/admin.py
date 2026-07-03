from django.contrib import admin

from .models import RawEmail


@admin.register(RawEmail)
class RawEmailAdmin(admin.ModelAdmin):
    list_display = (
        "gmail_message_id",
        "sender_email",
        "subject",
        "classification",
        "processing_status",
        "received_at",
    )
    list_filter = ("classification", "processing_status", "received_at")
    search_fields = ("gmail_message_id", "sender_email", "subject", "raw_body")
    readonly_fields = ("created_at", "updated_at")
