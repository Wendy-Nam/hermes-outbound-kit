# Composio World-News Workflow

Use this reference for scheduled global-news briefings that combine delegated discovery with parent-side verification.

## Recommended lane split

Dispatch independent workers before direct research when the job requires delegation:

1. Geopolitics, conflict, diplomacy, major politics
2. Disasters, accidents, climate emergencies
3. Economy, finance, trade, monetary policy

Pass the exact date and cutoff timezone. Require reputable same-day sources, exact URLs, publication timestamps, key figures, and explicit attribution for disputed claims. Exclude unwanted beats such as AI/technology at the prompt level rather than filtering only at the end.

## Composio discovery sequence

1. Call `COMPOSIO_SEARCH_TOOLS` with one query per lane and create a new session.
2. Confirm the search toolkit is active and preserve the returned `session_id` for every later meta-tool call.
3. Try `COMPOSIO_SEARCH_NEWS` with `when: "d"`, explicit language/region, and narrow lane queries.
4. Treat `successful=true` with empty result arrays as no usable result.
5. If news search returns transient 5xx failures across a parallel batch, switch backends instead of repeating the same burst:
   - call `COMPOSIO_SEARCH_WEB`
   - use one focused query at a time
   - include the exact date, subject lane, and preferred outlets
6. Read `citations` and `publishedDate`; the generated `answer` is discovery context only.

Example fallback query shapes:

```text
July 30 2026 latest major world geopolitics diplomacy conflict Reuters AP BBC
July 30 2026 global earthquake flood wildfire storm Reuters AP BBC
July 30 2026 world economy trade tariffs central bank Reuters FT AP
July 30 2026 major political social events Africa Europe Asia Americas
```

## Candidate hygiene

Before fetching pages:

- Remove results from the wrong year even if month/day match.
- Merge canonical articles and syndications into one event.
- Prefer a wire-service canonical URL, but keep a readable syndication when the original is inaccessible.
- Do not let the search answer's narrative introduce facts absent from its citations.
- Keep separate fields for `confirmed`, `official_claim`, `party_claim`, and `under_investigation` when casualty figures diverge.

## Direct page verification

Batch several shortlisted URLs into one `COMPOSIO_SEARCH_FETCH_URL_CONTENT` call when possible:

```json
{
  "urls": ["https://source-a/article", "https://source-b/article"],
  "text": true,
  "summary": true,
  "max_characters": 10000
}
```

Read the extracted article text, not just `summary`. Check:

- dateline and publication time
- exact actor/action/location
- latest confirmed count
- whether the article itself attributes the number to officials, state media, activists, or witnesses
- updates that change earlier headlines

For policy decisions, fetch the primary institution's statement. For conflict and election violence, pair a strong newsroom with another independent outlet or official statement, while recognizing that an official denial is not neutral confirmation.

## Selection and delivery pattern

A compact world briefing usually works best with 5–7 events. Choose by consequence and verification confidence, then enforce diversity across conflict, disaster, economy, and politics without padding.

Each item should contain:

1. Concrete headline
2. One sentence for what happened
3. One sentence for scale/consequence or uncertainty
4. One or two links immediately after the paragraph

Korean compact example shape:

```markdown
**사건명과 핵심 변화**
확인된 사실과 핵심 수치를 먼저 쓴다. 주장이나 조사 중인 부분은 같은 문단에서 바로 선을 긋는다. [출처](<https://example.com>)
```

The final cron-delivered message must not mention delegation, tool retries, backend failures, or verification steps.
