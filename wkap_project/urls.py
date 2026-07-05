from django.contrib import admin
from django.urls import path, re_path

from ingestion import views as ingestion_views
from publishing import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("internal/cloudflare-email-ingest/", ingestion_views.cloudflare_email_ingest, name="cloudflare_email_ingest"),
    path("", views.home, name="home"),
    path("submit-to-wkap-ledger.html", views.submit_to_ledger, name="submit_to_ledger"),
    path("specs/wow-packet-v0.1.md", views.markdown_resource, {"resource_key": "wow_packet_v0_1"}, name="wow_packet_spec_v0_1"),
    path("skills/wkap-wow-skill-v0.1.md", views.markdown_resource, {"resource_key": "wkap_wow_skill_v0_1"}, name="wkap_wow_skill_v0_1"),
    path("skills/wkap-wow-codex/SKILL.md", views.markdown_resource, {"resource_key": "wkap_wow_codex_skill"}, name="wkap_wow_codex_skill"),
    path("specs/wow-packet-latest.md", views.markdown_latest_redirect, {"target_path": "/specs/wow-packet-v0.1.md"}, name="wow_packet_spec_latest"),
    path("skills/wkap-wow-skill-latest.md", views.markdown_latest_redirect, {"target_path": "/skills/wkap-wow-skill-v0.1.md"}, name="wkap_wow_skill_latest"),
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
