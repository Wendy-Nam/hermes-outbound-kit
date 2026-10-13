# Daily briefing curation heuristics

Use this when the user asks for a short morning briefing or a top-news digest.

## Query set

- Prefer a small topical mix instead of one broad keyword.
- Good starter queries for Korean current affairs:
  - `정치`
  - `경제`
  - `사회`
  - `국제`
  - `국회`
  - `대통령실`
  - `환율`
  - `부동산`
  - `미국 관세`

## Selection rules

1. For a "top news" briefing, **fan out across several topical queries** instead of one broad keyword. Start with `정치`, `경제`, `사회`, `국제`, `국회`, `대통령실`, `환율`, `부동산`, `미국 관세` and any user-specified focus.
2. Pull recent items with `sort=date`.
3. Merge all results and dedupe by `original_link` first, then `link`, then title.
4. Exclude entertainment, sports, idol/celebrity, and pure culture fluff unless the user explicitly wants them.
5. Prefer items with clear national policy, market, public safety, diplomacy, or major domestic issue relevance.
6. If the broad query returns noisy matches, tighten it with a policy or macro term rather than retrying the same keyword.
7. When a topic returns many near-duplicates or the first result is only weakly related, drop the weak match and keep the story with the clearest public-policy signal.
8. When finished, present exactly 5 strongest 시사 items as title + one-line summary + link; do not pad with weak matches.

## Output shape

- Keep each item to: 제목 + 한줄 요약 + 링크.
- If the result set is thin, still return the best available items and do not pad with weak matches.
- When summarizing, avoid adding claims that are not present in the API description.
