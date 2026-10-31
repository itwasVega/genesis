# Contributing to Genesis

Thanks for helping. Genesis is a small project, so a clear bug report is often as valuable as code.

## Reporting a bug or idea

- Search [existing issues](../../issues) first.
- Use the **Bug report** or **Feature request** form. Include your macOS version, the Genesis build (Genesis › About), and which plugins you have on.
- **Never paste course material, grades, Canvas pages, emails or anything personal into an issue.** Describe what happened instead, or use made-up examples.
- Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## Making a change

1. Fork the repo and create a branch from `main` (`fix/answer-box-drop`, `feature/new-plugin`).
2. Set up the project as described in [Building from source](README.md#building-from-source).
3. Keep changes focused: one fix or feature per pull request.
4. Run the tests before you open the PR:
   ```sh
   python3 tests/test_engine.py
   python3 tests/test_policies.py
   ```
   Add a check to `tests/test_policies.py` for any new planner, grading, notes or companion behavior.
5. For UI changes, include a screenshot or short screen recording in the PR.
6. Open the pull request and fill in the template.

## Guidelines

- **Plugins stay optional.** The planner, the companion and iPhone notes are the core. A new place to gather assignments, documents, dates or announcements must be a plugin that is off until the student adds it, and must do nothing when it's off.
- **Local first.** Study records stay on the student's Mac. Don't add servers, analytics or telemetry.
- **No shipped credentials or personal data.** No API keys, accounts, course IDs, real student work or private files in the repo, tests or fixtures.
- **Honest learning signals.** Don't count something as mastered unless the student showed it. Hints, partial answers and same-day repairs are tracked separately on purpose.
- **The companion is a friend, not an assistant.** It starts conversations without asking questions, lets the student lead, takes "not now" well, never gives answers away when helping, and is always truthful that it's an AI. Read `Mac/Backend/outputs/school_hq_persona.py` before changing its voice.
- Swift: SwiftUI, macOS 15 APIs, no third-party packages. Python: standard library first; vendored packages live in `Mac/Backend/outputs/vendor` with their licenses.
- Match the surrounding style. Comments explain *why*.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
