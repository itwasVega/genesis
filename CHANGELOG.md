# Changelog

## 1.0 (53) — October 31, 2026

### Changed
- **Genesis, everywhere.** The last traces of the app's working name are gone: every file, folder, setting and Keychain entry now carries the Genesis name, and the Mac app's identifier is `com.xander.genesis`.
- **Upgrading keeps everything.** The first launch of this build quietly carries over your settings, your Canvas sign-in, your saved Canvas calendar, your records and your study history. Two things may ask once: macOS may ask again to allow notifications, and it may ask whether Genesis can use a saved Keychain item (choose Always Allow).

## 1.0 (52) — October 31, 2026

### Added
- **Genesis finds your class's past exams.** For each class, Genesis searches your school's own website for past exams and practice exams (with answer keys), review sheets, department exam archives, the professor's course pages and old syllabi, then folds them into your plan. Practice comes from real past exams, timed sets rehearse them (your professor's first), and topics that came up on past exams go first. It looks again before each exam. Nothing to set up.
- **Safe by design.** Only your school's own site is read. Homework-answer and leak sites are never touched, and nothing that looks like answers to graded homework or projects is kept.

### Changed
- **Models are Auto.** Genesis picks the AI model and strength for every job from what your account offers, and checks problems with a different model when it can. Want control? Settings › Models › Manual lets you choose each job's model and strength.

## 1.0 (51) — October 31, 2026

### Changed
- **Canvas connects with an access token first.** Setup walks you through making one in four drawn steps, white line sketches on black that show exactly where to click: Account › Settings, Approved Integrations › + New Access Token, name it Genesis › Generate Token, then copy and paste. If you copied the token, it's already waiting in the box when you come back.
- **If your school turns tokens off,** Genesis takes you to your school's own Canvas login page instead.

## 1.0 (50) — October 31, 2026

### Added
- **Meet Genesis.** The first launch opens to pure black; a small light grows into the orb, and she introduces herself. Then she walks you through setup in plain words: your name, ChatGPT (found on your Mac for you), your school's Canvas, your classes (found for you), your Canvas calendar (picked up for you), school email, the iPhone app and notifications. Replay it any time in Settings.
- **Any school.** Canvas works for every school: by access token, or your school's login page if tokens are off. Your time zone, your classes' names and the words you use for them come from you.
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
