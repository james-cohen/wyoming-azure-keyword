import argparse  # noqa: D100
import asyncio
import contextlib
import logging
import os  # Import to access environment variables
import signal
from functools import partial

from wyoming.info import Attribution, Info, WakeModel, WakeProgram
from wyoming.server import AsyncServer

from . import KeywordDetectionConfig
from .azure_speech_keyword import AzureSpeechKeyword
from .handler import AzureSpeechKeywordEventHandler
from .version import __version__

_LOGGER = logging.getLogger(__name__)

stop_event = asyncio.Event()


def handle_stop_signal(*args):
    """Handle shutdown signal and set the stop event."""
    _LOGGER.info("Received stop signal. Shutting down...")
    stop_event.set()
    exit()


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--uri", default="tcp://0.0.0.0:10300", help="unix:// or tcp://"
    )
    parser.add_argument(
        "--model-path",
        default=os.getenv("MODEL_PATH"),
        help="Path to the keyword model file",
    )
    parser.add_argument(
        "--keyword-name",
        default=os.getenv("KEYWORD_NAME"),
        help="Name of the keyword to detect",
    )
    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    return parser.parse_args()


def validate_args(args):
    """Validate command-line arguments."""
    if not args.model_path or not args.keyword_name:
        raise ValueError(
            "Both --model-path and --keyword-name must be provided either as command-line arguments or environment variables."
        )


async def main() -> None:
    """Start Wyoming Azure Keyword server."""
    args = parse_arguments()
    validate_args(args)

    speech_config = KeywordDetectionConfig(
        model_path=args.model_path,
        keyword_name=args.keyword_name,
    )

    # Set up logging
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    _LOGGER.debug("Arguments parsed successfully.")

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

    # Load Microsoft STT model
    try:
        _LOGGER.debug("Loading Azure Speech Keyword")
        wake_model = AzureSpeechKeyword(speech_config)
        _LOGGER.info("Azure Speech Keyword model loaded successfully.")
    except Exception as e:
        _LOGGER.error(f"Failed to load Azure Speech Keyword model: {e}")
        return

    # Initialize server and run
    server = AsyncServer.from_uri(args.uri)
    _LOGGER.info("Ready")
    model_lock = asyncio.Lock()
    try:
        await server.run(
            partial(
                AzureSpeechKeywordEventHandler,
                wyoming_info,
                args,
                wake_model,
                model_lock,
            )
        )
    except Exception as e:
        _LOGGER.error(f"An error occurred while running the server: {e}")


if __name__ == "__main__":
    # Set up signal handling for graceful shutdown
    signal.signal(signal.SIGTERM, handle_stop_signal)
    signal.signal(signal.SIGINT, handle_stop_signal)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
