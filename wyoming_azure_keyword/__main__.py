#!/usr/bin/env python3
"""
Simple Wyoming satellite using Azure Speech SDK for wake word detection.
"""

import argparse
import asyncio
import json
import logging
import multiprocessing as mp
from datetime import datetime
from functools import partial

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, WakeModel, WakeProgram
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.wake import Detection

from .debug import mem_print
from .version import __version__
from .worker import worker_main

_LOGGER = logging.getLogger(__name__)


class AzureWakeWordHandler(AsyncEventHandler):
    """Handler for wake word detection using Azure Speech SDK in subprocess."""

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

        self.worker_process = None
        self.audio_queue = None
        self.result_queue = None
        self.ctx = mp.get_context("spawn")
        self.check_result_task = None
        self.stream_format = None
        self.restart_timer_task = None
        self.restart_interval = 30  # Restart every 30 seconds

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

    def start_detection_subprocess(self) -> None:
        """Start a new detection subprocess."""
        self.stop_detection_subprocess()

        self.audio_queue = self.ctx.Queue()
        self.result_queue = self.ctx.Queue()

        self.worker_process = self.ctx.Process(
            target=worker_main,
            args=(
                self.cli_args.model_path,
                self.audio_queue,
                self.result_queue,
                self.stream_format,
            ),
        )
        self.worker_process.start()
        _LOGGER.info("Started detection subprocess (pid=%s)", self.worker_process.pid)
        mem_print("START")

        if self.check_result_task:
            self.check_result_task.cancel()
        self.check_result_task = asyncio.create_task(self._check_detection_results())

        if self.restart_timer_task:
            self.restart_timer_task.cancel()
        self.restart_timer_task = asyncio.create_task(self._restart_timer())

    def stop_detection_subprocess(self) -> None:
        """Stop and clean up the detection subprocess."""
        if self.check_result_task:
            self.check_result_task.cancel()
            self.check_result_task = None

        if self.restart_timer_task:
            self.restart_timer_task.cancel()
            self.restart_timer_task = None

        audio_q = self.audio_queue
        result_q = self.result_queue
        process = self.worker_process

        # Clear immediately
        self.audio_queue = None
        self.result_queue = None
        self.worker_process = None

        # Send stop signal
        if audio_q:
            try:
                audio_q.put_nowait(None)  # Send sentinel
            except Exception:
                pass

        if process and process.is_alive():
            process.join(timeout=2)
            if process.is_alive():
                _LOGGER.warning("Terminating subprocess")
                process.terminate()
                process.join()
            _LOGGER.info("Stopped detection subprocess")

        if audio_q:
            try:
                audio_q.cancel_join_thread()
                audio_q.close()
            except Exception:
                pass

        if result_q:
            try:
                result_q.cancel_join_thread()
                result_q.close()
            except Exception:
                pass

    async def _restart_timer(self) -> None:
        """Periodically restart subprocess every N seconds."""
        try:
            await asyncio.sleep(self.restart_interval)
            _LOGGER.info("Periodic restart after %ds", self.restart_interval)
            mem_print(f"PERIODIC_RESTART_{self.restart_interval}s")
            self.start_detection_subprocess()
        except asyncio.CancelledError:
            pass

    async def _check_detection_results(self) -> None:
        """Background task to check for detection results from subprocess."""
        try:
            while True:
                result = await self.loop.run_in_executor(
                    None, self._get_result_nonblocking
                )

                if result:
                    result_data = json.loads(result)
                    if result_data.get("status") == "detected":
                        _LOGGER.info("Wake word detected: %s", result_data.get("text"))

                        # Send Detection event
                        detection = Detection(
                            name=self.cli_args.keyword_name,
                            timestamp=int(datetime.now().timestamp()),
                        )
                        await self.write_event(detection.event())
                        _LOGGER.debug("Detection event sent")

                        # Restart subprocess for next detection
                        self.start_detection_subprocess()

                    elif result_data.get("status") == "error":
                        _LOGGER.error("Detection error: %s", result_data.get("err"))

                await asyncio.sleep(0.05)  # Check every 50ms
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Error checking detection results: %s", e)

    def _get_result_nonblocking(self) -> str | None:
        """Get result from queue without blocking."""
        import queue

        if not self.result_queue:
            return None
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

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

        self.stream_format = {
            "rate": audio_start.rate,
            "width": audio_start.width,
            "channels": audio_start.channels,
        }

        self.start_detection_subprocess()

    async def handle_audio_chunk(self, chunk: AudioChunk) -> None:
        """Process audio chunk by sending to subprocess."""
        if self.audio_queue and self.worker_process and self.worker_process.is_alive():
            # Send audio to subprocess queue in executor to avoid blocking
            await self.loop.run_in_executor(
                None, self._send_audio_to_queue, chunk.audio
            )

    def _send_audio_to_queue(self, audio_data: bytes) -> None:
        """Send audio data to subprocess queue."""
        if not self.audio_queue:
            return
        try:
            self.audio_queue.put_nowait(audio_data)
        except Exception as e:
            _LOGGER.error("Failed to send audio to subprocess: %s", e)

    def handle_audio_stop(self) -> None:
        """Stop audio processing."""
        _LOGGER.debug("Audio stop")

        # Stop the detection subprocess
        self.stop_detection_subprocess()


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

    mp.freeze_support()
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
