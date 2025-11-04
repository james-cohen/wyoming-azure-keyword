# kw_subproc.py
import json
import multiprocessing as mp
import os
import resource
import sys
import time
import tracemalloc

import azure.cognitiveservices.speech as speechsdk
import dotenv

dotenv.load_dotenv()

MODEL_PATH = os.getenv("MODEL_PATH")
KEYWORD = os.getenv("KEYWORD_NAME")


def mem_print(tag):
    # ru_maxrss is kilobytes on Linux; convert to bytes
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    cur, peak = tracemalloc.get_traced_memory()
    print(
        f"[{time.strftime('%H:%M:%S')}] {tag} | RSS={rss_bytes / 1e6:.1f}MB "
        f"Py(cur={cur / 1e6:.1f}MB, peak={peak / 1e6:.1f}MB) pid={os.getpid()}"
    )


def rss_kb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:
        return 0


def worker_main(model_path: str, out_q: mp.Queue):
    # Build fresh objects each run
    model = speechsdk.KeywordRecognitionModel(model_path)
    recognizer = speechsdk.KeywordRecognizer()

    # Optional: callbacks (not strictly required for recognize_once_async)
    def _recognized(evt: speechsdk.SpeechRecognitionEventArgs):
        pass

    def _canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs):
        pass

    recognizer.recognized.connect(_recognized)
    recognizer.canceled.connect(_canceled)

    fut = recognizer.recognize_once_async(model)
    res: speechsdk.KeywordRecognitionResult | None = None
    try:
        res: speechsdk.KeywordRecognitionResult | None = (
            fut.get()
        )  # blocks inside child
        out = {
            "status": "ok",
            "reason": str(res.reason if res else None),
            "text": getattr(res, "text", None),
            "rss_kb": rss_kb(),
        }
        out_q.put_nowait(json.dumps(out))
    except Exception as e:
        out_q.put_nowait(json.dumps({"status": "error", "err": repr(e)}))
    finally:
        try:
            recognizer.stop_recognition_async().get()
        except Exception:
            pass
        try:
            recognizer.recognized.disconnect_all()
            recognizer.canceled.disconnect_all()
        except Exception:
            pass


def run_once(model_path, keyword, timeout_s=15):
    ctx = mp.get_context("spawn")
    out_q = ctx.Queue(1)
    p = ctx.Process(target=worker_main, args=(model_path, out_q))
    p.start()
    p.join(timeout_s)

    if p.is_alive():
        p.terminate()
        p.join()
        return {"status": "timeout_killed"}

    if not out_q.empty():
        return json.loads(out_q.get_nowait())
    return {"status": "no_output"}


def main():
    if not MODEL_PATH or not KEYWORD:
        print("Set MODEL_PATH and KEYWORD_NAME env vars.", file=sys.stderr)
        sys.exit(2)

    # Loop forever. Each cycle runs in a fresh child process.
    while True:
        print("Starting keyword recognition cycle...")
        res = run_once(MODEL_PATH, KEYWORD, timeout_s=20)
        print(res)
        # Restart policy: always start a fresh child, so memory is reclaimed.
        time.sleep(0.5)
        mem_print("AFTER_RUN_ONCE")


if __name__ == "__main__":
    mp.freeze_support()
    main()
