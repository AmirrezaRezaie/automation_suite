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
- Install deps: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
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
  export CONFLUENCE_BASE_URL="https://your-domain.atlassian.net/wiki"
  export CONFLUENCE_USERNAME="your-username"
  export CONFLUENCE_PASSWORD="your-api-token"
  export CONFLUENCE_TIMEOUT="30"
  # optional: CONFLUENCE_IS_PARENT, CONFLUENCE_MAX_CHILDREN, CONFLUENCE_MACROS
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

- Update Jira issues (labels, summary, fields, assignee):
  ```bash
  python3 -m automation.cli.update_issue \
    --add-label "oncall" \
    --remove-label "backlog" \
    --set-summary "New summary text" \
    --set-field "Custom Field 1=Some value" \
    --epic-key "PROJ-1" \
    --assignee "<accountId>" \
    --issue-type "Sub-task" \
    --jql "project = PROJ AND labels = oncall" \
    PROJ-123 PROJ-456
  ```
  You can predefine defaults in `config.json` under `defaults.update`:
  ```json
  "defaults": {
    "update": {
      "add_labels": ["oncall"],
      "remove_labels": ["backlog"],
      "fields": { "Custom Field 1": "Value" },
      "epic_key": "PROJ-1",
      "epic_field": "Epic Link",
      "summary": "Updated by automation",
      "assignee": "<accountId>",
      "issue_type": "Sub-task",
      "jql": "project = PROJ AND labels = oncall"
    }
  }
  ```
  Env overrides are supported:
  `JIRA_UPDATE_ADD_LABELS`, `JIRA_UPDATE_REMOVE_LABELS`, `JIRA_UPDATE_FIELDS` (comma `KEY=VAL` list), `JIRA_UPDATE_SUMMARY`, `JIRA_UPDATE_ASSIGNEE`, `JIRA_UPDATE_ISSUE_TYPE`, `JIRA_UPDATE_EPIC_KEY`, `JIRA_UPDATE_EPIC_FIELD`, `JIRA_UPDATE_JQL`.

- Fetch a section or macro contents from Confluence (optionally across child pages):
  ```bash
  python3 -m automation.cli.confluence_content \
    --section "Call Center" \
    --macro jira \
    --is-parent \
    https://your-domain.atlassian.net/wiki/spaces/SPACE/pages/123456/Parent+Page
  ```

- Find a Jira field id by name:
  ```bash
  python3 -m automation.cli.jira_field_id "Report Related Team"
  ```

- Fetch Jira issues referenced in a Confluence macro and update labels:
  ```bash
  python3 -m automation.cli.confluence_labeler \
    --macro jira \
    --is-parent \
    --issue-type "Task" \
    --add-label report_label \
    464175603
  ```
  Defaults can be set under `defaults.confluence_labeler` in `config.json`:
  ```json
  "defaults": {
    "confluence_labeler": {
      "macro": "jira",
      "add_labels": ["report_label"],
      "remove_labels": [],
      "issue_type": "Task"
    }
  }
  ```
  Env overrides: `CONFLUENCE_LABEL_MACRO`, `CONFLUENCE_LABEL_ADD`, `CONFLUENCE_LABEL_REMOVE`, `CONFLUENCE_LABEL_ISSUE_TYPE`.

Add `--help` to any script for all flags. All scripts are short and extensible; to add Confluence or other services, create a new service under `automation/`.
