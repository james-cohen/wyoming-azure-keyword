import os
import resource
import time
import tracemalloc


def mem_print(tag):
    # ru_maxrss is kilobytes on Linux; convert to bytes
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    cur, peak = tracemalloc.get_traced_memory()
    print(
        f"[{time.strftime('%H:%M:%S')}] {tag} | RSS={rss_bytes / 1e6:.1f}MB "
        f"Py(cur={cur / 1e6:.1f}MB, peak={peak / 1e6:.1f}MB) pid={os.getpid()}"
    )
