"""WSGI config for WKAP."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wkap_project.settings")

application = get_wsgi_application()

from core.startup import run_production_startup_tasks

run_production_startup_tasks()
