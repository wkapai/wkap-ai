from django.contrib import admin
from django.urls import path, re_path

from ingestion import views as ingestion_views
from publishing import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("internal/cloudflare-email-ingest/", ingestion_views.cloudflare_email_ingest, name="cloudflare_email_ingest"),
    path("", views.home, name="home"),
    path("submit-to-wkap-ledger.html", views.submit_to_ledger, name="submit_to_ledger"),
    path("daily-wow-chat-sim/", views.daily_wow_chat_sim, name="daily_wow_chat_sim"),
    path("internal/daily-wow-chat-sim/", views.daily_wow_chat_sim_api, name="daily_wow_chat_sim_api"),
    path("specs/wow-packet-v0.2.md", views.markdown_resource, {"resource_key": "wow_packet_v0_2"}, name="wow_packet_spec_v0_2"),
    path("specs/wow-crm-v0.2.json", views.json_resource, {"resource_key": "wow_crm_v0_2"}, name="wow_crm_spec_v0_2"),
    path("specs/wow-intake-flow-v0.2.json", views.json_resource, {"resource_key": "wow_intake_flow_v0_2"}, name="wow_intake_flow_v0_2"),
    path("specs/daily-wow-state-v0.2.schema.json", views.json_resource, {"resource_key": "daily_wow_state_v0_2"}, name="daily_wow_state_schema_v0_2"),
    path("skills/wkap-wow-skill-v0.2.md", views.markdown_resource, {"resource_key": "wkap_wow_skill_v0_2"}, name="wkap_wow_skill_v0_2"),
    path("skills/wkap-wow-codex/SKILL.md", views.markdown_resource, {"resource_key": "wkap_wow_codex_skill"}, name="wkap_wow_codex_skill"),
    path("skills/wkap-wow-codex/references/daily-packet-template.md", views.markdown_resource, {"resource_key": "wkap_wow_codex_daily_packet_template"}, name="wkap_wow_codex_daily_packet_template"),
    path("skills/wkap-wow-codex/references/private-journal-template.md", views.markdown_resource, {"resource_key": "wkap_wow_codex_private_journal_template"}, name="wkap_wow_codex_private_journal_template"),
    path("skills/wkap-wow-codex/references/wow-packet-v0.2.md", views.markdown_resource, {"resource_key": "wkap_wow_codex_packet_snapshot"}, name="wkap_wow_codex_packet_snapshot"),
    path("specs/wow-packet-latest.md", views.markdown_latest_redirect, {"target_path": "/specs/wow-packet-v0.2.md"}, name="wow_packet_spec_latest"),
    path("specs/wow-crm-latest.json", views.markdown_latest_redirect, {"target_path": "/specs/wow-crm-v0.2.json"}, name="wow_crm_spec_latest"),
    path("specs/wow-intake-flow-latest.json", views.markdown_latest_redirect, {"target_path": "/specs/wow-intake-flow-v0.2.json"}, name="wow_intake_flow_latest"),
    path("specs/daily-wow-state-latest.schema.json", views.markdown_latest_redirect, {"target_path": "/specs/daily-wow-state-v0.2.schema.json"}, name="daily_wow_state_schema_latest"),
    path("skills/wkap-wow-skill-latest.md", views.markdown_latest_redirect, {"target_path": "/skills/wkap-wow-skill-v0.2.md"}, name="wkap_wow_skill_latest"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("radar/", views.radar_archive, name="radar_archive"),
    path("investors/", views.investor_archive, name="investor_archive"),
    re_path(
        r"^radar/wkap-radar-feed-(?P<market_date>\d{4}-\d{2}-\d{2})\.html$",
        views.radar_issue,
        name="radar_issue",
    ),
    re_path(r"^investors/(?P<investor_id>w\d{4})/$", views.investor_home, name="investor_home"),
    re_path(
        r"^investors/(?P<investor_id>w\d{4})/wows/$",
        views.investor_wows,
        name="investor_wows",
    ),
    re_path(
        r"^investors/(?P<investor_id>w\d{4})/wows/wow-(?P=investor_id)-(?P<market_date>\d{4}-\d{2}-\d{2})\.html$",
        views.wow_submission,
        name="wow_submission",
    ),
]
