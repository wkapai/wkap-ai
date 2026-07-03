from django.contrib import admin

from .models import AgentSuggestedWoW, DailyWoWPacket, Investor, LedgerEvent, RadarIssue, ReadingLogItem


@admin.register(Investor)
class InvestorAdmin(admin.ModelAdmin):
    list_display = ("investor_id", "display_name", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("investor_id", "email_private", "display_name")


@admin.register(RadarIssue)
class RadarIssueAdmin(admin.ModelAdmin):
    list_display = ("market_date", "title", "content_sha256", "ots_status", "updated_at")
    search_fields = ("title", "body_text", "content_sha256", "github_commit_sha")
    readonly_fields = ("created_at", "updated_at")


class ReadingLogItemInline(admin.TabularInline):
    model = ReadingLogItem
    extra = 0


class AgentSuggestedWoWInline(admin.TabularInline):
    model = AgentSuggestedWoW
    extra = 0


@admin.register(DailyWoWPacket)
class DailyWoWPacketAdmin(admin.ModelAdmin):
    list_display = ("investor", "market_date", "selected_wow_id", "content_sha256", "ots_status")
    list_filter = ("market_date", "ots_status")
    search_fields = ("investor__investor_id", "selected_wow_id", "content_sha256", "raw_email_sha256")
    readonly_fields = ("created_at", "updated_at")
    inlines = (ReadingLogItemInline, AgentSuggestedWoWInline)


@admin.register(LedgerEvent)
class LedgerEventAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "event_name", "status", "entity_type", "entity_id", "run_id")
    list_filter = ("event_name", "status", "entity_type", "environment")
    search_fields = ("run_id", "gmail_message_id", "sender_email", "investor_id", "canonical_url", "error_message")
    readonly_fields = ("timestamp",)
