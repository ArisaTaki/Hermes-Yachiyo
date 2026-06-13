#!/usr/bin/env python3
"""Run provider smoke with an API key read outside shell history."""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

BASE_URL_ENV = "OHA_YACHIYO_SMOKE_BASE_URL"
MODEL_ENV = "OHA_YACHIYO_SMOKE_MODEL"
API_KEY_ENV = "OHA_YACHIYO_SMOKE_API_KEY"
DEFAULT_VERIFIER_ARGS: tuple[str, ...] = (
    "--run-provider-smoke",
    "--report-json",
    "tmp/rc-verification-provider-smoke.json",
)


def _strip_remainder_separator(items: Sequence[str]) -> list[str]:
    values = list(items)
    if values and values[0] == "--":
        return values[1:]
    return values


def _api_key_from_prompt(*, prompt: str) -> str:
    return getpass.getpass(prompt).strip()


def _api_key_from_stdin() -> str:
    if sys.stdin.isatty():
        return _api_key_from_prompt(prompt=f"{API_KEY_ENV}: ")
    return sys.stdin.readline().strip()


def _provider_env(args: argparse.Namespace) -> tuple[dict[str, str], list[str]]:
    base_url = str(args.base_url or os.environ.get(BASE_URL_ENV, "")).strip()
    model = str(args.model or os.environ.get(MODEL_ENV, "")).strip()
    api_key = ""
    if not args.force_prompt:
        api_key = os.environ.get(API_KEY_ENV, "").strip()
    missing = [
        name
        for name, value in (
            (BASE_URL_ENV, base_url),
            (MODEL_ENV, model),
        )
        if not value
    ]
    if missing and not api_key:
        return dict(os.environ), [*missing, API_KEY_ENV]
    if not api_key:
        api_key = (
            _api_key_from_stdin()
            if args.api_key_stdin
            else _api_key_from_prompt(prompt=f"{API_KEY_ENV}: ")
        )

    if not api_key:
        missing.append(API_KEY_ENV)
    env = dict(os.environ)
    if base_url:
        env[BASE_URL_ENV] = base_url
    if model:
        env[MODEL_ENV] = model
    if api_key:
        env[API_KEY_ENV] = api_key
    return env, missing


def _verifier_command(root: Path, verifier_args: Sequence[str]) -> list[str]:
    forwarded = _strip_remainder_separator(verifier_args)
    if not forwarded:
        forwarded = list(DEFAULT_VERIFIER_ARGS)
    if "--run-provider-smoke" not in forwarded:
        forwarded = ["--run-provider-smoke", *forwarded]
    return [sys.executable, str(root / "scripts" / "verify_release_candidate.py"), *forwarded]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Oha-Yachiyo real provider smoke without putting the API key in "
            "shell history or process arguments."
        )
    )
    parser.add_argument("--base-url", default="", help=f"Provider base URL, or {BASE_URL_ENV}.")
    parser.add_argument("--model", default="", help=f"Provider model, or {MODEL_ENV}.")
    parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read the API key from stdin instead of an interactive hidden prompt.",
    )
    parser.add_argument(
        "--force-prompt",
        action="store_true",
        help=f"Prompt for {API_KEY_ENV} even if it is already set in the environment.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the verifier command and credential presence without running it.",
    )
    parser.add_argument(
        "verifier_args",
        nargs=argparse.REMAINDER,
        help="Arguments after -- are forwarded to verify_release_candidate.py.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    env, missing = _provider_env(args)
    command = _verifier_command(root, args.verifier_args)
    if missing:
        print(
            "provider smoke credentials missing: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2

    print(
        "provider smoke wrapper: "
        f"{BASE_URL_ENV}=set, {MODEL_ENV}=set, {API_KEY_ENV}=set"
    )
    print("provider smoke wrapper command: " + " ".join(command))
    if args.dry_run:
        return 0
    completed = subprocess.run(command, cwd=root, env=env, text=True)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
