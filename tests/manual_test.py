import gc
import os
import resource
import time
import tracemalloc

import azure.cognitiveservices.speech as speechsdk
import dotenv

tracemalloc.start()
dotenv.load_dotenv()

model_path = os.getenv("MODEL_PATH")
keyword = os.getenv("KEYWORD_NAME")


def mem_print(tag):
    # ru_maxrss is kilobytes on Linux; convert to bytes
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    cur, peak = tracemalloc.get_traced_memory()
    print(
        f"[{time.strftime('%H:%M:%S')}] {tag} | RSS={rss_bytes / 1e6:.1f}MB "
        f"Py(cur={cur / 1e6:.1f}MB, peak={peak / 1e6:.1f}MB) pid={os.getpid()}"
    )


def speech_recognize_keyword_locally_from_microphone():
    """runs keyword spotting locally, with direct access to the result audio"""

    done = False

    def recognized_cb(evt: speechsdk.SpeechRecognitionEventArgs):
        # Only a keyword phrase is recognized. The result cannot be 'NoMatch'
        # and there is no timeout. The recognizer runs until a keyword phrase
        # is detected or recognition is canceled (by stop_recognition_async()
        # or due to the end of an input file or stream).
        result = evt.result
        if result.reason == speechsdk.ResultReason.RecognizedKeyword:
            print("RECOGNIZED KEYWORD: {}".format(result.text))
        nonlocal done
        done = True

    def canceled_cb(evt: speechsdk.SpeechRecognitionCanceledEventArgs):
        result = evt.result
        if result.reason == speechsdk.ResultReason.Canceled:
            print("CANCELED: {}".format(result.cancellation_details))
        nonlocal done
        done = True

    while True:
        print("Starting...")
        # Creates an instance of a keyword recognition model. Update this to
        # point to the location of your keyword recognition model.
        model = speechsdk.KeywordRecognitionModel(model_path)

        # Create a local keyword recognizer with the default microphone device for input.
        keyword_recognizer = speechsdk.KeywordRecognizer()
        print("Recognizer initialized")
        # Connect callbacks to the events fired by the keyword recognizer.
        keyword_recognizer.recognized.connect(recognized_cb)
        keyword_recognizer.canceled.connect(canceled_cb)
        print("Callbacks connected")
        # Start keyword recognition.
        fut = keyword_recognizer.recognize_once_async(model)
        print(
            'Say something starting with "{}" followed by whatever you want...'.format(
                keyword
            )
        )
        fut.get()
        print("Recognition done")
        print("Resetting...")
        stop_future = keyword_recognizer.stop_recognition_async()
        stop_future.get()
        del model
        del keyword_recognizer
        del fut
        del stop_future
        gc.collect()
        mem_print("AFTER_RUN_ONCE")

    # If active keyword recognition needs to be stopped before results, it can be done with
    #
    #   stop_future = keyword_recognizer.stop_recognition_async()
    #   print('Stopping...')
    #   stopped = stop_future.get()


if __name__ == "__main__":
    speech_recognize_keyword_locally_from_microphone()
