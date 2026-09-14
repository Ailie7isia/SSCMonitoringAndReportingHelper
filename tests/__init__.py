"""Offline test suite for the SSC Monitoring and Reporting Helper.

Run from the project root:

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v

No test contacts SecurityScorecard: every API interaction goes through
``tests.fakes.FakeClient``.
"""

import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Services.scores binds the history path at import time. Point it at a
# throwaway workbook so tests never touch the operator's real score history.
_TEST_DIR = Path(tempfile.mkdtemp(prefix="ssc-helper-tests-"))
os.environ["SSC_SCORE_HISTORY_PATH"] = str(_TEST_DIR / "score-history.xlsx")
