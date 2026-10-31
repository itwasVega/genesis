# Changelog

## 1.0 (50) — October 31, 2026

### Added
- **Meet Genesis.** The first launch opens to pure black; a small light grows into the orb, and she introduces herself. Then she walks you through setup in plain words: your name, ChatGPT (found on your Mac for you), your school's Canvas, your classes (found for you), your Canvas calendar (picked up for you), school email, the iPhone app and notifications. Replay it any time in Settings.
- **Any school.** Canvas works for every school: sign in like usual, or use an access token if your school allows one. Your time zone, your classes' names and the words you use for them come from you.
- **Add opens setup right away.** Adding a plugin goes straight into its sign-in or instant setup.
- **A real installer window.** Genesis.dmg opens to a black, drag-to-Applications window.

### Changed
- Plugins are the sources for your brief: Canvas, Calendar and School email.
- No school-specific code ships with Genesis.
- The empty plan no longer shows a drawn icon.


## 1.0 (49) — October 31, 2026

First public beta.

### Added
- **Plugins** are the sources Genesis reads for your brief: Canvas, Calendar, Email and Professor websites. Pick them on first launch or in Settings › Plugins; anything you don't add never runs.
- **iPhone notes just work.** The Mac picks up the first note you send from the Genesis iPhone app, with nothing to set up. Until then, Genesis suggests the iPhone app now and then (a card under Tell Genesis, an occasional word from the companion, and a button in Settings).
- **All-in-one answer box.** Type, drop in a file, or use the paperclip to choose one or import a photo, scan or sketch from your iPhone or iPad. Pages show inside the box, and you check your answer from it.
- **Companion faces.** The orb's light gathers into a face (happy, playful, curious, empathetic, sad, thinking, listening, proud) that follows what's being said.
- **A companion that feels alive.** A different entrance every time, small unpredictable movements while it's with you, a soft arrival sound you can turn off, and lines that don't repeat.
- **Two-choice openers.** Every appearance starts with "talk" or "not now". No close button; it takes no for an answer.
- **Quiet time.** The companion is on by default. In Settings you can turn it off for an hour, 4 hours, until tomorrow, a week, or until you turn it back on.
- **Check-ins.** Now and then, the companion drops by just to check on you. You lead the conversation, and it lasts as long as you want.
- Your own classes and your own Codex account, set up in Settings.
- A bundled Python runtime and a native PDF and OCR helper (PDFKit and Vision).

### Changed
- New installs keep their data in `~/Library/Application Support/Genesis`. Existing workspaces keep their records and custom model settings; any replaced code is backed up first.
