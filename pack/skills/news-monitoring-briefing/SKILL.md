---
name: news-monitoring-briefing
description: "Research, verify, rank, and write concise current-news briefings across regions and domains. Use for daily/weekly world-news digests, scheduled news monitoring, or any request that demands only the most important verified stories with source links."
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [news, world-news, briefing, monitoring, verification, web-search, cron]
    related_skills: [web-reader, naver-news-search, buying-signals]
---

# News Monitoring and Briefing

## Purpose

Produce a short, high-signal briefing from live reporting rather than a search-result dump. The job has four parts: broad discovery, direct verification, importance ranking, and compact delivery.

This skill applies to daily or weekly news digests, scheduled world-news briefings, topic watchlists, and requests for the day's most important developments.

## Core Rules

1. **Anchor the reporting window first.** Resolve the user's timezone and the exact cutoff time. Treat search-engine relative dates as coarse hints, then filter every candidate by its actual publication timestamp.
2. **Separate discovery from verification.** Search summaries identify candidates; they are not evidence. Open the shortlisted source pages before using their facts.
3. **Cover independent lanes.** For a general world briefing, search at least:
   - geopolitics, conflict, and diplomacy
   - disasters, accidents, and climate emergencies
   - economy, finance, trade, and monetary policy
   - major political and social events
4. **Parallelize broad research when required or useful.** Delegate independent regional/domain lanes first, while retaining a direct verification pass in the parent workflow. Give workers the date, timezone, exclusions, source hierarchy, and required output fields.
5. **Cross-check consequential claims.** Use an official source when one exists; otherwise use two independent reputable reports where practical. Never turn a party's allegation into an established fact.
6. **Rank globally, not by search frequency.** Repeated syndication does not make a story more important.
7. **Deduplicate by event.** Combine follow-ups, regional variants, cascading consequences, and syndicated copies into one item unless the user asks for separate infrastructure impacts.
8. **Separate the clocks.** Record occurrence time, article publication time, and latest official tally time independently. An older event qualifies for a same-day briefing only when a material report or update actually appeared inside the requested window.
9. **Trace source lineage.** Two outlets republishing the same AP/Reuters/AFP dispatch are one evidentiary lineage, not independent confirmation. Pair the wire with an official record or genuinely independent local reporting.
10. **Reconcile count categories.** Do not silently choose between conflicting casualty totals. Preserve distinctions such as confirmed, disaster-linked but under review, missing, cumulative seasonal deaths, and incident-specific deaths.
11. **Treat synthesized search answers as untrusted candidate generators.** Reject an apparently current event when its cited page does not open, the body is unrelated, the year is wrong, or a second source strategy cannot support it.
12. **Deliver only the briefing.** Do not expose search queries, delegation chatter, tool failures, or verification logs unless the user explicitly asks.

## Source Hierarchy

Prefer, in order:

1. Official authorities and primary records: governments, central banks, emergency agencies, international organizations, election commissions.
2. Global wire services and established newsrooms: Reuters, AP, AFP, BBC and similarly accountable outlets.
3. Strong regional outlets with direct local reporting.
4. Syndicated copies when the canonical page is inaccessible; label the underlying wire service when clear.
5. Commentary, aggregators, and AI-generated search answers only for discovery, never as sole factual support.

A single official statement can establish what that institution announced. It cannot independently establish disputed battlefield outcomes, casualty claims, or responsibility for an attack.

## Workflow

### 1. Define scope and exclusions

Record the date/time cutoff, geography, topic lanes, language, desired item count, and explicit exclusions. For a scheduled run with no user present, make conservative defaults and continue autonomously.

### 2. Broad discovery

Search each lane with multiple query angles and reputable-source terms. Include the exact calendar date in general web-search queries. Search multiple regions so one heavily covered conflict does not crowd out disasters, economics, Africa, Latin America, or Asia.

If delegation is part of the job, split workers by independent lane rather than asking several workers the same broad question. Require each worker to return: headline, two-sentence factual summary, publication timestamp, exact URL, verification status, and why the event matters.

### 3. Normalize candidates

For every candidate:

- parse and compare the actual publication date to the briefing window
- reject stale same-day/month results from earlier years
- canonicalize or deduplicate URLs
- merge stories covering the same underlying event
- separate confirmed facts, official claims, opposition claims, and estimates
- retain the newest reliable casualty or damage count, while noting whether it is confirmed or under investigation

### 4. Direct verification

Open the short list in batches when the fetch tool supports multiple URLs. Verify:

- title and publication timestamp
- actor, location, and sequence of events
- casualty/damage/economic figures
- whether a number is confirmed, estimated, or claimed
- whether a developing story has materially changed since earlier reports

For major conflict, election violence, or disputed casualty reporting, seek a second independent report or official record. For monetary policy, legislation, elections, and disaster bulletins, link the primary institution where possible. When an official dashboard is dynamic or inaccessible, search for a dated static press release, bulletin, or PDF; use quoted exact figures and a source-language query to locate poorly indexed updates.

For fast-moving disasters, maintain a small event ledger and reconcile numeric categories before writing. See `references/live-disaster-news-verification.md` for the three-clock model, source-lineage checks, exact-figure search technique, and casualty-count reconciliation.

### 5. Rank and select

Score candidates by:

- global or regional consequence
- escalation risk and diplomatic significance
- human impact and disaster scale
- market, trade, or policy impact
- novelty within the current reporting window
- confidence in verification

Select only the requested number, usually 5–7. Keep category balance but never pad the list with weak stories merely to fill a lane.

### 6. Write the briefing

Default shape:

- one short heading with date and cutoff timezone
- 5–7 items
- bold, concrete headline
- one compact paragraph, usually 2–3 sentences
- source links immediately after the item

Lead with the fact, then consequence. Put uncertainty next to the uncertain claim: “단체는 30명 사망을 주장했지만 당국 확인은 없다.” Do not bury this caveat later.

Respect the user's language and link-format rules. If URLs must be protected from embedding, wrap each one in angle brackets: `[BBC](<https://…>)`.

## Search-Backend Recovery

If a news-specific search endpoint returns empty data or transient 5xx errors:

1. Do not conclude that no news exists.
2. Retry with a broader query or switch to general web search.
3. When bursty parallel search fails, run narrower fallback searches sequentially.
4. Use returned citations and timestamps for discovery; ignore the search engine's synthesized answer as evidence.
5. Fetch the selected article pages directly and continue the normal verification process.

See `references/composio-world-news-workflow.md` for a concrete Composio search/fetch pattern and failure-resistant checks.

## Pitfalls

- **Date leakage:** Exact-date queries still return old articles with matching month/day terms. Filter `publishedDate` manually.
- **Syndication inflation:** Ten copies of one Reuters story are still one source/event.
- **Headline-only synthesis:** Snippets frequently omit attribution, uncertainty, or updated casualty counts.
- **False confirmation:** Two articles repeating the same unnamed source are not independent confirmation.
- **Premature certainty:** Use “당국 발표”, “현지 매체 보도”, “단체 주장”, or “조사 중” explicitly.
- **Overlong background:** A briefing is not an explainer. Include only enough context to understand why today's development matters.
- **Process leakage:** The final scheduled message contains the finished briefing, not a research diary.
- **Unbalanced search:** A dominant conflict can consume every result. Preserve separate discovery lanes before ranking globally.

## Verification Checklist

- [ ] Exact date/time window anchored in the user's timezone
- [ ] All requested domains and major regions searched
- [ ] Explicit exclusions enforced
- [ ] Candidate dates checked; stale-year collisions removed
- [ ] Shortlisted pages opened directly
- [ ] Disputed claims attributed and cross-checked
- [ ] Duplicate events merged
- [ ] Final list contains only the requested number of high-impact stories
- [ ] Every item has an immediately usable source link
- [ ] Final output contains no tool/delegation/process report
