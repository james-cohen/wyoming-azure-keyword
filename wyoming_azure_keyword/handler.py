"""Event handler for clients of the server."""

import argparse
import asyncio
import logging
import time

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler
from wyoming.wake import Detect, Detection, NotDetected

from .azure_speech_keyword import AzureSpeechKeyword

_LOGGER = logging.getLogger(__name__)


class AzureSpeechKeywordEventHandler(AsyncEventHandler):
    """Event handler for clients."""

    def __init__(
        self,
        wyoming_info: Info,
        cli_args: argparse.Namespace,
        model: AzureSpeechKeyword,
        model_lock: asyncio.Lock,
        *args,
        **kwargs,
    ) -> None:
        """Initialize."""
        super().__init__(*args, **kwargs)

        self.cli_args = cli_args
        self.wyoming_info_event = wyoming_info.event()
        self.model = model
        self.model_lock = model_lock

    async def handle_event(self, event: Event) -> bool:
        """Handle an event."""
        if Describe.is_type(event.type):
            await self.write_event(self.wyoming_info_event)
            _LOGGER.debug("Sent info")
            return True

        if Detect.is_type(event.type):
            detect = Detect.from_event(event)
            _LOGGER.debug(f"Detected keyword: {detect.names}")
            return True

        if AudioStart.is_type(event.type):
            start = AudioStart.from_event(event)
            _LOGGER.debug(
                f"Receiving audio: {start.width * 8}bit {start.rate}Hz {start.channels}ch"
            )

            async with self.model_lock:
                self.model.start_keyword_detection(
                    bits_per_sample=start.width * 8,
                    samples_per_second=start.rate,
                    channels=start.channels,
                )

        if AudioChunk.is_type(event.type):
            chunk = AudioChunk.from_event(event)
            async with self.model_lock:
                self.model.push_audio_chunk(chunk.audio)

            return True

        if AudioStop.is_type(event.type):
            _LOGGER.debug("Audio stopped")

            async with self.model_lock:
                try:
                    start_time = time.time()
                    _LOGGER.debug("Starting detection")
                    text = self.model.get_results()
                    _LOGGER.info(
                        f"Keyword detection completed in {time.time() - start_time:.2f} seconds"
                    )
                    if text:
                        await self.write_event(Detection(name=text).event())
                    else:
                        await self.write_event(NotDetected().event())
                except Exception as e:
                    _LOGGER.error(f"Failed to transcribe audio: {e}")
                    return True

            # Reset
            return False

        return True
