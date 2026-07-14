from agent_dashboard.cli import main


def test_cli_requires_a_command(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["agent-dashboard", "--help"])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0
    assert "tui" in capsys.readouterr().out


def test_cli_server_starts_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", ["agent-dashboard", "server", "--host", "0.0.0.0", "--port", "9000"])
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))
    main()
    assert calls == [(('agent_dashboard.api:app',), {"host": "0.0.0.0", "port": 9000, "reload": False,
                                                     "timeout_graceful_shutdown": 2})]


def test_cli_server_passes_database_path_to_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", ["agent-dashboard", "server", "--db", "/tmp/dashboard.db"])
    monkeypatch.delenv("AGENT_DASHBOARD_DB", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))
    main()
    assert calls[0][1]["reload"] is False
    assert __import__("os").environ["AGENT_DASHBOARD_DB"] == "/tmp/dashboard.db"
