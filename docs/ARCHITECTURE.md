# How Genesis fits together

Genesis is two programs that share a folder: a native SwiftUI app and a Python backend that the app runs on a bundled interpreter.

```
┌──────────────────────── Genesis.app ────────────────────────┐
│ SwiftUI (Mac/Source)                                        │
│  Today · Task · AnswerComposer · Practice · Library         │
│  Companion + OrbRenderer (Metal)   PluginsView   Settings   │
│  LocalCanvas: a hidden WKWebView that reads Canvas          │
│        │ runScript(...)  JSON over stdin/stdout              │
│        ▼                                                    │
│ Python 3.12 (Contents/Resources/Python)                     │
│  Backend copied to ~/Library/Application Support/Genesis    │
└─────────────────────────────────────────────────────────────┘
```

## The daily loop

1. **Collect.** With the Canvas plugin, `LocalCanvas.swift` and `CanvasStructured.js` read each class read-only from the school's Canvas, through the student's own signed-in session or an access token they made. `school_hq_local_worker.py` runs the optional plugins (calendar, email) only when they're on.
2. **Catalog.** `school_hq_catalog.py` reads practice files once and lists each problem with its page (`school_hq_pdf.py` calls the native `GenesisPDF` helper).
3. **Plan.** `school_hq_engine.py` and `school_hq_planning.py` find what's due, what each assessment covers, and which topics aren't mastered (`new → practiced → independent → retained`). `paced_quota` spreads topics across the days left so nothing lands the night before.
4. **Generate and verify.** Problems are written in the professor's format, then solved independently by a separate session against a private rubric (`school_hq_verification.py`).
5. **Grade.** `school_hq_grader.py` checks typed answers and pages of handwritten work. `school_hq_coaching.py` records honest evidence: independent, supported (used a hint), partial, repaired the same day, or incorrect.

## Notes

`school_hq_context.py` turns notes into labeled chips (missed class, a reported date, scope, struggling). Rapid-fire messages from the phone arrive as a session and are combined using context before they change the plan.

## First launch

`Setup.swift` is the black-window welcome and the guided setup. The same steps open when a plugin is added later, so nothing needs a trip into Settings. Classes come from the Canvas API (`findCourses`), and the calendar feed from the student's Canvas profile.

## The companion

`Companion.swift` decides *when* the orb appears (a new plan, stuck on a task, about to drift, done for the day, a check-in) and how it moves. `school_hq_companion.py` decides *what* it says: help that never gives the answer away, remarks after grading, and chats in the student's own register. The character and its judgment live in `school_hq_persona.py`. Each reply carries a `mood`, which `OrbRenderer.swift` eases into a face drawn from the orb's interior light.

## Plugins

`GenesisConfiguration.swift` and `school_hq_connections.py` read the same `connections.json`. Plugins are sources for the brief. Each is checked where its work happens (sync, and the worker's optional sources), so a plugin that's off does nothing at all. The companion and iPhone notes aren't plugins: they're part of Genesis, and phone notes start working the first time one arrives.

## The iPhone app

`iOS/` writes notes to a durable outbox in the student's iCloud Drive folder; the Mac imports them and publishes the class list back. Delivery uses exact batches and nonce-checked callbacks, so notes are never lost or replayed.
