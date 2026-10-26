# paperwatch / ourak

## Two separate systems here

- **Lab Watch** (`app/lab_watch.py`, `.github/workflows/lab-watch.yml` + `lab-watch-daily.yml`) — the active one. Tracks papers authored by lab members and papers citing the lab's work.
- **Paper Watch Digest** (`app/main.py`, `.github/workflows/digest.yml`) — the older topic-keyword discovery pipeline. **Disabled** in GitHub Actions (`gh workflow disable`) since it isn't used anymore. Don't re-enable it or invest effort fixing it without checking first; its code is kept working but dormant.

## The Slack bot sends exactly two kinds of message. Nothing else.

1. A **daily reminder** when a new lab-authored paper is found (`lab-watch-daily.yml`, `app.lab_watch`'s "New from the lab" message).
2. A **weekly digest link** — never an itemized list of papers. Citations get too noisy to post individually (dozens a week), so they're rendered to a static page and Slack gets a one-line pointer to it (`build_citation_pointer_message` in `app/slack.py`, posted to `LAB_CITATIONS_URL`). If the (disabled) discovery pipeline is ever revived, it follows the same rule — `build_digest_pointer_message`, not a paper list.

If you're adding or changing anything that touches `post_to_slack`, check it still only produces one of these two message shapes. Don't add a new message type without the user asking for it explicitly — the channel has deliberately been kept to just these two.

## Don't debug by sending real messages

If the bot is broken and you're iterating on a fix, do not run the pipeline for real against the production webhook to "see if it works now." A bug in the middle of a fix can mean the bot sends something half-correct (or the full old-style list, or neither of the two shapes above) straight to the channel — which is exactly what caused the confusion this guideline exists to prevent.

Instead:
- `python -m app.lab_watch --dry-run` — prints the digest, touches nothing, no Slack call at all.
- `gh workflow run lab-watch.yml -f dry_run=true` / `lab-watch-daily.yml -f dry_run=true` — same, via Actions.
- Mock `post_to_slack` in tests rather than calling it live.
- Only run for real (`dry_run=false` / no flag) once you're confident the change is correct, and say so before doing it.
