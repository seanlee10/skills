# Supplement Route 53 with another source

## GoDaddy for a second registrar quote

Use GoDaddy when the user requests a comparison or an extension that Route 53 does not support.
If no token is configured, use public domain search in the browser when accessible. Do not create an account,
purchase an access plan, or ask for tokens in chat merely to complete an optional comparison.

The current developer guides recommend Domains v3 and a Personal Access Token with `domains.domain:read`.
Read it from the user's existing `GODADDY_PAT` environment variable inside the request process.
Do not echo it, pass a literal token to a tool, or put it into a generated report.
Use an HTTP client that reads the environment directly and constructs the header in memory.

These are the documented read-only requests:

```text
GET https://api.godaddy.com/v3/domains/check-availability?domain=example.com&optimizeFor=ACCURACY
Authorization: Bearer <token read from GODADDY_PAT>

GET https://api.godaddy.com/v3/domains/suggestions?query=sunrise%20bakery&tlds=com,net,shop&pageSize=10
Authorization: Bearer <token read from GODADDY_PAT>
```

Encode query parameters and use punycode for IDN names. No POST or checkout request is needed for search.
The v3 guide reports `available`, `definitive`, `inventory`, and per-term `prices[]`.
An available result with `definitive=false` is provisional. Respect the distinction between registry stock and other inventory.
For a comparable annual quote, choose the `term=YEAR`, `period=1` entry.
Read `price`, `renewalPrice`, and their `currencyCode`. USD values in v3 are cents, so 1199 means USD 11.99.
Preserve missing renewal data as unknown rather than inventing a rate. Prices remain indicative, not a purchase commitment.

Do not mix v3 pricing units with older v1/v2 examples. Those APIs use different schemas, authentication,
and price conventions. Classic `sso-key` credentials do not work with v3.

The sources have different access-policy scopes. GoDaddy's April 2026 announcement says the legacy Availability API
retains a higher portfolio threshold, while its v3 guides updated 2026-10-19 describe read-only search with a scoped PAT.
Do not promise that every account can access every version, or require a particular portfolio size from old guidance alone.
For 401 or 403, inspect the response error code, report authentication, scope, or eligibility failure, and stop.
For 429, honor `Retry-After` once if the delay fits the task, otherwise leave the comparison pending.
This skill's GoDaddy route is documentation-based until a real authenticated request succeeds.

Sources checked on 2026-10-24:

- [Current v3 domain search, suggestions, and indicative pricing](https://developer.godaddy.com/en/docs/api-users/domains/search).
- [Current credentials, scopes, and account eligibility](https://developer.godaddy.com/en/docs/api-users/auth).
- [Earlier DNS API and Availability API access announcement](https://www.godaddy.com/resources/news/godaddy-dns-api-now-works-with-a-single-domain).

## RDAP for public registration details

RDAP provides structured registration data over HTTPS. It is the preferred starting point for public lookup.
Use [ICANN Lookup](https://lookup.icann.org/) through the browser, or obtain a registry's authoritative RDAP endpoint
from the [IANA DNS bootstrap](https://data.iana.org/rdap/dns.json).
The bootstrap maps the final TLD label to registry service URLs. Prefer HTTPS, append `domain/` and the punycode domain
to the selected service base, and use a bounded HTTP timeout. Follow the service's rate limits.
For example, the IANA-selected .com service serves `https://rdap.verisign.com/com/v1/domain/example.com`.
Do not assume this same server handles another TLD.

Return only requested facts such as `ldhName`, `unicodeName`, `status`, registrar identity, and registration or expiration events.
Registration data may be redacted. A missing registrant contact is not proof that the domain has no owner.
A domain record returned by RDAP is evidence of an existing registration. A missing record is not a registrar quote.
Reserved names, registry restrictions, unsupported services, and temporary failures can all prevent registration even without a lookup result.
Do not convert RDAP 404, 429, timeouts, or missing bootstrap entries into `AVAILABLE`.
Expiration alone does not predict release or deletion.

## WHOIS as a fallback

Some registries still require WHOIS. If the authoritative RDAP route is unavailable and `whois` exists locally,
query the normalized domain as one argument, for example `whois 'example.com'`, with a process timeout.
Check which registry or registrar answered. WHOIS output is unstructured and provider-specific, so preserve the relevant field labels.
An empty response, a rate-limit notice, or `No match` is not proof that a domain can be bought.
WHOIS does not supply a reliable registration price. Return to the registrar for availability and pricing.

Sources:

- [ICANN's RDAP-based registration lookup](https://lookup.icann.org/).
- [ICANN lookup FAQ, redaction, and WHOIS fallback](https://lookup.icann.org/en/faq).
- [IANA RDAP bootstrap data](https://data.iana.org/rdap/dns.json).
