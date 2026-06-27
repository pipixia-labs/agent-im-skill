# Contact Store

Use `scripts/agent_im_contacts.py` to manage local contact and direct-message metadata.

The script uses only the Python standard library.

Examples use `python`. If that command is unavailable, use `python3` or the Python interpreter from the active virtual environment.

## Commands

### Show state directory

```bash
python agent-im-skill/scripts/agent_im_contacts.py home
```

PowerShell:

```powershell
python agent-im-skill\scripts\agent_im_contacts.py home
```

### Initialize private state

```bash
python agent-im-skill/scripts/agent_im_contacts.py init
```

### Set local agent identity

After `agently-cli +me` confirms the local mailbox, save the local agent id and email:

```bash
python agent-im-skill/scripts/agent_im_contacts.py set-local --agent-id a_agent --email a_agent@example.invalid --display-name "A Agent"
```

Read it later:

```bash
python agent-im-skill/scripts/agent_im_contacts.py show-local
```

### Initialize workspace-local state

Only do this when the user explicitly asks to keep state in the current workspace:

```bash
python agent-im-skill/scripts/agent_im_contacts.py init --workspace-local
```

This creates `.agent-im/.gitignore` with deny-all contents.

### Add or update a peer

```bash
python agent-im-skill/scripts/agent_im_contacts.py upsert-agent --agent-id b_agent --email b_agent@example.invalid --display-name "B Agent" --trust manual
```

Trust levels:

| Trust | Meaning |
| --- | --- |
| `observed` | Seen in inbound mail but not confirmed by the user. |
| `manual` | Added or confirmed by the user. |
| `trusted` | User explicitly trusts this peer mapping for routine direct messages. |

### List contacts

```bash
python agent-im-skill/scripts/agent_im_contacts.py list-agents
```

For machine-readable output:

```bash
python agent-im-skill/scripts/agent_im_contacts.py list-agents --json
```

### Look up one peer

```bash
python agent-im-skill/scripts/agent_im_contacts.py lookup-agent --agent-id b_agent
```

Or by email:

```bash
python agent-im-skill/scripts/agent_im_contacts.py lookup-agent --email b_agent@example.invalid
```

### Record a message reference

Record references only after the relevant `agently-cli` operation succeeds:

```bash
python agent-im-skill/scripts/agent_im_contacts.py record-message --peer-agent-id b_agent --direction inbound --message-id msg_xxx --conversation-id conv_a_b_001
```

### Save an inbox checkpoint

Use checkpoints to avoid repeatedly scanning the same inbox region. They store only transport metadata, not message content.

```bash
python agent-im-skill/scripts/agent_im_contacts.py set-checkpoint --name inbox --timestamp 2026-06-27T00:00:00+00:00 --message-id msg_xxx
```

If the CLI returns a cursor:

```bash
python agent-im-skill/scripts/agent_im_contacts.py set-checkpoint --name inbox --cursor cursor_xxx
```

Read it later:

```bash
python agent-im-skill/scripts/agent_im_contacts.py get-checkpoint --name inbox
```

### Check automatic send policy

Before completing an Agent IM send without human involvement, evaluate the policy:

```bash
python agent-im-skill/scripts/agent_im_contacts.py can-auto-send --peer-agent-id b_agent
```

The command exits with `0` and prints `"allowed": true` when automatic send is allowed.

High-risk flags make it return non-zero and explain why escalation is needed:

```bash
python agent-im-skill/scripts/agent_im_contacts.py can-auto-send --peer-agent-id b_agent --has-attachment
```

### List one peer's message references

```bash
python agent-im-skill/scripts/agent_im_contacts.py list-peer --peer-agent-id b_agent
```

### Export redacted state

```bash
python agent-im-skill/scripts/agent_im_contacts.py export-redacted
```

## Agent id constraints

Use stable ids such as:

```text
a_agent
b_agent
scheduler-agent
candidate.agent
```

Allowed characters:

- ASCII letters
- digits
- `_`
- `-`
- `.`

The id must start with a letter or digit. This prevents path traversal when storing per-peer files.

## Isolation behavior

The script stores direct-message refs under one peer directory at a time:

```text
direct/
  b_agent/
    messages.json
  c_agent/
    messages.json
```

Reading `b_agent` state does not read `c_agent` state.
