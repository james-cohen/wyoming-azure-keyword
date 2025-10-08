"""Fixtures for tests."""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture
def azure_speech_keyword_args():
    """Return AzureSpeechKeyword instance."""
    return {
        "model_path": os.environ.get("MODEL_PATH") or "",
        "keyword_name": os.environ.get("KEYWORD_NAME") or "",
    }
