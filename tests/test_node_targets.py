import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import node_targets as nt

PEERS = [{"id": "b", "name": "Bedroom", "accepts_playback": True, "last_seen": 100},
         {"id": "c", "name": "Cellar", "accepts_playback": False, "last_seen": 100},
         {"id": "d", "name": "Den", "accepts_playback": True, "last_seen": 10},
         {"id": "e", "name": "Eve", "accepts_playback": True, "last_seen": 100}]


def test_readiness_states_and_ordering():
    rows = nt.targets(PEERS, {"b", "c", "d"}, {}, 105)
    st = {r["id"]: r["status"] for r in rows}
    assert st == {"b": nt.READY, "c": nt.NOT_ENABLED, "d": nt.OFFLINE, "e": nt.NOT_TRUSTED}
    assert rows[0]["id"] == "b" and rows[0]["selectable"] and not rows[-1]["selectable"]
    assert nt.targets(PEERS, {"b"}, {"b": "roomA"}, 105)[0]["status"] == nt.BUSY


def test_fence_one_owner_and_stale_commands_rejected():
    f = nt.Fence()
    e, _ = f.claim("b", "roomA")
    assert f.claim("b", "roomB")[0] is None and f.claim("b", "roomA")[0] == e
    assert f.accept("b", "roomA", e, "pause")[0]
    assert not f.accept("b", "roomB", e, "pause")[0] and not f.accept("b", "roomA", e + 1, "pause")[0]


def test_release_then_new_owner_gets_new_epoch_and_old_epoch_dies():
    f = nt.Fence()
    e1, _ = f.claim("b", "A")
    f.release("b", "other", e1)
    assert f.owners() == {"b": "A"}
    f.release("b", "A", e1)
    e2, _ = f.claim("b", "B")
    assert e2 != e1 and not f.accept("b", "A", e1, "seek")[0] and f.accept("b", "B", e2, "seek")[0]


def test_delayed_release_from_an_old_claim_cannot_drop_the_new_claim():
    """#738: claim A/e1, release, claim A/e2, then stale release(A, e1) arrives."""
    f = nt.Fence()
    e1, _ = f.claim("n", "A")
    assert f.release("n", "A", e1) is True
    e2, _ = f.claim("n", "A")
    assert e2 != e1
    assert f.release("n", "A", e1) is False  # delayed cleanup from the first cast
    assert f.accept("n", "A", e2, "pause") == (True, "")
    assert f.release("n", "B", e2) is False  # foreign room does nothing
    assert f.owners() == {"n": "A"}
    assert f.release("n", "A", e2) is True   # frees exactly once
    assert f.release("n", "A", e2) is False
    assert f.owners() == {}


def test_release_requires_the_epoch_and_revoke_is_the_explicit_admin_path():
    f = nt.Fence()
    e, _ = f.claim("n", "A")
    assert f.release("n", "A", e + 1) is False and f.owners() == {"n": "A"}
    assert f.revoke("n") is True and f.owners() == {}
    assert f.revoke("n") is False
    assert f.accept("n", "A", e, "pause")[0] is False


def test_readiness_requires_literal_opt_in_and_fresh_numeric_timestamp():
    """#740: malformed inventory must never advertise a selectable receiver."""
    cases = [
        ({"accepts_playback": True, "last_seen": 100}, nt.READY),
        ({"accepts_playback": True, "last_seen": 80}, nt.READY),
        ({"accepts_playback": True, "last_seen": 79.999}, nt.OFFLINE),
        ({"accepts_playback": True, "last_seen": 100.001}, nt.OFFLINE),
        ({"accepts_playback": True, "last_seen": float("nan")}, nt.OFFLINE),
        ({"accepts_playback": True, "last_seen": float("inf")}, nt.OFFLINE),
        ({"accepts_playback": True, "last_seen": -float("inf")}, nt.OFFLINE),
        ({"accepts_playback": True, "last_seen": 10**400}, nt.OFFLINE),
        ({"accepts_playback": True, "last_seen": "100"}, nt.OFFLINE),
        ({"accepts_playback": True}, nt.OFFLINE),
        ({"accepts_playback": False, "last_seen": 100}, nt.NOT_ENABLED),
        ({"last_seen": 100}, nt.NOT_ENABLED),
        ({"accepts_playback": "false", "last_seen": 100}, nt.NOT_ENABLED),
        ({"accepts_playback": 1, "last_seen": 100}, nt.NOT_ENABLED),
    ]
    for fields, expected in cases:
        row = nt.targets([{"id": "n", **fields}], {"n"}, {}, 100)[0]
        assert row["status"] == expected, fields
        assert row["selectable"] is (expected == nt.READY), fields

    for boolean in (False, True):
        row = nt.targets([{"id": "n", "accepts_playback": True, "last_seen": boolean}],
                         {"n"}, {}, 10)[0]
        assert row["status"] == nt.OFFLINE and not row["selectable"]


def test_concurrent_claim_one_winner_one_busy_one_epoch():
    """Two rooms race to claim the same node; exactly one wins, one gets busy,
    and exactly one epoch is minted across repeated races."""
    import threading

    f = nt.Fence()

    for _ in range(200):
        results = []
        errors = []

        def claim_room(session):
            try:
                epoch, msg = f.claim("n", session)
                results.append((session, epoch, msg))
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(exc)

        t1 = threading.Thread(target=claim_room, args=("roomA",))
        t2 = threading.Thread(target=claim_room, args=("roomB",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"unexpected exceptions: {errors}"
        assert len(results) == 2
        winners = [r for r in results if r[1] is not None]
        busies = [r for r in results if r[1] is None]
        assert len(winners) == 1, f"expected exactly one winner, got {results}"
        assert len(busies) == 1, f"expected exactly one busy, got {results}"
        assert winners[0][2] == ""  # no error message on success
        assert busies[0][2] == "That computer is playing for another room."
        assert f.owners() == {"n": winners[0][0]}
        # Release for the next race
        session, epoch, _ = winners[0]
        f.release("n", session, epoch)


def test_concurrent_snapshot_and_release_no_iteration_exceptions():
    """Concurrent owners() calls during claims/releases must not raise or
    return partial answers."""
    import threading

    f = nt.Fence()
    f.claim("n", "roomA")

    errors = []
    snapshots = []

    def snapshot():
        for _ in range(50):
            try:
                snapshots.append(f.owners())
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(exc)

    def churn():
        for _ in range(25):
            f.release("n", "roomA", 1)
            f.claim("n", "roomA")

    threads = [threading.Thread(target=snapshot) for _ in range(3)]
    threads.append(threading.Thread(target=churn))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"iteration exceptions: {errors}"
    for snap in snapshots:
        assert snap == {} or snap == {"n": "roomA"}, f"partial snapshot: {snap}"


def test_concurrent_distinct_nodes_independent():
    """Claims on different nodes must not interfere with each other."""
    import threading

    f = nt.Fence()
    results = {}
    errors = []

    def claim_node(node, session):
        try:
            results[(node, session)] = f.claim(node, session)
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(exc)

    threads = [
        threading.Thread(target=claim_node, args=(f"n{i}", f"room{i}"))
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 20
    for (node, session), (epoch, msg) in results.items():
        assert epoch is not None
        assert msg == ""
        assert f.owners()[node] == session
