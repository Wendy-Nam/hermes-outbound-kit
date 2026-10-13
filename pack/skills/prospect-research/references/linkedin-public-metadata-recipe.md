# LinkedIn public metadata recipe

Use this when researching a LinkedIn prospect from public web only and normal browser/Jina/search access is authwalled or sparse.

## What worked

1. Fetch the exact profile URL and `kr.linkedin.com/in/<handle>` variant with a crawler-style user agent such as `Twitterbot/1.0`.
   - Goal: collect public `<title>`, `og:title`, `description`/`og:description`, and JSON-LD.
   - Do not treat login/authwall HTML as profile evidence; only use metadata or JSON-LD that names the same handle/person.
2. Parse JSON-LD from `<script type="application/ld+json">` on the profile page.
   - Useful fields observed: `Person.name`, `sameAs`/`url`, `address`, `worksFor`, `alumniOf`, `interactionStatistic`, and `@graph` items for articles/posts.
   - If job titles are blank or inconsistent, cite only the fields actually present and mark current role as uncertain.
3. Fetch public post URLs directly with a normal browser UA or crawler UA.
   - Public LinkedIn posts often expose the post text in `<title>`, `og:title`, and `description` even when body content is unavailable.
   - Use the URL slug + metadata only if the author/handle matches the target.
4. Use search results as leads, not evidence, unless the result links to a source URL that can be inspected.

## Reporting rules

- Cite the exact profile or post URL next to every fact.
- Distinguish stale profile metadata from newer posts. Example: profile says current company X, but a later post says the person left X; report current role as uncertain.
- Same-name collisions are common. Ignore GitHub/social profiles or directory results unless a public link ties them to the target LinkedIn handle.
- Do not save environment-specific browser/fetch failures as rules; save the retry pattern above.
