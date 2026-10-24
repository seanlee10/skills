---
name: domain-search
description: Search domain name availability, naming alternatives, and registration or renewal prices with AWS Route 53. Use GoDaddy for optional registrar comparisons and RDAP or WHOIS for existing registration details. Use for finding a domain to register, not DNS record management.
---

# Domain search

Use Route 53 Domains as the default registrar because the user can reuse an existing AWS profile.
Use native clients and public registration lookup tools. No custom credential store is needed.
This workflow searches and compares. Do not register, transfer, renew, purchase, create hosted zones, or change DNS records.

## Choose candidates

For explicit domains, check those names first. For a naming brief, generate a small set based on the product, audience,
preferred extensions, and budget in the conversation. If unspecified, start with up to ten candidates rather than blocking on preferences.
Distinguish names you invented from names a registrar actually checked. Expand only if the shortlist is insufficient.

Pass domain names, not URLs or email addresses. Lowercase and remove a final root dot.
For internationalized names, convert labels to IDNA A-labels and show both the Unicode name and queried punycode.
Do not silently replace unsupported characters. TLD-specific IDN and eligibility rules can still reject a syntactically valid name.
Do not assume that an arbitrary subdomain can be registered. Treat multi-label registration suffixes such as `co.uk` as a unit.

## Check with Route 53

Use [references/route53.md](references/route53.md) for commands, client compatibility, authentication, and price interpretation.
Use the profile the user names. Otherwise preserve the active AWS environment and default credential chain.
If no credentials work, show the local login step from the reference. Never request AWS keys in chat or change the user's AWS configuration.
Always call `route53domains` in `us-east-1`. The `route53` hosted-zone service is not a domain registration search.

1. Check each explicit candidate with `check-domain-availability`. Preserve the exact returned status.
2. For naming alternatives, use `get-domain-suggestions` with `--only-available`, then check shortlisted results directly.
3. Fetch standard registration and renewal prices with `list-prices`, once for each supported registration suffix.
4. For an available finalist, use domain-specific pricing when the client supports the documented `GetDomainPrices` operation.
   If it cannot be called, label TLD prices as standard-rate estimates and leave the actual premium price unverified.

Only `AVAILABLE` means ordinarily registerable through Route 53. Report reserved, preorder, premium-unavailable,
restricted, invalid-name, and unsupported-TLD results separately. An unsupported TLD is not proof that a domain is taken.
For `PENDING`, wait a few seconds and retry once. For `DONT_KNOW`, a registry outage, or a network error,
report an unknown result after at most one retry. Stop a batch on authentication or permission failures.

## Use another source when it helps

Read [references/providers.md](references/providers.md) when the user requests GoDaddy comparison or ownership information,
or when AWS cannot check the requested extension.

- GoDaddy is an optional registrar source for availability, alternatives, and pricing. It needs separate credentials or a public browser lookup.
  Do not present this route as account-tested unless a real request succeeded. Preserve `definitive=false` as provisional.
- Prefer RDAP for registration details, with WHOIS as a fallback for registries that still need it.
  A registration record is evidence of an existing registration. A 404, no match, timeout, or absent DNS record does not prove purchase availability.
  Use the registrar to confirm availability and price. Report differences between providers rather than silently choosing one answer.

## Present a shortlist

Return a compact table with domain, registrar status, first-year registration price, annual renewal price, and source.
Keep raw registrar statuses alongside a short explanation when they are not `AVAILABLE` or `UNAVAILABLE`.
Attach a checked-at time with timezone. State the currency, registration term, and whether each price is domain-specific,
an indicative registrar quote, or a standard TLD estimate. Missing prices stay unknown, not zero.
Do not compare a first-year promotion with another registrar's multi-year total or omit recurring renewal costs.
Keep DNS hosting charges separate from registration prices.

Recommend a few candidates based on the user's criteria and verified results. Availability can change before registration.
For existing domains, summarize only the requested public registration facts, such as registrar, status, and expiration date.
Link to the actual registrar or RDAP source. Do not infer that expiration means the domain becomes available on that date.
