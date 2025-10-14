#!/usr/bin/env python3
"""
Simple Wyoming satellite using Azure Speech SDK for wake word detection.
"""

import argparse
import asyncio
import gc
import logging
import os
from datetime import datetime
from functools import partial

import azure.cognitiveservices.speech as speechsdk
import psutil
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, WakeModel, WakeProgram
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.wake import Detection

from .debug import mem_print
from .version import __version__

_LOGGER = logging.getLogger(__name__)


async def shutdown_after_delay(delay: int):
    await asyncio.sleep(max(delay, 1))
    _LOGGER.info("Shutting down after %ds of idle since last detection.", delay)
    os._exit(0)


async def check_time_exit():
    """Check time and exit if between 2am-3am."""
    while True:
        now = datetime.now()
        if now.hour == 2:
            _LOGGER.info("Current time is between 2am and 3am, exiting process.")
            os._exit(0)
        else:
            _LOGGER.info("Current time is not between 2am and 3am, continuing.")
        await asyncio.sleep(60 * 30)  # sleep for 30 minutes


class AzureWakeWordHandler(AsyncEventHandler):
    """Handler for wake word detection using Azure Speech SDK."""

    def __init__(
        self,
        wyoming_info: Info,
        cli_args: argparse.Namespace,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.cli_args = cli_args
        self.wyoming_info_event = wyoming_info.event()
        self.loop = asyncio.get_running_loop()
        self._shutdown_timer = None
        # Azure setup
        self.keyword_model = speechsdk.KeywordRecognitionModel(cli_args.model_path)
        self.push_stream = None
        self.audio_config = None
        self.keyword_recognizer = None
        self.is_detecting = False
        self.check_time_exit_task = None

        _LOGGER.debug("Handler initialized")

    async def handle_event(self, event: Event) -> bool:
        """Handle events from Wyoming client."""

        if AudioStart.is_type(event.type):
            await self.handle_audio_start(AudioStart.from_event(event))
        elif AudioChunk.is_type(event.type):
            chunk = AudioChunk.from_event(event)
            await self.handle_audio_chunk(chunk)
        elif AudioStop.is_type(event.type):
            self.handle_audio_stop()
        elif Describe.is_type(event.type):
            await self.handle_describe(Describe.from_event(event))
        else:
            _LOGGER.debug("Unhandled event type: %s", event.type)

        return True

    def check_memory(self) -> None:
        """Handle detect event."""
        # Cancel any existing shutdown timer
        if self._shutdown_timer is not None:
            self._shutdown_timer.cancel()
        vm = psutil.virtual_memory()
        memory_used = int(round(100 - (vm.available / vm.total * 100)))
        _LOGGER.info("Memory used: %d%%", memory_used)
        if memory_used > 75:
            # Allow time for current task to finish
            _LOGGER.info("Memory used is greater than 75%, shutting down in 10 seconds")
            self._shutdown_timer = self.loop.create_task(shutdown_after_delay(10))
        elif memory_used > 90:
            # Force shutdown
            _LOGGER.info("Memory used is greater than 90%, shutting down")
            self._shutdown_timer = self.loop.create_task(shutdown_after_delay(1))

    def reset_keyword_recognizer(self) -> None:
        """Reset keyword recognizer."""
        if self.keyword_recognizer:
            del self.keyword_recognizer
        if self.keyword_model:
            del self.keyword_model
        gc.collect()
        self.keyword_recognizer = speechsdk.KeywordRecognizer(
            audio_config=self.audio_config
        )
        self.keyword_recognizer.recognized.connect(self._on_recognized)
        self.keyword_recognizer.canceled.connect(self._on_canceled)
        self.keyword_model = speechsdk.KeywordRecognitionModel(self.cli_args.model_path)
        self.is_detecting = True
        _LOGGER.info("Wake word detection reset")
        self.keyword_recognizer.recognize_once_async(self.keyword_model)
        mem_print("RESET")

    async def handle_describe(self, describe: Describe) -> None:
        """Handle describe event."""
        _LOGGER.debug("Describe event: %s", describe)
        await self.write_event(self.wyoming_info_event)

    async def handle_audio_start(self, audio_start: AudioStart) -> None:
        """Start audio processing."""
        _LOGGER.debug(
            "Audio start: rate=%s, width=%s, channels=%s",
            audio_start.rate,
            audio_start.width,
            audio_start.channels,
        )

        # Create push stream with audio format
        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=audio_start.rate,
            bits_per_sample=audio_start.width * 8,
            channels=audio_start.channels,
        )

        self.push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        self.audio_config = speechsdk.audio.AudioConfig(stream=self.push_stream)
        self.reset_keyword_recognizer()

    async def handle_audio_chunk(self, chunk: AudioChunk) -> None:
        """Process audio chunk."""
        if self.push_stream and self.is_detecting:
            # Push audio to Azure in a thread to avoid blocking
            await asyncio.get_event_loop().run_in_executor(
                None, self.push_stream.write, chunk.audio
            )

    def handle_audio_stop(self) -> None:
        """Stop audio processing."""
        _LOGGER.debug("Audio stop")

        if self.push_stream:
            self.push_stream.close()

        if self.keyword_recognizer:
            self.keyword_recognizer.stop_recognition_async()
            self.keyword_recognizer.recognized.disconnect_all()
            self.keyword_recognizer.canceled.disconnect_all()
            self.keyword_recognizer = None

        self.is_detecting = False
        self.push_stream = None
        self.audio_config = None

    def _on_recognized(self, evt) -> None:
        """Called when keyword is recognized."""
        if evt.result.reason == speechsdk.ResultReason.RecognizedKeyword:
            _LOGGER.info("Wake word detected: %s", evt.result.text)

            # Send Detect event
            detection = Detection(
                name=self.cli_args.keyword_name,
                timestamp=int(datetime.now().timestamp()),
            )
            asyncio.run_coroutine_threadsafe(
                self.write_event(detection.event()), self.loop
            )
            _LOGGER.debug("Detect event sent")
            if self.keyword_recognizer:
                self.keyword_recognizer.stop_recognition_async()
                self.reset_keyword_recognizer()
                self.check_memory()
                if self.check_time_exit_task:
                    self.check_time_exit_task.cancel()
                self.check_time_exit_task = self.loop.create_task(check_time_exit())

    def _on_canceled(self, evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
        """Called when keyword is canceled."""
        _LOGGER.debug("Keyword recognition canceled", evt)
        if evt.result.reason == speechsdk.ResultReason.Canceled:
            _LOGGER.debug("Keyword recognition canceled")


async def main() -> None:
    """Start Wyoming server."""
    parser = argparse.ArgumentParser(description="Azure Speech SDK Wyoming Satellite")
    parser.add_argument(
        "--uri",
        default="tcp://0.0.0.0:10400",
        help="Wyoming server URI (default: tcp://0.0.0.0:10400)",
    )
    parser.add_argument(
        "--model-path",
        required=True,
        help="Path to Azure keyword model (.table file)",
    )
    parser.add_argument(
        "--keyword-name",
        default="azure_wake_word",
        help="Name of wake word to report (default: azure_wake_word)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    _LOGGER.info("Starting Azure Wake Word Wyoming Server")
    _LOGGER.info("Model: %s", args.model_path)
    _LOGGER.info("Keyword: %s", args.keyword_name)
    _LOGGER.info("URI: %s", args.uri)

    # Create Wyoming info
    wyoming_info = Info(
        wake=[
            WakeProgram(
                name="Azure",
                description="Azure speech keyword detection",
                attribution=Attribution(
                    name="James Cohen",
                    url="https://github.com/jamescohen/wyoming-azure-keyword/",
                ),
                version=__version__,
                installed=True,
                models=[
                    WakeModel(
                        name="Microsoft Azure Keyword",
                        description="Azure keyword detection",
                        attribution=Attribution(
                            name="Microsoft",
                            url="https://pypi.org/project/azure-cognitiveservices-speech/",
                        ),
                        phrase=args.keyword_name,
                        version=__version__,
                        installed=True,
                        languages=["en-US"],
                    )
                ],
            )
        ],
    )

    # Start server
    server = AsyncServer.from_uri(args.uri)

    _LOGGER.info("Server ready")

    await server.run(
        partial(
            AzureWakeWordHandler,
            wyoming_info,
            args,
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
