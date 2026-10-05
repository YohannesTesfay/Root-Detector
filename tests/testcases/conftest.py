"""Core pytest configuration; rendered browser acceptance is in tests/browser.

The inherited BaseCase reads TESTS_TO_SKIP as a string and tests membership.
Use separators for readability; it does not parse JSON or a Python tuple.
"""
import os

os.environ['TESTS_TO_SKIP'] = ','.join([
    'test_download_all',  # Covered against the live server by tests/browser.
    'test_load_results',  # Covered against the live server by tests/browser.
    'test_add_boxes',  # RootDetector has no box annotations.
    'test_overlay_side_by_side_switch',  # RootDetector removed side-by-side view.
])
