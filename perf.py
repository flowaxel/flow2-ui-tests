"""
Lightweight performance timing collection for the flow2 UI test suite.

The point isn't to replace real profiling - it's to give Axel a cheap,
consistent number for "how long did this actually take, on THIS
install, right now" for the handful of operations that matter most for
comparing middleware/backend performance across installs: login/WS
connect, dashboard load, search, opening a clip, a metadata save
round-trip, and (the usual bottleneck) upload -> ingest -> visible.
Every test run's timings print as a table at the end and get written
to a JSON file, so results from different installs/runs can be
diffed rather than just eyeballed from scrollback.
"""
import json
import os
import time
from contextlib import contextmanager

_records = []


def record(op, seconds, **extra):
    _records.append({"op": op, "seconds": round(seconds, 3), **extra})


@contextmanager
def timed(op, **extra):
    """Time a block and record it under `op`. Records even on exception,
    since a timeout is itself a meaningful (very large) timing data point,
    not something to discard."""
    start = time.monotonic()
    try:
        yield
    finally:
        record(op, time.monotonic() - start, **extra)


def all_records():
    return list(_records)


def write_report(target_url):
    """Writes the full JSON report; path overridable via
    FLOW2_PERF_REPORT for when the container has a volume mounted at a
    different path to persist results outside the container."""
    path = os.environ.get("FLOW2_PERF_REPORT", "/tests/perf-report.json")
    try:
        with open(path, "w") as f:
            json.dump(
                {"target": target_url, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "records": all_records()},
                f, indent=2,
            )
        return path
    except OSError as e:
        return f"(could not write report: {e})"
