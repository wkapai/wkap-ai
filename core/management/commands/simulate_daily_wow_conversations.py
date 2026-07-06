from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

from core.wow_daily_simulation import SIM_INVESTOR_ID, default_journal_path, run_daily_wow_simulation


class Command(BaseCommand):
    help = "Simulate Daily WoW agent/user conversations, lifecycle flows, and local journal training data."

    def add_arguments(self, parser):
        parser.add_argument("--journal-path", default=str(default_journal_path()))
        parser.add_argument("--start-date", default="2026-07-06")
        parser.add_argument("--author-id", default=SIM_INVESTOR_ID)
        parser.add_argument("--publish", action="store_true", help="Publish completed simulated packets to the local WKAP ledger.")
        parser.add_argument("--no-journal", action="store_true", help="Run without writing local journal artifacts.")
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    def handle(self, *args, **options):
        report = run_daily_wow_simulation(
            journal_path=Path(options["journal_path"]),
            start_date=date.fromisoformat(options["start_date"]),
            author_id=options["author_id"],
            publish=options["publish"],
            write_journal=not options["no_journal"],
        )
        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
            return

        self.stdout.write(self.style.SUCCESS("Daily WoW simulation completed."))
        self.stdout.write(f"Journal path: {report['journal_path']}")
        self.stdout.write(f"Cases: {report['case_count']}")
        self.stdout.write(f"Completed packets: {report['completed_case_count']}")
        self.stdout.write(f"Published packets: {report['published_case_count']}")
        self.stdout.write(f"Lifecycle transitions covered: {report['lifecycle_transition_count']}")
        self.stdout.write("Findings:")
        for finding in report["findings"]:
            self.stdout.write(f"  {finding['severity']} {finding['title']} - {finding['status']}")
