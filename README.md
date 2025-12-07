# Scripts

A simple structure for Jira automation scripts.

## Structure
- `automation/settings.py`: Configuration and environment variable loading.
- `automation/utils.py`: Shared helpers (reading issues, building URLs, etc.).
 - `automation/jira/client.py`: Jira connection setup and HTTP wrapper (no external SDK).
 - `automation/jira/service.py`: Core Jira logic (listing issues, fetching fields, transitions).
- `automation/cli/*.py`: Ready-to-run CLI entry points.

The Jira client is now a lightweight REST wrapper built on `requests`; no external SDK is required.

## Setup
- Install deps (only `requests`): `python3 -m venv .venv && source .venv/bin/activate && pip install requests`
- Configure credentials and defaults:
  - Copy `config.example.json` to `config.json` and fill in Jira URL, user, API token/password, timeout, project key, queue id, service desk id, default fields, grouping keywords, and status names.
  - Optionally point to a different file with `JIRA_CONFIG_FILE=/path/to/config.json`.
  - CLI flags override env vars; env vars override config values.
- Export env vars in your shell (or add to `~/.zshrc` and `source` it):
  ```bash
  export JIRA_BASE_URL="https://your-jira-domain.atlassian.net"
  export JIRA_USERNAME="your-username"
  export JIRA_PASSWORD="your-password"
  export JIRA_TIMEOUT="30"
  # optional: JIRA_PROJECT, JIRA_QUEUE_ID, JIRA_SERVICE_DESK_ID
  ```
- Run commands from the repo root. Prefer the module form so Python finds the package:
  `python3 -m automation.cli.<script> ...`

## CLI examples
- List open issues in a queue (filter by multiple statuses):
  ```bash
  python3 -m automation.cli.list_issues \
    --project <PROJECT_KEY> \
    --queue-id <QUEUE_ID> \
    --status "Open" \
    --status "Waiting"
  ```

- Transition issues to a target status (accepts multiple keys or `--file`):
  ```bash
  python3 -m automation.cli.transition_status \
    --target-status "Resolved" --only-status "Waiting for support" \
    <PROJECT_KEY>-3208 <PROJECT_KEY>-3210
  ```

Add `--help` to any script for all flags. All scripts are short and extensible; to add Confluence or other services, create a new service under `automation/`.
