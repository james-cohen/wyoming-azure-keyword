"""Worker process for keyword detection using Azure Speech SDK."""

import json
import multiprocessing as mp
import time

import azure.cognitiveservices.speech as speechsdk


def rss_kb():
    """Get RSS memory usage in KB (Linux only)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:
        return 0


def worker_main(
    model_path: str,
    audio_queue: mp.Queue,
    result_queue: mp.Queue,
    stream_format_dict: dict,
):
    """Worker process that runs keyword detection on streaming audio."""
    import queue

    recognizer = None
    push_stream = None

    try:
        model = speechsdk.KeywordRecognitionModel(model_path)

        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=stream_format_dict["rate"],
            bits_per_sample=stream_format_dict["width"] * 8,
            channels=stream_format_dict["channels"],
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        recognizer = speechsdk.KeywordRecognizer(audio_config=audio_config)

        def _recognized(evt: speechsdk.SpeechRecognitionEventArgs):
            if evt.result.reason == speechsdk.ResultReason.RecognizedKeyword:
                result_queue.put_nowait(
                    json.dumps(
                        {
                            "status": "detected",
                            "text": evt.result.text,
                            "rss_kb": rss_kb(),
                        }
                    )
                )

        def _canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs):
            pass

        recognizer.recognized.connect(_recognized)
        recognizer.canceled.connect(_canceled)

        fut = recognizer.recognize_once_async(model)

        while True:
            try:
                msg = audio_queue.get(timeout=0.1)
                if msg is None:
                    break
                push_stream.write(msg)
            except queue.Empty:
                continue
            except Exception:
                break

        if push_stream:
            push_stream.close()

        # Wait a bit for any pending recognition to complete
        timeout_end = time.time() + 1.0
        while time.time() < timeout_end:
            try:
                fut.get()
                break
            except Exception:
                break

    except Exception as e:
        result_queue.put_nowait(json.dumps({"status": "error", "err": repr(e)}))
    finally:
        if recognizer:
            try:
                recognizer.stop_recognition_async().get()
            except Exception:
                pass
            try:
                recognizer.recognized.disconnect_all()
                recognizer.canceled.disconnect_all()
            except Exception:
                pass
