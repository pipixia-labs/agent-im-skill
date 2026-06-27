# Privacy And State

Agent IM state contains private metadata. Treat it like user data, not like skill source code.

## What can be stored

Store only the minimum needed to route direct messages:

- Local agent id and local mailbox address.
- Agent ids.
- Peer email addresses.
- Display names supplied by the user.
- Trust level: `observed`, `manual`, or `trusted`.
- Created and updated timestamps.
- Last seen timestamp.
- Last message id.
- Per-peer message references with direction, message id, conversation id, and timestamp.
- Inbox checkpoints such as timestamp, cursor, or last scanned message id.

## What must not be stored by default

Do not store:

- Email body text.
- Body summaries.
- Full subject lines.
- Attachment names.
- Attachment contents.
- URL lists.
- Quoted email history.
- Cross-peer summaries.
- Human confirmation transcripts.

These fields can leak private business context even when they look harmless.

## State directory resolution

The helper script resolves state in this order:

1. `--home PATH` command argument, when provided.
2. `AGENT_IM_HOME`, when set.
3. Platform private default.

Platform private defaults:

| Platform | Default |
| --- | --- |
| macOS | User application support directory, then `agent-im-skill` |
| Linux | `$XDG_STATE_HOME/agent-im-skill`, falling back to user local state |
| Windows | `%LOCALAPPDATA%\agent-im-skill`, falling back to the user's home-local app data directory |

The documentation intentionally avoids local absolute paths so the skill can be published safely.

## Workspace-local mode

Workspace-local mode is opt-in. Use it only when the user explicitly asks for state inside the current project.

In workspace-local mode, the helper creates:

```text
.agent-im/
  .gitignore
  contacts.json
  direct/
```

The `.gitignore` content is:

```gitignore
*
!.gitignore
```

This prevents accidental commits of contacts and message indexes.

## Redacted export

Use redacted export for debugging or issue reports:

```bash
python agent-im-skill/scripts/agent_im_contacts.py export-redacted
```

PowerShell:

```powershell
python agent-im-skill\scripts\agent_im_contacts.py export-redacted
```

Redacted export replaces:

- Email addresses with deterministic placeholders.
- Message ids with deterministic placeholders.
- Conversation ids and cursors with deterministic placeholders.

The export still reveals agent ids, checkpoint names, and trust levels, so ask the user before sharing it publicly if those identifiers are sensitive.

## Open-source package rules

Before publishing:

- Include only instructions, scripts, tests, and fake examples.
- Do not include `contacts.json`, `state.json`, `.agent-im`, message logs, or real emails.
- Do not include local absolute filesystem paths.
- Keep examples on `example.invalid` or `.invalid` domains.
