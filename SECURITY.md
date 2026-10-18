# Security policy

## Supported versions

Only the [latest release](https://github.com/tzachbon/harness-discussion/releases/latest) gets security fixes.

## Report a vulnerability

Please don't open a public issue. Use GitHub's private reporting instead: go to the [Security tab](https://github.com/tzachbon/harness-discussion/security), choose **Report a vulnerability**, and include steps to reproduce.

## In scope

- The updater: download verification, installer handoff, and release trust.
- The local speech-to-text server: access token handling, origin and Host checks.
- Clipboard snapshot and restore.
- Reading the Cursor sign-in token and sending it to Cursor's speech service.
- Anything that sends selected text or logs it when it shouldn't.

Cursor, Codex, Edge, Windows, and macOS speech services are run by their vendors. Report issues in those services to them.
