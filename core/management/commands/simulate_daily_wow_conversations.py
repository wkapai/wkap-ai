from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

from core.wow_daily_simulation import (
    SIM_INVESTOR_ID,
    default_journal_path,
    reset_daily_wow_simulation,
    run_daily_wow_simulation,
)


class Command(BaseCommand):
    help = "Simulate Daily WoW agent/user conversations, lifecycle flows, and local journal training data."

    def add_arguments(self, parser):
        parser.add_argument("--journal-path", default=str(default_journal_path()))
        parser.add_argument("--start-date", default="2026-07-06")
        parser.add_argument("--investor-id", default=SIM_INVESTOR_ID)
        parser.add_argument("--publish", action="store_true", help="Publish completed simulated packets to the local WKAP ledger.")
        parser.add_argument("--no-journal", action="store_true", help="Run without writing local journal artifacts.")
        parser.add_argument("--reset", action="store_true", help="Delete prior local simulation data before running.")
        parser.add_argument("--reset-only", action="store_true", help="Delete prior local simulation data and exit.")
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    def handle(self, *args, **options):
        reset_report = None
        if options["reset"] or options["reset_only"]:
            reset_report = reset_daily_wow_simulation(
                journal_path=Path(options["journal_path"]),
                investor_id=options["investor_id"],
            )
        if options["reset_only"]:
            if options["json"]:
                self.stdout.write(json.dumps({"reset": reset_report}, indent=2, sort_keys=True))
                return
            self.stdout.write(self.style.SUCCESS("Daily WoW simulation data reset completed."))
            self.stdout.write(f"Deleted packets: {reset_report['deleted']['daily_wow_packets']}")
            self.stdout.write(f"Deleted raw emails: {reset_report['deleted']['raw_emails']}")
            self.stdout.write(f"Deleted ledger events: {reset_report['deleted']['ledger_events']}")
            self.stdout.write(f"Removed paths: {reset_report['deleted']['paths']}")
            return

        report = run_daily_wow_simulation(
            journal_path=Path(options["journal_path"]),
            start_date=date.fromisoformat(options["start_date"]),
            investor_id=options["investor_id"],
            publish=options["publish"],
            write_journal=not options["no_journal"],
        )
        if reset_report:
            report["reset"] = reset_report
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
