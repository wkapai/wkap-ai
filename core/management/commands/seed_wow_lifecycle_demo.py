from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ingestion.models import RawEmail
from ledger.models import DailyWoWPacket, Investor, LedgerEvent
from ledger.services import create_wow_submission
from ledger.wow_lifecycle_rules import ALLOWED_STATUS_TRANSITIONS, WOW_TYPE_DEFAULT_STATUS
from publishing.services import publish_artifact, rebuild_indexes


DEMO_INVESTOR_ID = "w0999"
DEMO_EMAIL = "wkap-lifecycle-demo@example.com"
DEMO_NAME = "WKAP Lifecycle Demo Agent"
START_DATE = date(2026, 7, 6)

REALISTIC_SCENARIOS = {
    "candidate_wow": [
        (
            "GPU rental price pressure",
            "Cloud GPU rental checks hint at AI infrastructure pricing pressure",
            "https://www.coreweave.com/blog",
            "Spot GPU rental quotes and shorter reservation commitments may become an early sign that AI compute supply is loosening.",
        ),
        (
            "AI inference margin pressure",
            "Inference API price cuts create a new read-through for model serving margins",
            "https://openai.com/news/",
            "Repeated model API price cuts may pressure investors to separate usage growth from gross-margin durability.",
        ),
        (
            "Enterprise AI seat expansion quality",
            "Software AI seat adoption may be shifting from pilots to budget scrutiny",
            "https://www.microsoft.com/en-us/investor",
            "Management commentary around paid AI seats could reveal whether enterprise adoption is broadening or just concentrated in pilots.",
        ),
    ],
    "trackable_wow": [
        (
            "AI data-center power bottlenecks",
            "AI data-center buildouts keep running into power and interconnect constraints",
            "https://www.digitimes.com/",
            "Power availability and grid interconnection timelines are becoming recurring constraints for AI capacity deployment.",
        ),
        (
            "advanced packaging lead-time scarcity",
            "Advanced packaging checks show CoWoS-like capacity still gating accelerator supply",
            "https://www.tsmc.com/english/investorRelations",
            "Advanced packaging bottlenecks could keep the AI supply-chain profit pool concentrated even if GPU demand broadens.",
        ),
        (
            "HBM pricing and memory cycle quality",
            "Memory earnings revisions may depend more on HBM mix than commodity DRAM beta",
            "https://semiconductor.samsung.com/resources/",
            "The next memory cycle may be judged by high-bandwidth memory allocation and gross margin mix, not just bit growth.",
        ),
    ],
    "scoreable_signal": [
        (
            "stablecoin reserve-income architecture",
            "Open USD and stablecoin reserve economics put Circle revenue assumptions in focus",
            "https://reports.tiger-research.com/p/how-open-usd-sent-circle-down-17-eng",
            "Stablecoin issuers will face public evidence of reserve-income sharing pressure before the review date.",
        ),
        (
            "hyperscaler power constraint disclosure",
            "Hyperscaler capex commentary increasingly mentions power as a deployment constraint",
            "https://www.microsoft.com/en-us/investor/earnings",
            "At least one hyperscaler will cite power availability or interconnection delay as an AI deployment bottleneck.",
        ),
        (
            "robotaxi utilization proof point",
            "Autonomy optionality needs utilization evidence beyond launch-area headlines",
            "https://ir.tesla.com/",
            "Public robotaxi or autonomy data will show measurable utilization progress before the review date.",
        ),
        (
            "exchange moat absorption thesis",
            "Regulated exchanges may absorb crypto market-structure innovation rather than be displaced",
            "https://www.cmegroup.com/investor-relations.html",
            "An incumbent exchange will announce or disclose a crypto/RWA market-structure integration before the review date.",
        ),
    ],
    "thesis_wow": [
        (
            "regulated exchange market-structure moat",
            "Why established exchanges are harder to displace than the market believes",
            "https://substack.com/home/post/p-204294860",
            "Regulation, settlement, clearing, and institutional access may matter more than matching-engine technology in exchange moats.",
        ),
        (
            "AI deployment profit pool shift",
            "China AI deployment reframes the AI profit pool toward cost, hardware, and manufacturing integration",
            "https://mp.weixin.qq.com/s/HdZmqCHfzRBUyFT1QjAlzw",
            "The public-market AI profit pool may migrate from frontier model benchmarks to deployment, integration, and physical-world hardware.",
        ),
        (
            "agent-native investor workflow",
            "Investor logs may become training data for personal market agents",
            "https://wkap.ai/submit-to-wkap-ledger.html",
            "Agent-readable investor records may become more valuable than short-form investment takes as agents learn user standards.",
        ),
    ],
}


@dataclass(frozen=True)
class Target:
    wow_id: str
    wow_type: str
    current_status: str
    theme: str
    source_url: str


class Command(BaseCommand):
    help = "Seed one local investor with realistic WKAP WoW lifecycle demo packets."

    def add_arguments(self, parser):
        parser.add_argument("--keep-existing", action="store_true", help="Do not reset the existing w0999 demo data first.")

    def handle(self, *args, **options):
        if not options["keep_existing"]:
            self._reset_demo()

        Investor.objects.update_or_create(
            investor_id=DEMO_INVESTOR_ID,
            defaults={
                "email_private": DEMO_EMAIL,
                "display_name": DEMO_NAME,
                "status": Investor.Status.ACTIVE,
            },
        )

        run_id = uuid.uuid4()
        packet_urls: list[str] = []
        day_offset = 0
        transition_number = 1

        for wow_type, previous_map in ALLOWED_STATUS_TRANSITIONS.items():
            for previous_status, new_statuses in previous_map.items():
                for new_status in sorted(new_statuses):
                    target_date = START_DATE + timedelta(days=day_offset)
                    target = self._create_target_packet(
                        market_date=target_date,
                        wow_type=wow_type,
                        transition_number=transition_number,
                        run_id=run_id,
                    )
                    day_offset += 1
                    packet_urls.append(self._url_for(target_date))

                    if previous_status != target.current_status:
                        prerequisite_date = START_DATE + timedelta(days=day_offset)
                        prerequisite_type = self._update_type_for(previous_status, target.wow_type)
                        self._create_status_update_packet(
                            market_date=prerequisite_date,
                            target=target,
                            previous_status=target.current_status,
                            new_status=previous_status,
                            update_type=prerequisite_type,
                            run_id=run_id,
                            title=f"Prepare {target.theme} for {previous_status}",
                        )
                        target = Target(
                            wow_id=target.wow_id,
                            wow_type=target.wow_type,
                            current_status=previous_status,
                            theme=target.theme,
                            source_url=target.source_url,
                        )
                        day_offset += 1
                        packet_urls.append(self._url_for(prerequisite_date))

                    update_date = START_DATE + timedelta(days=day_offset)
                    self._create_status_update_packet(
                        market_date=update_date,
                        target=target,
                        previous_status=previous_status,
                        new_status=new_status,
                        update_type=self._update_type_for(new_status, target.wow_type, previous_status=previous_status),
                        run_id=run_id,
                        title=f"{target.theme}: {previous_status} to {new_status}",
                    )
                    day_offset += 1
                    packet_urls.append(self._url_for(update_date))
                    transition_number += 1

        rebuild_indexes(run_id=run_id)
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(packet_urls)} local WoW lifecycle demo packets for {DEMO_INVESTOR_ID}."))
        self.stdout.write(f"Investor home: http://127.0.0.1:8000/investors/{DEMO_INVESTOR_ID}/")
        self.stdout.write(f"WoW archive:   http://127.0.0.1:8000/investors/{DEMO_INVESTOR_ID}/wows/")
        self.stdout.write("Sample status update pages:")
        for url in packet_urls[-10:]:
            self.stdout.write(f"  {url}")

    def _reset_demo(self) -> None:
        packet_ids = list(DailyWoWPacket.objects.filter(investor__investor_id=DEMO_INVESTOR_ID).values_list("id", flat=True))
        LedgerEvent.objects.filter(investor_id=DEMO_INVESTOR_ID).delete()
        LedgerEvent.objects.filter(sender_email=DEMO_EMAIL).delete()
        DailyWoWPacket.objects.filter(investor__investor_id=DEMO_INVESTOR_ID).delete()
        RawEmail.objects.filter(sender_email=DEMO_EMAIL).delete()
        Investor.objects.filter(investor_id=DEMO_INVESTOR_ID).delete()

        self._remove_path(settings.WKAP_PUBLIC_SITE_ROOT / "investors" / DEMO_INVESTOR_ID)
        artifact_root = settings.BASE_DIR / "ledger_artifacts"
        for packet_id in packet_ids:
            self._remove_path(artifact_root / "manifests" / f"wow-{packet_id}.json")
            self._remove_path(artifact_root / "timestamps" / f"wow-{packet_id}.json")
            self._remove_path(artifact_root / "timestamps" / f"wow-{packet_id}.json.ots")
        for path in (artifact_root / "raw-emails" / "wow-packets").glob(f"wow-packet-{DEMO_INVESTOR_ID}-*.txt"):
            self._remove_path(path)

    def _remove_path(self, path: Path) -> None:
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            return
        workspace = settings.BASE_DIR.resolve()
        if workspace not in resolved.parents and resolved != workspace:
            raise RuntimeError(f"Refusing to remove path outside workspace: {resolved}")
        if not resolved.exists():
            return
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()

    def _create_target_packet(self, *, market_date: date, wow_type: str, transition_number: int, run_id: uuid.UUID) -> Target:
        theme, reading_title, source_url, _ = self._scenario_for(wow_type, transition_number)
        wow_id = self._wow_id(market_date, "001")
        item = self._root_item(wow_id=wow_id, wow_type=wow_type, theme=theme, source_url=source_url)
        packet = self._packet(
            market_date=market_date,
            title=f"{theme} baseline",
            summary=f"Baseline public WoW used to test {wow_type} lifecycle updates with realistic market context.",
            reading_title=reading_title,
            source_url=source_url,
            wow_items=[item, self._candidate_item(market_date, "002"), self._candidate_item(market_date, "003")],
            selected_wow_id=wow_id,
            reason=f"Baseline {wow_type} needed for local lifecycle reconstruction testing.",
        )
        self._ingest_and_publish(market_date=market_date, packet=packet, run_id=run_id)
        return Target(
            wow_id=wow_id,
            wow_type=wow_type,
            current_status=WOW_TYPE_DEFAULT_STATUS[wow_type],
            theme=theme,
            source_url=source_url,
        )

    def _create_status_update_packet(
        self,
        *,
        market_date: date,
        target: Target,
        previous_status: str,
        new_status: str,
        update_type: str,
        run_id: uuid.UUID,
        title: str,
    ) -> None:
        update_id = self._wow_id(market_date, "001")
        update_item = {
            "wow_id": update_id,
            "wow_type": "status_update",
            "investor_id": DEMO_INVESTOR_ID,
            "target_wow_type": target.wow_type,
            "target_wow_id": target.wow_id,
            "target_root_wow_id": target.wow_id,
            "update_type": update_type,
            "previous_status": previous_status,
            "new_status": new_status,
            "update_summary": f"{target.theme} moved from {previous_status} to {new_status}.",
            "evidence_summary": self._evidence_for(target, previous_status, new_status),
            "scoreable": False,
            "accuracy_endpoint_eligible": False,
            "lineage_node": False,
            "source_refs": ["Reading Item 1"],
            "agent_facts": {
                "wow_type": "status_update",
                "lineage_node": False,
                "target_wow_type": target.wow_type,
                "target_wow_id": target.wow_id,
                "target_root_wow_id": target.wow_id,
                "update_type": update_type,
                "previous_status": previous_status,
                "new_status": new_status,
            },
        }
        if update_type == "resolution" and new_status in {"resolved_correct", "resolved_incorrect"}:
            update_item["resolution_source_used"] = target.source_url

        second_item = self._promotion_child_item(market_date, target, new_status) or self._candidate_item(market_date, "002")
        packet = self._packet(
            market_date=market_date,
            title=title,
            summary=f"Append-only status update for {target.wow_id}.",
            reading_title=self._status_reading_title(target, new_status),
            source_url=target.source_url,
            wow_items=[update_item, second_item, self._candidate_item(market_date, "003")],
            selected_wow_id=update_id,
            reason=f"This status update is the clearest local demo of {previous_status} to {new_status}.",
        )
        self._ingest_and_publish(market_date=market_date, packet=packet, run_id=run_id)

    def _ingest_and_publish(self, *, market_date: date, packet: dict, run_id: uuid.UUID) -> None:
        body = "# WKAP Daily WoW Packet\n\n```yaml\n" + yaml.safe_dump({"packet": packet}, sort_keys=False, allow_unicode=True) + "```\n"
        received_at = timezone.make_aware(datetime.combine(market_date, time(21, 0)))
        raw = RawEmail.objects.create(
            gmail_message_id=f"local-lifecycle-demo-{market_date.isoformat()}",
            sender_email=DEMO_EMAIL,
            subject=f"Daily WoW Packet - {market_date} - {DEMO_NAME}",
            raw_body=body,
            received_at=received_at,
            classification=RawEmail.Classification.WOW,
            processing_status=RawEmail.ProcessingStatus.SAVED,
        )
        submission = create_wow_submission(raw, run_id=run_id)
        publish_artifact("wow", submission.id, run_id=run_id)

    def _packet(
        self,
        *,
        market_date: date,
        title: str,
        summary: str,
        reading_title: str,
        source_url: str,
        wow_items: list[dict],
        selected_wow_id: str,
        reason: str,
    ) -> dict:
        return {
            "packet_id": f"WKAP-{DEMO_INVESTOR_ID}-{market_date}",
            "investor_id": DEMO_INVESTOR_ID,
            "market_date": market_date.isoformat(),
            "created_at": f"{market_date}T21:00:00-04:00",
            "packet_spec_version": "v0.2",
            "packet_spec_url": "https://wkap.ai/specs/wow-packet-latest.md",
            "skill_version": "v0.2",
            "skill_url": "https://wkap.ai/skills/wkap-wow-skill-latest.md",
            "human_view": {"title": title, "summary": summary},
            "agent_facts": {
                "packet_id": f"WKAP-{DEMO_INVESTOR_ID}-{market_date}",
                "investor_id": DEMO_INVESTOR_ID,
                "packet_spec_version": "v0.2",
            },
            "reading_log": [
                {
                    "item_number": 1,
                    "source_title": reading_title,
                    "source_url": source_url,
                    "source_type": "article",
                    "published_time": f"{market_date}T13:00:00Z",
                    "tickers": ["NVDA", "TSM", "CRCL"],
                    "themes": ["AI infrastructure", "market structure", "stablecoin rails"],
                    "reading_origin": "agent_suggested",
                    "agent_summary": "Realistic public-market source used to pressure-test WKAP lifecycle reconstruction and outside-agent tracking.",
                }
            ],
            "wow_items": wow_items,
            "selection": {
                "selected_wow_id": selected_wow_id,
                "reason_for_selection": reason,
                "reason_for_pass": "",
                "closest_rejected_wow": "",
                "missing_evidence": "",
            },
            "validation_notes": {"schema_valid": True, "missing_fields": [], "warnings": ["local_lifecycle_demo_seed"]},
        }

    def _root_item(self, *, wow_id: str, wow_type: str, theme: str, source_url: str) -> dict:
        base = {
            "wow_id": wow_id,
            "wow_type": wow_type,
            "scoreable": False,
            "accuracy_endpoint_eligible": False,
            "parent_wow_id": None,
            "root_wow_id": wow_id,
            "source_refs": ["Reading Item 1"],
            "agent_facts": {"wow_type": wow_type, "scoreable": False, "accuracy_endpoint_eligible": False},
        }
        if wow_type == "candidate_wow":
            base.update(
                {
                    "observation": f"{theme} is showing up enough to preserve, but the evidence cadence is not yet clean.",
                    "why_worth_watching": "The idea could become trackable if repeated public evidence appears.",
                    "candidate_status": "active_candidate",
                }
            )
        elif wow_type == "trackable_wow":
            base.update(
                {
                    "claim": f"{theme} is becoming a concrete market pattern worth monitoring.",
                    "evidence_to_watch": ["management commentary", "pricing data", "filings or transcript mentions"],
                    "review_cadence": "weekly",
                    "next_review_at": "2026-09-30",
                    "trackable_status": "active_trackable",
                }
            )
        elif wow_type == "scoreable_signal":
            base.update(
                {
                    "scoreable": True,
                    "accuracy_endpoint_eligible": True,
                    "claim": f"{theme} will produce confirmable public evidence before 2026-09-30.",
                    "invalidate_test": f"No qualifying public evidence for {theme} appears by resolve_by.",
                    "resolve_by": "2026-09-30",
                    "resolution_source": source_url,
                    "signal_status": "pending_scoreable",
                    "agent_facts": {"wow_type": wow_type, "scoreable": True, "accuracy_endpoint_eligible": True},
                }
            )
        elif wow_type == "thesis_wow":
            base.update(
                {
                    "thesis_claim": f"{theme} is a broader investment thesis that can collect child WoWs over time.",
                    "thesis_status": "active_thesis",
                }
            )
        return base

    def _promotion_child_item(self, market_date: date, target: Target, new_status: str) -> dict | None:
        if new_status == "promoted_trackable":
            return {
                "wow_id": self._wow_id(market_date, "002"),
                "wow_type": "trackable_wow",
                "scoreable": False,
                "accuracy_endpoint_eligible": False,
                "parent_wow_id": target.wow_id,
                "root_wow_id": target.wow_id,
                "claim": f"{target.theme} now has enough evidence to monitor as an active trackable.",
                "evidence_to_watch": ["repeat source mentions", "company commentary", "pricing or volume signals"],
                "review_cadence": "weekly",
                "next_review_at": "2026-09-30",
                "trackable_status": "active_trackable",
                "source_refs": ["Reading Item 1"],
                "agent_facts": {"wow_type": "trackable_wow", "scoreable": False, "accuracy_endpoint_eligible": False},
            }
        if new_status == "promoted_scoreable":
            return {
                "wow_id": self._wow_id(market_date, "002"),
                "wow_type": "scoreable_signal",
                "scoreable": True,
                "accuracy_endpoint_eligible": True,
                "parent_wow_id": target.wow_id,
                "root_wow_id": target.wow_id,
                "claim": f"{target.theme} will generate confirmable evidence by 2026-09-30.",
                "invalidate_test": "No qualifying evidence appears by resolve_by.",
                "resolve_by": "2026-09-30",
                "resolution_source": target.source_url,
                "signal_status": "pending_scoreable",
                "source_refs": ["Reading Item 1"],
                "agent_facts": {"wow_type": "scoreable_signal", "scoreable": True, "accuracy_endpoint_eligible": True},
            }
        return None

    def _candidate_item(self, market_date: date, suffix: str) -> dict:
        wow_id = self._wow_id(market_date, suffix)
        return {
            "wow_id": wow_id,
            "wow_type": "candidate_wow",
            "scoreable": False,
            "accuracy_endpoint_eligible": False,
            "parent_wow_id": None,
            "root_wow_id": wow_id,
            "observation": "A secondary signal was noticed but not chosen as today's main lifecycle action.",
            "why_worth_watching": "It may become relevant if future evidence repeats.",
            "candidate_status": "active_candidate",
            "source_refs": ["Reading Item 1"],
            "agent_facts": {"wow_type": "candidate_wow", "scoreable": False, "accuracy_endpoint_eligible": False},
        }

    def _update_type_for(self, new_status: str, wow_type: str, *, previous_status: str = "") -> str:
        if previous_status and new_status == previous_status:
            return "evidence"
        if new_status in {"promoted_trackable", "promoted_scoreable"}:
            return "promotion"
        if new_status in {"resolved_correct", "resolved_incorrect", "unresolved"}:
            return "resolution"
        if new_status == "killed":
            return "killed"
        if new_status == "stale":
            return "stale"
        if new_status == "voided":
            return "voided"
        if new_status == "invalid_test":
            return "invalid_test"
        if wow_type == "thesis_wow" and new_status in {"supported", "weakened", "retired"}:
            return "thesis_update"
        return "other"

    def _wow_id(self, market_date: date, suffix: str) -> str:
        return f"WOW-{DEMO_INVESTOR_ID}-{market_date}-{suffix}"

    def _scenario_for(self, wow_type: str, index: int) -> tuple[str, str, str, str]:
        scenarios = REALISTIC_SCENARIOS[wow_type]
        return scenarios[(index - 1) % len(scenarios)]

    def _status_reading_title(self, target: Target, new_status: str) -> str:
        return f"{target.theme} lifecycle evidence now supports {new_status.replace('_', ' ')}"

    def _evidence_for(self, target: Target, previous_status: str, new_status: str) -> str:
        evidence_by_status = {
            "promoted_trackable": "The signal repeated across sources and now has a concrete evidence watchlist plus review cadence.",
            "promoted_scoreable": "The signal now has a falsifiable claim, explicit invalidate test, review date, and resolution source.",
            "resolved_correct": "The declared public source produced evidence consistent with the original claim.",
            "resolved_incorrect": "The declared public source produced evidence that invalidates the original claim.",
            "unresolved": "The review date arrived without enough clean evidence to score the claim either way.",
            "invalid_test": "The original test was too ambiguous or mismatched to judge the market claim cleanly.",
            "voided": "The signal remained unjudgeable after the grace window and should no longer pollute active CRM state.",
            "killed": "Follow-up evidence made the idea no longer worth active attention.",
            "stale": "The idea has not repeated recently and should be deprioritized until fresh evidence appears.",
            "active_candidate": "Fresh evidence revived the previously stale candidate into active watch status.",
            "active_trackable": "Fresh evidence revived the stale trackable into active monitoring status.",
            "supported": "New evidence strengthens the broader thesis without making it a single scoreable claim.",
            "weakened": "New evidence weakens the thesis and should lower confidence or narrow its scope.",
            "retired": "The thesis no longer helps current investor work and should be archived.",
        }
        reason = evidence_by_status.get(new_status, "New evidence changes the CRM state.")
        return (
            f"{reason} Source used: {target.source_url}. "
            f"Transition: {previous_status} -> {new_status}."
        )

    def _url_for(self, market_date: date) -> str:
        return f"http://127.0.0.1:8000/investors/{DEMO_INVESTOR_ID}/wows/wow-{DEMO_INVESTOR_ID}-{market_date}.html"
