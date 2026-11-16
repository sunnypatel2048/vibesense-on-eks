# ADR-0015: Gmail SMTP for reports, Amazon SES deferred

**Status:** Accepted

## Context

Reports go to whatever address the user types. A new SES account is in sandbox mode and can send only to verified addresses.

## Decision

Keep Gmail SMTP with an app password (STARTTLS on 587); Mailpit stands in locally. Load-test jobs use `example.com` addresses, which the notification worker logs instead of emailing (`SUPPRESS_EMAIL_DOMAINS`), protecting the sending account's reputation.

## Consequences

- Works for any recipient today, no sandbox exit request.
- Gmail's sending limits rule out real volume; SES is listed under "What production would change".

## Alternatives considered

Amazon SES (the production answer once out of the sandbox); a third-party email API (another vendor and key).
