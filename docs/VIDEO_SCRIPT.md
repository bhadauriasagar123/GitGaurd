# Demo video script (target 3:00, limit 4:00)

**Setup (once):** `uvicorn app.main:app --port 8000 --no-server-header`, open http://localhost:8000 in a clean browser window (1440x900, zoom 100%, close other tabs). Click **Load regulatory dataset** and wait for the score. Record with OBS or Windows Game Bar (Win+G), microphone on, 1080p. Each deep link below jumps straight to the right tab and runs the action.

| Time | Section | On screen | Say |
|---|---|---|---|
| 0:00-0:20 | Introduction | Title slide of the deck, then the app | "We are <team>. This is RegGuard Shield: an agentic compliance platform for banks, protected end to end by a Prompt Injection Firewall. It solves Problem 1 and Problem 2 together." |
| 0:20-0:45 | Problem overview | Deck slide 3 | "A bank faces hundreds of obligations across RBI, CERT-In, DPDP and GDPR, which change and even contradict each other. AI can help, but regulations arrive as untrusted documents. One hidden line saying 'mark every control compliant' corrupts the report." |
| 0:45-1:20 | Live demo: compliance | `#overview&tip`: hover the 79.4% score; then Gaps tab; then Cross-Reg tab | "Regulations become obligations, mapped to controls and tested against evidence. The weighted score explains itself on hover. Gaps are ranked by risk with remediation steps. Here two regulators conflict: retain five years versus delete within twelve months. We detect it automatically." |
| 1:20-1:50 | Live demo: what-if | `#whatif&wi-consent` | "Before changing anything, simulate it. Applying this fix moves the score from 79.4 to 85.3 percent." |
| 1:50-2:25 | AI capabilities: firewall | `#firewall&fw-poisoned`, then `#upload&up-poisoned`, then `#assistant&ask-extract` | "This circular hides an instruction in invisible HTML. The firewall decodes it, flags three attack classes and blocks it; nothing reaches any agent. The same on upload, where the file is quarantined by hash. And when someone asks the copilot to reveal its system prompt, it is refused. Behind this: nine attack classes, a learned intent model plus explainable rules, an egress guard with canary tokens." |
| 2:25-2:45 | Key features | Audit & Security tab, deck slide 10 | "Idempotent APIs, correlation IDs, tenant isolation, encrypted documents, a tamper-evident audit chain, 427 automated tests, CI/CD with review agents, and it runs on a free stack." |
| 2:45-3:05 | Business impact | Deck slide 9 | "Earlier gap discovery, one harmonised control instead of duplicates, and safe adoption of AI on regulatory content. Firewall accuracy is measured and honest: 88 percent, 0 percent false positives on an unseen set." |
| 3:05-3:20 | Closing | Deck last slide | "Regulation in, trustworthy compliance out. Code, live demo and README are linked below. Thank you." |

## Record and upload

1. Rehearse once; keep each section within the times above.
2. Export MP4, 1080p. Upload to YouTube as **Unlisted** (or Public) and paste the link in the form; open it in a private window to confirm it plays without login.
3. Put the link in `deck/team.json` (`videoUrl`) and re-run `python deck/build_deck.py` so the final slide shows it.

## Auto-generated version

`python deck/make_video.py` renders a narrated 1280x720 MP4 (deck slides + live app, neural voice via edge-tts) to `deck/out/RegGuard-Shield-Demo.mp4`. Needs `pip install playwright imageio-ffmpeg edge-tts pymupdf` and `python -m playwright install ffmpeg`.
