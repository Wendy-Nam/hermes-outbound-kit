# Live Disaster News Verification

Use this reference for same-day disaster, accident, wildfire, flood, earthquake, and mass-casualty briefings where figures change quickly.

## Candidate ledger

Track one row per underlying event, not per article:

- event ID and region
- occurrence time in local time and UTC/KST when relevant
- first-report time, article publication time, and latest-update time
- latest casualty categories: confirmed dead, disaster-linked deaths under review, missing, injured, evacuated/displaced
- damage units with definitions: burned area, inundated cropland, homes/structures, affected population
- official source and exact URL
- independent newsroom or wire source and exact URL
- source lineage: original reporting, official-bulletin rewrite, or wire syndication
- verification status and unresolved discrepancies

## Verification sequence

1. **Discover broadly, verify narrowly.** Search answers and snippets may suggest candidates but cannot establish facts.
2. **Open the article body.** Confirm that the URL resolves, the body describes the claimed event, and its actual publication/update timestamp falls in the requested window.
3. **Separate three clocks.** Record occurrence time, publication time, and latest official tally time. A same-day briefing may legitimately include an older event only when a source published a material update in the requested window.
4. **Find the primary record.** Search the agency, local-government, meteorological, fire, seismic, or disaster-management site. If a dynamic dashboard is inaccessible, seek its dated static release, bulletin, press page, or PDF rather than treating the dashboard failure as absence of data.
5. **Use exact-figure and source-language searches.** Search a distinctive pair of figures in quotes, then repeat in the local language. This often finds the canonical official update hidden behind weak English indexing.
6. **Open at least one independent account.** Two sites republishing AP/Reuters/AFP are one source lineage. Count the wire plus a local newsroom or official bulletin, not two syndications.
7. **Reconcile, do not flatten, conflicting counts.** Prefer the newest dated official tally and preserve categories. Example: “34 reported by the prefecture: 25 confirmed disaster deaths plus 9 under review,” rather than silently choosing 25 or 34.
8. **Deduplicate cascading consequences.** A wildfire, bridge collapse caused by that fire, road closure, and evacuation are one event unless the user explicitly requests separate infrastructure stories.

## Numeric consistency checks

Before writing, compare each figure across sources and ask:

- Is this cumulative for the season or specific to the current episode?
- Does “affected” mean residents, households, villages, or districts?
- Are missing people included in the death toll?
- Are hectares/acres and local number formats converted correctly?
- Is containment percentage timestamped?
- Did a newer update revise the count downward or split confirmed vs suspected cases?

When figures differ because of update time, cite both timestamps and use the newest reliable figure. When the reason is unclear, state the range or disagreement.

## Synthetic-answer trap

Search backends can return fluent but unsupported event summaries, including plausible future-dated URLs, incorrect incident identities, or stale events from another year. Reject a candidate when the cited page does not open, the body is unrelated, or no primary/independent source supports the claim after a second query strategy. Do not replace failed verification with a confident summary.

## Output pattern

For each selected event include:

- concrete title and region
- occurrence time/date, clearly separated from report date
- exactly the requested summary length
- primary article URL with publication date
- verification URL(s) with dates and source lineage where useful
- importance rationale based on human impact, geographic scale, infrastructure damage, escalation risk, and confidence

Do not expose failed searches or the research diary unless requested.