# Privacy

_Last updated: October 31, 2026_

Genesis is a study app for Mac and iPhone. It's built to keep your data with you.

## The short version

- Genesis has **no servers, no accounts and no analytics**. The developer receives nothing about you or how you use it.
- Your study records stay **on your Mac**.
- When Genesis uses AI, it goes through **your own Codex installation and OpenAI account**, under OpenAI's terms.
- Every outside connection is a **plugin you choose**. If you don't add it, it never runs.
- The companion is built in. It talks through the same Codex session, and you can see and delete what it remembers about you.

## What Genesis stores, and where

On your Mac, in `~/Library/Application Support/Genesis` (or a folder you choose):

- your class list, plan, practice problems, answers, grading feedback and progress
- notes you send from the Mac or the iPhone app
- what the companion has learned about how you study and talk (Settings › Accounts › *What Genesis knows about you* lists it, and you can delete any of it)
- a local activity log used to learn your focus habits (what you're doing in the app, never what you type)

In the macOS Keychain: your email app password and private calendar link, if you add those plugins.

## What leaves your Mac

| When | What | Where |
| --- | --- | --- |
| Canvas plugin syncs | Requests to read your classes, using your own signed-in session | Your school's Canvas site |
| Genesis writes, checks or grades practice, labels a note, or the companion talks | The course material and text needed for that one job | OpenAI, through your Codex session |
| Email plugin | Read-only mailbox requests | Your email provider |
| Calendar plugin | A request for your private calendar feed | Your school's Canvas site |
| iPhone notes plugin | Notes you write on your phone | Your iCloud Drive (Apple), then your Mac |

Nothing else is sent anywhere.

## The iPhone app

The Genesis iPhone app saves your notes to a folder in your iCloud Drive, where the Mac app picks them up. It collects no analytics and has no account. Its privacy manifest declares no tracking and no data collection by the developer.

## Your choices

- Remove any plugin in **Settings › Plugins** and it stops right away.
- Delete what the companion knows in **Settings › Accounts**.
- Delete everything by removing the Genesis folder in Application Support, and the app.

## Children

Genesis is meant for college students and is not directed at children under 13.

## Contact

Questions about privacy: open a [discussion](../../discussions) or a [private advisory](../../security/advisories/new) on this repository.
