# SPDX-License-Identifier: Apache-2.0
"""End-to-end model fetch & verify pipeline orchestrator."""
from __future__ import annotations

import logging
import sys

import click

from .consistency import main as consistency_main
from .fetch import fetch_model
from .manifest import write_manifest
from .smoke import main as smoke_main
from .verify import main as verify_main

log = logging.getLogger("nullpii-convert")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@click.group()
def cli() -> None:
    """nullpii model fetch & verify pipeline."""


@cli.command("fetch")
def cmd_fetch() -> None:
    _setup_logging()
    fetch_model()


@cli.command("manifest")
def cmd_manifest() -> None:
    _setup_logging()
    write_manifest()


@cli.command("verify")
def cmd_verify() -> None:
    sys.exit(verify_main())


@cli.command("smoke")
def cmd_smoke() -> None:
    sys.exit(smoke_main())


@cli.command("consistency")
def cmd_consistency() -> None:
    sys.exit(consistency_main())


@cli.command("all")
def cmd_all() -> None:
    """Run the full chain: fetch → manifest → verify → smoke → consistency."""
    _setup_logging()
    fetch_model()
    write_manifest()
    if (rc := verify_main()) != 0:
        sys.exit(rc)
    if (rc := smoke_main()) != 0:
        sys.exit(rc)
    sys.exit(consistency_main())


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
