# Lab Model Monitor

- This is an independent laboratory model monitor; Python runtime uses only the standard library and its own `.venv`.
- Preserve the fixed candy prompt, grading contract, original run IDs and timestamps. API failures, timeouts and incomplete answers must stay distinct from wrong answers.
- Never read, print, commit or publish private credential values. Runtime configuration, credentials, database and logs belong under ignored `runtime/`.
- Model calls require the configured endpoint and key. Site sync and delivery retries must never rerun model samples.
- The local database owns original evidence; Sites D1 stores the bounded display projection. Do not add a second detector or cloud schedule.
- Keep the existing Site identity in `.openai/hosting.json`. Preserve its current audience and domain unless the user requests a change.
- Run `.venv\Scripts\python.exe -m unittest discover -s tests -v` for Python changes. Typecheck and build for website changes.
- Keep changes local on the current branch; do not create worktrees. Claude review is not required for this migration.
