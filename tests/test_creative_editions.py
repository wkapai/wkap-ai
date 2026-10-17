from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from ingestion.models import RawEmail
from ingestion.services import classify_email, process_raw_email_for_publish
from ledger.models import CreativeEdition
from ledger.parsers import ParseError, parse_creative_edition
from ledger.services import create_creative_edition
from publishing.services import publish_artifact, timestamp_pending_artifacts, upgrade_opentimestamps, validate_ledger


RUN_ID = "00000000-0000-0000-0000-000000000101"
PNG_BYTES = b"\x89PNG\r\n\x1a\nexact-wkap-cover-pixels"


class CreativeEditionTests(TestCase):
    def creative_body(self, *, rationale: str = "Jensen's verified chip role makes him the load-bearing builder in this semiconductor story.", lesson: str = "Check hands, faces, and phone crop before review.") -> str:
        return f'''```yaml
creative_edition:
  format_version: creative_edition_v1
  market_date: 2026-10-19
  edition_version: 1
  title: "The chip factory holds up the market"
  article_url: "https://x.com/wkapai/status/123"
  image_source_url: "https://pbs.twimg.com/media/cover.png"
  episode_premise: "The day's market show compressed into a single source-backed frame."
  market_hooks:
    - story: "Chip production became the day's market hinge."
      why_it_matters: "Supply execution links the news to valuation."
      source_urls: ["https://example.com/chips"]
  scenes:
    - story: "Precision chip production supports the market structure."
      source_urls: ["https://example.com/chips"]
      visual_joke: "A CEO literally keeps the market building upright while fabricating wafers."
      character_choices: "Jensen Huang as the operating builder."
      character_rationale: "{rationale}"
      relationship_semantics: "The whole scene reads as operational support, not an unsupported hero/villain rivalry or false alliance."
      interaction_or_action: "He braces the building while mechanical tools align the wafer line."
      show_seed: "Follow the factory floor into the next earnings call."
  credits:
    human_contribution: "Alex: product direction and optional taste feedback; no routine daily touch"
    ai_contribution: "AI: research synthesis, iteration, and rendering assistance"
    publisher: "WKAP.ai"
  rejected_choices:
    - "A famous athlete was rejected because fame did not connect to the chip story."
  corrections:
    - "Corrected hand geometry and simplified the phone crop."
  lesson_next_time: "{lesson}"
```'''

    def raw_email(self, *, body: str | None = None, message_id: str = "creative-1") -> RawEmail:
        return RawEmail.objects.create(
            gmail_message_id=message_id,
            sender_email="playinc@gmail.com",
            subject="WKAP Creative Edition - 2026-10-19 - v1",
            raw_body=body or self.creative_body(),
            received_at=datetime(2026, 10, 19, 1, 30, tzinfo=datetime_timezone.utc),
        )

    def test_parser_requires_defensible_character_rationale_and_same_day(self):
        raw = self.raw_email(body=self.creative_body(rationale=""))
        with self.assertRaisesRegex(ParseError, "character_rationale"):
            parse_creative_edition(raw)

        raw.raw_body = self.creative_body()
        raw.received_at = datetime(2026, 10, 18, 1, 30, tzinfo=datetime_timezone.utc)
        with self.assertRaisesRegex(ParseError, "backdating"):
            parse_creative_edition(raw)

    def test_classification_precedes_generic_market_context(self):
        raw = self.raw_email(body=self.creative_body() + "\nmarket context")
        self.assertEqual(classify_email(raw, run_id=RUN_ID), RawEmail.Classification.CREATIVE)

    def test_identical_retry_is_noop_but_changed_bytes_require_new_version(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp, override_settings(
            WKAP_PUBLIC_SITE_ROOT=Path(tmp) / "public",
            WKAP_CREATIVE_AUTHORIZED_SENDERS={"playinc@gmail.com"},
        ), patch("ledger.services._download_creative_image", return_value=(PNG_BYTES, "image/png", "png")):
            first = create_creative_edition(self.raw_email(), run_id=RUN_ID)
            duplicate = create_creative_edition(self.raw_email(message_id="creative-2"), run_id=RUN_ID)
            self.assertEqual(first.id, duplicate.id)
            self.assertEqual(CreativeEdition.objects.count(), 1)

            conflict_raw = self.raw_email(body=self.creative_body(lesson="A materially different lesson."), message_id="creative-3")
            with self.assertRaisesRegex(ParseError, "publish the correction as v2"):
                create_creative_edition(conflict_raw, run_id=RUN_ID)

    def test_completed_identical_redelivery_does_not_republish(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp, override_settings(
            WKAP_PUBLIC_SITE_ROOT=Path(tmp) / "public",
            WKAP_CREATIVE_AUTHORIZED_SENDERS={"playinc@gmail.com"},
        ), patch("ledger.services._download_creative_image", return_value=(PNG_BYTES, "image/png", "png")):
            edition = create_creative_edition(self.raw_email(), run_id=RUN_ID)
            edition.canonical_url = "https://wkap.ai/creative/edition.html"
            edition.content_sha256 = "a" * 64
            edition.github_file_url = "https://github.com/wkapai/wkap-ledger/blob/main/creative/edition.html"
            edition.github_commit_sha = "b" * 40
            edition.manifest_url = "https://github.com/wkapai/wkap-ledger/blob/main/manifests/creative-1.json"
            edition.save()
            duplicate = self.raw_email(message_id="creative-redelivery")

            with patch("publishing.services.publish_artifact") as republish:
                returned = process_raw_email_for_publish(duplicate, run_id=RUN_ID)

            duplicate.refresh_from_db()
            self.assertEqual(returned.id, edition.id)
            self.assertEqual(duplicate.processing_status, RawEmail.ProcessingStatus.PUBLISHED)
            republish.assert_not_called()

    def test_publish_writes_actual_cover_page_manifest_and_queued_proof(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp)
            with override_settings(
                BASE_DIR=root,
                WKAP_BASE_URL="https://wkap.ai",
                WKAP_PUBLIC_SITE_ROOT=root / "public",
                WKAP_LEDGER_REPO_PATH="",
                WKAP_LEDGER_GITHUB_BASE_URL="https://github.com/wkapai/wkap-ledger/blob/main",
                WKAP_CREATIVE_AUTHORIZED_SENDERS={"playinc@gmail.com"},
                WKAP_OPENTIMESTAMP_ENABLED=False,
            ), patch("ledger.services._download_creative_image", return_value=(PNG_BYTES, "image/png", "png")):
                edition = create_creative_edition(self.raw_email(), run_id=RUN_ID)
                published = publish_artifact("creative", edition.id, run_id=RUN_ID)

                page = root / "public" / "creative" / "wkap-creative-edition-2026-10-19-v1.html"
                image = root / "public" / "creative" / "assets" / "wkap-cover-2026-10-19-v1.png"
                manifest = root / "ledger_artifacts" / "manifests" / f"creative-{edition.id}.json"
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                html = page.read_text(encoding="utf-8")

                self.assertEqual(image.read_bytes(), PNG_BYTES)
                self.assertEqual(payload["image_sha256"], edition.image_sha256)
                self.assertEqual(payload["journal_sha256"], edition.journal_sha256)
                self.assertEqual(payload["ots_status"], "queued")
                self.assertIn("Why they belong", html)
                self.assertIn("Future show seed", html)
                self.assertIn("do not prove authorship", html)
                self.assertEqual(validate_ledger("creative", edition.id), [])
                self.assertEqual(published.source_email.processing_status, RawEmail.ProcessingStatus.PUBLISHED)

                response = self.client.get("/creative/wkap-creative-edition-2026-10-19-v1.html")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, edition.image_sha256)
                self.assertContains(response, "Relationship semantics")
                self.assertContains(response, f'<meta property="og:image" content="{payload["image_url"]}">')

    def test_queued_creative_proof_is_eligible_for_existing_catchup(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp)
            with override_settings(
                BASE_DIR=root,
                WKAP_PUBLIC_SITE_ROOT=root / "public",
                WKAP_LEDGER_REPO_PATH="",
                WKAP_CREATIVE_AUTHORIZED_SENDERS={"playinc@gmail.com"},
                WKAP_OPENTIMESTAMP_ENABLED=False,
            ), patch("ledger.services._download_creative_image", return_value=(PNG_BYTES, "image/png", "png")):
                edition = create_creative_edition(self.raw_email(), run_id=RUN_ID)
                edition.canonical_url = "https://wkap.ai/creative/edition.html"
                edition.content_sha256 = "a" * 64
                edition.github_file_url = "https://github.com/wkapai/wkap-ledger/blob/main/creative/edition.html"
                edition.github_commit_sha = "b" * 40
                edition.manifest_url = "https://github.com/wkapai/wkap-ledger/blob/main/manifests/creative-1.json"
                edition.ots_status = "queued"
                edition.save()

                processed = timestamp_pending_artifacts(run_id=RUN_ID, entity_type="creative")

            self.assertEqual([item.id for item in processed], [edition.id])

    def test_timestamp_pending_then_verified_upgrade_preserves_original_proof(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            root = Path(tmp)

            def pending_ots(*args):
                if args[0] == "stamp":
                    Path(f"{args[1]}.ots").write_bytes(b"original-proof-v1")
                    return ""
                raise subprocess.CalledProcessError(1, args, stderr="Pending confirmation")

            def verified_ots(*args):
                if args[0] == "upgrade":
                    Path(args[1]).write_bytes(b"upgraded-proof-v2")
                return "verified"

            with override_settings(
                BASE_DIR=root,
                WKAP_BASE_URL="https://wkap.ai",
                WKAP_PUBLIC_SITE_ROOT=root / "public",
                WKAP_LEDGER_REPO_PATH="",
                WKAP_LEDGER_GITHUB_BASE_URL="https://github.com/wkapai/wkap-ledger/blob/main",
                WKAP_CREATIVE_AUTHORIZED_SENDERS={"playinc@gmail.com"},
                WKAP_OPENTIMESTAMP_ENABLED=True,
            ), patch("ledger.services._download_creative_image", return_value=(PNG_BYTES, "image/png", "png")), patch(
                "publishing.services._run_ots", side_effect=pending_ots
            ):
                edition = create_creative_edition(self.raw_email(), run_id=RUN_ID)
                published = publish_artifact("creative", edition.id, run_id=RUN_ID)
                self.assertEqual(published.ots_status, "submitted_pending")
                self.assertEqual(published.ots_proof_version, 1)

            with override_settings(
                BASE_DIR=root,
                WKAP_PUBLIC_SITE_ROOT=root / "public",
                WKAP_LEDGER_REPO_PATH="",
                WKAP_OPENTIMESTAMP_ENABLED=True,
            ), patch("publishing.services._run_ots", side_effect=verified_ots):
                upgraded = upgrade_opentimestamps(run_id=RUN_ID, entity_type="creative", entity_id=edition.id)

            edition.refresh_from_db()
            history = root / "ledger_artifacts" / "timestamps" / "history" / f"creative-{edition.id}-proof-v1.ots"
            self.assertEqual(len(upgraded), 1)
            self.assertEqual(history.read_bytes(), b"original-proof-v1")
            self.assertEqual(edition.ots_status, "verified_bitcoin")
            self.assertEqual(edition.ots_proof_version, 2)
            self.assertIsNotNone(edition.bitcoin_verified_at)
