from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import call_command

from core.environment import environment_errors

def run_production_startup_tasks() -> None:
    if settings.WKAP_ENVIRONMENT != "production":
        return
    if os.getenv("WKAP_SKIP_STARTUP_TASKS", "").lower() in {"1", "true", "yes", "on"}:
        return

    _configure_ledger_ssh()
    _bootstrap_ledger_repo()
    call_command("migrate", interactive=False, verbosity=1)
    errors = environment_errors()
    if errors:
        raise RuntimeError("WKAP production startup checks failed: " + "; ".join(errors))


def _configure_ledger_ssh() -> None:
    key_base64 = os.getenv("WKAP_LEDGER_DEPLOY_KEY_BASE64", "")
    if not key_base64:
        return

    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_path = ssh_dir / "wkap_ledger_deploy_key"
    key_path.write_bytes(base64.b64decode(key_base64))
    key_path.chmod(0o600)

    known_hosts = ssh_dir / "known_hosts"
    existing_hosts = known_hosts.read_text(encoding="utf-8") if known_hosts.exists() else ""
    if "github.com" not in existing_hosts:
        result = subprocess.run(["ssh-keyscan", "github.com"], text=True, capture_output=True, check=True)
        with known_hosts.open("a", encoding="utf-8") as handle:
            handle.write(result.stdout)

    os.environ["GIT_SSH_COMMAND"] = f"ssh -i {key_path} -o IdentitiesOnly=yes"


def _bootstrap_ledger_repo() -> None:
    if not settings.WKAP_LEDGER_REPO_PATH or not settings.WKAP_LEDGER_REPO_URL:
        return

    repo = Path(settings.WKAP_LEDGER_REPO_PATH)
    repo.parent.mkdir(parents=True, exist_ok=True)
    branch = settings.WKAP_LEDGER_BRANCH
    if (repo / ".git").exists():
        _git(repo, "fetch", "origin", branch)
        _git(repo, "checkout", branch)
        _git(repo, "pull", "--ff-only", "origin", branch)
    else:
        if repo.exists():
            for child in repo.iterdir():
                if child.is_dir():
                    import shutil

                    shutil.rmtree(child)
                else:
                    child.unlink()
        _git(repo.parent, "clone", "--branch", branch, settings.WKAP_LEDGER_REPO_URL, str(repo))

    _git(repo, "config", "user.name", os.getenv("WKAP_GIT_USER_NAME", "WKAP Ledger Bot"))
    _git(repo, "config", "user.email", os.getenv("WKAP_GIT_USER_EMAIL", "ledger@wkap.ai"))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run([settings.WKAP_GIT_EXECUTABLE, *args], cwd=cwd, text=True, capture_output=True, check=True)
