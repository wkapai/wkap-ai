from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.wow_daily_simulation import (
    SIM_INVESTOR_ID,
    base_daily_options,
    initial_daily_state,
    lifecycle_transition_options,
    normalize_user_reply,
    packet_from_state,
    packet_markdown,
    reading_log_for_day,
    render_daily_options_prompt,
    run_daily_wow_simulation,
    validate_daily_state,
)
from ingestion.models import RawEmail
from ledger.parsers import ParseError, parse_wow
from ledger.wow_lifecycle_rules import ALLOWED_STATUS_TRANSITIONS


class DailyWoWSimulationTests(TestCase):
    def daily_state(self, *, market_date: date | None = None, journal_path: Path | None = None):
        market_date = market_date or date(2026, 7, 6)
        journal_path = journal_path or Path("C:/tmp/wkap-wow-test-journal")
        return initial_daily_state(
            author_id=SIM_INVESTOR_ID,
            market_date=market_date,
            journal_path=journal_path,
            reading_log=reading_log_for_day(market_date),
            wow_options=base_daily_options(market_date),
        )

    def raw_packet(self, markdown: str, *, market_date: date):
        return RawEmail(
            gmail_message_id=f"test-daily-wow-sim-{market_date.isoformat()}",
            sender_email="sim-test@example.com",
            subject=f"Daily WoW Packet - {market_date.isoformat()} - Sim Test",
            raw_body=markdown,
            received_at=timezone.make_aware(datetime.combine(market_date, time(21, 0))),
        )

    def test_selection_flow_hides_wow_ids_and_generates_parseable_packet(self):
        state = self.daily_state()
        prompt = render_daily_options_prompt(state["wow_options"])
        self.assertNotIn(state["wow_options"][0]["wow_id"], prompt)
        self.assertIn("Pick one WoW: 1, 2, 3, or pass.", prompt)

        state, prompt, normalized = normalize_user_reply(
            state,
            "The scoreable one, because I want calibration practice when the evidence is clean.",
        )

        self.assertEqual(state["state"], "ready_to_submit")
        self.assertEqual(normalized["selected_wow_id"], state["wow_options"][1]["wow_id"])
        self.assertEqual(validate_daily_state(state), [])
        packet = packet_from_state(state)
        parsed = parse_wow(self.raw_packet(packet_markdown(packet), market_date=date(2026, 7, 6)))
        self.assertEqual(parsed.selected_wow_id, state["wow_options"][1]["wow_id"])
        self.assertEqual(parsed.scoreable_count, 1)

    def test_missing_selection_reason_asks_only_for_reason(self):
        state = self.daily_state()
        state, prompt, normalized = normalize_user_reply(state, "1")

        self.assertEqual(state["state"], "awaiting_selection_reason")
        self.assertEqual(prompt, "Why did you select this WoW?")
        self.assertEqual(normalized["selected_wow_id"], state["wow_options"][0]["wow_id"])
        self.assertEqual(state["selection"]["reason_for_selection"], "")

        state, prompt, normalized = normalize_user_reply(state, "Because this is the recurring evidence stream I want trained.")

        self.assertEqual(state["state"], "ready_to_submit")
        self.assertEqual(validate_daily_state(state), [])
        self.assertIn("recurring evidence stream", normalized["reason_for_selection"])

    def test_pass_flow_requires_closest_rejected_wow_from_today_options(self):
        state = self.daily_state()
        state, prompt, normalized = normalize_user_reply(
            state,
            "pass; closest: macro regime; reason: interesting but too broad; missing: company-level evidence",
        )

        self.assertEqual(state["state"], "awaiting_pass_fields")
        self.assertEqual(prompt, "Which of today's 3 WoWs came closest?")
        self.assertEqual(normalized["missing"], "closest_rejected_wow")

        state, prompt, normalized = normalize_user_reply(state, "closest: 3")

        self.assertEqual(state["state"], "ready_to_submit")
        self.assertEqual(state["selection"]["selected_wow_id"], "none")
        self.assertEqual(state["selection"]["closest_rejected_wow"], state["wow_options"][2]["wow_id"])
        self.assertEqual(validate_daily_state(state), [])

    def test_lifecycle_simulation_covers_every_allowed_transition_with_parseable_packets(self):
        expected_count = sum(
            len(new_statuses)
            for previous_map in ALLOWED_STATUS_TRANSITIONS.values()
            for new_statuses in previous_map.values()
        )
        parsed_count = 0
        market_date = date(2026, 8, 1)
        transition_number = 1
        for target_wow_type, previous_map in ALLOWED_STATUS_TRANSITIONS.items():
            for previous_status, new_statuses in previous_map.items():
                for new_status in sorted(new_statuses):
                    current_date = market_date + timedelta(days=transition_number - 1)
                    state = initial_daily_state(
                        author_id=SIM_INVESTOR_ID,
                        market_date=current_date,
                        journal_path=Path("C:/tmp/wkap-wow-test-journal"),
                        reading_log=reading_log_for_day(current_date, count=1),
                        wow_options=lifecycle_transition_options(
                            current_date,
                            author_id=SIM_INVESTOR_ID,
                            transition_number=transition_number,
                            target_wow_type=target_wow_type,
                            previous_status=previous_status,
                            new_status=new_status,
                        ),
                    )
                    state, _, _ = normalize_user_reply(state, "1 because this is the cleanest lifecycle update today.")
                    self.assertEqual(validate_daily_state(state), [])
                    packet = packet_from_state(state)
                    parsed = parse_wow(self.raw_packet(packet_markdown(packet), market_date=current_date))
                    self.assertEqual(parsed.status_update_count, 1)
                    parsed_count += 1
                    transition_number += 1

        self.assertEqual(parsed_count, expected_count)

    def test_parser_rejects_explicit_status_update_author_mismatch(self):
        market_date = date(2026, 8, 1)
        state = initial_daily_state(
            author_id=SIM_INVESTOR_ID,
            market_date=market_date,
            journal_path=Path("C:/tmp/wkap-wow-test-journal"),
            reading_log=reading_log_for_day(market_date, count=1),
            wow_options=lifecycle_transition_options(
                market_date,
                author_id=SIM_INVESTOR_ID,
                transition_number=1,
                target_wow_type="trackable_wow",
                previous_status="active_trackable",
                new_status="promoted_scoreable",
            ),
        )
        state, _, _ = normalize_user_reply(state, "1 because this promotion is the daily CRM event.")
        packet = packet_from_state(state)
        packet["wow_items"][0]["author_id"] = "w0001"

        with self.assertRaises(ParseError) as exc:
            parse_wow(self.raw_packet(packet_markdown(packet), market_date=market_date))

        self.assertIn("author_id must match packet author_id", str(exc.exception))

    def test_simulation_command_writes_journal_report_and_training_profile(self):
        with TemporaryDirectory() as temp_dir:
            output = StringIO()
            call_command(
                "simulate_daily_wow_conversations",
                "--journal-path",
                temp_dir,
                "--start-date",
                "2026-07-06",
                "--json",
                stdout=output,
            )
            report = json.loads(output.getvalue())
            self.assertEqual(report["lifecycle_transition_count"], 27)
            self.assertEqual(report["published_case_count"], 0)
            self.assertFalse([case for case in report["cases"] if case["errors"]])
            self.assertTrue((Path(temp_dir) / "user-judgment-profile.md").exists())
            self.assertTrue((Path(temp_dir) / "simulation" / "daily-wow-pressure-test-report.md").exists())
            self.assertIn("daily-wow-simulation:start", (Path(temp_dir) / "receipts.md").read_text(encoding="utf-8"))
            self.assertIn("Daily WoW Simulation Public Verification", (Path(temp_dir) / "public-verification.md").read_text(encoding="utf-8"))
            self.assertIn("Daily WoW Simulation Pending Scoreables", (Path(temp_dir) / "pending-scoreables.md").read_text(encoding="utf-8"))

    def test_run_simulation_returns_full_coverage_without_publish(self):
        with TemporaryDirectory() as temp_dir:
            report = run_daily_wow_simulation(
                journal_path=Path(temp_dir),
                start_date=date(2026, 7, 6),
                publish=False,
                write_journal=True,
            )

        self.assertEqual(report["lifecycle_transition_count"], 27)
        self.assertGreaterEqual(report["completed_case_count"], 32)
        self.assertFalse([case for case in report["cases"] if case["errors"]])
