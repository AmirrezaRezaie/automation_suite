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
    --project SREAUTO \
    --queue-id 213 \
    --status "Waiting for Support" \
    --status "Waiting"
  ```

- Transition issues to a target status (accepts multiple keys or `--file`):
  ```bash
  python3 -m automation.cli.transition_status \
    --target-status "Resolved" \
    SREAUTO-3208 SREAUTO-3210
  ```

- Fetch monitoring dependencies for an issue:
  ```bash
  python3 -m automation.cli.monitoring_deps SREAUTO-3208
  ```

Add `--help` to any script for all flags. All scripts are short and extensible; to add Confluence or other services, create a new service under `automation/`.
