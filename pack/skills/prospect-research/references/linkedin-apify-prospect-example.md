# LinkedIn public-profile Apify example

This reference captures a reusable pattern from a prospect-research session, not a durable claim about tool availability.

## Request shape

User asked to inspect `https://www.linkedin.com/in/<public-handle>/` using non-login public sources or Apify/Composio if available, then return concise structured facts for a customized outbound cold message. The user explicitly said not to send any message.

## Working source path

1. Prefer the simplest working path; do not build custom scrapers when an existing task fits.
2. Use Composio search for Apify actor/task support.
3. Confirm Apify connection is ACTIVE.
4. Reuse an existing Apify task instead of creating new code:
   - Example: an existing task wrapping a public LinkedIn profile-posts actor
5. Inspect task input before running; it accepted `targetUrls`, post limits, comment/reaction settings.
6. Run with small overrides:
   - `targetUrls`: `["https://www.linkedin.com/in/<public-handle>/"]`
   - `maxPosts`: `5`
   - `maxComments`: `0`
   - `maxReactions`: `0`
   - `includeQuotePosts`: `false`
   - `includeReposts`: `false`
   - dataset `limit`: `5`
7. Extract only facts tied to `author.publicIdentifier == "<public-handle>"` and source post URLs.

## Useful fact types returned

- Author metadata: name, headline, public identifier, LinkedIn URL.
- Public post content: recent career transition, self-described role history, interests/values.
- Post metadata: `linkedinUrl`, `postedAt.date`, engagement counts when useful.

## Reporting pattern

Good final structure:

- 수행한 일 / checked sources
- 검증된 구조화 사실
  - name/headline/identifier
  - recent trigger event
  - self-described company/role/team details
  - interests or values visible in posts
  - event/geography/business context
- safe outbound angles
- material gaps or blocked source attempts

## Pitfalls observed

- Direct unauthenticated LinkedIn fetch may be blocked. Do not encode that as a permanent rule; just prefer authorized public extractors when available.
- Web-search summaries may merge same-name people. Do not report career facts from summaries unless tied to the target handle or source URL.
- If the user requested “do not send,” keep the task read-only even if outbound hooks are requested.
