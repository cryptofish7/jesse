"""Shared fixtures and test configuration."""

import os

# Set dummy API credentials BEFORE any src imports.
# This ensures Settings() singleton construction succeeds.
# Values are never sent to a real exchange because tests mock
# the exchange or use FakeDataProvider.
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("API_SECRET", "test-api-secret")
