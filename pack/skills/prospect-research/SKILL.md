---
name: prospect-research
description: Use when researching a person or company for outbound cold messages, sales personalization, recruiting outreach, or warm-intro prep. Collect only verifiable public facts, cite every claim, and do not send messages unless explicitly asked.
version: 1.0.0
author: Hermes Outbound Kit contributors
license: MIT
metadata:
  hermes:
    tags: [prospecting, outbound, linkedin, apify, research, citations]
    related_skills: [lead-prospecting, linkedin-cold-messaging, outbound-scoring, web-reader]
---

# Prospect Research

## Overview

Research a prospect just enough to draft a credible customized outbound message. The deliverable is not a biography; it is a concise set of verified facts, source links, and safe personalization angles.

Follow the user's requested scope strictly. If they ask for research only, **do not send, draft, schedule, or contact anyone** unless they separately ask for that action.

## When to Use

Use this skill when the user asks to:
- Check a LinkedIn/profile URL for public information useful for a cold message.
- Gather facts about a person for outbound sales, recruiting, partnership, investor, or warm-intro outreach.
- Produce personalization hooks from public posts, profiles, blogs, podcasts, GitHub, company pages, or public search results.
- Use Apify/Composio or non-login public sources to inspect a prospect.

Don't use this for:
- Scoring which accounts to call first — use `outbound-scoring` or `lead-prospecting`.
- Monitoring feeds or ongoing alerts — use a cron/blogwatcher-style skill.
- Sending the outbound message — treat that as a separate explicit side-effect task.

## Workflow

### 1. Lock scope and safety boundary

Restate internally:
- Target entity and URL(s).
- Allowed source types: public web, non-login pages, connected tools the user permits (e.g. Apify/Composio).
- Forbidden action: no messaging/contacting unless explicitly requested.

Completion criterion: the final response cannot include uncited claims or any claim inferred from private/login-only data unless the user provided it.

### 2. Use the fastest source ladder

Use the simplest working source first and stop when enough verified facts exist for a useful outbound hook.

1. **Provided URL first** — inspect the target page or public extraction task before broad search.
2. **Existing connected tools** — if Apify/Composio has an active connection and a relevant task/actor exists, use it rather than building custom scrapers.
3. **Public web search** — query exact handles, quoted names, company + role, and snippets for corroboration.
4. **Direct fetch/browser fallback** — try simple HTTP/browser only when it adds evidence; expect some sites to block unauthenticated scraping.

Completion criterion: at least one primary source has been checked, and any fallback failures are not treated as durable tool limitations.

### 3. LinkedIn public-profile pattern with Apify/Composio

When the target is a LinkedIn profile and Apify is available:

1. Search Composio tools for Apify actor/task capabilities.
2. Confirm the Apify toolkit has an ACTIVE connection before executing.
3. List or inspect existing tasks before creating anything new; reuse a relevant task with `inputOverrides` when a task already matches the actor.
4. Match the actor's exact input schema before running it. Do not assume LinkedIn actors share fields:
   - Post/comment scrapers often use `targetUrls`, `maxPosts`, `maxComments`, etc.
   - Single-profile scrapers may use `url`, `publicIdentifier`, or `profileId` only.
   - If the schema is not returned by Composio, inspect the public Apify actor metadata/source schema before guessing.
5. Run a small, low-cost pull first:
   - For post scrapers: `targetUrls`, `maxPosts`: 5-10, `maxComments`: 0, `maxReactions`: 0, `includeReposts`: false unless needed.
   - For profile scrapers: one profile URL or public identifier, dataset `limit`: 1-3, explicit wait/timeout.
6. If the target returns an empty dataset, retry once with another schema-valid identifier form, then run one known public control profile to separate “target unavailable” from “actor/account/config issue.”
7. Extract facts only if the returned data identifies the same public identifier/profile URL.

Completion criterion: the output includes the profile identifier/name, source URLs for each cited claim, and no claims derived from an empty scrape or a search-engine summary when a source URL was unavailable.

### 4. Corroborate before reporting career claims

Career-history claims are risky because names collide. Use this hierarchy:

- Strong: target profile's own post/profile metadata states it.
- Strong: company page, official bio, or exact profile URL states it.
- Medium: public search result/snippet with exact name + unique handle + company.
- Weak: generic web-search summary, unlinked snippet, or same-name result.

Report strong facts plainly. Report medium facts with attribution and caveat. Drop weak facts unless the user specifically asks for leads to investigate.

Completion criterion: every title/company/date claim has either a source URL or is omitted.

### 5. Produce concise outbound-useful facts

Default output structure:

```
- 수행한 일 / checked sources
- 검증된 구조화 사실
  1. Identity / current headline
  2. Recent change or trigger event
  3. Role/company/market facts
  4. Interests or values visible in posts
  5. Relevant geographies/events/communities
- Safe personalization angles
- Gaps / blocked sources, if material
```

Keep it short. Prefer a few reliable facts over many weak ones. Include direct markdown links next to the claims they support.

Completion criterion: a future agent or user can draft a personalized outbound message using only the listed facts without needing to re-open the raw scrape.

## Common Pitfalls

1. **Sending when asked only to research/draft** — prospect research and draft generation are read-only unless the user separately asks for delivery. Drafting is allowed when explicitly requested, but sending/scheduling is a separate side effect.
2. **Drafting from an empty or unverified scrape** — if the requested extractor returns `items: []`, do not invent “profile-based” personalization. Say the profile was not verified, report the attempted schema-valid inputs briefly, and withhold the tailored draft unless the user supplies facts or approves a generic sample.
3. **Overclaiming from search summaries** — search summaries often merge same-name people. Use them to guide searches, not as final evidence.
4. **Ignoring public identifier matching** — verify the scraped author/publicIdentifier/profile URL matches the requested profile before using the data.
5. **Too much scraping** — start with 5-10 posts and no comments/reactions for post scrapers, or 1-3 records for profile scrapers. Increase only if the user asks for deeper personalization.
6. **Uncited personalization hooks** — every hook should point to the post/profile/company page that supports it.
7. **Hardening transient tool failures** — if browser/direct fetch is blocked or an actor returns empty, note the session limitation in the answer, but don't save a rule like “LinkedIn cannot be fetched” or “this actor is broken.” The durable rule is: use schema-valid retries, a control profile, authorized public extractors, and cite returned source URLs.
8. **Mixing people with similar names** — if public search reveals multiple same-name people, only include facts tied to the target URL/handle.

## Reference Files

- `references/linkedin-apify-prospect-example.md` — concrete public LinkedIn + Apify/Composio pattern with small-limit task overrides and reporting shape.
- `references/linkedin-public-metadata-recipe.md` — public-web-only LinkedIn fallback using crawler-visible metadata/JSON-LD and public post meta tags when profile pages are authwalled.

## Verification Checklist

- [ ] Target URL/handle matched in collected data.
- [ ] At least one public source or authorized public extractor checked.
- [ ] Every factual claim has a source URL or explicit attribution.
- [ ] Same-name ambiguity resolved or omitted.
- [ ] No message was sent or scheduled without explicit user instruction.
- [ ] Output is concise and directly useful for outbound personalization.
