# Security policy

## Supported versions

Only the [latest release](https://github.com/tzachbon/codex-speak/releases/latest) gets security fixes.

## Report a vulnerability

Please don't open a public issue. Use GitHub's private reporting instead: go to the [Security tab](https://github.com/tzachbon/codex-speak/security), choose **Report a vulnerability**, and include steps to reproduce.

## In scope

- The updater: download verification, installer handoff, and release trust.
- The local speech-to-text server: access token handling, origin and Host checks.
- Clipboard snapshot and restore.
- Anything that sends selected text or logs it when it shouldn't.

Codex, Edge, and Windows speech services are run by their vendors. Report issues in those services to them.
