from __future__ import annotations

import json
import base64
import re
from html import unescape
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
from ledger.wow_lifecycle_rules import ALLOWED_STATUS_TRANSITIONS
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
    purge_radar_cache,
    publish_artifact,
    rebuild_indexes,
    timestamp_artifact,
    upgrade_opentimestamps,
    validate_ledger,
    warm_radar_cache,
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
                    "closest_rejected_wow: WOW-2026-06-29-002",
                    "why_pass: The signal was interesting but not concrete enough today.",
                    "missing_evidence: Confirmed backlog growth or named customer commentary.",
                ]
            )
        return "\n".join(lines)

    def structured_wow_packet_body(self):
        return """# WKAP Daily WoW Packet

Human summary:
AI infrastructure is moving from broad narrative into testable supply-chain bottlenecks.

```yaml
packet:
  packet_id: WKAP-w0202-2026-06-29
  author_id: w0202
  market_date: 2026-06-29
  created_at: 2026-06-29T21:00:00Z
  packet_spec_version: v0.2
  packet_spec_url: https://wkap.ai/specs/wow-packet-v0.2.md
  packet_spec_latest_url: https://wkap.ai/specs/wow-packet-latest.md
  skill_version: v0.2
  skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md
  human_view:
    title: AI infrastructure bottleneck
    summary: Watch whether AI compute demand is shifting bottlenecks into power and advanced packaging.
    top_wows:
      - WOW-w0202-2026-06-29-001
  agent_facts:
    packet_id: WKAP-w0202-2026-06-29
    author_id: w0202
    packet_spec_version: v0.2
    wow_count: 3
    scoreable_count: 1
    trackable_count: 1
    thesis_count: 0
    candidate_count: 1
    status_update_count: 0
  reading_log:
    - item_number: 1
      source_title: AI data center supply chain checks
      source_url: https://example.com/ai-supply
      source_type: article
      published_time: 2026-06-29T13:00:00Z
      tickers:
        - NVDA
        - TSM
      themes:
        - AI infrastructure
        - advanced packaging
      reading_origin: user_browsed
      agent_summary: Packaging and power constraints are becoming repeated evidence points.
  wow_items:
    - wow_id: WOW-w0202-2026-06-29-001
      wow_type: trackable_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-2026-06-29-001
      claim: AI infrastructure bottlenecks are moving toward power and packaging.
      evidence_to_watch:
        - advanced packaging lead times
        - utility interconnection queues
      review_cadence: daily
      next_review_at: 2026-06-30
      trackable_status: active_trackable
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: trackable_wow
        scoreable: false
        accuracy_endpoint_eligible: false
    - wow_id: WOW-w0202-2026-06-29-002
      wow_type: scoreable_signal
      scoreable: true
      accuracy_endpoint_eligible: true
      parent_wow_id: null
      root_wow_id: WOW-w0202-2026-06-29-002
      claim: At least one hyperscaler will cite power availability as an AI capex bottleneck by 2026-09-30.
      invalidate_test: No hyperscaler cites power availability as an AI capex bottleneck by resolve_by.
      resolve_by: 2026-09-30
      resolution_source: hyperscaler earnings transcripts
      signal_status: pending_scoreable
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: scoreable_signal
        scoreable: true
        accuracy_endpoint_eligible: true
    - wow_id: WOW-w0202-2026-06-29-003
      wow_type: candidate_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-2026-06-29-003
      observation: AI hardware discussions increasingly mention grid equipment.
      why_worth_watching: It may broaden the AI supply-chain basket.
      candidate_status: active_candidate
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: candidate_wow
        scoreable: false
        accuracy_endpoint_eligible: false
  selection:
    selected_wow_id: WOW-w0202-2026-06-29-001
    reason_for_selection: Best daily watch item with clear follow-up evidence.
    reason_for_pass:
    closest_rejected_wow:
    missing_evidence:
  validation_notes:
    schema_valid: true
    missing_fields: []
    warnings: []
```
"""

    def structured_status_update_packet_body(self):
        return """# WKAP Daily WoW Packet

```yaml
packet:
  packet_id: WKAP-w0202-2026-07-01
  author_id: w0202
  market_date: 2026-07-01
  created_at: 2026-07-01T21:00:00Z
  packet_spec_version: v0.2
  packet_spec_url: https://wkap.ai/specs/wow-packet-v0.2.md
  skill_version: v0.2
  skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md
  human_view:
    title: AI power bottleneck lifecycle update
    summary: New utility evidence promotes yesterday's AI power bottleneck from trackable to scoreable.
  agent_facts:
    packet_id: WKAP-w0202-2026-07-01
    author_id: w0202
    packet_spec_version: v0.2
  reading_log:
    - item_number: 1
      source_title: Utility interconnection queue update
      source_url: https://example.com/utility-queue
      source_type: filing
      published_time: 2026-07-01T13:00:00Z
      tickers:
        - NVDA
        - NEE
      themes:
        - AI data centers
        - power bottlenecks
      reading_origin: agent_suggested
      agent_summary: Interconnection queue disclosures made the AI power bottleneck more testable.
  wow_items:
    - wow_id: WOW-w0202-2026-07-01-001
      wow_type: status_update
      author_id: w0202
      target_wow_type: trackable_wow
      target_wow_id: WOW-w0202-2026-06-29-001
      target_root_wow_id: WOW-w0202-2026-06-29-001
      update_type: promotion
      previous_status: active_trackable
      new_status: promoted_scoreable
      update_summary: Utility queue evidence makes the prior AI power bottleneck WoW scoreable.
      evidence_summary: A named utility backlog item can now be checked against future earnings commentary.
      scoreable: false
      accuracy_endpoint_eligible: false
      lineage_node: false
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: status_update
        lineage_node: false
        target_wow_type: trackable_wow
        target_wow_id: WOW-w0202-2026-06-29-001
        target_root_wow_id: WOW-w0202-2026-06-29-001
        update_type: promotion
        previous_status: active_trackable
        new_status: promoted_scoreable
    - wow_id: WOW-w0202-2026-07-01-002
      wow_type: scoreable_signal
      scoreable: true
      accuracy_endpoint_eligible: true
      parent_wow_id: WOW-w0202-2026-06-29-001
      root_wow_id: WOW-w0202-2026-06-29-001
      claim: A hyperscaler will cite power access as an AI deployment constraint by 2026-09-30.
      invalidate_test: No hyperscaler cites power access as an AI deployment constraint by resolve_by.
      resolve_by: 2026-09-30
      resolution_source: hyperscaler earnings transcripts
      signal_status: pending_scoreable
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: scoreable_signal
        scoreable: true
        accuracy_endpoint_eligible: true
    - wow_id: WOW-w0202-2026-07-01-003
      wow_type: candidate_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-2026-07-01-003
      observation: Power names may become part of the AI infrastructure basket.
      why_worth_watching: It may become trackable if future AI power sourcing evidence repeats.
      candidate_status: active_candidate
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: candidate_wow
        scoreable: false
        accuracy_endpoint_eligible: false
  selection:
    selected_wow_id: WOW-w0202-2026-07-01-001
    reason_for_selection: The promotion captures the day's most important lifecycle change.
    reason_for_pass:
    closest_rejected_wow:
    missing_evidence:
  validation_notes:
    schema_valid: true
    missing_fields: []
    warnings: []
```
"""

    def structured_lifecycle_packet_body(
        self,
        *,
        market_date: str,
        update_index: int,
        target_wow_type: str,
        previous_status: str,
        new_status: str,
        update_type: str,
    ):
        target_id = f"WOW-w0202-2026-06-29-{update_index:03d}"
        packet_id = f"WKAP-w0202-{market_date}"
        wow_id = f"WOW-w0202-{market_date}-001"
        theme = {
            "candidate_wow": "GPU rental pricing pressure",
            "trackable_wow": "AI data-center power availability",
            "scoreable_signal": "Stablecoin reserve-income architecture",
            "thesis_wow": "Regulated exchange moat thesis",
        }.get(target_wow_type, "AI infrastructure")
        source_title = {
            "candidate_wow": "Cloud GPU rental price checks show early loosening",
            "trackable_wow": "AI data-center power constraints appear in hyperscaler commentary",
            "scoreable_signal": "How Open USD Sent Circle Down 17%",
            "thesis_wow": "Why established exchanges are harder to displace than the market believes",
        }.get(target_wow_type, "AI infrastructure source")
        source_url = {
            "candidate_wow": "https://www.coreweave.com/blog",
            "trackable_wow": "https://www.digitimes.com/",
            "scoreable_signal": "https://reports.tiger-research.com/p/how-open-usd-sent-circle-down-17-eng",
            "thesis_wow": "https://substack.com/home/post/p-204294860",
        }.get(target_wow_type, "https://www.reuters.com/technology/")
        ticker = {
            "candidate_wow": "CRWV",
            "trackable_wow": "NVDA",
            "scoreable_signal": "CRCL",
            "thesis_wow": "CME",
        }.get(target_wow_type, "NVDA")
        follow_up_item = self._lifecycle_follow_up_item(
            market_date=market_date,
            target_id=target_id,
            new_status=new_status,
        )
        return f"""# WKAP Daily WoW Packet

```yaml
packet:
  packet_id: {packet_id}
  author_id: w0202
  market_date: {market_date}
  created_at: {market_date}T21:00:00Z
  packet_spec_version: v0.2
  packet_spec_url: https://wkap.ai/specs/wow-packet-v0.2.md
  skill_version: v0.2
  skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md
  human_view:
    title: {theme} lifecycle check
    summary: Daily lifecycle update for {theme}.
  agent_facts:
    packet_id: {packet_id}
    author_id: w0202
    packet_spec_version: v0.2
  reading_log:
    - item_number: 1
      source_title: {source_title}
      source_url: {source_url}
      source_type: article
      published_time: {market_date}T13:00:00Z
      tickers:
        - {ticker}
      themes:
        - {theme}
      reading_origin: agent_suggested
      agent_summary: Public market evidence changed the lifecycle status for {theme}; the item is useful for testing how WKAP agents preserve idea state.
  wow_items:
    - wow_id: {wow_id}
      wow_type: status_update
      author_id: w0202
      target_wow_type: {target_wow_type}
      target_wow_id: {target_id}
      target_root_wow_id: {target_id}
      update_type: {update_type}
      previous_status: {previous_status}
      new_status: {new_status}
      update_summary: {target_wow_type} moved from {previous_status} to {new_status}.
      evidence_summary: Evidence from today's public market source supports the lifecycle update.
      resolution_source_used: {source_url}
      scoreable: false
      accuracy_endpoint_eligible: false
      lineage_node: false
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: status_update
        lineage_node: false
        target_wow_type: {target_wow_type}
        target_wow_id: {target_id}
        target_root_wow_id: {target_id}
        update_type: {update_type}
        previous_status: {previous_status}
        new_status: {new_status}
{follow_up_item}
    - wow_id: WOW-w0202-{market_date}-003
      wow_type: candidate_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-{market_date}-003
      observation: Market context remains relevant but not scoreable today.
      why_worth_watching: It may become a concrete candidate if the same theme repeats in future sources.
      candidate_status: active_candidate
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: candidate_wow
        scoreable: false
        accuracy_endpoint_eligible: false
  selection:
    selected_wow_id: {wow_id}
    reason_for_selection: This lifecycle update is the most important CRM maintenance item today.
    reason_for_pass:
    closest_rejected_wow:
    missing_evidence:
  validation_notes:
    schema_valid: true
    missing_fields: []
    warnings: []
```
"""

    def _lifecycle_follow_up_item(self, *, market_date: str, target_id: str, new_status: str) -> str:
        if new_status == "promoted_trackable":
            return f"""    - wow_id: WOW-w0202-{market_date}-002
      wow_type: trackable_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: {target_id}
      root_wow_id: {target_id}
      claim: The promoted idea now has a concrete evidence watchlist and review cadence.
      evidence_to_watch:
        - public company commentary
        - pricing or demand data
      review_cadence: weekly
      next_review_at: 2026-09-01
      trackable_status: active_trackable
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: trackable_wow
        scoreable: false
        accuracy_endpoint_eligible: false"""
        if new_status == "promoted_scoreable":
            return f"""    - wow_id: WOW-w0202-{market_date}-002
      wow_type: scoreable_signal
      scoreable: true
      accuracy_endpoint_eligible: true
      parent_wow_id: {target_id}
      root_wow_id: {target_id}
      claim: The promoted idea will produce confirmable public evidence before 2026-09-30.
      invalidate_test: No qualifying public evidence appears by resolve_by.
      resolve_by: 2026-09-30
      resolution_source: public filings or earnings transcripts
      signal_status: pending_scoreable
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: scoreable_signal
        scoreable: true
        accuracy_endpoint_eligible: true"""
        return f"""    - wow_id: WOW-w0202-{market_date}-002
      wow_type: scoreable_signal
      scoreable: true
      accuracy_endpoint_eligible: true
      parent_wow_id: null
      root_wow_id: WOW-w0202-{market_date}-002
      claim: At least one public-market source will mention AI power constraints before 2026-09-30.
      invalidate_test: No qualifying source mentions AI power constraints by resolve_by.
      resolve_by: 2026-09-30
      resolution_source: public filings or earnings transcripts
      signal_status: pending_scoreable
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: scoreable_signal
        scoreable: true
        accuracy_endpoint_eligible: true"""

    def structured_thesis_context_packet_body(self):
        return """# WKAP Daily WoW Packet

```yaml
packet:
  packet_id: WKAP-w0202-2026-06-30
  author_id: w0202
  market_date: 2026-06-30
  created_at: 2026-06-30T21:00:00Z
  packet_spec_version: v0.2
  packet_spec_url: https://wkap.ai/specs/wow-packet-v0.2.md
  skill_version: v0.2
  skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md
  human_view:
    title: Market structure and China AI context
    summary: Preserve one thesis, one context note, and one candidate from real market reading.
  agent_facts:
    packet_id: WKAP-w0202-2026-06-30
    author_id: w0202
    packet_spec_version: v0.2
  reading_log:
    - item_number: 1
      source_title: Why established exchanges are harder to displace than the market believes
      source_url: https://substack.com/home/post/p-204294860
      source_type: article
      published_time: 2026-06-30T13:00:00Z
      tickers:
        - CME
        - ICE
      themes:
        - market structure
        - regulated exchanges
      reading_origin: user_browsed
      agent_summary: Exchange moats may be institutional and regulatory rather than purely technical.
    - item_number: 2
      source_title: China AI deployment discussion
      source_url: https://mp.weixin.qq.com/s/HdZmqCHfzRBUyFT1QjAlzw
      source_type: article
      published_time: 2026-06-30T14:00:00Z
      tickers:
        - BABA
      themes:
        - China AI
        - industrial AI
      reading_origin: agent_suggested
      agent_summary: China AI may compound through low-cost deployment and manufacturing integration.
  wow_items:
    - wow_id: WOW-w0202-2026-06-30-001
      wow_type: thesis_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-2026-06-30-001
      thesis_claim: Regulated exchange moats may absorb crypto market-structure innovation instead of being displaced by it.
      thesis_status: active_thesis
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: thesis_wow
        scoreable: false
        accuracy_endpoint_eligible: false
    - wow_id: WOW-w0202-2026-06-30-002
      wow_type: candidate_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-2026-06-30-002
      observation: China AI edge may show up in deployment cost and hardware integration before frontier benchmark leadership.
      why_worth_watching: It could become trackable if public market sources repeat the deployment-cost angle.
      candidate_status: active_candidate
      source_refs:
        - Reading Item 2
      agent_facts:
        wow_type: candidate_wow
        scoreable: false
        accuracy_endpoint_eligible: false
    - wow_id: WOW-w0202-2026-06-30-003
      wow_type: candidate_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-2026-06-30-003
      observation: Stablecoin reserve-income sharing may become a repeated fintech valuation debate.
      why_worth_watching: It links Circle, Coinbase, exchanges, and payment infrastructure into one revenue-architecture question.
      candidate_status: active_candidate
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: candidate_wow
        scoreable: false
        accuracy_endpoint_eligible: false
  selection:
    selected_wow_id: WOW-w0202-2026-06-30-001
    reason_for_selection: The thesis is a useful root for future exchange and stablecoin market-structure evidence.
    reason_for_pass:
    closest_rejected_wow:
    missing_evidence:
  validation_notes:
    schema_valid: true
    missing_fields: []
    warnings: []
```
"""

    def structured_target_update_packet_body(
        self,
        *,
        market_date: str,
        target_wow_id: str,
        target_wow_type: str,
        previous_status: str,
        new_status: str,
        update_type: str,
        selected_suffix: str = "001",
    ):
        source_url = "https://www.reuters.com/technology/"
        resolution_source = f"      resolution_source_used: {source_url}\n" if new_status in {"resolved_correct", "resolved_incorrect"} else ""
        return f"""# WKAP Daily WoW Packet

```yaml
packet:
  packet_id: WKAP-w0202-{market_date}
  author_id: w0202
  market_date: {market_date}
  created_at: {market_date}T21:00:00Z
  packet_spec_version: v0.2
  packet_spec_url: https://wkap.ai/specs/wow-packet-v0.2.md
  skill_version: v0.2
  skill_url: https://wkap.ai/skills/wkap-wow-skill-latest.md
  human_view:
    title: Existing WoW Signal Status Update
    summary: Append-only lifecycle update for an existing public WoW signal.
  agent_facts:
    packet_id: WKAP-w0202-{market_date}
    author_id: w0202
    packet_spec_version: v0.2
  reading_log:
    - item_number: 1
      source_title: Public investment source updates prior WoW lifecycle
      source_url: {source_url}
      source_type: article
      published_time: {market_date}T13:00:00Z
      tickers:
        - NVDA
        - CRCL
      themes:
        - AI infrastructure
        - market structure
      reading_origin: agent_suggested
      agent_summary: The new source changes the public lifecycle state for an existing WoW.
  wow_items:
    - wow_id: WOW-w0202-{market_date}-{selected_suffix}
      wow_type: status_update
      author_id: w0202
      target_wow_type: {target_wow_type}
      target_wow_id: {target_wow_id}
      target_root_wow_id: {target_wow_id}
      update_type: {update_type}
      previous_status: {previous_status}
      new_status: {new_status}
      update_summary: {target_wow_id} moved from {previous_status} to {new_status}.
      evidence_summary: Today's public source provides enough evidence for this append-only CRM status change.
{resolution_source}      scoreable: false
      accuracy_endpoint_eligible: false
      lineage_node: false
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: status_update
        lineage_node: false
        target_wow_type: {target_wow_type}
        target_wow_id: {target_wow_id}
        target_root_wow_id: {target_wow_id}
        update_type: {update_type}
        previous_status: {previous_status}
        new_status: {new_status}
    - wow_id: WOW-w0202-{market_date}-002
      wow_type: candidate_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-{market_date}-002
      observation: The source is useful context for ongoing investor research but is not selected today.
      why_worth_watching: It may become a candidate if future evidence turns the context into a concrete market signal.
      candidate_status: active_candidate
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: candidate_wow
        scoreable: false
        accuracy_endpoint_eligible: false
    - wow_id: WOW-w0202-{market_date}-003
      wow_type: candidate_wow
      scoreable: false
      accuracy_endpoint_eligible: false
      parent_wow_id: null
      root_wow_id: WOW-w0202-{market_date}-003
      observation: A related but weaker market observation remains below selection bar.
      why_worth_watching: It may matter later but has less direct evidence today.
      candidate_status: active_candidate
      source_refs:
        - Reading Item 1
      agent_facts:
        wow_type: candidate_wow
        scoreable: false
        accuracy_endpoint_eligible: false
  selection:
    selected_wow_id: WOW-w0202-{market_date}-{selected_suffix}
    reason_for_selection: This existing WoW status change is the most important investor CRM update today.
    reason_for_pass:
    closest_rejected_wow:
    missing_evidence:
  validation_notes:
    schema_valid: true
    missing_fields: []
    warnings: []
```
"""

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

    def test_radar_parser_uses_subject_date_before_body_date(self):
        raw = self.raw_email(
            subject="WKAP Radar Feed - 2026 - 06 - 30",
            body="Market_date: 2026-07-06\nTitle: Historical Radar\nBody: Context from a historical resend",
        )

        parsed = parse_radar(raw)

        self.assertEqual(str(parsed.market_date), "2026-06-30")
        self.assertEqual(parsed.title, "Historical Radar")
        self.assertEqual(parsed.body_text, raw.raw_body)

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
        self.assertEqual(parsed.format_version, "wow_packet_v0.2")
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

    def test_wow_packet_parser_accepts_public_namespaced_wow_ids(self):
        body = self.wow_packet_body(selected="WOW-w0204-2026-06-29-001")
        body = body.replace("wow_id: WOW-2026-06-29-001", "wow_id: WOW-w0204-2026-06-29-001")
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Namespaced Agent", body=body)

        parsed = parse_wow(raw)

        self.assertEqual(parsed.selected_wow_id, "WOW-2026-06-29-001")
        self.assertEqual(parsed.suggested_wows[0].wow_id, "WOW-2026-06-29-001")

    def test_wow_packet_parser_accepts_legacy_user_note_field(self):
        body = self.wow_packet_body().replace("reason_for_selection:", "user_note:")
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Legacy Agent", body=body)

        parsed = parse_wow(raw)

        self.assertEqual(parsed.reason_for_selection, "Focus on the supplier evidence.")

    def test_wow_packet_parser_requires_reason_for_selected_wow(self):
        body = self.wow_packet_body().replace(
            "reason_for_selection: Focus on the supplier evidence.",
            "reason_for_selection:",
        )
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Missing Reason Agent", body=body)

        with self.assertRaisesMessage(ParseError, "reason_for_selection"):
            parse_wow(raw)

    def test_structured_wow_packet_v01_parses_and_stores_lifecycle_payload(self):
        run_id = "00000000-0000-0000-0000-000000000040"
        raw = self.raw_email(sender="structured@example.com", subject="Daily WoW Packet - 2026-06-29 - Structured Agent", body=self.structured_wow_packet_body())

        parsed = parse_wow(raw)
        packet = create_wow_submission(raw, run_id=run_id)

        self.assertEqual(parsed.format_version, "wow_packet_v0.2")
        self.assertEqual(parsed.packet_spec_version, "v0.2")
        self.assertEqual(parsed.author_id, "w0202")
        self.assertEqual(parsed.scoreable_count, 1)
        self.assertEqual(parsed.trackable_count, 1)
        self.assertEqual(parsed.candidate_count, 1)
        self.assertEqual(parsed.selected_wow_id, "WOW-2026-06-29-001")
        self.assertEqual(packet.format_version, "wow_packet_v0.2")
        self.assertEqual(packet.author_id, "w0202")
        self.assertEqual(packet.packet_spec_version, "v0.2")
        self.assertEqual(packet.wow_count, 3)
        self.assertEqual(packet.scoreable_count, 1)
        self.assertEqual(packet.trackable_count, 1)
        self.assertEqual(packet.candidate_count, 1)
        self.assertEqual(packet.raw_packet_json["author_id"], "w0202")
        self.assertEqual(packet.wow_items_json[1]["wow_type"], "scoreable_signal")

        response = self.client.get("/investors/w0202/wows/wow-w0202-2026-06-29.html")
        self.assertNotContains(response, "Packet Summary")
        self.assertNotContains(response, "Protocol WoW Items")
        self.assertContains(response, "Agent Suggested WoW Signals")
        self.assertContains(response, "scoreable_signal")
        self.assertContains(response, "trackable_wow")
        self.assertContains(response, "candidate_wow")
        self.assertContains(response, "packet_spec_version")
        self.assertContains(response, "scoreable_count")

    def test_structured_wow_packet_requires_type_specific_fields(self):
        body = self.structured_wow_packet_body().replace(
            "trackable_status: active_trackable",
            "trackable_status:",
        )
        raw = self.raw_email(sender="structured@example.com", subject="Daily WoW Packet - 2026-06-29 - Structured Agent", body=body)

        with self.assertRaisesMessage(ParseError, "trackable_wow"):
            parse_wow(raw)

    def test_structured_wow_packet_rejects_removed_broad_context_type(self):
        removed_type = "context" + "_note"
        body = self.structured_wow_packet_body().replace(
            "wow_type: candidate_wow",
            f"wow_type: {removed_type}",
            1,
        )
        raw = self.raw_email(sender="structured@example.com", subject="Daily WoW Packet - 2026-06-29 - Structured Agent", body=body)

        with self.assertRaisesMessage(ParseError, f"invalid wow_type: {removed_type}"):
            parse_wow(raw)

    def test_structured_wow_packet_requires_scoreable_resolution_fields(self):
        body = self.structured_wow_packet_body().replace(
            "resolution_source: hyperscaler earnings transcripts",
            "resolution_source:",
        )
        raw = self.raw_email(sender="structured@example.com", subject="Daily WoW Packet - 2026-06-29 - Structured Agent", body=body)

        with self.assertRaisesMessage(ParseError, "scoreable_signal"):
            parse_wow(raw)

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
                "closest_rejected_wow: WOW-2026-06-29-002",
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
        self.assertEqual(parsed.closest_rejected_idea, "WOW-2026-06-29-002")
        self.assertEqual(parsed.why_pass, "The signal was interesting but not concrete enough today.")
        self.assertEqual(parsed.missing_evidence, "Confirmed backlog growth or named customer commentary.")

    def test_wow_packet_parser_requires_closest_rejected_wow_to_match_suggested_wow(self):
        body = self.wow_packet_body(selected="none").replace(
            "closest_rejected_wow: WOW-2026-06-29-002",
            "closest_rejected_wow: GPU rental price weakness could signal supply normalization.",
        )
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=body)

        with self.assertRaisesMessage(ParseError, "closest_rejected_wow must match one of today's suggested WoW IDs"):
            parse_wow(raw)

    def test_wow_packet_parser_accepts_reason_for_pass_field(self):
        body = self.wow_packet_body(selected="none").replace(
            "why_pass: The signal was interesting but not concrete enough today.",
            "reason_for_pass: The signal was interesting but not concrete enough today.",
        )
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=body)

        parsed = parse_wow(raw)

        self.assertEqual(parsed.selected_wow_id, "none")
        self.assertEqual(parsed.why_pass, "The signal was interesting but not concrete enough today.")

    def test_wow_packet_parser_requires_exactly_three_suggested_wows(self):
        body = (
            self.wow_packet_body().split("### Suggested WoW 3")[0]
            + "## 3. User Selection / Pass\nselected_wow_id: WOW-2026-06-29-001\nreason_for_selection: Focus."
        )
        raw = self.raw_email(subject="Daily WoW Packet - 2026-06-29 - Test Agent", body=body)

        with self.assertRaisesMessage(ParseError, "exactly 3 suggested WoW signals"):
            parse_wow(raw)

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
                self.assertIn("content_sha256_covers", manifest_payload)
                self.assertIn("content_sha256_covers", target_payload)
                self.assertEqual(manifest_payload["public_selected_wow_id"], "WOW-w0202-2026-06-29-001")
                self.assertEqual(manifest_payload["suggested_wows"][0]["public_wow_id"], "WOW-w0202-2026-06-29-001")
                self.assertEqual(manifest_payload["source_urls"], ["https://example.com/source"])
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

    def test_publish_radar_warms_cache_when_enabled(self):
        run_id = "00000000-0000-0000-0000-000000000029"
        raw = self.raw_email(sender="playinc@gmail.com", body="Market_date: 2026-07-03\nTitle: Warm Radar\nBody: Context")
        issue = create_radar_issue(raw, run_id=run_id)

        with TemporaryDirectory() as tmp:
            with override_settings(
                WKAP_PUBLIC_SITE_ROOT=Path(tmp),
                WKAP_LEDGER_REPO_PATH="",
                WKAP_SEND_RECEIPTS=False,
                WKAP_CLOUDFLARE_CACHE_PURGE_ENABLED=True,
                WKAP_CLOUDFLARE_ZONE_ID="zone-id",
                WKAP_CLOUDFLARE_API_TOKEN="token",
                WKAP_CACHE_WARMUP_ENABLED=True,
            ):
                with patch("publishing.services.purge_radar_cache") as purge_cache, patch("publishing.services.warm_radar_cache") as warm_cache:
                    publish_artifact("radar", issue.id, run_id=run_id)

        purge_cache.assert_called_once()
        self.assertEqual(str(purge_cache.call_args.args[0]), "2026-07-03")
        warm_cache.assert_called_once()
        self.assertEqual(str(warm_cache.call_args.args[0]), "2026-07-03")

    def test_purge_radar_cache_sends_archive_and_issue_urls_to_cloudflare(self):
        class PurgeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"success": true}'

            def getcode(self):
                return 200

        run_id = "00000000-0000-0000-0000-000000000034"
        with override_settings(WKAP_BASE_URL="https://wkap.ai", WKAP_CLOUDFLARE_ZONE_ID="zone-id", WKAP_CLOUDFLARE_API_TOKEN="token"):
            with patch("publishing.services.urllib.request.urlopen", return_value=PurgeResponse()) as urlopen:
                results = purge_radar_cache("2026-07-03", run_id=run_id)

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.cloudflare.com/client/v4/zones/zone-id/purge_cache")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            payload["files"],
            [
                "https://wkap.ai/radar/",
                "https://wkap.ai/radar/wkap-radar-feed-2026-07-03.html",
            ],
        )
        self.assertEqual([result["status_code"] for result in results], [200, 200])
        self.assertTrue(LedgerEvent.objects.filter(event_name="radar_cache_purge_succeeded", entity_type="radar").exists())

    def test_warm_radar_cache_uses_get_and_records_cf_headers(self):
        class WarmupResponse:
            headers = {
                "cf-cache-status": "MISS",
                "cache-control": "public, max-age=300",
                "content-length": "1234",
            }

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b"ok"

            def getcode(self):
                return 200

        run_id = "00000000-0000-0000-0000-000000000030"
        with override_settings(WKAP_BASE_URL="https://wkap.ai"):
            with patch("publishing.services.urllib.request.urlopen", side_effect=[WarmupResponse(), WarmupResponse()]) as urlopen:
                results = warm_radar_cache("2026-07-03", run_id=run_id)

        requested_urls = [call.args[0].full_url for call in urlopen.call_args_list]
        requested_methods = [call.args[0].get_method() for call in urlopen.call_args_list]
        self.assertEqual(
            requested_urls,
            [
                "https://wkap.ai/radar/",
                "https://wkap.ai/radar/wkap-radar-feed-2026-07-03.html",
            ],
        )
        self.assertEqual(requested_methods, ["GET", "GET"])
        self.assertEqual([result["cf_cache_status"] for result in results], ["MISS", "MISS"])
        self.assertTrue(LedgerEvent.objects.filter(event_name="radar_cache_warmup_succeeded", entity_type="radar").exists())

    def test_warm_radar_cache_cli_returns_header_details(self):
        output = StringIO()
        fake_results = [
            {
                "url": "https://wkap.ai/radar/wkap-radar-feed-2026-07-03.html",
                "method": "GET",
                "status_code": 200,
                "cf_cache_status": "HIT",
            },
        ]

        with patch("core.management.commands.wkap.warm_radar_cache", return_value=fake_results):
            with redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
                call_command("wkap", "--json", "warm-radar-cache", "--market-date", "2026-07-03")

        self.assertEqual(exit_context.exception.code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["market_date"], "2026-07-03")
        self.assertEqual(payload["details"]["results"][0]["cf_cache_status"], "HIT")

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
        issue_response = self.client.get("/radar/wkap-radar-feed-2026-06-29.html")

        self.assertContains(response, 'href="/radar/wkap-radar-feed-2026-06-29.html"')
        self.assertContains(response, "WKAP Radar Feed 2026-06-29")
        self.assertIn("public", response.headers["Cache-Control"])
        self.assertIn("max-age=300", response.headers["Cache-Control"])
        self.assertIn("public", issue_response.headers["Cache-Control"])
        self.assertIn("max-age=300", issue_response.headers["Cache-Control"])

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
        self.assertContains(home_response, 'data-field="entry_count"')
        self.assertNotContains(home_response, 'data-field="submission_count"')
        self.assertContains(index_response, expected_href)
        self.assertContains(index_response, expected_label)
        self.assertContains(index_response, 'data-field="entry_count"')
        self.assertNotContains(index_response, 'data-field="submission_count"')

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
        self.assertContains(archive_response, 'data-field="entry_count"')
        self.assertNotContains(archive_response, 'data-field="submission_count"')

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

    def test_home_shows_daily_wow_training_coming_soon(self):
        home_response = self.client.get("/")
        setup_response = self.client.get("/submit-to-wkap-ledger.html")

        self.assertNotContains(home_response, 'href="/submit-to-wkap-ledger.html"')
        self.assertContains(home_response, "Build Your AI-Native")
        self.assertContains(home_response, "Investor Loop")
        self.assertContains(home_response, "daily investment research")
        self.assertContains(home_response, "feedback loop for you and your agent")
        self.assertContains(home_response, "WoW = Worth Watching Workout")
        self.assertContains(home_response, "Your agent logs what you read, skip, select, publish, and revisit")
        self.assertContains(home_response, "turning daily research into memory it can use")
        self.assertContains(home_response, "Your public WoW Ledger builds your investor record")
        self.assertContains(home_response, "Your private WoW loop sharpens your judgment over time")
        self.assertContains(home_response, 'aria-label="Daily WoW Training coming soon"')
        self.assertContains(home_response, 'class="coming-soon-badge"')
        self.assertContains(home_response, ">Coming soon<")
        self.assertNotContains(home_response, "Daily WoW Training is being polished for launch")
        self.assertContains(home_response, '<button class="button-link primary button-link-disabled" type="button" disabled', html=True)
        self.assertContains(home_response, "Start Daily WoW Training")
        self.assertContains(setup_response, "Start Daily WoW Training")
        self.assertContains(setup_response, "Set up the feedback loop for you and your agent")
        self.assertContains(setup_response, "WKAP turns daily investment research into a simple training loop")
        self.assertContains(setup_response, "brings you three Worth Watching signals")
        self.assertContains(setup_response, "Daily WoW Packet")
        self.assertContains(setup_response, "ledger@wkap.ai")
        self.assertContains(setup_response, "Private WoW Loop")
        self.assertContains(setup_response, "drafts, no-reply days, skipped ideas, selected WoWs, revisits")
        self.assertContains(setup_response, "Public WoW Ledger")
        self.assertContains(setup_response, "published Daily WoW Packets, public and agent-readable")
        self.assertContains(setup_response, "Copy &amp; Paste This Agent Prompt")
        self.assertContains(setup_response, "Set up WKAP WoW for me.")
        self.assertContains(setup_response, "Install WKAP WoW Skill as a durable skill")
        self.assertContains(setup_response, "Use this universal skill as the source of truth")
        self.assertContains(setup_response, "If you are Codex, install this Codex-native skill")
        self.assertContains(setup_response, "verify the install by checking for a local wkap-wow/SKILL.md file")
        self.assertContains(setup_response, "Tell me whether the install is verified")
        self.assertNotContains(setup_response, "Read and follow:")
        self.assertContains(setup_response, "adapt the universal WKAP WoW Skill to your native format and install it")
        self.assertContains(setup_response, "Follow the skill defaults for my Private WoW Journal")
        self.assertContains(setup_response, "tell me where it is stored")
        self.assertNotContains(setup_response, "Store my private WoW Journal in agent memory or ask me for a local file path")
        self.assertContains(setup_response, "When I do daily investor research in an agent-accessible browser")
        self.assertNotContains(setup_response, "Connect your sources")
        self.assertContains(setup_response, "Based on my behavior pattern, infer when I usually finish most of my daily market investment research")
        self.assertContains(setup_response, "set the Daily WoW Packet send time after that")
        self.assertContains(setup_response, "If you cannot infer it, ask me")
        self.assertContains(setup_response, "Run the daily workflow exactly as the installed WKAP WoW Skill specifies")
        self.assertNotContains(setup_response, "existing WoW signal status update")
        self.assertNotContains(setup_response, "Once per US market day, suggest exactly 3 WoW signals")
        self.assertNotContains(setup_response, "ask for my reason_for_selection")
        self.assertNotContains(setup_response, "ask for reason_for_pass")
        self.assertNotContains(setup_response, "Do not ask for a second approval")
        self.assertNotContains(setup_response, "Schedule it once per market day")
        self.assertContains(setup_response, "/skills/wkap-wow-codex/SKILL.md")
        self.assertNotContains(setup_response, "Fallback Agent Setup Prompt")
        self.assertNotContains(setup_response, 'data-agent-prompt="wkap-investor-log"')
        self.assertContains(setup_response, 'data-agent-install-prompt="wkap-wow"')
        self.assertContains(setup_response, 'data-copy-prompt')
        self.assertContains(setup_response, 'aria-label="Copy WKAP agent setup prompt"')
        self.assertContains(setup_response, "<span>Copy</span>")
        self.assertNotContains(setup_response, "skill install")
        self.assertContains(setup_response, "wow_packet_spec_latest_url")
        self.assertContains(setup_response, "wow_crm_spec_latest_url")
        self.assertContains(setup_response, "wow_intake_flow_latest_url")
        self.assertContains(setup_response, "daily_wow_state_schema_latest_url")
        self.assertContains(setup_response, "wkap_wow_skill_latest_url")
        self.assertContains(setup_response, "https://wkap.ai/specs/wow-packet-latest.md")
        self.assertContains(setup_response, "https://wkap.ai/skills/wkap-wow-skill-latest.md")
        self.assertContains(setup_response, "wkap_wow_codex_skill_url")
        self.assertContains(setup_response, "private_journal_required")
        self.assertContains(setup_response, "public_submission_requires_completed_daily_choice")
        self.assertContains(setup_response, "user_decision_completes_packet")
        self.assertContains(setup_response, "required_wow_options")
        self.assertContains(setup_response, "current_submission_format")
        self.assertContains(setup_response, "protocol_reference_version")
        self.assertNotContains(setup_response, "Before preparing any Daily WoW Packet, read:")
        self.assertNotContains(setup_response, "```yaml")
        self.assertNotContains(setup_response, "wow_type: trackable_wow")

    def test_wow_protocol_markdown_routes_are_public_and_redirect_latest(self):
        packet = self.client.get("/specs/wow-packet-v0.2.md")
        crm = self.client.get("/specs/wow-crm-v0.2.json")
        intake = self.client.get("/specs/wow-intake-flow-v0.2.json")
        daily_state = self.client.get("/specs/daily-wow-state-v0.2.schema.json")
        skill = self.client.get("/skills/wkap-wow-skill-v0.2.md")
        codex_skill = self.client.get("/skills/wkap-wow-codex/SKILL.md")
        packet_latest = self.client.get("/specs/wow-packet-latest.md")
        crm_latest = self.client.get("/specs/wow-crm-latest.json")
        intake_latest = self.client.get("/specs/wow-intake-flow-latest.json")
        daily_state_latest = self.client.get("/specs/daily-wow-state-latest.schema.json")
        skill_latest = self.client.get("/skills/wkap-wow-skill-latest.md")

        self.assertEqual(packet.status_code, 200)
        self.assertEqual(crm.status_code, 200)
        self.assertEqual(intake.status_code, 200)
        self.assertEqual(daily_state.status_code, 200)
        self.assertEqual(skill.status_code, 200)
        self.assertEqual(codex_skill.status_code, 200)
        self.assertEqual(packet.headers["Content-Type"], "text/markdown; charset=utf-8")
        self.assertEqual(crm.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(intake.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(daily_state.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(skill.headers["Content-Type"], "text/markdown; charset=utf-8")
        self.assertEqual(codex_skill.headers["Content-Type"], "text/markdown; charset=utf-8")
        self.assertEqual(json.loads(crm.content)["selection_rules"]["daily_options_required"], 3)
        self.assertIn("awaiting_user_choice", json.loads(intake.content)["states"])
        self.assertIn("wow_options", json.loads(daily_state.content)["required"])
        self.assertContains(codex_skill, "name: wkap-wow")
        self.assertContains(codex_skill, "Private WoW Journal")
        self.assertContains(codex_skill, "status_update")
        self.assertEqual(packet_latest.status_code, 302)
        self.assertEqual(packet_latest.headers["Location"], "/specs/wow-packet-v0.2.md")
        self.assertEqual(crm_latest.status_code, 302)
        self.assertEqual(crm_latest.headers["Location"], "/specs/wow-crm-v0.2.json")
        self.assertEqual(intake_latest.status_code, 302)
        self.assertEqual(intake_latest.headers["Location"], "/specs/wow-intake-flow-v0.2.json")
        self.assertEqual(daily_state_latest.status_code, 302)
        self.assertEqual(daily_state_latest.headers["Location"], "/specs/daily-wow-state-v0.2.schema.json")
        self.assertEqual(skill_latest.status_code, 302)
        self.assertEqual(skill_latest.headers["Location"], "/skills/wkap-wow-skill-v0.2.md")

    def test_wow_protocol_generated_specs_are_in_sync(self):
        out = StringIO()

        call_command("build_wow_protocol", "--check", stdout=out)

        self.assertIn("WKAP WoW protocol checked", out.getvalue())

    def test_wow_protocol_crm_json_matches_backend_lifecycle_rules(self):
        from ledger.wow_lifecycle_rules import ALLOWED_STATUS_TRANSITIONS, UPDATE_TYPE_TO_NEW_STATUS, VALID_WOW_TYPES

        response = self.client.get("/specs/wow-crm-v0.2.json")
        crm = json.loads(response.content)

        self.assertEqual(set(crm["wow_types"]), VALID_WOW_TYPES)
        self.assertEqual(
            {key: {status: set(values) for status, values in transitions.items()} for key, transitions in crm["allowed_status_transitions"].items()},
            ALLOWED_STATUS_TRANSITIONS,
        )
        self.assertEqual(
            {key: set(values) for key, values in crm["update_type_to_new_status"].items()},
            UPDATE_TYPE_TO_NEW_STATUS,
        )
        display = crm["selection_rules"]["daily_suggestion_display"]
        self.assertEqual(display["user_chooses_by"], "option_number")
        self.assertEqual(display["wow_id_visibility"], "internal_only_by_default")
        self.assertIn("visible_type_label", display["required_visible_fields"])
        self.assertEqual(display["type_labels"]["scoreable_signal"], "Scoreable")

    def test_wow_intake_and_state_schema_require_visible_daily_options(self):
        intake = json.loads(self.client.get("/specs/wow-intake-flow-v0.2.json").content)
        daily_state = json.loads(self.client.get("/specs/daily-wow-state-v0.2.schema.json").content)

        display_contract = intake["states"]["draft_options"]["display_contract"]
        self.assertTrue(display_contract["wow_id_hidden_by_default"])
        self.assertTrue(display_contract["user_must_not_be_required_to_choose_by_wow_id"])
        self.assertIn("user_is_required_to_choose_by_wow_id", display_contract["invalid_if"])

        required = daily_state["properties"]["wow_options"]["items"]["required"]
        for field in ["wow_id", "wow_type", "visible_type_label", "plain_english_title", "why_worth_watching"]:
            self.assertIn(field, required)

    def test_wow_protocol_markdown_has_no_removed_or_ambiguous_status_values(self):
        packet = self.client.get("/specs/wow-packet-v0.2.md").content.decode()
        skill = self.client.get("/skills/wkap-wow-skill-v0.2.md").content.decode()
        combined = packet + "\n" + skill

        self.assertNotIn("context" + "_note", combined)
        self.assertNotIn("active_context", combined)
        self.assertNotIn("context_update", combined)
        self.assertNotRegex(combined, r"(?m)^\s*-\s*promoted\s*$")
        self.assertNotRegex(combined, r"(?m)^\s*-\s*pending\s*$")

    def test_wow_packet_protocol_markdown_contains_agent_contract(self):
        response = self.client.get("/specs/wow-packet-v0.2.md")
        body = response.content.decode()

        self.assertIn("# WKAP WoW Packet Spec v0.2", body)
        self.assertNotIn("canonical_hash", body)
        self.assertIn("author_id", body)
        self.assertNotIn("contributor_id", body)
        for wow_type in ["candidate_wow", "trackable_wow", "scoreable_signal", "thesis_wow", "status_update"]:
            self.assertIn(wow_type, body)
        self.assertNotIn("context" + "_note", body)
        self.assertIn("status_update", body)
        self.assertIn("scoreable: false", body)
        self.assertIn("append-only", body)
        self.assertIn("voided", body)
        self.assertIn("invalid_test", body)
        self.assertIn("unresolved", body)
        self.assertIn("unresolved_grace_window_days: 30", body)
        self.assertIn("signal_status_record_mapping", body)
        self.assertIn("invalid_test` is a discipline penalty, not a mulligan", body)
        self.assertIn("voided` is calibration-neutral but visible", body)
        self.assertIn("unresolved` is pending-past-due, not accuracy-neutral", body)
        self.assertIn("parent_wow_id", body)
        self.assertIn("root_wow_id", body)
        self.assertIn("root_wow_id must equal wow_id", body)
        self.assertNotIn("lineage_depth:", body)
        self.assertNotIn("transition_reason:", body)
        self.assertIn("target_wow_id", body)
        self.assertIn("target_root_wow_id", body)
        self.assertIn("A `status_update` is not a lineage node.", body)
        self.assertIn("private journal lineage is context, not public proof", body.lower())
        self.assertIn("public lineage proof weight starts at the earliest publicly ledgered ancestor", body.lower())
        self.assertIn("Receipt is useful confirmation, not the sole source of truth", body)
        self.assertIn("Future packet formats will change", body)
        self.assertIn("version-aware", body)
        self.assertIn("https://wkap.ai/skills/wkap-wow-skill-latest.md", body)
        self.assertIn("https://wkap.ai/specs/wow-crm-latest.json", body)
        self.assertIn("https://wkap.ai/specs/wow-intake-flow-latest.json", body)
        self.assertIn("https://wkap.ai/specs/daily-wow-state-latest.schema.json", body)
        self.assertIn("strict agent execution contract", body)
        self.assertIn("show the mismatch to the user", body)
        self.assertIn("spec_mismatch_detected", body)
        self.assertIn("reading_log_max_items: 10", body)
        self.assertIn("suggested_wow_count: 3", body)
        self.assertIn("Daily Suggestion Display Contract", body)
        self.assertIn("visible_type_label", body)
        self.assertIn("plain_english_title", body)
        self.assertIn("why_worth_watching", body)
        self.assertIn("Pick one WoW: 1, 2, 3, or pass.", body)
        self.assertIn("SHOULD NOT show `wow_id` in the default user-facing choice prompt", body)
        self.assertIn("reason_for_pass", body)
        self.assertIn("User selection/pass plus the required reason completes the Daily WoW Packet", body)
        self.assertIn("The agent must remove or summarize private/confidential material", body)
        self.assertIn("tracking_inputs", body)
        self.assertIn("WoW Type Decision Rules", body)
        self.assertIn("candidate_to_scoreable", body)
        self.assertIn("Do not use `pending_scoreable` as the `new_status`", body)
        self.assertIn("signal_status: pending_scoreable", body)

    def test_wkap_wow_skill_markdown_contains_private_journal_contract(self):
        response = self.client.get("/skills/wkap-wow-skill-v0.2.md")
        body = response.content.decode()

        self.assertIn("# WKAP WoW Skill v0.2", body)
        self.assertNotIn("canonical_hash", body)
        self.assertIn("https://wkap.ai/specs/wow-packet-latest.md", body)
        self.assertIn("https://wkap.ai/specs/wow-crm-latest.json", body)
        self.assertIn("https://wkap.ai/specs/wow-intake-flow-latest.json", body)
        self.assertIn("https://wkap.ai/specs/daily-wow-state-latest.schema.json", body)
        self.assertIn("machine-readable CRM, intake, and daily state JSON specs are the execution contract", body)
        self.assertIn("show the mismatch to the user", body)
        self.assertIn("spec_mismatch_detected", body)
        self.assertIn("Strict Intake Program Rule", body)
        self.assertIn("behave like an intake program", body)
        self.assertIn("normalize the reply into the Daily WoW State object", body)
        self.assertIn("Do not invent required user fields", body)
        self.assertIn("The daily choice flow is fixed", body)
        self.assertIn("fetch the latest WoW Packet Spec daily", body)
        self.assertIn("refresh the spec at least every 30 days", body)
        self.assertIn("setup_mode: low_friction_defaults_first", body)
        self.assertIn("ask_user_only_when_blocked: true", body)
        self.assertIn("durable_private_journal_required: true", body)
        self.assertIn("agent_memory_cache_only: true", body)
        self.assertIn("The agent should not start with a long interview", body)
        self.assertIn("use a stable local draft identity", body)
        self.assertIn("infer from the user's behavior pattern", body)
        self.assertIn("agent-accessible browser activity", body)
        self.assertIn("default_packet_scope: one Daily WoW Packet for the current US market day", body)
        self.assertIn("weekly_review_requires_explicit_user_request: true", body)
        self.assertIn("The default WKAP WoW run is one Daily WoW Packet for the current US market day", body)
        self.assertIn("Do not summarize the user's past 7 days", body)
        self.assertIn("Suggest exactly 3 WoW signals for the user to choose from", body)
        self.assertIn("reason_for_pass", body)
        self.assertIn("The user selection/pass plus required reason completes the Daily WoW Packet", body)
        self.assertIn("Do not ask for a second confirmation", body)
        self.assertIn("Daily Suggestion Display Contract", body)
        self.assertIn("visible_type_label", body)
        self.assertIn("plain_english_title", body)
        self.assertIn("why_worth_watching", body)
        self.assertIn("Pick one WoW: 1, 2, 3, or pass.", body)
        self.assertIn("SHOULD NOT show `wow_id` in the default user-facing choice prompt", body)
        self.assertIn("user_is_required_to_choose_by_wow_id", body)
        self.assertIn("The agent must remove or summarize private/confidential material", body)
        self.assertIn("The agent must not decide that a completed daily choice should stay private", body)
        self.assertIn('A prose list of "top private WoWs" is not a valid WKAP WoW output by itself', body)
        self.assertIn("select WoW 1", body)
        self.assertIn("Do not block private setup on WKAP `author_id`", body)
        self.assertIn("Default completion flow is assumed", body)
        self.assertIn("The Private WoW Journal must be stored in durable user-owned storage", body)
        self.assertIn("If the agent has local filesystem access, it must use a local Markdown folder by default", body)
        self.assertIn("Create the folder and files if missing", body)
        self.assertIn("Agent memory may be used as a cache, but it must not be the only Private WoW Journal", body)
        self.assertIn("tell the user where the Private WoW Journal is stored", body)
        self.assertIn("Every prepared Daily WoW Packet must be saved to the Private WoW Journal", body)
        self.assertIn("Private journal drafts may be saved before completion", body)
        self.assertIn("Public submission requires a completed daily choice", body)
        self.assertIn("save the prepared packet privately and must not submit publicly", body)
        self.assertIn("private_status: user_no_reply", body)
        self.assertIn("submission_status: not_submitted", body)
        self.assertIn("Private lineage helps the agent", body)
        self.assertIn("private lineage as context, not public timing proof", body.lower())
        self.assertIn("prepare_status_update_items", body)
        self.assertIn("move_unresolved_to_voided_after_grace_window", body)
        self.assertIn("unresolved-to-voided", body)
        self.assertIn("WKAP receipt email", body)
        self.assertIn("WKAP public site / public ledger", body)
        self.assertIn("If no receipt exists but the packet is published on WKAP", body)
        self.assertIn("Lifecycle Sync Contract", body)
        self.assertIn("backend_ledger", body)
        self.assertIn("private_crm", body)
        self.assertIn("public_page", body)
        self.assertIn("A day is not publicly done until it appears on WKAP Ledger", body)
        self.assertIn("Agent CRM Operating Loop", body)
        self.assertIn("WoW Type Decision Rules", body)
        self.assertIn("Status Update Playbook", body)
        self.assertIn("candidate_to_trackable", body)
        self.assertIn("trackable_to_scoreable", body)
        self.assertIn("Do not use `pending_scoreable` as the `new_status`", body)
        self.assertIn("crm_record_minimum_fields", body)

    def test_codex_wkap_wow_skill_uses_low_friction_defaults(self):
        response = self.client.get("/skills/wkap-wow-codex/SKILL.md")
        body = response.content.decode()

        self.assertIn("Apply setup defaults first; do not start with a long interview", body)
        self.assertIn("https://wkap.ai/specs/wow-crm-latest.json", body)
        self.assertIn("https://wkap.ai/specs/wow-intake-flow-latest.json", body)
        self.assertIn("https://wkap.ai/specs/daily-wow-state-latest.schema.json", body)
        self.assertIn("show the mismatch to the user", body)
        self.assertIn("spec_mismatch_detected", body)
        self.assertIn("Strict Intake Program Rule", body)
        self.assertIn("behave like an intake program", body)
        self.assertIn("Selection/pass plus required fields completes the Daily WoW Packet", body)
        self.assertIn("C:\\Users\\ASUS\\Documents\\wkap\\WKAP WoW Journal", body)
        self.assertIn("If the journal folder or required files are missing, create them before the first prepared packet", body)
        self.assertIn("Codex Local Journal Layout", body)
        self.assertIn("Daily packets go in `daily\\YYYY-MM-DD.md`", body)
        self.assertIn("tell the user the journal path and whether the local files were created or already existed", body)
        self.assertIn("use a stable local draft identity and do not block setup", body)
        self.assertIn("infer the daily send time from the user's behavior pattern", body)
        self.assertIn("agent-accessible browser activity", body)
        self.assertIn("Default scope is one Daily WoW Packet for the current US market day", body)
        self.assertIn("Do not produce a past-7-day summary, weekly review, or general private research memo", body)
        self.assertIn("A prose list of top private WoWs is not enough", body)
        self.assertIn("Do not decide to keep a completed daily choice private", body)
        self.assertIn("Show exactly 3 WoW signal options", body)
        self.assertIn("Selection/pass plus reason completes the Daily WoW Packet", body)
        self.assertIn("Daily Suggestion Display Contract", body)
        self.assertIn("visible_type_label", body)
        self.assertIn("Pick one WoW: 1, 2, 3, or pass.", body)
        self.assertIn("do not show `wow_id` in the default user-facing choice prompt", body)
        self.assertIn("Before suggesting the 3 WoWs, inspect", body)
        self.assertIn("Ask the user only for information that is required and cannot be inferred or safely defaulted", body)
        self.assertIn("Lifecycle Sync Contract", body)
        self.assertIn("backend WKAP parse data plus `LedgerEvent` lifecycle logs", body)
        self.assertIn("local Private WoW Journal tracking files", body)
        self.assertIn("public WKAP WoW page and agent-readable facts", body)
        self.assertIn("WoW Type Decision Rules", body)
        self.assertIn("Agent CRM Operating Loop", body)
        self.assertIn("Do not use `pending_scoreable` as a `status_update.new_status`", body)

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
        self.assertContains(response, 'class="summary-strip wow-summary-strip"')
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
        summary_start = response.content.decode().index('class="summary-strip wow-summary-strip"')
        summary_end = response.content.decode().index("</dl>", summary_start)
        summary_html = response.content.decode()[summary_start:summary_end]
        self.assertNotIn("Raw email SHA256", summary_html)
        self.assertNotIn("Canonical URL", summary_html)
        self.assertNotIn("Packet ID", summary_html)
        self.assertNotIn("Selected WoW", summary_html)
        self.assertNotIn("WoW Items", summary_html)
        self.assertContains(response, "subject_line_display_name")
        self.assertContains(response, "WOW-w0202-2026-06-29-001")
        self.assertContains(response, "packet_selected_wow_id")
        self.assertContains(response, "content_sha256_covers")
        self.assertContains(response, "tickers_json")
        self.assertContains(response, "themes_json")
        self.assertContains(response, "source_urls_json")
        self.assertContains(response, "evidence_to_watch_json")
        self.assertContains(response, 'data-field="reason_for_pass"')
        self.assertContains(response, 'data-field="closest_rejected_wow"')
        self.assertContains(response, 'data-field="missing_evidence"')
        self.assertContains(response, "N/A - Not Applicable", count=3)
        self.assertContains(response, 'data-selection-status="selected"')
        self.assertContains(response, 'data-field="selection_status"')
        self.assertContains(response, 'data-field="source_url"')
        self.assertContains(response, 'data-field="evidence_to_watch"')
        self.assertContains(response, "selected_theme")
        self.assertContains(response, "source_urls")
        self.assertNotContains(response, "private-wow@example.com")

    def test_wow_lifecycle_status_updates_are_logged_validated_and_displayed(self):
        run_id = "00000000-0000-0000-0000-000000000099"
        raw = self.raw_email(
            sender="lifecycle-wow@example.com",
            subject="Daily WoW Packet - 2026-07-01 - Lifecycle Agent",
            body=self.structured_status_update_packet_body(),
        )

        submission = create_wow_submission(raw, run_id=run_id)

        item_events = LedgerEvent.objects.filter(
            entity_type="wow",
            entity_id=str(submission.id),
            event_name="wow_lifecycle_item_logged",
        )
        status_events = LedgerEvent.objects.filter(
            entity_type="wow",
            entity_id=str(submission.id),
            event_name="wow_lifecycle_status_update_logged",
        )
        self.assertEqual(item_events.count(), 2)
        self.assertEqual(status_events.count(), 1)
        status_details = status_events.get().details
        self.assertEqual(status_details["wow_id"], "WOW-w0202-2026-07-01-001")
        self.assertEqual(status_details["target_wow_type"], "trackable_wow")
        self.assertEqual(status_details["target_wow_id"], "WOW-w0202-2026-06-29-001")
        self.assertEqual(status_details["target_root_wow_id"], "WOW-w0202-2026-06-29-001")
        self.assertEqual(status_details["update_type"], "promotion")
        self.assertEqual(status_details["previous_status"], "active_trackable")
        self.assertEqual(status_details["new_status"], "promoted_scoreable")

        submission.github_file_url = "https://github.com/wkapai/wkap-ledger/blob/main/investors/w0202/wows/wow-w0202-2026-07-01.html"
        submission.github_commit_sha = "a" * 40
        submission.manifest_url = "https://github.com/wkapai/wkap-ledger/blob/main/manifests/wow-1.json"
        submission.ots_status = "queued"
        submission.raw_email_github_url = "https://github.com/wkapai/wkap-ledger/blob/main/raw-emails/wow-packets/wow-packet-w0202-2026-07-01.txt"
        submission.raw_email_commit_sha = "a" * 40
        submission.save()
        generate_wow_html(submission, run_id=run_id)
        self.assertEqual(validate_ledger("wow", submission.id), [])

        status_events.delete()
        self.assertIn("lifecycle LedgerEvent missing for WOW-w0202-2026-07-01-001", validate_ledger("wow", submission.id))

        # Restore the evidence event so page checks below represent the healthy path.
        create_wow_submission(raw, run_id=run_id)
        submission.refresh_from_db()
        submission.canonical_url = "https://wkap.ai/investors/w0202/wows/wow-w0202-2026-07-01.html"
        submission.content_sha256 = "d" * 64
        submission.save()

        response = self.client.get("/investors/w0202/wows/wow-w0202-2026-07-01.html")
        self.assertContains(response, "<h1>AI power bottleneck lifecycle update</h1>", html=True)
        self.assertContains(response, 'data-agent-wow-type-fields="status_update"')
        self.assertContains(response, 'data-agent-wow-type-fields="scoreable_signal"')
        self.assertContains(response, 'data-agent-wow-type-fields="candidate_wow"')
        self.assertContains(response, 'data-field="target_wow_id"')
        self.assertContains(response, 'data-field="target_wow_type"')
        self.assertContains(response, 'data-field="target_root_wow_id"')
        self.assertContains(response, 'data-field="previous_status"')
        self.assertContains(response, 'data-field="new_status"')
        self.assertContains(response, 'data-field="invalidate_test"')
        self.assertContains(response, 'data-field="resolve_by"')
        self.assertContains(response, 'data-field="resolution_source"')
        self.assertContains(response, 'data-field="observation"')
        self.assertContains(response, "Existing WoW Signal Status Update")
        self.assertContains(response, 'data-agent-lifecycle="status_updates"')
        self.assertContains(response, 'data-target-wow-id="WOW-w0202-2026-06-29-001"')
        self.assertContains(response, 'data-update-type="promotion"')
        self.assertContains(response, "active_trackable")
        self.assertContains(response, "promoted_scoreable")
        self.assertContains(response, "lifecycle_events_json")
        self.assertContains(response, "current_wow_state_json")
        self.assertContains(response, "status_updates_json")
        self.assertContains(response, "target_root_wow_id")
        self.assertContains(response, "WOW-w0202-2026-06-29-001")
        self.assertNotContains(response, "Packet Summary")
        self.assertNotContains(response, "Protocol WoW Items")

    def test_malformed_status_update_is_rejected_before_publish(self):
        body = self.structured_status_update_packet_body().replace(
            "      target_root_wow_id: WOW-w0202-2026-06-29-001\n",
            "",
            1,
        )
        raw = self.raw_email(
            sender="bad-lifecycle@example.com",
            subject="Daily WoW Packet - 2026-07-01 - Bad Lifecycle Agent",
            body=body,
        )

        with self.assertRaises(ParseError) as exc:
            parse_wow(raw)

        self.assertIn("status_update WOW-w0202-2026-07-01-001 missing required fields: target_root_wow_id", str(exc.exception))

    def test_status_update_requires_evidence_summary_before_publish(self):
        body = self.structured_status_update_packet_body().replace(
            "      evidence_summary: A named utility backlog item can now be checked against future earnings commentary.\n",
            "",
            1,
        )
        raw = self.raw_email(
            sender="missing-evidence-summary@example.com",
            subject="Daily WoW Packet - 2026-07-01 - Bad Lifecycle Agent",
            body=body,
        )

        with self.assertRaises(ParseError) as exc:
            parse_wow(raw)

        self.assertIn("status_update WOW-w0202-2026-07-01-001 missing required fields: evidence_summary", str(exc.exception))

    def test_invalid_status_transition_is_rejected_before_publish(self):
        body = self.structured_status_update_packet_body().replace(
            "      new_status: promoted_scoreable",
            "      new_status: resolved_correct",
            1,
        )
        raw = self.raw_email(
            sender="bad-transition@example.com",
            subject="Daily WoW Packet - 2026-07-01 - Bad Transition Agent",
            body=body,
        )

        with self.assertRaises(ParseError) as exc:
            parse_wow(raw)

        self.assertIn("trackable_wow cannot transition from active_trackable to resolved_correct", str(exc.exception))

    def test_one_investor_lifecycle_crm_covers_all_allowed_status_transitions(self):
        investor_sender = "one-crm-investor@example.com"
        created_packets = []
        update_index = 1
        for target_wow_type, previous_map in ALLOWED_STATUS_TRANSITIONS.items():
            for previous_status, new_statuses in previous_map.items():
                for new_status in sorted(new_statuses):
                    market_date = (datetime(2026, 8, 1).date() + timedelta(days=update_index - 1)).isoformat()
                    body = self.structured_lifecycle_packet_body(
                        market_date=market_date,
                        update_index=update_index,
                        target_wow_type=target_wow_type,
                        previous_status=previous_status,
                        new_status=new_status,
                        update_type=self._update_type_for_new_status(new_status),
                    )
                    raw = self.raw_email(
                        sender=investor_sender,
                        subject=f"Daily WoW Packet - {market_date} - Lifecycle CRM Agent",
                        body=body,
                    )
                    packet = create_wow_submission(raw, run_id=f"00000000-0000-0000-0000-{update_index:012d}")
                    packet._expected_transition = {
                        "target_wow_type": target_wow_type,
                        "target_wow_id": f"WOW-w0202-2026-06-29-{update_index:03d}",
                        "target_root_wow_id": f"WOW-w0202-2026-06-29-{update_index:03d}",
                        "update_type": self._update_type_for_new_status(new_status),
                        "previous_status": previous_status,
                        "new_status": new_status,
                    }
                    created_packets.append(packet)
                    update_index += 1

        investor_ids = {packet.investor.investor_id for packet in created_packets}
        self.assertEqual(len(investor_ids), 1)
        expected_transition_count = sum(
            len(new_statuses)
            for previous_map in ALLOWED_STATUS_TRANSITIONS.values()
            for new_statuses in previous_map.values()
        )
        self.assertEqual(len(created_packets), expected_transition_count)

        status_events = LedgerEvent.objects.filter(event_name="wow_lifecycle_status_update_logged", entity_type="wow")
        self.assertEqual(status_events.count(), len(created_packets))
        for event in status_events:
            self.assertIn(event.details["new_status"], ALLOWED_STATUS_TRANSITIONS[event.details["target_wow_type"]][event.details["previous_status"]])

        for packet in created_packets:
            expected = packet._expected_transition
            response = self.client.get(f"/investors/{packet.investor.investor_id}/wows/wow-{packet.investor.investor_id}-{packet.market_date}.html")
            self.assertEqual(response.status_code, 200)
            self._assert_outside_agent_can_reconstruct_transition(response, expected)

    def _update_type_for_new_status(self, new_status: str) -> str:
        if new_status in {"promoted_trackable", "promoted_scoreable", "pending_scoreable"}:
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
        if new_status in {"supported", "weakened", "retired"}:
            return "thesis_update"
        return "other"

    def _assert_outside_agent_can_reconstruct_transition(self, response, expected: dict[str, str]) -> None:
        content = response.content.decode()
        self.assertContains(response, 'data-agent-wow-type-fields="status_update"')
        self.assertContains(response, 'data-agent-lifecycle="status_updates"')
        self.assertContains(response, 'data-field="target_wow_type"')
        self.assertContains(response, 'data-field="target_wow_id"')
        self.assertContains(response, 'data-field="target_root_wow_id"')
        self.assertContains(response, 'data-field="update_type"')
        self.assertContains(response, 'data-field="previous_status"')
        self.assertContains(response, 'data-field="new_status"')
        self.assertContains(response, 'data-field="update_summary"')
        self.assertContains(response, 'data-field="evidence_summary"')
        self.assertContains(response, 'data-field="lifecycle_events_json"')
        self.assertContains(response, 'data-field="current_wow_state_json"')
        self.assertContains(response, 'data-field="status_updates_json"')
        for field, value in expected.items():
            self.assertIn(value, content)
        self.assertIn(f'data-target-wow-type="{expected["target_wow_type"]}"', content)
        self.assertIn(f'data-target-wow-id="{expected["target_wow_id"]}"', content)
        self.assertIn(f'data-target-root-wow-id="{expected["target_root_wow_id"]}"', content)
        self.assertIn(f'data-update-type="{expected["update_type"]}"', content)
        self.assertIn(f'data-previous-status="{expected["previous_status"]}"', content)
        self.assertIn(f'data-new-status="{expected["new_status"]}"', content)
        self.assertContains(response, 'data-field="resolution_source_used"')
        if expected["new_status"] == "promoted_scoreable":
            self.assertContains(response, 'data-agent-wow-type-fields="scoreable_signal"')
            self.assertIn(f'<dd data-field="parent_wow_id">{expected["target_wow_id"]}</dd>', content)
            self.assertIn(f'<dd data-field="root_wow_id">{expected["target_root_wow_id"]}</dd>', content)
            self.assertIn('<dd data-field="signal_status">pending_scoreable</dd>', content)
        if expected["new_status"] == "promoted_trackable":
            self.assertContains(response, 'data-agent-wow-type-fields="trackable_wow"')
            self.assertIn(f'<dd data-field="parent_wow_id">{expected["target_wow_id"]}</dd>', content)
            self.assertIn(f'<dd data-field="root_wow_id">{expected["target_root_wow_id"]}</dd>', content)
            self.assertIn('<dd data-field="trackable_status">active_trackable</dd>', content)

    def test_outside_agent_reconstructs_one_investor_wow_lifecycle_from_public_pages(self):
        sender = "graph-crm-investor@example.com"
        scenarios = [
            ("2026-06-29", self.structured_wow_packet_body()),
            ("2026-06-30", self.structured_thesis_context_packet_body()),
            (
                "2026-07-01",
                self.structured_target_update_packet_body(
                    market_date="2026-07-01",
                    target_wow_id="WOW-w0202-2026-06-29-003",
                    target_wow_type="candidate_wow",
                    previous_status="active_candidate",
                    new_status="promoted_trackable",
                    update_type="promotion",
                ),
            ),
            (
                "2026-07-02",
                self.structured_target_update_packet_body(
                    market_date="2026-07-02",
                    target_wow_id="WOW-w0202-2026-06-29-001",
                    target_wow_type="trackable_wow",
                    previous_status="active_trackable",
                    new_status="promoted_scoreable",
                    update_type="promotion",
                ),
            ),
            (
                "2026-07-03",
                self.structured_target_update_packet_body(
                    market_date="2026-07-03",
                    target_wow_id="WOW-w0202-2026-06-29-002",
                    target_wow_type="scoreable_signal",
                    previous_status="pending_scoreable",
                    new_status="resolved_correct",
                    update_type="resolution",
                ),
            ),
            (
                "2026-07-04",
                self.structured_target_update_packet_body(
                    market_date="2026-07-04",
                    target_wow_id="WOW-w0202-2026-06-30-001",
                    target_wow_type="thesis_wow",
                    previous_status="active_thesis",
                    new_status="supported",
                    update_type="thesis_update",
                ),
            ),
            (
                "2026-07-05",
                self.structured_target_update_packet_body(
                    market_date="2026-07-05",
                    target_wow_id="WOW-w0202-2026-06-30-001",
                    target_wow_type="thesis_wow",
                    previous_status="supported",
                    new_status="retired",
                    update_type="thesis_update",
                ),
            ),
        ]
        packets = []
        for index, (market_date, body) in enumerate(scenarios, start=1):
            raw = self.raw_email(
                sender=sender,
                subject=f"Daily WoW Packet - {market_date} - Graph CRM Agent",
                body=body,
            )
            packets.append(create_wow_submission(raw, run_id=f"00000000-0000-0000-0000-99{index:010d}"))

        investor_ids = {packet.investor.investor_id for packet in packets}
        self.assertEqual(investor_ids, {"w0202"})

        reconstructed: dict[str, dict[str, str]] = {}
        transitions = []
        for packet in sorted(packets, key=lambda item: item.market_date):
            response = self.client.get(f"/investors/{packet.investor.investor_id}/wows/wow-{packet.investor.investor_id}-{packet.market_date}.html")
            self.assertEqual(response.status_code, 200)
            wow_items = self._agent_fact_json(response, "wow_items_json")
            status_updates = self._agent_fact_json(response, "status_updates_json")

            for item in wow_items:
                wow_type = item.get("wow_type")
                if wow_type == "status_update":
                    continue
                wow_id = item["wow_id"]
                reconstructed[wow_id] = {
                    "wow_type": wow_type,
                    "root_wow_id": item.get("root_wow_id") or wow_id,
                    "current_status": self._initial_status(item),
                    "last_public_packet": packet.canonical_url,
                }

            for update in status_updates:
                target_id = update["target_wow_id"]
                self.assertIn(target_id, reconstructed, f"outside agent cannot find target {target_id}")
                self.assertEqual(update["target_wow_type"], reconstructed[target_id]["wow_type"])
                self.assertEqual(update["target_root_wow_id"], reconstructed[target_id]["root_wow_id"])
                self.assertEqual(update["previous_status"], reconstructed[target_id]["current_status"])
                self.assertTrue(update["update_summary"])
                self.assertTrue(update["evidence_summary"])
                reconstructed[target_id]["current_status"] = update["new_status"]
                reconstructed[target_id]["last_public_packet"] = packet.canonical_url
                transitions.append(update)

        self.assertEqual(reconstructed["WOW-w0202-2026-06-29-003"]["current_status"], "promoted_trackable")
        self.assertEqual(reconstructed["WOW-w0202-2026-06-29-001"]["current_status"], "promoted_scoreable")
        self.assertEqual(reconstructed["WOW-w0202-2026-06-29-002"]["current_status"], "resolved_correct")
        self.assertEqual(reconstructed["WOW-w0202-2026-06-30-001"]["current_status"], "retired")
        self.assertEqual(len(transitions), 5)

        lifecycle_events = LedgerEvent.objects.filter(
            event_name="wow_lifecycle_status_update_logged",
            entity_type="wow",
        )
        self.assertEqual(lifecycle_events.count(), len(transitions))
        for transition in transitions:
            self.assertTrue(
                lifecycle_events.filter(details__wow_id=transition["wow_id"], details__target_wow_id=transition["target_wow_id"]).exists()
            )

    def _agent_fact_json(self, response, field_name: str):
        content = response.content.decode()
        match = re.search(
            rf'<dd data-field="{re.escape(field_name)}">(.*?)</dd>',
            content,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match, f"missing agent fact {field_name}")
        return json.loads(unescape(match.group(1)))

    def _initial_status(self, item: dict) -> str:
        wow_type = item.get("wow_type")
        if wow_type == "candidate_wow":
            return str(item.get("candidate_status") or "active_candidate")
        if wow_type == "trackable_wow":
            return str(item.get("trackable_status") or "active_trackable")
        if wow_type == "scoreable_signal":
            return str(item.get("signal_status") or "pending_scoreable")
        if wow_type == "thesis_wow":
            return str(item.get("thesis_status") or "active_thesis")
        return "unknown"

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
