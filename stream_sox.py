#!/usr/bin/env python3
"""Stream microphone using sox to Wyoming server."""

import argparse
import asyncio
import logging
import subprocess

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient
from wyoming.wake import Detect

_LOGGER = logging.getLogger(__name__)

# Audio settings
RATE = 16000
CHANNELS = 1
WIDTH = 2  # 16-bit
CHUNK_SIZE = 1024


async def stream_microphone(uri: str):
    """Stream microphone audio to Wyoming server."""

    # Start sox process
    sox_cmd = [
        "sox",
        "-d",  # Use default audio device
        "-t",
        "raw",  # Output raw audio
        "-r",
        str(RATE),  # Sample rate
        "-e",
        "signed-integer",  # Encoding
        "-b",
        "16",  # 16-bit
        "-c",
        str(CHANNELS),  # Mono
        "-",  # Output to stdout
    ]

    _LOGGER.info("Starting sox: %s", " ".join(sox_cmd))

    try:
        process = subprocess.Popen(
            sox_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
        )
    except FileNotFoundError:
        _LOGGER.error("sox not found! Install with: sudo apt-get install sox")
        return

    # Connect to Wyoming server
    _LOGGER.info("Connecting to Wyoming server at %s", uri)
    client = AsyncClient.from_uri(uri)
    await client.connect()

    _LOGGER.info("Connected! Streaming audio...")

    # Send AudioStart
    audio_start = AudioStart(
        rate=RATE,
        width=WIDTH,
        channels=CHANNELS,
    ).event()
    await client.write_event(audio_start)

    # Start listening for detections
    detection_task = asyncio.create_task(listen_for_detections(client))

    # Stream audio chunks
    try:
        _LOGGER.info("🎤 Microphone active - speak your wake word!")
        print("\n" + "=" * 50)
        print("Listening for wake word... (Press Ctrl+C to stop)")
        print("=" * 50 + "\n")

        if process.stdout is None:
            _LOGGER.error("sox stdout is None")
            return

        while True:
            # Read chunk from sox
            chunk = process.stdout.read(CHUNK_SIZE * WIDTH * CHANNELS)
            if not chunk:
                break

            # Send to Wyoming server
            audio_chunk = AudioChunk(
                rate=RATE,
                width=WIDTH,
                channels=CHANNELS,
                audio=chunk,
            ).event()
            await client.write_event(audio_chunk)

    except KeyboardInterrupt:
        _LOGGER.info("Stopped by user")
    finally:
        # Cleanup
        _LOGGER.info("Stopping...")
        process.terminate()
        process.wait()

        # Send AudioStop
        audio_stop = AudioStop().event()
        await client.write_event(audio_stop)

        detection_task.cancel()
        await client.disconnect()


async def listen_for_detections(client: AsyncClient):
    """Listen for detection events."""
    try:
        while True:
            event = await client.read_event()

            if event is None:
                break

            if Detect.is_type(event.type):
                detect = Detect.from_event(event)
                print("\n" + "=" * 50)
                print(f"✅ WAKE WORD DETECTED: {detect.names}")
                print("=" * 50 + "\n")
                _LOGGER.info("Detection: %s", detect.names)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        _LOGGER.error("Error reading events: %s", e)


async def main():
    parser = argparse.ArgumentParser(description="Stream microphone via sox to Wyoming")
    parser.add_argument(
        "--uri",
        default="tcp://127.0.0.1:10400",
        help="Wyoming server URI (default: tcp://127.0.0.1:10400)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    await stream_microphone(args.uri)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
