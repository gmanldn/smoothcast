from src import transfer_metrics as M

MB = M.MIB


def test_percentiles_nearest_rank_and_junk():
    xs = list(range(1, 101))
    assert (M.percentile(xs, 50), M.percentile(xs, 95), M.percentile(xs, 99)) == (50, 95, 99)
    assert M.percentile([], 50) == 0 and M.percentile([float("nan"), True, 7], 99) == 7


def test_jain():
    assert M.jain([5, 5, 5, 5]) == 1.0 and M.jain([]) == 1.0 and M.jain([0, 0]) == 1.0
    assert round(M.jain([10, 0, 0, 0]), 2) == 0.25


RUN = {"bytes": 100 * MB, "elapsed_s": 2.0, "link_bps": 1_000_000_000, "ttfb_s": 0.05, "playable_s": 0.4, "chunk_ms": [1, 2, 3, 40], "per_client_bytes": [50, 50],
       "corrupt_bytes": 0, "cpu_pct": 30, "fds_before": 10, "fds_after": 10}


def test_summarise_exact_numbers():
    s = M.summarise(RUN)
    assert s["mib_s"] == 50.0 and s["link_fraction"] == 0.419 and s["fairness"] == 1.0
    assert s["chunk_ms"] == {"p50": 2.0, "p95": 40.0, "p99": 40.0} and s["leaked_fds"] == 0
    assert M.summarise({})["mib_s"] == 0.0


def test_invariants_flag_hard_faults_only():
    assert M.invariants(M.summarise(RUN)) == []
    bad = M.invariants(M.summarise({**RUN, "corrupt_bytes": 3, "fds_after": 12, "stalls": 1, "per_client_bytes": [100, 0, 0, 0]}))
    assert len(bad) == 4 and bad[0] == "corrupt bytes: 3"


def test_baseline_detects_injected_slow_path_and_ignores_noise():
    base = M.summarise(RUN)
    assert M.compare(base, M.summarise({**RUN, "elapsed_s": 2.2})) == []              # 10% slower: tolerated
    slow = M.compare(base, M.summarise({**RUN, "elapsed_s": 10.0, "chunk_ms": [1, 2, 3, 400]}))
    assert len(slow) == 2 and slow[0].startswith("throughput 10.0 MiB/s")


def test_stalled_producer_shows_in_invariants():
    assert any("stalled" in x for x in M.invariants(M.summarise({**RUN, "stalls": 2})))


def test_bottleneck_priority():
    assert M.bottleneck({**RUN, "cpu_pct": 95}).startswith("CPU")
    assert M.bottleneck({**RUN, "bytes": 200 * MB}).startswith("Network")      # 0.84 of link
    assert M.bottleneck({**RUN, "fsync_ms_p95": 80}).startswith("Disk")
    assert M.bottleneck({**RUN, "stalls": 1}).startswith("Receiver")
    assert M.bottleneck(RUN) == "No single bottleneck stands out."


def test_redact_ips_and_filenames():
    r = M.redact({"client": "10.0.0.7 sent 'Holiday Video (1).MP4' and a.mkv", "n": [{"ip": "fe80::1:2"}], "x": 3})
    assert r == {"client": "<ip> sent <file> and <file>", "n": [{"ip": "<ip>"}], "x": 3}
