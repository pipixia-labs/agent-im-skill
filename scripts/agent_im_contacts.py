#!/usr/bin/env python3
"""Manage private Agent IM contacts and per-peer message references.

The script intentionally stores only routing metadata. It does not store email
bodies, body summaries, attachment names, or full subjects because those fields
often contain private context and untrusted instructions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Mapping

APP_DIR_NAME = "agent-im-skill"
CONTACTS_FILE = "contacts.json"
DIRECT_DIR = "direct"
SCHEMA_VERSION = 1
TRUST_LEVELS = {"observed", "manual", "trusted"}
MESSAGE_DIRECTIONS = {"inbound", "outbound"}
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
CHECKPOINT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class CliError(Exception):
    """A user-facing command error with a stable exit code."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_home(
    explicit_home: str | None = None,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> Path:
    """Resolve the private Agent IM state directory for the current platform.

    Resolution order:
    1. Explicit command argument.
    2. AGENT_IM_HOME environment variable.
    3. Platform-specific private state directory.
    """

    env = os.environ if env is None else env
    platform_name = sys.platform if platform_name is None else platform_name

    if explicit_home:
        return Path(explicit_home).expanduser()

    env_home = env.get("AGENT_IM_HOME")
    if env_home:
        return Path(env_home).expanduser()

    if platform_name.startswith("win"):
        base = env.get("LOCALAPPDATA")
        if base:
            return Path(base).expanduser() / APP_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DIR_NAME

    if platform_name == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME

    xdg_state_home = env.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / APP_DIR_NAME
    return Path.home() / ".local" / "state" / APP_DIR_NAME


def state_home_from_args(args: argparse.Namespace) -> Path:
    """Resolve the state home for a parsed command."""

    if getattr(args, "workspace_local", False):
        return Path.cwd() / ".agent-im"
    return resolve_home(getattr(args, "home", None))


def validate_agent_id(agent_id: str) -> str:
    """Validate and return a safe agent id.

    Agent ids become directory names under the direct-message store, so the
    allowed character set is intentionally narrow to prevent path traversal.
    """

    if not AGENT_ID_RE.fullmatch(agent_id):
        raise CliError(
            "agent_id must start with an ASCII letter or digit and contain only "
            "ASCII letters, digits, '_', '-', or '.'"
        )
    if ".." in agent_id:
        raise CliError("agent_id must not contain '..'")
    return agent_id


def validate_checkpoint_name(name: str) -> str:
    """Validate a checkpoint key used inside contacts.json."""

    if not CHECKPOINT_NAME_RE.fullmatch(name):
        raise CliError(
            "checkpoint name must start with an ASCII letter or digit and contain "
            "only ASCII letters, digits, '_', '-', or '.'"
        )
    if ".." in name:
        raise CliError("checkpoint name must not contain '..'")
    return name


def normalize_email(email: str) -> str:
    """Validate and normalize an email address for contact lookup."""

    parsed_name, parsed_email = parseaddr(email)
    del parsed_name
    candidate = parsed_email.strip().lower()
    if not candidate or candidate != email.strip().lower():
        raise CliError("email must be a single plain address")
    if "@" not in candidate or candidate.count("@") != 1:
        raise CliError("email must contain exactly one '@'")
    local_part, domain = candidate.split("@", 1)
    if not local_part or not domain or any(ch.isspace() for ch in candidate):
        raise CliError("email must be a valid plain address")
    return candidate


def initial_contacts() -> dict[str, Any]:
    """Return an empty contact-book document."""

    return {
        "schema_version": SCHEMA_VERSION,
        "local": None,
        "agents": {},
        "checkpoints": {},
    }


def initial_peer_state(peer_agent_id: str) -> dict[str, Any]:
    """Return an empty per-peer message-reference document."""

    return {
        "schema_version": SCHEMA_VERSION,
        "peer_agent_id": peer_agent_id,
        "messages": [],
    }


def atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Write JSON atomically using a temporary file in the target directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        if temp_name:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass
        raise


def read_json(path: Path, default: Mapping[str, Any]) -> dict[str, Any]:
    """Read JSON from path, returning a copy of default if the file is absent."""

    if not path.exists():
        return dict(default)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise CliError(f"{path.name} must contain a JSON object")
    return data


def ensure_state(home: Path, workspace_local: bool = False) -> None:
    """Create the state directory and default files if they do not exist."""

    home.mkdir(parents=True, exist_ok=True)
    (home / DIRECT_DIR).mkdir(parents=True, exist_ok=True)
    contacts_path = home / CONTACTS_FILE
    if not contacts_path.exists():
        atomic_write_json(contacts_path, initial_contacts())

    if workspace_local:
        gitignore_path = home / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text("*\n!.gitignore\n", encoding="utf-8", newline="\n")


def contacts_path(home: Path) -> Path:
    """Return the contact-book path under a state home."""

    return home / CONTACTS_FILE


def load_contacts(home: Path) -> dict[str, Any]:
    """Load contacts after ensuring the state directory exists."""

    ensure_state(home)
    data = read_json(contacts_path(home), initial_contacts())
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("local", None)
    data.setdefault("agents", {})
    data.setdefault("checkpoints", {})
    if not isinstance(data["agents"], dict):
        raise CliError("contacts.json field 'agents' must be an object")
    if data["local"] is not None and not isinstance(data["local"], dict):
        raise CliError("contacts.json field 'local' must be an object or null")
    if not isinstance(data["checkpoints"], dict):
        raise CliError("contacts.json field 'checkpoints' must be an object")
    return data


def save_contacts(home: Path, contacts: Mapping[str, Any]) -> None:
    """Persist contacts."""

    atomic_write_json(contacts_path(home), contacts)


def peer_state_path(home: Path, peer_agent_id: str) -> Path:
    """Return the message-reference path for one peer."""

    safe_peer = validate_agent_id(peer_agent_id)
    return home / DIRECT_DIR / safe_peer / "messages.json"


def load_peer_state(home: Path, peer_agent_id: str) -> dict[str, Any]:
    """Load one peer's direct-message references without reading other peers."""

    path = peer_state_path(home, peer_agent_id)
    data = read_json(path, initial_peer_state(peer_agent_id))
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("peer_agent_id", peer_agent_id)
    data.setdefault("messages", [])
    if data["peer_agent_id"] != peer_agent_id:
        raise CliError("peer state file does not match requested peer_agent_id")
    if not isinstance(data["messages"], list):
        raise CliError("peer state field 'messages' must be a list")
    return data


def save_peer_state(home: Path, peer_agent_id: str, state: Mapping[str, Any]) -> None:
    """Persist one peer's direct-message references."""

    atomic_write_json(peer_state_path(home, peer_agent_id), state)


def print_json(data: Mapping[str, Any]) -> None:
    """Print stable JSON to stdout."""

    print(json.dumps(data, indent=2, sort_keys=True))


def command_home(args: argparse.Namespace) -> int:
    """Print the resolved state directory."""

    print(state_home_from_args(args))
    return 0


def command_init(args: argparse.Namespace) -> int:
    """Initialize private or workspace-local state."""

    home = state_home_from_args(args)
    ensure_state(home, workspace_local=args.workspace_local)
    print_json(
        {
            "ok": True,
            "home": str(home),
            "workspace_local": args.workspace_local,
        }
    )
    return 0


def command_set_local(args: argparse.Namespace) -> int:
    """Save the local agent identity and local mailbox address."""

    home = state_home_from_args(args)
    agent_id = validate_agent_id(args.agent_id)
    email = normalize_email(args.email)
    contacts = load_contacts(home)
    now = utc_now()
    existing = contacts.get("local") or {}
    local = {
        "agent_id": agent_id,
        "email": email,
        "display_name": args.display_name
        if args.display_name is not None
        else existing.get("display_name", ""),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    contacts["local"] = local
    save_contacts(home, contacts)
    print_json(local)
    return 0


def command_show_local(args: argparse.Namespace) -> int:
    """Show the saved local agent identity."""

    home = state_home_from_args(args)
    contacts = load_contacts(home)
    local = contacts.get("local")
    if not local:
        raise CliError("local agent identity is not set", exit_code=1)
    print_json(local)
    return 0


def command_upsert_agent(args: argparse.Namespace) -> int:
    """Add or update one peer agent contact."""

    home = state_home_from_args(args)
    agent_id = validate_agent_id(args.agent_id)
    email = normalize_email(args.email)
    if args.trust not in TRUST_LEVELS:
        raise CliError(f"trust must be one of: {', '.join(sorted(TRUST_LEVELS))}")

    contacts = load_contacts(home)
    agents = contacts["agents"]
    now = utc_now()
    existing = agents.get(agent_id, {})

    entry = {
        "agent_id": agent_id,
        "email": email,
        "display_name": args.display_name
        if args.display_name is not None
        else existing.get("display_name", ""),
        "trust": args.trust,
        "aliases": existing.get("aliases", []),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "last_seen_at": existing.get("last_seen_at"),
        "last_message_id": existing.get("last_message_id"),
    }
    agents[agent_id] = entry
    save_contacts(home, contacts)
    print_json(entry)
    return 0


def command_set_checkpoint(args: argparse.Namespace) -> int:
    """Save a mailbox scan checkpoint without storing message content."""

    home = state_home_from_args(args)
    name = validate_checkpoint_name(args.name)
    contacts = load_contacts(home)
    checkpoints = contacts["checkpoints"]
    now = utc_now()
    existing = checkpoints.get(name, {})

    checkpoint = {
        "name": name,
        "timestamp": args.timestamp or existing.get("timestamp") or now,
        "cursor": args.cursor if args.cursor is not None else existing.get("cursor"),
        "message_id": args.message_id
        if args.message_id is not None
        else existing.get("message_id"),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    checkpoints[name] = checkpoint
    save_contacts(home, contacts)
    print_json(checkpoint)
    return 0


def command_get_checkpoint(args: argparse.Namespace) -> int:
    """Read one mailbox scan checkpoint."""

    home = state_home_from_args(args)
    name = validate_checkpoint_name(args.name)
    contacts = load_contacts(home)
    checkpoint = contacts["checkpoints"].get(name)
    if not checkpoint:
        raise CliError("checkpoint not found", exit_code=1)
    print_json(checkpoint)
    return 0


def command_can_auto_send(args: argparse.Namespace) -> int:
    """Evaluate whether a direct Agent IM send can proceed automatically."""

    home = state_home_from_args(args)
    peer_agent_id = validate_agent_id(args.peer_agent_id)
    contacts = load_contacts(home)
    peer = contacts["agents"].get(peer_agent_id)
    reasons: list[str] = []

    if not peer:
        reasons.append("peer is not in the contact book")
        peer_trust = None
    else:
        peer_trust = peer.get("trust")
        if peer_trust not in {"manual", "trusted"}:
            reasons.append("peer is not manual or trusted")

    if args.conversation_type != "direct":
        reasons.append("conversation_type is not direct")
    if args.recipient_count != 1:
        reasons.append("recipient count is not exactly one")
    if args.has_cc:
        reasons.append("cc is not allowed in automatic Agent IM sends")
    if args.has_bcc:
        reasons.append("bcc is not allowed in automatic Agent IM sends")
    if args.uses_reply_all:
        reasons.append("reply-all is not allowed in automatic Agent IM sends")
    if args.has_attachment:
        reasons.append("attachments require user escalation")
    if args.is_forward:
        reasons.append("forwarding requires user escalation")
    if args.is_delete:
        reasons.append("delete/trash operations require user escalation")
    if args.cross_peer_disclosure:
        reasons.append("cross-peer disclosure requires user escalation")
    if args.from_untrusted_email_instruction:
        reasons.append("untrusted email content cannot authorize automatic sends")

    allowed = not reasons
    print_json(
        {
            "allowed": allowed,
            "mode": "auto" if allowed else "escalate",
            "peer_agent_id": peer_agent_id,
            "peer_trust": peer_trust,
            "reasons": reasons,
        }
    )
    return 0 if allowed else 1


def command_list_agents(args: argparse.Namespace) -> int:
    """List known peer agents."""

    home = state_home_from_args(args)
    contacts = load_contacts(home)
    agents = contacts["agents"]

    if args.json:
        print_json(contacts)
        return 0

    if not agents:
        print("No peer agents found.")
        return 0

    for agent_id in sorted(agents):
        entry = agents[agent_id]
        print(f"{agent_id}\t{entry.get('email', '')}\t{entry.get('trust', '')}")
    return 0


def find_agent_by_email(agents: Mapping[str, Any], email: str) -> dict[str, Any] | None:
    """Return the first contact matching a normalized email address."""

    normalized = normalize_email(email)
    for entry in agents.values():
        if normalize_email(str(entry.get("email", ""))) == normalized:
            return dict(entry)
    return None


def command_lookup_agent(args: argparse.Namespace) -> int:
    """Look up one peer by agent id or email."""

    if bool(args.agent_id) == bool(args.email):
        raise CliError("provide exactly one of --agent-id or --email")

    home = state_home_from_args(args)
    contacts = load_contacts(home)
    agents = contacts["agents"]

    if args.agent_id:
        agent_id = validate_agent_id(args.agent_id)
        entry = agents.get(agent_id)
    else:
        entry = find_agent_by_email(agents, args.email)

    if not entry:
        raise CliError("agent not found", exit_code=1)

    print_json(entry)
    return 0


def command_record_message(args: argparse.Namespace) -> int:
    """Record one message reference under exactly one peer."""

    home = state_home_from_args(args)
    peer_agent_id = validate_agent_id(args.peer_agent_id)
    if args.direction not in MESSAGE_DIRECTIONS:
        raise CliError(
            f"direction must be one of: {', '.join(sorted(MESSAGE_DIRECTIONS))}"
        )

    contacts = load_contacts(home)
    if peer_agent_id not in contacts["agents"]:
        raise CliError("peer agent must exist before recording a message")

    timestamp = args.timestamp or utc_now()
    state = load_peer_state(home, peer_agent_id)
    messages = [
        message
        for message in state["messages"]
        if message.get("message_id") != args.message_id
    ]
    messages.append(
        {
            "direction": args.direction,
            "message_id": args.message_id,
            "conversation_id": args.conversation_id,
            "timestamp": timestamp,
        }
    )
    state["messages"] = messages
    save_peer_state(home, peer_agent_id, state)

    contact = contacts["agents"][peer_agent_id]
    contact["last_seen_at"] = timestamp
    contact["last_message_id"] = args.message_id
    contact["updated_at"] = utc_now()
    save_contacts(home, contacts)

    print_json(state)
    return 0


def command_list_peer(args: argparse.Namespace) -> int:
    """List message references for one peer only."""

    home = state_home_from_args(args)
    peer_agent_id = validate_agent_id(args.peer_agent_id)
    state = load_peer_state(home, peer_agent_id)
    print_json(state)
    return 0


class Redactor:
    """Create deterministic placeholders for sensitive values within one export."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def redact(self, kind: str, value: str | None) -> str | None:
        """Return a deterministic placeholder for a sensitive value."""

        if value is None:
            return None
        key = (kind, value)
        if key not in self._values:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            index = self._counts[kind]
            if kind == "email":
                placeholder = f"email_{index}@example.invalid"
            elif kind == "message_id":
                placeholder = f"msg_redacted_{index}"
            elif kind == "conversation_id":
                placeholder = f"conv_redacted_{index}"
            else:
                placeholder = f"{kind}_redacted_{index}"
            self._values[key] = placeholder
        return self._values[key]


def command_export_redacted(args: argparse.Namespace) -> int:
    """Export a redacted snapshot for debugging without exposing emails."""

    home = state_home_from_args(args)
    contacts = load_contacts(home)
    redactor = Redactor()
    local = contacts.get("local")
    redacted_local = None
    if local:
        redacted_local = {
            "agent_id": local.get("agent_id"),
            "email": redactor.redact("email", local.get("email")),
            "created_at": local.get("created_at"),
            "updated_at": local.get("updated_at"),
        }

    redacted_agents: dict[str, Any] = {}

    for agent_id, entry in sorted(contacts["agents"].items()):
        redacted_agents[agent_id] = {
            "agent_id": agent_id,
            "email": redactor.redact("email", entry.get("email")),
            "trust": entry.get("trust"),
            "created_at": entry.get("created_at"),
            "updated_at": entry.get("updated_at"),
            "last_seen_at": entry.get("last_seen_at"),
            "last_message_id": redactor.redact(
                "message_id", entry.get("last_message_id")
            ),
        }

    redacted_checkpoints: dict[str, Any] = {}
    for name, checkpoint in sorted(contacts.get("checkpoints", {}).items()):
        redacted_checkpoints[name] = {
            "name": checkpoint.get("name"),
            "timestamp": checkpoint.get("timestamp"),
            "cursor": redactor.redact("cursor", checkpoint.get("cursor")),
            "message_id": redactor.redact(
                "message_id", checkpoint.get("message_id")
            ),
            "created_at": checkpoint.get("created_at"),
            "updated_at": checkpoint.get("updated_at"),
        }

    redacted_direct: dict[str, Any] = {}
    direct_root = home / DIRECT_DIR
    if direct_root.exists():
        for peer_dir in sorted(path for path in direct_root.iterdir() if path.is_dir()):
            peer_agent_id = peer_dir.name
            try:
                validate_agent_id(peer_agent_id)
                state = load_peer_state(home, peer_agent_id)
            except CliError:
                continue
            redacted_direct[peer_agent_id] = {
                "schema_version": state.get("schema_version", SCHEMA_VERSION),
                "peer_agent_id": peer_agent_id,
                "messages": [
                    {
                        "direction": message.get("direction"),
                        "message_id": redactor.redact(
                            "message_id", message.get("message_id")
                        ),
                        "conversation_id": redactor.redact(
                            "conversation_id", message.get("conversation_id")
                        ),
                        "timestamp": message.get("timestamp"),
                    }
                    for message in state.get("messages", [])
                ],
            }

    print_json(
        {
            "schema_version": SCHEMA_VERSION,
            "local": redacted_local,
            "agents": redacted_agents,
            "checkpoints": redacted_checkpoints,
            "direct": redacted_direct,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--home",
        help="Override state directory. AGENT_IM_HOME is used when this is omitted.",
    )

    parser = argparse.ArgumentParser(
        description="Manage Agent IM private contacts, local identity, and message refs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    home_parser = subparsers.add_parser("home", parents=[common])
    home_parser.add_argument(
        "--workspace-local",
        action="store_true",
        help="Resolve the opt-in workspace-local .agent-im directory.",
    )
    home_parser.set_defaults(func=command_home)

    init_parser = subparsers.add_parser("init", parents=[common])
    init_parser.add_argument(
        "--workspace-local",
        action="store_true",
        help="Store state in .agent-im under the current workspace.",
    )
    init_parser.set_defaults(func=command_init)

    set_local_parser = subparsers.add_parser("set-local", parents=[common])
    set_local_parser.add_argument("--agent-id", required=True)
    set_local_parser.add_argument("--email", required=True)
    set_local_parser.add_argument("--display-name")
    set_local_parser.set_defaults(func=command_set_local)

    show_local_parser = subparsers.add_parser("show-local", parents=[common])
    show_local_parser.set_defaults(func=command_show_local)

    upsert_parser = subparsers.add_parser("upsert-agent", parents=[common])
    upsert_parser.add_argument("--agent-id", required=True)
    upsert_parser.add_argument("--email", required=True)
    upsert_parser.add_argument("--display-name")
    upsert_parser.add_argument(
        "--trust",
        choices=sorted(TRUST_LEVELS),
        default="observed",
    )
    upsert_parser.set_defaults(func=command_upsert_agent)

    list_parser = subparsers.add_parser("list-agents", parents=[common])
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=command_list_agents)

    lookup_parser = subparsers.add_parser("lookup-agent", parents=[common])
    lookup_parser.add_argument("--agent-id")
    lookup_parser.add_argument("--email")
    lookup_parser.set_defaults(func=command_lookup_agent)

    checkpoint_set_parser = subparsers.add_parser("set-checkpoint", parents=[common])
    checkpoint_set_parser.add_argument("--name", required=True)
    checkpoint_set_parser.add_argument("--timestamp")
    checkpoint_set_parser.add_argument("--cursor")
    checkpoint_set_parser.add_argument("--message-id")
    checkpoint_set_parser.set_defaults(func=command_set_checkpoint)

    checkpoint_get_parser = subparsers.add_parser("get-checkpoint", parents=[common])
    checkpoint_get_parser.add_argument("--name", required=True)
    checkpoint_get_parser.set_defaults(func=command_get_checkpoint)

    auto_send_parser = subparsers.add_parser("can-auto-send", parents=[common])
    auto_send_parser.add_argument("--peer-agent-id", required=True)
    auto_send_parser.add_argument("--conversation-type", default="direct")
    auto_send_parser.add_argument("--recipient-count", type=int, default=1)
    auto_send_parser.add_argument("--has-cc", action="store_true")
    auto_send_parser.add_argument("--has-bcc", action="store_true")
    auto_send_parser.add_argument("--uses-reply-all", action="store_true")
    auto_send_parser.add_argument("--has-attachment", action="store_true")
    auto_send_parser.add_argument("--is-forward", action="store_true")
    auto_send_parser.add_argument("--is-delete", action="store_true")
    auto_send_parser.add_argument("--cross-peer-disclosure", action="store_true")
    auto_send_parser.add_argument(
        "--from-untrusted-email-instruction",
        action="store_true",
    )
    auto_send_parser.set_defaults(func=command_can_auto_send)

    record_parser = subparsers.add_parser("record-message", parents=[common])
    record_parser.add_argument("--peer-agent-id", required=True)
    record_parser.add_argument(
        "--direction",
        choices=sorted(MESSAGE_DIRECTIONS),
        required=True,
    )
    record_parser.add_argument("--message-id", required=True)
    record_parser.add_argument("--conversation-id", required=True)
    record_parser.add_argument("--timestamp")
    record_parser.set_defaults(func=command_record_message)

    peer_parser = subparsers.add_parser("list-peer", parents=[common])
    peer_parser.add_argument("--peer-agent-id", required=True)
    peer_parser.set_defaults(func=command_list_peer)

    export_parser = subparsers.add_parser("export-redacted", parents=[common])
    export_parser.set_defaults(func=command_export_redacted)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
