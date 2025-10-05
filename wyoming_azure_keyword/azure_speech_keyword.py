"""Azure Speech Keyword detection module for Wyoming."""

import logging
import os
import time

import azure.cognitiveservices.speech as speechsdk

from . import KeywordDetectionConfig

_LOGGER = logging.getLogger(__name__)


class AzureSpeechKeyword:
    """Class to handle Azure Speech Keyword detection."""

    def __init__(self, config: KeywordDetectionConfig) -> None:
        """Initialize."""
        self.config = config

        self._stream: speechsdk.audio.PushAudioInputStream | None = None
        self._keyword_recognizer: speechsdk.KeywordRecognizer | None = None
        self._results: speechsdk.KeywordRecognitionResult | None = None

        if not os.path.isfile(self.config.model_path):
            raise FileNotFoundError(
                f"Keyword model file not found: {self.config.model_path}"
            )

    def start_keyword_detection(
        self,
        samples_per_second: int = 16000,
        bits_per_sample: int = 16,
        channels: int = 1,
    ) -> None:
        """Begin keyword detection."""
        _LOGGER.debug("Starting keyword detection")

        # Configure audio input for keyword detection
        _LOGGER.debug("Configuring audio input stream...")
        self._stream = speechsdk.audio.PushAudioInputStream(
            stream_format=speechsdk.audio.AudioStreamFormat(
                samples_per_second=samples_per_second,
                bits_per_sample=bits_per_sample,
                channels=channels,
            )
        )
        audio_config = speechsdk.audio.AudioConfig(stream=self._stream)
        # Create a keyword recognizer with the configured audio settings
        self._keyword_recognizer = speechsdk.KeywordRecognizer(
            audio_config=audio_config,
        )

        self.recognition_done = False

        def recognized_cb(evt: speechsdk.KeywordRecognitionEventArgs):
            # Only a keyword phrase is recognized. The result cannot be 'NoMatch'
            # and there is no timeout. The recognizer runs until a keyword phrase
            # is detected or recognition is canceled (by stop_recognition_async()
            # or due to the end of an input file or stream).
            result = evt.result
            if result.reason == speechsdk.ResultReason.RecognizedKeyword:
                print("RECOGNIZED KEYWORD: {}".format(result.text))
                self.recognition_done = True
                self._results = evt.result

        def canceled_cb(evt: speechsdk.SpeechRecognitionCanceledEventArgs):
            result = evt.result
            if result.reason == speechsdk.ResultReason.Canceled:
                print("CANCELED: {}".format(result.cancellation_details))

        self._keyword_recognizer.recognized.connect(recognized_cb)
        self._keyword_recognizer.canceled.connect(canceled_cb)

        model = speechsdk.KeywordRecognitionModel(self.config.model_path)
        self._keyword_recognizer.recognize_once_async(model)
        _LOGGER.debug("Recognizer initialized...")

    def push_audio_chunk(self, chunk: bytes) -> None:
        if self._stream is None:
            raise ValueError("Stream is not initialized")
        """Push an audio chunk to the recognizer."""
        _LOGGER.debug(f"Pushing audio chunk of size {len(chunk)} bytes...")
        self._stream.write(chunk)

    def stop_audio_chunk(self) -> None:
        """Stop the keyword detection."""
        _LOGGER.debug("Stopping keyword detection...")
        if self._stream is None:
            raise ValueError("Stream is not initialized")
        self._stream.close()

    def get_results(self):
        """Get the results of a keyword detection."""
        try:
            if self._keyword_recognizer is None:
                raise ValueError("Keyword recognizer is not initialized")
            self.stop_audio_chunk()

            # Wait for the recognition to finish
            while not self.recognition_done:
                _LOGGER.debug("Waiting for recognition to finish...")
                time.sleep(1)

            out_future = self._keyword_recognizer.stop_recognition_async()

            out = out_future.get()

            _LOGGER.debug(f"Keyword detection stopped, result: {out}")

            if self._results is None:
                _LOGGER.debug("No results from transcription.")
                return ""

            return self._results.text

        except Exception as e:
            _LOGGER.error(f"Failed to transcribe audio: {e}")
            return ""
