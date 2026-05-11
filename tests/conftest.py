"""
conftest.py — shared pytest fixtures for Voxa test suite.
"""
import os
import sys
import pytest

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Provide a dummy OPENAI_API_KEY so config.py doesn't complain during import
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key-for-unit-tests")
