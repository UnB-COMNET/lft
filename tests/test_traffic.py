from onos_topologies.runtime import traffic


def meta(tool, path):
    return {"id": "t1", "tool": tool, "client": "cl0", "server": "ds0", "file": str(path)}


def test_iperf_rows_skip_the_summary(tmp_path):
    path = tmp_path / "out.txt"
    path.write_text("[  5]   0.00-1.00   sec  4.12 MBytes  34.6 Mbits/sec    0   1.1 MBytes\n"
                    "[  5]   1.00-2.00   sec  512 KBytes  4.19 Mbits/sec\n"
                    "[  5]   0.00-2.00   sec  4.62 MBytes  19.4 Mbits/sec    0             sender\n")
    rows = traffic.rows(meta("iperf3", path))
    assert [(r["t_s"], r["mbps"]) for r in rows] == [(1.0, 34.6), (2.0, 4.19)]
    assert traffic.last(meta("iperf3", path))["rate_mbps"] == 4.19


def test_dash_and_ping_rows(tmp_path):
    dash = tmp_path / "cl0.jsonl"
    dash.write_text('{"iteration": 3, "resolution": "1080p", "rate": 4500, "speed_kbps": 12000, "buffer": 8.5, "stalls": 0}\n')
    assert traffic.rows(meta("dash", dash))[0] == {"session": "t1", "tool": "dash", "client": "cl0", "server": "ds0", "t_s": 3,
                                                   "mbps": 12.0, "resolution": "1080p", "bitrate_kbps": 4500, "buffer_s": 8.5,
                                                   "stalls": 0}
    ping = tmp_path / "ping.txt"
    ping.write_text("64 bytes from 192.168.0.1: icmp_seq=7 ttl=64 time=21.4 ms\n")
    assert traffic.rows(meta("ping", ping))[0]["rtt_ms"] == 21.4


def test_a_session_without_output_has_no_rate(tmp_path):
    assert traffic.last(meta("iperf3", tmp_path / "missing.txt")) == {"rate_mbps": None, "last": None}


def test_a_client_that_could_not_connect_reports_the_error(tmp_path):
    path = tmp_path / "out.txt"
    path.write_text("iperf3: error - unable to connect to server - server may have stopped running\n")
    assert traffic.last(meta("iperf3", path))["error"].startswith("iperf3: error - unable to connect")


def test_a_session_ends_with_its_client(tmp_path, monkeypatch):
    running = {**meta("iperf3", tmp_path / "out.txt"), "status": "running", "pids": [10, 11]}
    monkeypatch.setattr(traffic.sessions, "ls", lambda kind: [running])
    monkeypatch.setattr(traffic.sessions, "alive", lambda pid: pid == 10)   # the server still waits
    monkeypatch.setattr(traffic, "stop", lambda sid: {**running, "status": "stopped"})
    monkeypatch.setattr(traffic.sessions, "save", lambda kind, m: m)
    assert traffic.ls()[0]["status"] == "done"


def test_the_dash_player_follows_the_client_image(tmp_path, monkeypatch):
    hosts = {"cl0": {"kind": "host", "ip": "192.168.0.2", "image": "lft-pydash-client"},
             "cl1": {"kind": "host", "ip": "192.168.0.3", "image": "lft-dash-client"},
             "ds0": {"kind": "host", "ip": "192.168.0.1", "image": "lft-pydash-server"}}
    monkeypatch.setattr(traffic.state, "load", lambda: {})
    monkeypatch.setattr(traffic.state, "containers", lambda: {})
    monkeypatch.setattr(traffic, "_running_host", lambda current, live, name: hosts[name])
    monkeypatch.setattr(traffic.results, "path", lambda rel: tmp_path)
    monkeypatch.setattr(traffic.sessions, "new_id", lambda kind, prefix: "t1")
    monkeypatch.setattr(traffic.sessions, "save", lambda kind, m: m)
    commands = []
    monkeypatch.setattr(traffic.sessions, "spawn", lambda argv, path: commands.append(argv[-1]) or 1)
    for client in ("cl0", "cl1"):
        traffic.start("dash", client, "ds0", duration=30, report=lambda *a: None)
    assert [c.split("; ")[1] for c in commands] == ["exec pydash-play 192.168.0.1 30", "exec dash-play 192.168.0.1 30"]
