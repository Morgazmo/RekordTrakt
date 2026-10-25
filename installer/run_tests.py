"""Runs the test suite on the bundled runtime and the bundled copy of RekordTrakt (installer/build.py does this).

The tests put the source tree on sys.path; importing rekordtrakt first, from the bundle, makes them test that copy.
"""
import sys
import unittest
from pathlib import Path

import rekordtrakt

tests = Path(sys.argv[1])
print(f"rekordtrakt {rekordtrakt.__version__} from {Path(rekordtrakt.__file__).parent}")
sys.path.insert(0, str(tests))
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover(str(tests)))
sys.exit(0 if result.wasSuccessful() else 1)
