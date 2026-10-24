# Route 53 domain queries

## Use the existing profile

AWS CLI credentials, including SSO or a named profile, are sufficient. Preserve `AWS_PROFILE` when set.
Add `--profile PROFILE_NAME` to every call when the user specifies a profile. Do not print credential files,
access keys, session tokens, or full debug logs. The examples assume the active profile is already usable.

If credentials are missing, ask the user to configure their own local AWS CLI profile.
For an existing SSO profile, the local login command is `aws sso login --profile PROFILE_NAME`.
Do not try unrelated profiles until one works without the user's choice.

The example [read-only IAM policy](route53-read-only.json) covers availability, suggestions, and standard TLD prices.
It does not grant registration or DNS changes. Share it if a permission error requires the account administrator's help.
Do not attach policies or create credentials as part of a search.

## Query availability and suggestions

Use JSON output and disable the pager. Quote each domain as an argument. For programmatic calls, pass an argument array
rather than interpolating untrusted names into shell code.

```sh
aws route53domains check-domain-availability \
  --domain-name 'example.com' \
  --region us-east-1 --output json --no-cli-pager \
  --cli-connect-timeout 10 --cli-read-timeout 30

aws route53domains get-domain-suggestions \
  --domain-name 'example.com' --suggestion-count 10 --only-available \
  --region us-east-1 --output json --no-cli-pager \
  --cli-connect-timeout 10 --cli-read-timeout 30
```

Suggestions can be fewer than requested and can include different extensions. Check the shortlisted names again.
Treat `AVAILABLE_RESERVED` and `AVAILABLE_PREORDER` as conditional results, not ordinary availability.
`UNAVAILABLE_PREMIUM` is not an available premium listing. Preserve it as unavailable.

## Compare prices without confusing standard and premium rates

```sh
aws route53domains list-prices --tld 'com' \
  --region us-east-1 --output json --no-cli-pager \
  --cli-connect-timeout 10 --cli-read-timeout 30

aws route53domains list-prices --tld 'co.uk' \
  --region us-east-1 --output json --no-cli-pager \
  --cli-connect-timeout 10 --cli-read-timeout 30
```

Read `Prices[].RegistrationPrice` and `RenewalPrice`, including each `Currency`.
These are standard TLD rates. They do not prove the price of an individual premium name.
Use the supported registration suffix, not just the last label. To discover suffixes, call `list-prices` without `--tld`.
Keep normal CLI pagination enabled and inspect `Prices[].Name`. Match the longest suffix and confirm that the remaining registrant label is valid.
Do not classify an unsupported suffix or an empty price response as unavailable.

AWS also documents `GetDomainPrices`, which returns `DomainPrice.RegistrationPrice` and `RenewalPrice` for a specific domain.
Newer availability responses can include a registration `Price` with `PriceType`, but an older client may omit that field entirely.

Client compatibility matters. On 2026-10-24, the installed AWS CLI v2.27.24 and a separately tested AWS CLI v1.46.2
did not expose `get-domain-prices`. A documentation page alone does not prove that an installed client can call it.
For an installed CLI that exposes the command, the read-only request is:

```sh
aws route53domains get-domain-prices --domain-name 'CANDIDATE_DOMAIN' \
  --region us-east-1 --output json --no-cli-pager \
  --cli-connect-timeout 10 --cli-read-timeout 30
```

If the client says `Invalid choice`, stop trying this operation. Do not create registration requests to discover a price.
Report the standard TLD estimate and the unverified domain-specific price. Use the AWS console's domain search or another
registrar for a price cross-check if accessible. Do not silently upgrade the user's global AWS installation.
When this operation is supported, it also needs the corresponding read permission; the bundled minimal policy covers the three established operations only.

## Handle failures

- Missing, expired, or invalid credentials require local authentication. Stop the batch and report the login step.
- `AccessDenied` requires the relevant read permission. Stop the batch without modifying IAM.
- `UnsupportedTLD` means Route 53 cannot check or register that suffix. Try another registrar when useful.
- `TLDInMaintenance`, `PENDING`, `DONT_KNOW`, rate limits, and network errors are unknown results.
  Retry once after a short delay and stop if unresolved.

## Sources

- [CheckDomainAvailability and status definitions](https://docs.aws.amazon.com/Route53/latest/APIReference/API_domains_CheckDomainAvailability.html).
- [CLI suggestions and us-east-1 region requirement](https://docs.aws.amazon.com/cli/latest/reference/route53domains/get-domain-suggestions.html).
- [ListPrices and standard TLD rate limitations](https://docs.aws.amazon.com/Route53/latest/APIReference/API_domains_ListPrices.html).
- [Domain-specific prices including premium rates](https://docs.aws.amazon.com/Route53/latest/APIReference/API_domains_GetDomainPrices.html).
