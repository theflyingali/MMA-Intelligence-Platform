"""Databricks job entry point (spark_python_task). Task parameters are the CLI arguments."""

import os
import sys

try:
    here = os.path.dirname(os.path.abspath(__file__))
except NameError:  # __file__ is not always defined for job Python files
    here = os.getcwd()
sys.path.insert(0, here)

from ufcal_silver.cli import main  # noqa: E402

rc = main(sys.argv[1:])
if rc:
    sys.exit(rc)
