"""Tests for the Microsoft STT service."""

import asyncio
import logging
import os
import sys
import wave
from asyncio.subprocess import PIPE
from pathlib import Path

import pytest
from dotenv import load_dotenv
from wyoming.audio import AudioStart, AudioStop, wav_to_chunks
from wyoming.event import async_read_event, async_write_event
from wyoming.info import Describe, Info
from wyoming.wake import Detect

load_dotenv()
_LOGGER = logging.getLogger(__name__)

_DIR = Path(__file__).parent
_PROGRAM_DIR = _DIR.parent
_LOCAL_DIR = _PROGRAM_DIR / "local"
_SAMPLES_PER_CHUNK = 1024

_START_TIMEOUT = 5
_KEYWORD_DETECTION_TIMEOUT = 5


@pytest.mark.asyncio
async def test_keyword_detection() -> None:
    """Test the keyword detection."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "wyoming_azure_keyword",
        "--uri",
        "stdio://",
        "--model-path",
        os.environ.get("MODEL_PATH") or "",
        "--keyword-name",
        os.environ.get("KEYWORD_NAME") or "",
        "--debug",
        stdin=PIPE,
        stdout=PIPE,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    # Check info
    await async_write_event(Describe().event(), proc.stdin)
    while True:
        event = await asyncio.wait_for(
            async_read_event(proc.stdout), timeout=_START_TIMEOUT
        )
        assert event is not None

        if not Info.is_type(event.type):
            continue

        info = Info.from_event(event)
        assert len(info.wake) == 1, "Expected one wake service"
        wake = info.wake[0]
        assert len(wake.models) > 0, "Expected at least one model"
        break

    # Test known WAV
    with wave.open(str(_DIR / "keyword_pos.wav"), "rb") as example_wav:
        await async_write_event(
            AudioStart(
                rate=example_wav.getframerate(),
                width=example_wav.getsampwidth(),
                channels=example_wav.getnchannels(),
            ).event(),
            proc.stdin,
        )
        for chunk in wav_to_chunks(example_wav, _SAMPLES_PER_CHUNK):
            await async_write_event(chunk.event(), proc.stdin)
            _LOGGER.info("Sent bytes of audio data to the server")

        await async_write_event(AudioStop().event(), proc.stdin)
        _LOGGER.info("Sent audio stop event to the server")

    while True:
        event = await asyncio.wait_for(
            async_read_event(proc.stdout), timeout=_KEYWORD_DETECTION_TIMEOUT
        )
        assert event is not None

        if not Detect.is_type(event.type):
            continue

        detect = Detect.from_event(event)
        names = detect.names or []
        assert len(names) == 1, "Expected one keyword"
        name = names[0]
        _LOGGER.info(f"Received keyword: {name}")
        assert name == os.environ.get("KEYWORD_NAME") or "", "Expected keyword"
        break

    # Need to close stdin for graceful termination
    proc.stdin.close()
    _, stderr = await proc.communicate()

    assert proc.returncode == 0, stderr.decode()
