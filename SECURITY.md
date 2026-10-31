# Security Policy

## Supported versions

Only the latest release receives fixes during the beta.

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's private reporting instead:

1. Go to the [Security tab](../../security) of this repository.
2. Click **Report a vulnerability**.

Include what you found, how to reproduce it and what it could affect. You'll get a reply within a few days, and credit in the release notes if you'd like.

## What's in scope

- Anything that could expose a student's study records, Canvas session, email app password, calendar link or iPhone notes
- Code paths that run downloaded or course-supplied content
- The note handoff between the iPhone app and the Mac (outbox, nonces, replay protection)
- Signing, notarization and update integrity of release builds

## How Genesis protects data

- Passwords and private links are stored in the macOS Keychain, never in files.
- Canvas is read with the student's own signed-in session inside Genesis, read-only. No Canvas API keys are used or stored.
- The AI backend uses the student's own Codex installation; Genesis never reads its credentials.
- The bundled backend refuses symbolic-link destinations and backs up any code it replaces.
