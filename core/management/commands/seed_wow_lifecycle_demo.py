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
                        update_type=self._update_type_for(new_status, target.wow_type),
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
        theme = self._theme_for(wow_type, transition_number)
        source_url = self._source_for(wow_type, transition_number)
        wow_id = f"WOW-{market_date}-001"
        item = self._root_item(wow_id=wow_id, wow_type=wow_type, theme=theme, source_url=source_url)
        packet = self._packet(
            market_date=market_date,
            title=f"{theme} baseline",
            summary=f"Baseline public WoW used to test {wow_type} lifecycle updates.",
            reading_title=self._reading_title_for(wow_type, theme),
            source_url=source_url,
            wow_items=[item, self._context_item(market_date, "002"), self._candidate_item(market_date, "003")],
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
        update_id = f"WOW-{market_date}-001"
        update_item = {
            "wow_id": update_id,
            "wow_type": "status_update",
            "author_id": DEMO_INVESTOR_ID,
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

        second_item = self._promotion_child_item(market_date, target, new_status) or self._context_item(market_date, "002")
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
            "author_id": DEMO_INVESTOR_ID,
            "market_date": market_date.isoformat(),
            "created_at": f"{market_date}T21:00:00-04:00",
            "packet_spec_version": "v0.1",
            "packet_spec_url": "https://wkap.ai/specs/wow-packet-latest.md",
            "skill_version": "v0.1",
            "skill_url": "https://wkap.ai/skills/wkap-wow-skill-latest.md",
            "human_view": {"title": title, "summary": summary},
            "agent_facts": {
                "packet_id": f"WKAP-{DEMO_INVESTOR_ID}-{market_date}",
                "author_id": DEMO_INVESTOR_ID,
                "packet_spec_version": "v0.1",
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
                    "agent_summary": "Realistic public-market source used to pressure-test WKAP lifecycle reconstruction.",
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
        elif wow_type == "context_note":
            base.update(
                {
                    "observation": f"{theme} is useful context for future agent research but is not itself an investable claim.",
                    "context_status": "active_context",
                }
            )
        return base

    def _promotion_child_item(self, market_date: date, target: Target, new_status: str) -> dict | None:
        if new_status == "promoted_trackable":
            return {
                "wow_id": f"WOW-{market_date}-002",
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
                "wow_id": f"WOW-{market_date}-002",
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

    def _context_item(self, market_date: date, suffix: str) -> dict:
        wow_id = f"WOW-{market_date}-{suffix}"
        return {
            "wow_id": wow_id,
            "wow_type": "context_note",
            "scoreable": False,
            "accuracy_endpoint_eligible": False,
            "parent_wow_id": None,
            "root_wow_id": wow_id,
            "observation": "This source is useful context for the daily investor loop but not selected as the main CRM update.",
            "context_status": "active_context",
            "source_refs": ["Reading Item 1"],
            "agent_facts": {"wow_type": "context_note", "scoreable": False, "accuracy_endpoint_eligible": False},
        }

    def _candidate_item(self, market_date: date, suffix: str) -> dict:
        wow_id = f"WOW-{market_date}-{suffix}"
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

    def _update_type_for(self, new_status: str, wow_type: str) -> str:
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
        if wow_type == "context_note" and new_status in {"superseded", "retired"}:
            return "context_update"
        return "other"

    def _theme_for(self, wow_type: str, index: int) -> str:
        themes = {
            "candidate_wow": "GPU rental price pressure",
            "trackable_wow": "AI data-center power bottlenecks",
            "scoreable_signal": "stablecoin reserve-income architecture",
            "thesis_wow": "regulated exchange market-structure moat",
            "context_note": "China AI industrial deployment context",
        }
        return f"{themes[wow_type]} #{index}"

    def _source_for(self, wow_type: str, index: int) -> str:
        sources = {
            "candidate_wow": "https://www.coreweave.com/blog",
            "trackable_wow": "https://www.digitimes.com/",
            "scoreable_signal": "https://reports.tiger-research.com/p/how-open-usd-sent-circle-down-17-eng",
            "thesis_wow": "https://substack.com/home/post/p-204294860",
            "context_note": "https://mp.weixin.qq.com/s/HdZmqCHfzRBUyFT1QjAlzw",
        }
        return sources[wow_type]

    def _reading_title_for(self, wow_type: str, theme: str) -> str:
        titles = {
            "candidate_wow": "GPU cloud rental checks hint at AI infrastructure pricing pressure",
            "trackable_wow": "AI data-center buildouts keep running into power and interconnect constraints",
            "scoreable_signal": "Open USD and stablecoin reserve economics put Circle revenue assumptions in focus",
            "thesis_wow": "Incumbent exchanges may be harder to displace than crypto narratives imply",
            "context_note": "China AI deployment may compound through low-cost models and manufacturing integration",
        }
        return f"{titles[wow_type]}: {theme}"

    def _status_reading_title(self, target: Target, new_status: str) -> str:
        return f"{target.theme} lifecycle evidence now supports {new_status}"

    def _evidence_for(self, target: Target, previous_status: str, new_status: str) -> str:
        return (
            f"New public evidence from {target.source_url} changes {target.theme} from "
            f"{previous_status} to {new_status}; this is a local demo packet built so an outside agent can reconstruct the CRM state."
        )

    def _url_for(self, market_date: date) -> str:
        return f"http://127.0.0.1:8000/investors/{DEMO_INVESTOR_ID}/wows/wow-{DEMO_INVESTOR_ID}-{market_date}.html"
