"""
Shared pytest configuration for HPE-Monitor tests.
"""
import sys
import os

# Make the repo root importable without pip-installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
