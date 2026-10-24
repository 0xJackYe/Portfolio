"""Bounded, offline full-snapshot/SSE fanout contention profile.

Uses an already saved public snapshot and synthetic public book updates only.
Does not start the cache or connect to any upstream service.
"""

import json
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dashboard_server import MarketCache


def summary(samples):
    values = sorted(samples)
    if not values:
        return {"n": 0}
    return {"n": len(values), "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[min(len(values) - 1, int(len(values) * .95))], 3),
            "max_ms": round(values[-1], 3)}


class TimedLock:
    def __init__(self):
        self.lock = threading.Lock()
        self.writer_waits = []

    def acquire(self, *args, **kwargs):
        began = time.perf_counter()
        acquired = self.lock.acquire(*args, **kwargs)
        if acquired and threading.current_thread().name == "profile-writer" and (not args or args[0]):
            self.writer_waits.append((time.perf_counter() - began) * 1000)
        return acquired

    def release(self):
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


def main():
    shared = "--shared" in sys.argv
    source = ROOT / "verification" / "mark-recovery-live-snapshot-20261018.json"
    snapshot = json.loads(source.read_text(encoding="utf-8-sig"))
    with tempfile.TemporaryDirectory() as directory:
        cache = MarketCache(directory, websocket_factory=None)
        cache._snapshot = snapshot
        cache._rows_by_symbol = {row["symbol"]: row for row in snapshot["options"]}
        lock = TimedLock()
        cache._lock = lock
        cache._condition = threading.Condition(lock)
        symbol = next(iter(cache._rows_by_symbol))
        serial_reads, serial_json, wire_bytes = [], [], []
        began = time.perf_counter()
        # Initial read/JSON timings are separate; JSON runs after releasing lock.
        for _ in range(10):
            before = time.perf_counter()
            with cache._condition:
                value = cache._read_locked(False)
            split = time.perf_counter()
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            after = time.perf_counter()
            serial_reads.append((split - before) * 1000)
            serial_json.append((after - split) * 1000)
            wire_bytes.append(len(payload))
            if after - began > 2:
                break

        stop = threading.Event()
        barrier = threading.Barrier(4)
        reader_times = [[] for _ in range(3)]
        writer_times = []
        frame_builds = []
        packet_ids = [set() for _ in range(3)]
        original_read = cache._read_locked

        def measured_read(*args, **kwargs):
            before = time.perf_counter()
            value = original_read(*args, **kwargs)
            frame_builds.append((time.perf_counter() - before) * 1000)
            return value

        cache._read_locked = measured_read

        def reader(index):
            barrier.wait()
            revision = -1
            while not stop.is_set():
                before = time.perf_counter()
                if shared:
                    revision, packet = cache.wait_market_frame(revision, timeout=.25)
                    if packet is not None:
                        packet_ids[index].add(id(packet))
                else:
                    with cache._condition:
                        value = cache._read_locked(False)
                    json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
                elapsed = time.perf_counter() - before
                reader_times[index].append(elapsed * 1000)
                stop.wait(max(0, .25 - elapsed))

        def writer():
            barrier.wait()
            sequence = int(time.time() * 1000)
            while not stop.is_set():
                sequence += 1
                before = time.perf_counter()
                cache.apply_stream_message({"e": "bookTicker", "E": sequence, "u": sequence,
                    "s": symbol, "b": "50", "a": "55", "B": "2", "A": "3"})
                writer_times.append((time.perf_counter() - before) * 1000)
                stop.wait(.02)

        threads = [threading.Thread(target=reader, args=(index,), name="profile-reader-%s" % index)
                   for index in range(3)]
        threads.append(threading.Thread(target=writer, name="profile-writer"))
        for thread in threads:
            thread.start()
        stop.wait(min(4, max(0, 7 - (time.perf_counter() - began))))
        stop.set()
        for thread in threads:
            thread.join(1)
        elapsed = time.perf_counter() - began
        cache.stop()
        result = {
            "offline_only": True, "source": str(source), "rows": len(snapshot["options"]),
            "shared_frame_path": shared,
            "reader_count": 3, "reader_interval_ms": 250, "writer_interval_ms": 20,
            "elapsed_seconds": round(elapsed, 3), "serialized_bytes": max(wire_bytes),
            "serial_read_locked": summary(serial_reads), "serial_json": summary(serial_json),
            "concurrent_read_and_json": [summary(values) for values in reader_times],
            "concurrent_writer_lock_wait": summary(lock.writer_waits),
            "concurrent_ws_apply_total": summary(writer_times),
            "concurrent_snapshot_builds": summary(frame_builds),
            "shared_packet_counts_by_reader": [len(values) for values in packet_ids],
            "interpretation": "Measures local cache/JSON contention only; excludes network, browser rendering, and live stream volume. No upstream connection started.",
        }
        output = Path(__file__).with_name("profile_focused_pipeline_shared_20261018.json") if shared else Path(__file__).with_suffix(".json")
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
