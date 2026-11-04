"""Databricks job entry point (spark_python_task). Task parameters are the CLI arguments."""

import os
import sys

try:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:  # __file__ is not always defined for job Python files
    repo_root = os.path.dirname(os.getcwd())
sys.path.insert(0, repo_root)

from ingestion.ufcalendar.__main__ import main  # noqa: E402

rc = main(sys.argv[1:])
if rc:
    sys.exit(rc)  # non-zero fails the task; a clean run just returns
