from __future__ import annotations

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wkap_project.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(["manage.py", "wkap", *sys.argv[1:]])
