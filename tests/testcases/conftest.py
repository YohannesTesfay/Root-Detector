"""Core pytest configuration; rendered browser acceptance is in tests/browser.

The inherited BaseCase reads TESTS_TO_SKIP as a string and tests membership.
Use separators for readability; it does not parse JSON or a Python tuple.
"""
import os
from pathlib import Path

# pytest's __main__ lives in site-packages, not beside the application. Define
# source/model paths before importing backend modules on every test platform.
_repository = str(Path(__file__).resolve().parents[2])
os.environ.setdefault('ROOT_PATH', _repository)
os.environ.setdefault('INSTANCE_PATH', _repository)
os.makedirs(os.path.join(os.environ['INSTANCE_PATH'], 'cache'), exist_ok=True)

os.environ['TESTS_TO_SKIP'] = ','.join([
    'test_download_all',  # Covered against the live server by tests/browser.
    'test_load_results',  # Covered against the live server by tests/browser.
    'test_add_boxes',  # RootDetector has no box annotations.
    'test_overlay_side_by_side_switch',  # RootDetector removed side-by-side view.
])
