# SPDX-License-Identifier: Apache-2.0
"""Mirror fetched artifacts to the nullpii HF org. DEFERRED.

Will not run unless `HUGGING_FACE_HUB_TOKEN` is set AND `--confirm-publish`
is passed.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from .config import MODEL_DIR, TARGET_HF_REPO

log = logging.getLogger(__name__)

ENV_TOKEN = "HUGGING_FACE_HUB_TOKEN"
CONFIRM_FLAG = "--confirm-publish"


def mirror(target_repo: str = TARGET_HF_REPO, source: Path = MODEL_DIR) -> None:
    """Upload everything under `source` to `target_repo` on HF Hub.
    Refuses to run without env token + explicit CLI confirmation."""
    if CONFIRM_FLAG not in sys.argv:
        raise SystemExit(f"mirror: refusing to publish without {CONFIRM_FLAG}")
    token = os.environ.get(ENV_TOKEN)
    if not token:
        raise SystemExit(f"mirror: {ENV_TOKEN} env var required")

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(target_repo, repo_type="model", exist_ok=True)
    log.info("uploading %s -> %s", source, target_repo)
    api.upload_folder(folder_path=str(source), repo_id=target_repo, repo_type="model")
    log.info("upload complete")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    mirror()
    return 0


if __name__ == "__main__":
    sys.exit(main())
