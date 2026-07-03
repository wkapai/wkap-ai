from __future__ import annotations

import json
import base64
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone as datetime_timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from ingestion.models import RawEmail
from ingestion.services import classify_email
from ledger.investor_id import display_name_from_wow_subject, find_or_create_investor
from ledger.models import LedgerEvent
from ledger.services import create_radar_issue, create_wow_submission
from ledger.parsers import ParseError, parse_radar, parse_wow
from publishing.receipts import (
    radar_receipt_body,
    radar_receipt_subject,
    send_radar_receipt,
    send_wow_format_fix_receipt,
    send_wow_receipt,
    wow_format_fix_body,
    wow_receipt_body,
    wow_receipt_subject,
)
from publishing.services import (
    WOW_DISCLAIMER,
    commit_ledger,
    generate_manifest,
    generate_radar_html,
    generate_wow_html,
    publish_artifact,
    rebuild_indexes,
    timestamp_artifact,
    upgrade_opentimestamps,
    validate_ledger,
)


class WKAPV0Tests(TestCase):
    def raw_email(self, *, sender="playinc@gmail.com", subject="WKAP Radar Feed", body="Body: Market context"):
        return RawEmail.objects.create(
            gmail_message_id=f"msg-{RawEmail.objects.count() + 1}",
            sender_email=sender,
            subject=subject,
            raw_body=body,
            received_at=timezone.now(),
        )

    def wow_packet_body(self, *, selected="WOW-2026-06-29-001"):
        lines = [
            "# Daily WoW Packet",
            "",
            "## 1. Reading Log",
            "",
            "### Reading Item 1",
            "source_title: Physical AI suppliers note",
            "source_url: https://example.com/source",
            "source_type: article",
            "published_time: 2026-06-29T13:00:00Z",
            "tickers / themes: Physical AI",
            "reading_origin: user_browsed",
            "agent_summary: Supplier disclosures suggest component revenue may validate demand.",
            "",
            "---",
            "",
            "## 2. Agent Suggested WoW Signals",
            "",
            "### Suggested WoW 1",
            "wow_id: WOW-2026-06-29-001",
            "source_refs: Reading Item 1",
            "ticker / theme: Physical AI",
            "what's_worth_watching: Physical AI suppliers deserve closer review.",
            "why_now: Component revenue can validate the thesis.",
            "what_evidence_should_AI_watch_for: Check next quarterly disclosures.",
            "",
            "### Suggested WoW 2",
            "wow_id: WOW-2026-06-29-002",
            "source_refs: Reading Item 1",
            "ticker / theme: Robotics",
            "what's_worth_watching: Robotics suppliers may show order acceleration.",
            "why_now: Humanoid capex commentary is increasing.",
            "what_evidence_should_AI_watch_for: Track backlog and customer commentary.",
            "",
            "### Suggested WoW 3",
            "wow_id: WOW-2026-06-29-003",
            "source_refs: Reading Item 1",
            "ticker / theme: Edge AI",
            "what's_worth_watching: Edge AI demand may broaden.",
            "why_now: Device makers are discussing local inference.",
            "what_evidence_should_AI_watch_for: Track design wins and shipments.",
            "",
            "## 3. User Selection / Pass",
            "",
            f"selected_wow_id: {selected}",
            "reason_for_selection: Focus on the supplier evidence.",
        ]
        if selected.lower() == "none":
            lines.extend(
                [
                    "",
                    "### If Pass Only",
                    "",
                    "closest_rejected_idea: Robotics suppliers may show order acceleration.",
                    "why_pass: The signal was interesting but not concrete enough today.",
                    "missing_evidence: Confirmed backlog growth or named customer commentary.",
                ]
            )
        return "\n".join(lines)

    def cloudflare_payload(self, *, sender="investor@example.com", subject="Daily WoW Packet - 2026-06-29 - Cloud Agent", body=None):
        body = body or self.wow_packet_body()
        raw_mime = (
            f"From: {sender}\n"
            "To: ledger@wkap.ai\n"
            f"Subject: {subject}\n"
            "Message-ID: <cloudflare-test-1@example.com>\n"
            "Date: Mon, 29 Jun 2026 13:00:00 +0000\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "\n"
            f"{body}"
        ).encode("utf-8")
        return {
            "from": sender,
            "to": "ledger@wkap.ai",
            "subject": subject,
            "message_id": "cloudflare-test-1@example.com",
            "received_at": "Mon, 29 Jun 2026 13:00:00 +0000",
            "raw_mime_base64": base64.b64encode(raw_mime).decode("ascii"),
        }

    def test_classifies_radar_and_wow(self):
        run_id = "00000000-0000-0000-0000-000000000001"
        radar = self.raw_email(subject="WKAP Radar Feed", body="Market_date: 2026-06-30\nBody: Context")
        wow = self.raw_email(
            sender="investor@example.com",
            subject="Daily WoW Packet - 2026-06-29 - Test Agent",
            body=self.wow_packet_body(),
        )

        self.assertEqual(classify_email(radar, run_id=run_id), RawEmail.Classification.RADAR)
        self.assertEqual(classify_email(wow, run_id=run_id), RawEmail.Classification.WOW)

    def test_wow_reading_log_is_limited_to_ten_items(self):
        body = self.wow_packet_body()
        extra_items = []
        for number in range(2, 12):
            extra_items.extend(
                [
                    f"### Reading Item {number}",
                    f"source_title: Extra source {number}",
                    "source_url: https://example.com/extra",
                    "source_type: article",
                    "published_time: 2026-06-29T13:00:00Z",
                    "tickers / themes: AI",
                    "reading_origin: agent_suggested",
                    "agent_summary: Extra item.",
                    "",
                ]
            )
        body = body.replace("## 2. Agent Suggested WoW Signals", "\n".join(extra_items) + "\n## 2. Agent Suggested WoW Signals")
        raw = self.raw_email(
            sender="investor@example.com",
            subject="Daily WoW Packet - 2026-06-29 - Test Agent",
            body=body,
        )

        with self.assertRaisesRegex(ParseError, "at most 10 items"):
            parse_wow(raw)

    def test_cloudflare_ingest_rejects_invalid_secret(self):
        response = self.client.post(
            "/internal/cloudflare-email-ingest/",
            data=json.dumps(self.cloudflare_payload()),
            content_type="application/json",
            HTTP_X_WKAP_WORKER_SECRET="bad",
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(LedgerEvent.objects.filter(event_name="cloudflare_email_auth_failed").exists())
        self.assertEqual(RawEmail.objects.count(), 0)

    def test_cloudflare_ingest_saves_and_publishes_wow_packet(self):
        with TemporaryDirectory() as tmp:
            with override_settings(
                WKAP_CLOUDFLARE_INGEST_SECRET="secret",
                WKAP_PUBLIC_SITE_ROOT=Path(tmp),
                WKAP_LEDGER_REPO_PATH="",
                WKAP_SEND_RECEIPTS=False,
            ):
                response = self.client.post(
                    "/internal/cloudflare-email-ingest/",
                    data=json.dumps(self.cloudflare_payload()),
                    content_type="application/json",
                    HTTP_X_WKAP_WORKER_SECRET="secret",
                )
                payload = response.json()
                expected_page_exists = Path(
                    tmp,
                    "investors",
                    payload["investor_id"],
                    "wows",
                    f"wow-{payload['investor_id']}-2026-06-29.html",
                ).exists()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["entity_type"], "wow")
        raw = RawEmail.objects.get()
        self.assertEqual(raw.gmail_message_id, "cloudflare:cloudflare-test-1@example.com")
        self.assertEqual(raw.classification, RawEmail.Classification.WOW)
        self.assertIn("cloudflare_email_received", set(LedgerEvent.objects.values_list("event_name", flat=True)))
        self.assertTrue(expected_page_exists)

    def test_unauthorized_radar_is_rejected_and_logged(self):
        run_id = "00000000-0000-0000-0000-000000000002"
        raw = self.raw_email(sender="outsider@example.com", body="Market_date: 2026-06-30\nBody: Context")

        with self.assertRaises(PermissionError):
            create_radar_issue(raw, run_id=run_id)

        raw.refresh_from_db()
        self.assertEqual(raw.processing_status, RawEmail.ProcessingStatus.REJECTED)
        self.assertTrue(LedgerEvent.objects.filter(event_name="radar_rejected", status=LedgerEvent.Status.REJECTED).exists())

    def test_radar_parser_reads_newsletter_date_and_title(self):
        body = "\n".join(
            [
                "WKAP Radar Feed",
                "2026-06-29",
                "Physical AI component supply chain, humanoid robotics BOM",
                "",
                "Preheader:",
                "Make your AI track X alpha.",
            ]
        )
        raw = self.raw_email(body=body)

        parsed = parse_radar(raw)

        self.assertEqual(str(parsed.market_date), "2026-06-29")
        self.assertEqual(parsed.title, "Physical AI component supply chain, humanoid robotics BOM")
        self.assertEqual(parsed.body_text, body)

    def test_first_investor_gets_w0202_and_returning_sender_reuses_it(self):
        run_id = "00000000-0000-0000-0000-000000000003"
        first, created = find_or_create_investor("new@example.com", run_id=run_id)
        second, reused_created = find_or_create_investor("new@example.com", run_id=run_id)

        self.assertTrue(created)
        self.assertFalse(reused_created)
        self.assertEqual(first.investor_id, "w0202")
        self.assertEqual(second.investor_id, "w0202")

    def test_wow_subject_name_becomes_public_investor_label(self):
        run_id = "00000000-0000-0000-0000-000000000015"
        raw = self.raw_email(sender="named@example.com", subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=self.wow_packet_body())

        submission = create_wow_submission(raw, run_id=run_id)

        self.assertEqual(display_name_from_wow_subject(raw.subject), "Test Agent")
        self.assertEqual(submission.investor.display_name, "Test Agent")
        self.assertEqual(submission.investor.public_label, "Test Agent")

    def test_wow_html_has_disclaimer_and_hides_private_email(self):
        run_id = "00000000-0000-0000-0000-000000000004"
        raw = self.raw_email(sender="private@example.com", subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=self.wow_packet_body())
        submission = create_wow_submission(raw, run_id=run_id)

        with TemporaryDirectory() as tmp:
            with override_settings(WKAP_PUBLIC_SITE_ROOT=Path(tmp)):
                generate_wow_html(submission, run_id=run_id)
                output = Path(tmp) / "investors" / "w0202" / "wows" / "wow-w0202-2026-06-29.html"
                html = output.read_text(encoding="utf-8")

        self.assertIn(WOW_DISCLAIMER, html)
        self.assertNotIn("private@example.com", html)
        self.assertIn("Reading Log", html)
        self.assertIn("Agent Suggested WoW Signals", html)

    def test_rebuild_indexes_refreshes_existing_artifact_pages(self):
        run_id = "00000000-0000-0000-0000-000000000028"
        raw = self.raw_email(sender="refresh@example.com", subject="Daily WoW Packet - 2026-06-29 - Refresh Agent", body=self.wow_packet_body())
        submission = create_wow_submission(raw, run_id=run_id)

        with TemporaryDirectory() as tmp:
            with override_settings(WKAP_PUBLIC_SITE_ROOT=Path(tmp), WKAP_LEDGER_REPO_PATH=""):
                generate_wow_html(submission, run_id=run_id)
                output = Path(tmp) / "investors" / "w0202" / "wows" / "wow-w0202-2026-06-29.html"
                output.write_text("stale artifact html", encoding="utf-8")

                rebuild_indexes(run_id=run_id)
                html = output.read_text(encoding="utf-8")

        self.assertNotIn("stale artifact html", html)
        self.assertIn('href="/investors/w0202/"', html)

    def test_long_radar_body_preserves_formatting_and_field_like_lines(self):
        run_id = "00000000-0000-0000-0000-000000000020"
        long_section = "\n\n".join(
            f"THESIS_OBJECT_{index}\nRISK_TONE: Mixed\nKEY_QUESTION: Can signal {index} survive verification?\nBody paragraph {index}."
            for index in range(1, 80)
        )
        long_title = "Long Radar " + ("second-order market cognition " * 25)
        raw = self.raw_email(
            subject="WKAP Radar Feed - 2026-07-02",
            body=f"Market_date: 2026-07-02\nTitle: {long_title}\nBody: TODAY_SUMMARY\n\n{long_section}",
        )

        issue = create_radar_issue(raw, run_id=run_id)
        with TemporaryDirectory() as tmp:
            with override_settings(WKAP_PUBLIC_SITE_ROOT=Path(tmp)):
                generate_radar_html(issue, run_id=run_id)
                output = Path(tmp) / "radar" / "wkap-radar-feed-2026-07-02.html"
                html = output.read_text(encoding="utf-8")

        issue.refresh_from_db()
        self.assertLessEqual(len(issue.title), 500)
        self.assertEqual(issue.body_text, raw.raw_body)
        self.assertIn("THESIS_OBJECT_79", issue.body_text)
        self.assertIn("RISK_TONE: Mixed", issue.body_text)
        self.assertIn("THESIS_OBJECT_79", html)
        self.assertGreater(html.count("<p>"), 75)

    def test_radar_body_url_text_renders_as_clickable_links(self):
        run_id = "00000000-0000-0000-0000-000000000025"
        raw = self.raw_email(
            body="Market_date: 2026-07-03\nTitle: Link Radar\nBody: URL:\nhttps://example.com/source\n\nQuestion to ask: What changed?",
        )
        issue = create_radar_issue(raw, run_id=run_id)

        response = self.client.get("/radar/wkap-radar-feed-2026-07-03.html")

        self.assertContains(response, '<a href="https://example.com/source"')

    def test_long_wow_packet_preserves_raw_email_and_long_fields(self):
        run_id = "00000000-0000-0000-0000-000000000021"
        long_summary = " ".join(f"agent observation {index}" for index in range(500))
        long_evidence = " ".join(f"evidence checkpoint {index}" for index in range(500))
        body = self.wow_packet_body().replace(
            "agent_summary: Supplier disclosures suggest component revenue may validate demand.",
            f"agent_summary: {long_summary}",
        ).replace(
            "what_evidence_should_AI_watch_for: Check next quarterly disclosures.",
            f"what_evidence_should_AI_watch_for: {long_evidence}",
        )
        raw = self.raw_email(sender="long-wow@example.com", subject="Daily WoW Packet - 2026-06-29 - Long Agent", body=body)

        packet = create_wow_submission(raw, run_id=run_id)
        with TemporaryDirectory() as tmp:
            with override_settings(WKAP_PUBLIC_SITE_ROOT=Path(tmp)):
                generate_wow_html(packet, run_id=run_id)
                output = Path(tmp) / "investors" / "w0202" / "wows" / "wow-w0202-2026-06-29.html"
                html = output.read_text(encoding="utf-8")

        packet.refresh_from_db()
        reading_item = packet.reading_items.get(item_number=1)
        selected_wow = packet.suggested_wows.get(wow_id="WOW-2026-06-29-001")
        self.assertEqual(packet.source_email.raw_body, body)
        self.assertIn("agent observation 499", reading_item.agent_summary)
        self.assertIn("evidence checkpoint 499", selected_wow.evidence_to_watch_for)
        self.assertIn("agent observation 499", html)
        self.assertIn("evidence checkpoint 499", html)

    def test_wow_packet_parser_reads_reading_log_suggestions_and_selection(self):
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=self.wow_packet_body())

        parsed = parse_wow(raw)

        self.assertEqual(str(parsed.market_date), "2026-06-29")
        self.assertEqual(parsed.format_version, "wow_packet_v1")
        self.assertEqual(len(parsed.reading_items), 1)
        self.assertEqual(len(parsed.suggested_wows), 3)
        self.assertEqual(parsed.selected_wow_id, "WOW-2026-06-29-001")
        self.assertEqual(parsed.reason_for_selection, "Focus on the supplier evidence.")
        self.assertEqual(parsed.suggested_wows[0].ticker_or_theme, "Physical AI")

    def test_wow_packet_parser_tolerates_common_agent_format_drift(self):
        body = self.wow_packet_body().replace("## 1. Reading Log", "1. Reading Log")
        body = body.replace("## 2. Agent Suggested WoW Signals", "Agent Suggested 3 WoWs")
        body = body.replace("## 3. User Selection / Pass", "User Selection")
        body = body.replace("### Reading Item 1", "Reading Item 1")
        body = body.replace("### Suggested WoW 1", "Suggested WoW 1")
        body = body.replace("ticker / theme:", "ticker or theme:")
        body = body.replace("what_evidence_should_AI_watch_for:", "evidence to watch:")
        body = body.replace("selected_wow_id:", "Selected WoW:")
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Drift Agent", body=body)

        parsed = parse_wow(raw)

        self.assertEqual(parsed.selected_wow_id, "WOW-2026-06-29-001")
        self.assertEqual(parsed.suggested_wows[0].ticker_or_theme, "Physical AI")
        self.assertEqual(parsed.suggested_wows[0].evidence_to_watch_for, "Check next quarterly disclosures.")

    def test_wow_packet_parser_accepts_legacy_user_note_field(self):
        body = self.wow_packet_body().replace("reason_for_selection:", "user_note:")
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Legacy Agent", body=body)

        parsed = parse_wow(raw)

        self.assertEqual(parsed.reason_for_selection, "Focus on the supplier evidence.")

    def test_repaired_wow_publishes_and_receipt_reminds_setup_format(self):
        run_id = "00000000-0000-0000-0000-000000000028"
        body = self.wow_packet_body().replace("## 1. Reading Log", "1. Reading Log")
        body = body.replace("## 2. Agent Suggested WoW Signals", "Agent Suggested 3 WoWs")
        body = body.replace("## 3. User Selection / Pass", "User Selection")
        body = body.replace("### Reading Item 1", "Reading Item 1")
        body = body.replace("### Suggested WoW 1", "Suggested WoW 1")
        body = body.replace("selected_wow_id:", "Selected WoW:")
        raw = self.raw_email(sender="repair@example.com", subject="Daily WoW Packet - 2026-06-29 - Repair Agent", body=body)
        packet = create_wow_submission(raw, run_id=run_id)

        with TemporaryDirectory() as tmp:
            with override_settings(WKAP_PUBLIC_SITE_ROOT=Path(tmp), WKAP_SEND_RECEIPTS=False):
                publish_artifact("wow", packet.id, run_id=run_id)

        receipt_event = LedgerEvent.objects.filter(event_name="receipt_email_skipped", entity_type="wow").latest("id")
        self.assertTrue(LedgerEvent.objects.filter(event_name="wow_format_repaired", entity_type="wow", entity_id=str(packet.id)).exists())
        self.assertIn("was able to repair and publish", receipt_event.details["preview"])
        self.assertIn("/submit-to-wkap-ledger.html", receipt_event.details["preview"])

    def test_canonical_wow_receipt_does_not_include_format_reminder(self):
        run_id = "00000000-0000-0000-0000-000000000029"
        raw = self.raw_email(sender="canonical@example.com", subject="Daily WoW Packet - 2026-06-29 - Canonical Agent", body=self.wow_packet_body())
        packet = create_wow_submission(raw, run_id=run_id)

        body = wow_receipt_body(packet)

        self.assertNotIn("was able to repair and publish", body)

    def test_wow_packet_parser_rejects_pass_fields_when_wow_is_selected(self):
        body = "\n".join(
            [
                self.wow_packet_body(),
                "",
                "closest_rejected_idea: Robotics suppliers may show order acceleration.",
                "why_pass: Interesting but not selected.",
                "missing_evidence: Confirmed backlog growth.",
            ]
        )
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=body)

        with self.assertRaises(ParseError):
            parse_wow(raw)

    def test_wow_packet_parser_accepts_pass_only_when_selected_none(self):
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=self.wow_packet_body(selected="none"))

        parsed = parse_wow(raw)

        self.assertEqual(parsed.selected_wow_id, "none")
        self.assertEqual(parsed.closest_rejected_idea, "Robotics suppliers may show order acceleration.")
        self.assertEqual(parsed.why_pass, "The signal was interesting but not concrete enough today.")
        self.assertEqual(parsed.missing_evidence, "Confirmed backlog growth or named customer commentary.")

    def test_malformed_wow_is_saved_as_needs_format_fix(self):
        run_id = "00000000-0000-0000-0000-000000000026"
        raw = self.raw_email(
            sender="format-fix@example.com",
            subject="Daily WoW Packet - 2026-06-29 - Format Agent",
            body="# Daily WoW Packet\n\n## 1. Reading Log\nsource_title: One note",
        )

        with self.assertRaises(ParseError):
            create_wow_submission(raw, run_id=run_id)

        raw.refresh_from_db()
        self.assertEqual(raw.processing_status, RawEmail.ProcessingStatus.NEEDS_FORMAT_FIX)
        self.assertIn("missing section", raw.error_message.lower())
        self.assertTrue(LedgerEvent.objects.filter(event_name="wow_format_fix_needed", entity_id=raw.id).exists())

    def test_wow_format_fix_receipt_skips_when_disabled(self):
        run_id = "00000000-0000-0000-0000-000000000027"
        raw = self.raw_email(sender="format-fix@example.com", subject="Daily WoW Packet - 2026-06-29 - Format Agent")
        raw.processing_status = RawEmail.ProcessingStatus.NEEDS_FORMAT_FIX
        raw.error_message = "selected_wow_id is required."
        raw.save(update_fields=["processing_status", "error_message"])

        with override_settings(WKAP_SEND_RECEIPTS=False):
            send_wow_format_fix_receipt(raw, run_id=run_id)

        event = LedgerEvent.objects.filter(event_name="format_fix_receipt_skipped", entity_id=raw.id).latest("id")
        self.assertIn("selected_wow_id is required.", event.details["preview"])
        self.assertIn("current setup prompt format", wow_format_fix_body(raw))

    def test_spam_or_empty_email_stays_quiet(self):
        run_id = "00000000-0000-0000-0000-000000000030"
        spam = self.raw_email(sender="spam@example.com", subject="Casino lottery", body="unsubscribe lottery casino")
        empty = self.raw_email(sender="empty@example.com", subject="Hello", body="")

        self.assertEqual(classify_email(spam, run_id=run_id), RawEmail.Classification.SPAM)
        self.assertEqual(classify_email(empty, run_id=run_id), RawEmail.Classification.UNKNOWN)

        self.assertFalse(
            LedgerEvent.objects.filter(
                event_name__contains="receipt",
                gmail_message_id__in=[spam.gmail_message_id, empty.gmail_message_id],
            ).exists()
        )

    def test_wow_packet_ledger_writes_raw_email_artifact(self):
        run_id = "00000000-0000-0000-0000-000000000014"
        raw = self.raw_email(sender="raw-ledger@example.com", subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=self.wow_packet_body())
        packet = create_wow_submission(raw, run_id=run_id)

        with TemporaryDirectory() as tmp:
            with override_settings(WKAP_PUBLIC_SITE_ROOT=Path(tmp) / "public", WKAP_LEDGER_REPO_PATH=""):
                generate_wow_html(packet, run_id=run_id)
                generate_manifest("wow", packet.id, run_id=run_id)
                committed = commit_ledger("wow", packet.id, run_id=run_id)
                raw_artifact = Path(committed.raw_email_github_url)

                self.assertTrue(raw_artifact.exists())
                self.assertEqual(raw_artifact.read_text(encoding="utf-8"), raw.raw_body)
                self.assertEqual(committed.raw_email_commit_sha, "not_configured")

    def test_opentimestamp_enabled_stamps_stable_target(self):
        run_id = "00000000-0000-0000-0000-000000000031"
        raw = self.raw_email(sender="ots@example.com", subject="Daily WoW Packet - 2026-06-29 - OTS Agent", body=self.wow_packet_body())
        packet = create_wow_submission(raw, run_id=run_id)

        def fake_ots(*args):
            self.assertEqual(args[0], "stamp")
            target = Path(args[1])
            Path(f"{target}.ots").write_text("fake ots proof", encoding="utf-8")
            return "submitted"

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with override_settings(
                WKAP_PUBLIC_SITE_ROOT=root / "public",
                WKAP_LEDGER_REPO_PATH="",
                WKAP_OPENTIMESTAMP_ENABLED=True,
                WKAP_LEDGER_GITHUB_BASE_URL="https://github.com/wkapai/wkap-ledger/blob/main",
            ):
                generate_wow_html(packet, run_id=run_id)
                generate_manifest("wow", packet.id, run_id=run_id)
                committed = commit_ledger("wow", packet.id, run_id=run_id)
                target = Path(settings.BASE_DIR) / "ledger_artifacts" / "timestamps" / f"wow-{packet.id}.json"
                proof = Path(f"{target}.ots")
                if proof.exists():
                    proof.unlink()
                with patch("publishing.services._run_ots", side_effect=fake_ots):
                    stamped = timestamp_artifact("wow", committed.id, run_id=run_id)

                manifest = Path(settings.BASE_DIR) / "ledger_artifacts" / "manifests" / f"wow-{packet.id}.json"
                manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
                target_payload = json.loads(target.read_text(encoding="utf-8"))

                self.assertTrue(target.exists())
                self.assertTrue(proof.exists())
                self.assertEqual(stamped.ots_status, "stamped")
                self.assertTrue(stamped.ots_proof_url.endswith(f"timestamps/wow-{packet.id}.json.ots"))
                self.assertEqual(manifest_payload["ots_status"], "stamped")
                self.assertEqual(target_payload["content_sha256"], stamped.content_sha256)
                self.assertNotIn("ots_status", target_payload)
                self.assertTrue(LedgerEvent.objects.filter(event_name="opentimestamp_succeeded", entity_type="wow").exists())

    def test_upgrade_opentimestamps_updates_status_without_mutating_target(self):
        run_id = "00000000-0000-0000-0000-000000000032"
        raw = self.raw_email(sender="ots-upgrade@example.com", subject="Daily WoW Packet - 2026-06-29 - OTS Agent", body=self.wow_packet_body())
        packet = create_wow_submission(raw, run_id=run_id)

        def fake_stamp(*args):
            target = Path(args[1])
            Path(f"{target}.ots").write_text("fake ots proof", encoding="utf-8")
            return "submitted"

        def fake_upgrade(*args):
            self.assertEqual(args[0], "upgrade")
            Path(args[1]).write_text("upgraded ots proof", encoding="utf-8")
            return "upgraded"

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with override_settings(WKAP_PUBLIC_SITE_ROOT=root / "public", WKAP_LEDGER_REPO_PATH="", WKAP_OPENTIMESTAMP_ENABLED=True):
                generate_wow_html(packet, run_id=run_id)
                generate_manifest("wow", packet.id, run_id=run_id)
                commit_ledger("wow", packet.id, run_id=run_id)
                target = Path(settings.BASE_DIR) / "ledger_artifacts" / "timestamps" / f"wow-{packet.id}.json"
                proof = Path(f"{target}.ots")
                if proof.exists():
                    proof.unlink()
                with patch("publishing.services._run_ots", side_effect=fake_stamp):
                    timestamp_artifact("wow", packet.id, run_id=run_id)
                before = target.read_text(encoding="utf-8")
                with patch("publishing.services._run_ots", side_effect=fake_upgrade):
                    upgraded = upgrade_opentimestamps(run_id=run_id, entity_type="wow", entity_id=packet.id)

                packet.refresh_from_db()
                self.assertEqual(len(upgraded), 1)
                self.assertEqual(packet.ots_status, "upgraded")
                self.assertEqual(target.read_text(encoding="utf-8"), before)
                self.assertTrue(LedgerEvent.objects.filter(event_name="opentimestamp_upgrade_succeeded", entity_type="wow").exists())

    def test_wow_receipt_includes_url_hash_and_privacy_note(self):
        run_id = "00000000-0000-0000-0000-000000000016"
        raw = self.raw_email(sender="receipt@example.com", subject="Daily WoW Packet - 2026-06-29 - Receipt Agent", body=self.wow_packet_body())
        packet = create_wow_submission(raw, run_id=run_id)
        packet.canonical_url = "https://wkap.ai/investors/w0202/wows/wow-w0202-2026-06-29.html"
        packet.content_sha256 = "d" * 64
        packet.raw_email_sha256 = "e" * 64
        packet.ots_status = "queued"
        packet.save()

        subject = wow_receipt_subject(packet)
        body = wow_receipt_body(packet)

        self.assertIn("2026-06-29", subject)
        self.assertIn(packet.canonical_url, body)
        self.assertIn(packet.content_sha256, body)
        self.assertIn(packet.raw_email_sha256, body)
        self.assertIn("Your email address stays private.", body)

    def test_wow_receipt_skips_when_disabled(self):
        run_id = "00000000-0000-0000-0000-000000000017"
        raw = self.raw_email(sender="receipt-skip@example.com", subject="Daily WoW Packet - 2026-06-29 - Receipt Agent", body=self.wow_packet_body())
        packet = create_wow_submission(raw, run_id=run_id)

        with override_settings(WKAP_SEND_RECEIPTS=False):
            send_wow_receipt(packet, run_id=run_id)

        packet.refresh_from_db()
        self.assertIsNone(packet.receipt_email_sent_at)
        self.assertEqual(packet.receipt_email_message_id, "")
        self.assertTrue(LedgerEvent.objects.filter(event_name="receipt_email_skipped", status=LedgerEvent.Status.SKIPPED).exists())

    def test_radar_receipt_includes_url_hash_manifest_and_sender(self):
        run_id = "00000000-0000-0000-0000-000000000022"
        raw = self.raw_email(sender="playinc@gmail.com", body="Market_date: 2026-06-30\nTitle: Morning Radar\nBody: Context")
        issue = create_radar_issue(raw, run_id=run_id)
        issue.canonical_url = "https://wkap.ai/radar/wkap-radar-feed-2026-06-30.html"
        issue.content_sha256 = "d" * 64
        issue.manifest_url = "https://github.com/wkap/ledger/manifests/radar-1.json"
        issue.ots_status = "queued"
        issue.save()

        subject = radar_receipt_subject(issue)
        body = radar_receipt_body(issue)

        self.assertEqual(subject, "WKAP Ledger receipt: Radar Feed logged for 2026-06-30")
        self.assertIn(issue.canonical_url, body)
        self.assertIn(issue.content_sha256, body)
        self.assertIn(issue.manifest_url, body)
        self.assertIn("Proof status:", body)

    def test_receipts_use_public_urls_when_db_has_stale_local_values(self):
        run_id = "00000000-0000-0000-0000-000000000029"
        radar_raw = self.raw_email(sender="playinc@gmail.com", body="Market_date: 2026-07-03\nTitle: Morning Radar\nBody: Context")
        radar = create_radar_issue(radar_raw, run_id=run_id)
        radar.canonical_url = "http://127.0.0.1:8000/radar/wkap-radar-feed-2026-07-03.html"
        radar.manifest_url = r"C:\Users\ASUS\Documents\wkap\ledger_artifacts\manifests\radar-2.json"
        radar.save(update_fields=["canonical_url", "manifest_url"])
        wow_raw = self.raw_email(sender="receipt-url@example.com", subject="Daily WoW Packet - 2026-06-29 - Receipt Agent", body=self.wow_packet_body())
        packet = create_wow_submission(wow_raw, run_id=run_id)
        packet.canonical_url = "http://127.0.0.1:8000/investors/w0202/wows/wow-w0202-2026-06-29.html"
        packet.save(update_fields=["canonical_url"])

        with override_settings(WKAP_BASE_URL="https://wkap.ai", WKAP_LEDGER_GITHUB_BASE_URL="https://github.com/wkapai/wkap-ledger/blob/main"):
            radar_body = radar_receipt_body(radar)
            wow_body = wow_receipt_body(packet)

        self.assertIn("https://wkap.ai/radar/wkap-radar-feed-2026-07-03.html", radar_body)
        self.assertIn(f"https://github.com/wkapai/wkap-ledger/blob/main/manifests/radar-{radar.id}.json", radar_body)
        self.assertIn("https://wkap.ai/investors/w0202/wows/wow-w0202-2026-06-29.html", wow_body)
        self.assertNotIn("127.0.0.1", radar_body + wow_body)
        self.assertNotIn(r"C:\Users", radar_body)

    def test_radar_receipt_skips_when_disabled(self):
        run_id = "00000000-0000-0000-0000-000000000023"
        raw = self.raw_email(sender="playinc@gmail.com", body="Market_date: 2026-06-30\nTitle: Morning Radar\nBody: Context")
        issue = create_radar_issue(raw, run_id=run_id)

        with override_settings(WKAP_SEND_RECEIPTS=False):
            send_radar_receipt(issue, run_id=run_id)

        issue.refresh_from_db()
        self.assertIsNone(issue.receipt_email_sent_at)
        self.assertEqual(issue.receipt_email_message_id, "")
        self.assertTrue(
            LedgerEvent.objects.filter(
                event_name="receipt_email_skipped",
                entity_type="radar",
                status=LedgerEvent.Status.SKIPPED,
            ).exists()
        )

    def test_reledgered_radar_resets_receipt_state_for_fresh_receipt(self):
        run_id = "00000000-0000-0000-0000-000000000030"
        first_raw = self.raw_email(sender="playinc@gmail.com", body="Market_date: 2026-07-02\nTitle: First Radar\nBody: Context")
        issue = create_radar_issue(first_raw, run_id=run_id)
        issue.receipt_email_sent_at = timezone.now()
        issue.receipt_email_message_id = "old-message-id"
        issue.receipt_email_error = "old error"
        issue.save(update_fields=["receipt_email_sent_at", "receipt_email_message_id", "receipt_email_error"])
        second_raw = self.raw_email(
            sender="playinc@gmail.com",
            subject="WKAP Radar Feed - 2026 - 07 - 02",
            body="Market_date: 2026-07-02\nTitle: Updated Radar\nBody: Fresh context",
        )

        updated_issue = create_radar_issue(second_raw, run_id=run_id)

        self.assertEqual(updated_issue.id, issue.id)
        self.assertEqual(updated_issue.source_email, second_raw)
        self.assertIsNone(updated_issue.receipt_email_sent_at)
        self.assertEqual(updated_issue.receipt_email_message_id, "")
        self.assertEqual(updated_issue.receipt_email_error, "")

    def test_publish_radar_attempts_receipt_after_proof_fields(self):
        run_id = "00000000-0000-0000-0000-000000000024"
        raw = self.raw_email(sender="playinc@gmail.com", body="Market_date: 2026-06-30\nTitle: Morning Radar\nBody: Context")
        issue = create_radar_issue(raw, run_id=run_id)

        with TemporaryDirectory() as tmp:
            with override_settings(WKAP_PUBLIC_SITE_ROOT=Path(tmp), WKAP_LEDGER_REPO_PATH="", WKAP_SEND_RECEIPTS=False):
                publish_artifact("radar", issue.id, run_id=run_id)

        event = LedgerEvent.objects.filter(event_name="receipt_email_skipped", entity_type="radar").latest("id")
        self.assertIn("wkap-radar-feed-2026-06-30.html", event.details["preview"])
        self.assertIn("Proof status:", event.details["preview"])
        self.assertTrue(
            LedgerEvent.objects.filter(
                event_name="publish_started",
                entity_type="radar",
                entity_id=str(issue.id),
                status=LedgerEvent.Status.STARTED,
            ).exists()
        )
        self.assertTrue(LedgerEvent.objects.filter(event_name="publish_succeeded", entity_type="radar", entity_id=str(issue.id)).exists())

    def test_show_events_cli_returns_agent_readable_json(self):
        run_id = "00000000-0000-0000-0000-000000000026"
        raw = self.raw_email(body="Market_date: 2026-06-30\nTitle: Morning Radar\nBody: Context")
        issue = create_radar_issue(raw, run_id=run_id)
        output = StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
            call_command(
                "wkap",
                "--json",
                "show-events",
                "--entity-type",
                "radar",
                "--entity-id",
                str(issue.id),
                "--limit",
                "10",
            )

        self.assertEqual(exit_context.exception.code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["entity_type"], "ledger_events")
        self.assertGreaterEqual(payload["details"]["count"], 1)
        event = payload["details"]["events"][0]
        self.assertEqual(event["entity_type"], "radar")
        self.assertEqual(event["entity_id"], str(issue.id))
        self.assertIn("event_name", event)
        self.assertIn("timestamp", event)

    def test_validate_ledger_reports_missing_evidence(self):
        run_id = "00000000-0000-0000-0000-000000000005"
        raw = self.raw_email(body="Market_date: 2026-06-30\nTitle: Morning Radar\nBody: Context")
        issue = create_radar_issue(raw, run_id=run_id)

        errors = validate_ledger("radar", issue.id)

        self.assertIn("canonical_url is missing", errors)
        self.assertIn("content_sha256 is missing", errors)

    def test_radar_archive_uses_iso_url_and_feed_label(self):
        run_id = "00000000-0000-0000-0000-000000000006"
        raw = self.raw_email(body="Market_date: 2026-06-29\nTitle: Physical AI component supply chain\nBody: Context")
        create_radar_issue(raw, run_id=run_id)

        response = self.client.get("/radar/")

        self.assertContains(response, 'href="/radar/wkap-radar-feed-2026-06-29.html"')
        self.assertContains(response, "WKAP Radar Feed 2026-06-29")

    def test_wow_indexes_use_iso_url_and_feed_label(self):
        run_id = "00000000-0000-0000-0000-000000000007"
        raw = self.raw_email(sender="wow@example.com", subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=self.wow_packet_body())
        create_wow_submission(raw, run_id=run_id)

        home_response = self.client.get("/investors/w0202/")
        index_response = self.client.get("/investors/w0202/wows/")

        expected_href = 'href="/investors/w0202/wows/wow-w0202-2026-06-29.html"'
        expected_label = "Test Agent - 2026-06-29"
        self.assertContains(home_response, expected_href)
        self.assertContains(home_response, expected_label)
        self.assertContains(index_response, expected_href)
        self.assertContains(index_response, expected_label)

    def test_home_and_investor_archive_link_to_wow_ledger(self):
        run_id = "00000000-0000-0000-0000-000000000008"
        raw = self.raw_email(sender="wow@example.com", subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=self.wow_packet_body())
        create_wow_submission(raw, run_id=run_id)

        home_response = self.client.get("/")
        archive_response = self.client.get("/investors/")

        self.assertContains(home_response, 'href="/investors/"')
        self.assertContains(home_response, "Open WoW ledger")
        self.assertContains(archive_response, "Test Agent - 2026-06-29")
        self.assertContains(archive_response, 'href="/investors/w0202/wows/wow-w0202-2026-06-29.html"')

    def test_investor_archive_lists_recently_active_investors_first(self):
        run_id = "00000000-0000-0000-0000-000000000018"
        older = self.raw_email(sender="older@example.com", subject="Daily WoW Packet - 2026-06-29 - Older Agent", body=self.wow_packet_body())
        newer = self.raw_email(sender="newer@example.com", subject="Daily WoW Packet - 2026-07-04 - Newer Agent", body=self.wow_packet_body())
        older_packet = create_wow_submission(older, run_id=run_id)
        newer_packet = create_wow_submission(newer, run_id=run_id)
        now = timezone.now()
        older_packet.created_at = now - timedelta(hours=1)
        older_packet.save(update_fields=["created_at"])
        newer_packet.created_at = now
        newer_packet.save(update_fields=["created_at"])

        response = self.client.get("/investors/")
        content = response.content.decode()

        self.assertLess(content.index("Newer Agent"), content.index("Older Agent"))

    def test_latest_wows_order_by_creation_time_not_market_date(self):
        run_id = "00000000-0000-0000-0000-000000000019"
        earlier_created = self.raw_email(
            sender="calendar-new@example.com",
            subject="Daily WoW Packet - 2026-07-04 - Calendar New Agent",
            body=self.wow_packet_body(),
        )
        later_created = self.raw_email(
            sender="calendar-old@example.com",
            subject="Daily WoW Packet - 2026-06-29 - Calendar Old Agent",
            body=self.wow_packet_body(),
        )
        earlier_packet = create_wow_submission(earlier_created, run_id=run_id)
        later_packet = create_wow_submission(later_created, run_id=run_id)
        now = timezone.now()
        earlier_packet.created_at = now - timedelta(hours=1)
        earlier_packet.save(update_fields=["created_at"])
        later_packet.created_at = now
        later_packet.save(update_fields=["created_at"])

        response = self.client.get("/investors/")
        content = response.content.decode()

        self.assertLess(content.index("Calendar Old Agent - 2026-06-29"), content.index("Calendar New Agent - 2026-07-04"))

    def test_home_links_to_investor_log_setup_page(self):
        home_response = self.client.get("/")
        setup_response = self.client.get("/submit-to-wkap-ledger.html")

        self.assertContains(home_response, 'href="/submit-to-wkap-ledger.html"')
        self.assertContains(home_response, "Setup My Investor Log")
        self.assertContains(setup_response, "Setup My Investor Log")
        self.assertContains(setup_response, "Daily WoW Packet")
        self.assertContains(setup_response, "ledger@wkap.ai")
        self.assertContains(setup_response, 'data-agent-prompt="wkap-investor-log"')

    def test_pages_expose_agent_search_metadata(self):
        run_id = "00000000-0000-0000-0000-000000000009"
        raw = self.raw_email(body="Market_date: 2026-06-29\nTitle: Physical AI component supply chain\nBody: Context")
        issue = create_radar_issue(raw, run_id=run_id)
        issue.canonical_url = "https://wkap.ai/radar/wkap-radar-feed-2026-06-29.html"
        issue.content_sha256 = "a" * 64
        issue.github_file_url = "https://github.com/wkap/ledger/radar/wkap-radar-feed-2026-06-29.html"
        issue.github_commit_sha = "b" * 40
        issue.manifest_url = "https://github.com/wkap/ledger/manifests/radar-1.json"
        issue.ots_status = "stamped"
        issue.ots_proof_url = "https://github.com/wkap/ledger/timestamps/radar-1.json.ots"
        issue.save()

        with override_settings(WKAP_LEDGER_GITHUB_BASE_URL="https://github.com/wkap/ledger"):
            response = self.client.get("/radar/wkap-radar-feed-2026-06-29.html")

        self.assertContains(response, '<meta name="agent-readable" content="true">')
        self.assertContains(response, '<link rel="canonical" href="https://wkap.ai/radar/wkap-radar-feed-2026-06-29.html">')
        self.assertContains(response, 'type="application/ld+json"')
        self.assertContains(response, 'data-agent-readable="true"')
        self.assertContains(response, 'data-agent-proof="true"')
        self.assertContains(response, 'data-opentimestamp-status="stamped"')
        self.assertContains(response, "This artifact has an OpenTimestamp proof file.")
        self.assertContains(response, 'href="https://opentimestamps.org/"')
        self.assertContains(response, 'src="/static/img/opentimestamps-logo.png?v=ots-logo-tight-v1"')
        self.assertContains(response, 'alt="OpenTimestamps"')
        self.assertContains(response, "Proof file")
        self.assertContains(response, "Timestamp target")
        self.assertContains(response, "https://github.com/wkap/ledger/timestamps/radar-1.json.ots")
        self.assertContains(response, "https://github.com/wkap/ledger/timestamps/radar-1.json")
        self.assertContains(response, "Agent-readable facts")
        self.assertContains(response, "content_sha256")

    def test_wow_agent_metadata_does_not_publish_private_email(self):
        run_id = "00000000-0000-0000-0000-000000000010"
        raw = self.raw_email(sender="private-wow@example.com", subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=self.wow_packet_body())
        raw.received_at = datetime(2026, 7, 3, 13, 14, tzinfo=datetime_timezone.utc)
        raw.save(update_fields=["received_at"])
        submission = create_wow_submission(raw, run_id=run_id)
        submission.canonical_url = "https://wkap.ai/investors/w0202/wows/wow-w0202-2026-06-29.html"
        submission.content_sha256 = "c" * 64
        submission.save()

        response = self.client.get("/investors/w0202/wows/wow-w0202-2026-06-29.html")

        self.assertContains(response, 'data-artifact-type="wow"')
        self.assertContains(response, 'class="summary-strip"')
        self.assertContains(response, "Agent-readable facts")
        self.assertContains(response, "private_email_published", count=0)
        self.assertContains(response, "investor_id")
        self.assertContains(response, 'data-field="ledgered_by"')
        self.assertContains(response, "Ledgered by")
        self.assertContains(response, "Test Agent")
        self.assertContains(response, "Investor ID")
        self.assertContains(response, 'data-field="investor_id"')
        self.assertContains(response, 'href="/investors/w0202/"')
        self.assertContains(response, "w0202")
        self.assertContains(response, 'data-field="submission_channel"')
        self.assertContains(response, "email")
        self.assertContains(response, 'data-field="received_at_et"')
        self.assertContains(response, "2026-07-03 09:14 ET")
        self.assertNotContains(response, "2026-07-03 13:14 ET")
        summary_start = response.content.decode().index('class="summary-strip"')
        summary_end = response.content.decode().index("</dl>", summary_start)
        summary_html = response.content.decode()[summary_start:summary_end]
        self.assertNotIn("Raw email SHA256", summary_html)
        self.assertNotIn("Canonical URL", summary_html)
        self.assertContains(response, "subject_line_display_name")
        self.assertContains(response, 'data-field="closest_rejected_idea"')
        self.assertContains(response, 'data-field="missing_evidence"')
        self.assertContains(response, "N/A - Not Applicable", count=2)
        self.assertContains(response, 'data-selection-status="selected"')
        self.assertContains(response, 'data-field="selection_status"')
        self.assertContains(response, 'data-field="source_url"')
        self.assertContains(response, 'data-field="evidence_to_watch"')
        self.assertContains(response, "selected_theme")
        self.assertContains(response, "source_urls")
        self.assertNotContains(response, "private-wow@example.com")

    def test_robots_and_sitemap_are_agent_friendly(self):
        run_id = "00000000-0000-0000-0000-000000000011"
        raw = self.raw_email(body="Market_date: 2026-06-29\nTitle: Physical AI component supply chain\nBody: Context")
        create_radar_issue(raw, run_id=run_id)

        robots = self.client.get("/robots.txt")
        sitemap = self.client.get("/sitemap.xml")

        self.assertEqual(robots.headers["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(sitemap.headers["Content-Type"], "application/xml; charset=utf-8")
        self.assertContains(robots, "User-agent: *")
        self.assertContains(robots, f"Sitemap: {settings.WKAP_BASE_URL}/sitemap.xml")
        self.assertContains(sitemap, f"<loc>{settings.WKAP_BASE_URL}/</loc>")
        self.assertContains(
            sitemap,
            f"<loc>{settings.WKAP_BASE_URL}/radar/wkap-radar-feed-2026-06-29.html</loc>",
        )
