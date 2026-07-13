# Security Policy

> **This is an independent, community-maintained fork of
> [`duosecurity/duo_log_sync`](https://github.com/duosecurity/duo_log_sync) and is
> NOT covered by Duo Security's or Cisco's security process.** Reports here are
> handled by this project's maintainer on a best-effort basis.
>
> A vulnerability in the **Duo product or the Duo Admin API itself** should be
> reported to Duo/Cisco through their official channels, not here.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 2.5.x   | ✅        |
| < 2.5   | ❌        |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Use GitHub's private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability** (Security advisories → New draft advisory),
   or use this link:
   <https://github.com/MarkTripod-Duo/duo_log_sync/security/advisories/new>
3. Include a description, affected version, reproduction steps, and impact.

Please give a reasonable time for a fix before any public disclosure.

## Handling secrets

Duo Log Sync consumes Duo Admin API credentials (`ikey`/`skey`). When sharing
logs or configuration in an advisory or issue, **always redact** integration
keys, secret keys, hostnames, and any captured log data.
