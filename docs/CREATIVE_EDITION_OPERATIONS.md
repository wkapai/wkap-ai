# WKAP Creative Edition operations

`creative_edition_v1` adds a public creative journal to the existing weekday producer. It is not a new workflow and it never blocks the X Article or Radar Feed.

## Producer order

1. Research and publish the X Article and final cover through the existing producer.
2. Use the actual final `pbs.twimg.com` image URL, never a prompt, draft, local render, or yesterday's private study.
3. Curate the public journal from the internal working record. Keep private chain-of-thought and unused exploration private.
4. Email `ledger@wkap.ai` with subject `WKAP Creative Edition - YYYY-MM-DD - vN` and exactly one fenced YAML or JSON block matching [the public schema](https://wkap.ai/specs/creative-edition-latest.schema.json).
5. Identical retries are no-ops. Any changed journal or image byte requires the next version; an existing version is never overwritten.

The email receipt date in Asia/Ho_Chi_Minh must equal `market_date`, preventing backdating. The image host is restricted to `pbs.twimg.com`; redirects away, unsupported image bytes, MIME mismatches, and oversize images are rejected.

## Editorial quality gate

Each meaningful scene needs a verified market story, source links, a visual joke, an interaction or action, and a concise future-show seed. A recognizable character is necessary in the current phase but not sufficient. `character_rationale` must explain why the character's real role or traits fit that specific story and joke. `relationship_semantics` must review the whole scene's dominant audience associations, hero/villain implications, and relationships among the characters. A mechanically apt prop cannot rescue a false narrative implication; decorative costumes and post-hoc rationalizations should be rejected before submission.

Before showing Alex, inspect rendered pixels at phone size and at face/reference detail. Record rejected choices and corrections. Convert each recurring failure into a reusable preflight check; use journal history to look for fewer repeated corrections and stronger first-review results. The public journal is curated; the producer's internal revision log stays private and separate.

## Proof semantics

The canonical page, cover asset, manifest, and OpenTimestamps target are mirrored into `wkapai/wkap-ledger`. The manifest includes SHA-256 for exact image bytes and canonical JSON journal bytes.

- `queued`: proof runtime unavailable or disabled; publication remains valid.
- `submitted_pending`: a proof exists, but Bitcoin verification is not available yet.
- `verified_bitcoin`: independent `ots verify` succeeded.
- `verification_failed`: verification returned a non-pending error and needs review.

Proof upgrades preserve prior `.ots` bytes under `timestamps/history/` and increment `ots_proof_version`. A proof binds bytes; it does not prove authorship, invention, or exact creation time. Proof follow-up belongs in the existing weekday catch-up or scheduled review—never a new monitor.

## Example envelope

```yaml
creative_edition:
  format_version: creative_edition_v1
  market_date: 2026-10-19
  edition_version: 1
  title: "One-frame market show title"
  article_url: "https://x.com/example/status/1"
  image_source_url: "https://pbs.twimg.com/media/example.jpg"
  episode_premise: "The day's market episode compressed into one frame."
  market_hooks:
    - story: "Verified market development"
      why_it_matters: "Why the move belongs in today's frame"
      source_urls: ["https://example.com/source"]
  scenes:
    - story: "Verified story represented by this scene"
      source_urls: ["https://example.com/source"]
      visual_joke: "The visual compression or joke"
      character_choices: "The recognizable characters used"
      character_rationale: "How their real traits or roles connect to the story and joke"
      relationship_semantics: "Why the combination does not imply a false rivalry, alliance, hero/villain role, or other unsupported relationship"
      interaction_or_action: "What the characters are doing together"
      show_seed: "A concise continuation seed for a future market-news show"
  credits:
    human_contribution: "Alex: editorial judgment and final approval"
    ai_contribution: "AI: research synthesis, iteration, and rendering assistance"
    publisher: "WKAP.ai"
  rejected_choices: ["A rejected choice and why it failed"]
  corrections: ["A concrete correction made before publication"]
  lesson_next_time: "One reusable lesson or preflight check"
```
