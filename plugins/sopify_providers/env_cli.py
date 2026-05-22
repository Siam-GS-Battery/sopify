"""`sopify env` subcommand — manage credentials in ~/.hermes/.env.

Why this exists:
  Hermes reads ~/.hermes/.env on boot. The microVM mounts this file
  read-only, so writing to it from the host is the canonical way to
  push a credential into the sandbox without rebuilding the image.

  `sopify login` also works (writes to ~/.sopify/auth.json which the
  auth_override plugin mirrors here at dashboard startup), but `env`
  is more direct — useful when you already know exactly which
  HERMES_DEFAULT_PROVIDER var or extra setting you want to set.

Usage:
  sopify env list                       # show keys (lengths only, no values)
  sopify env set anthropic              # prompt + write ANTHROPIC_TOKEN(+_API_KEY)
  sopify env set ANTHROPIC_TOKEN        # prompt + write that exact var
  sopify env set HERMES_DEFAULT_PROVIDER anthropic   # explicit non-secret
  sopify env unset openrouter           # remove OPENROUTER_API_KEY
  sopify env unset SOME_VAR             # remove that exact var
"""
from __future__ import annotations

import getpass
import sys
from typing import Optional

from . import env_file


# Friendly provider aliases → env var names that Hermes reads.
# Listed in priority order: first var is the primary; rest are aliases.
PROVIDER_ALIASES: dict[str, list[str]] = {
    "anthropic":   ["ANTHROPIC_TOKEN", "ANTHROPIC_API_KEY"],
    "openrouter":  ["OPENROUTER_API_KEY"],
    "openai":      ["OPENAI_API_KEY"],
    "novita":      ["NOVITA_API_KEY"],
    "huggingface": ["HUGGINGFACE_TOKEN", "HF_TOKEN"],
    "hf":          ["HUGGINGFACE_TOKEN", "HF_TOKEN"],
    "google":      ["GOOGLE_API_KEY"],
    "xai":         ["XAI_API_KEY"],
}

# Vars considered secrets (never echoed back, only length shown).
SECRET_PATTERNS = (
    "API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE",
)


def _is_secret(var: str) -> bool:
    return any(p in var for p in SECRET_PATTERNS)


def _resolve_vars(target: str) -> list[str]:
    """Map a CLI argument to one or more concrete env var names."""
    low = target.lower()
    if low in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[low]
    # Treat as a literal env var name (must be uppercase-ish).
    return [target.upper() if target.islower() else target]


def cmd_list(argv: list[str]) -> int:
    """sopify env list — names + lengths of keys in ~/.hermes/.env."""
    keys = env_file.read_keys()
    if not keys:
        print(f"sopify env: {env_file.env_path()} is empty or missing.")
        print("           Run `sopify env set anthropic` to add a credential.")
        return 0
    print(f"sopify env — {env_file.env_path()}")
    name_w = max(len(k) for k in keys)
    for var in sorted(keys):
        value = keys[var]
        if _is_secret(var):
            shown = f"({len(value)} chars)"
        else:
            shown = value if len(value) <= 60 else value[:57] + "..."
        print(f"  {var.ljust(name_w)}  {shown}")
    return 0


def cmd_set(argv: list[str]) -> int:
    """sopify env set <provider|VAR> [value]

    Interactive when no value is given:
      - secrets are read via getpass (hidden input)
      - non-secrets are echoed back for confirmation
    """
    if not argv:
        print("usage: sopify env set <provider|VAR> [value]", file=sys.stderr)
        return 2

    target = argv[0]
    explicit_value: Optional[str] = " ".join(argv[1:]).strip() if len(argv) > 1 else None
    vars_to_set = _resolve_vars(target)

    if explicit_value is None:
        primary = vars_to_set[0]
        if _is_secret(primary):
            print(f"sopify env set: paste value for {primary} (input hidden).")
            if len(vars_to_set) > 1:
                print(f"                this also writes: {', '.join(vars_to_set[1:])}")
            value = getpass.getpass(f"  {primary}: ").strip()
        else:
            value = input(f"  {primary}: ").strip()
    else:
        value = explicit_value

    if not value:
        print("sopify env set: empty value — aborting.", file=sys.stderr)
        return 1

    updates = {v: value for v in vars_to_set}
    changed = env_file.set_keys(updates)
    if changed:
        for v in vars_to_set:
            shown = f"({len(value)} chars)" if _is_secret(v) else value
            print(f"  ✓ {v} = {shown}")
        print(f"\n  Saved to {env_file.env_path()} (mode 0600).")
        print("  Run `sopify dashboard` (or restart the sandbox) to pick it up.")
    else:
        print(f"  ✓ {target} already set to that value — nothing to do.")
    return 0


def cmd_unset(argv: list[str]) -> int:
    """sopify env unset <provider|VAR>"""
    if not argv:
        print("usage: sopify env unset <provider|VAR>", file=sys.stderr)
        return 2

    target = argv[0]
    vars_to_strip = _resolve_vars(target)
    keys = env_file.read_keys()
    present = [v for v in vars_to_strip if v in keys]
    if not present:
        print(f"sopify env unset: {target} not set — nothing to do.")
        return 0

    env_file.set_keys({}, strip=present)
    for v in present:
        print(f"  ✓ removed {v}")
    return 0


def main(argv: list[str]) -> int:
    """Entry point used by the sopify shim's `env` subcommand."""
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    sub = argv[0]
    rest = argv[1:]
    if sub == "list":
        return cmd_list(rest)
    if sub == "set":
        return cmd_set(rest)
    if sub == "unset":
        return cmd_unset(rest)
    print(f"sopify env: unknown subcommand '{sub}'. Try `sopify env --help`.",
          file=sys.stderr)
    return 2
