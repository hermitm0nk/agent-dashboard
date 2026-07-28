from agent_dashboard.cli import main


def test_cli_requires_a_command(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["agent-dashboard", "--help"])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0
    output = capsys.readouterr().out
    assert "tui" in output
    assert "helper" in output


def test_cli_server_starts_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", ["agent-dashboard", "server", "--host", "0.0.0.0", "--port", "9000"])
    monkeypatch.setattr("agent_dashboard.server.run_server", lambda **kwargs: calls.append(kwargs))
    main()
    assert calls == [{"host": "0.0.0.0", "port": 9000, "reload": False}]


def test_cli_server_passes_database_path_to_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", ["agent-dashboard", "server", "--db", "/tmp/dashboard.db"])
    monkeypatch.delenv("AGENT_DASHBOARD_DB", raising=False)
    monkeypatch.setattr("agent_dashboard.server.run_server", lambda **kwargs: calls.append(kwargs))
    main()
    assert calls[0]["reload"] is False
    assert __import__("os").environ["AGENT_DASHBOARD_DB"] == "/tmp/dashboard.db"


def test_cli_server_reads_multi_instance_settings_from_environment(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", ["agent-dashboard", "server"])
    monkeypatch.setenv("AGENT_DASHBOARD_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("AGENT_DASHBOARD_PORT", "8123")
    monkeypatch.setenv("AGENT_DASHBOARD_DB", "/tmp/helper.db")
    monkeypatch.setenv("AGENT_DASHBOARD_HOST_ID", "workstation-a")
    monkeypatch.setenv("AGENT_DASHBOARD_MAIN_SERVER", "http://127.0.0.1:8000")
    monkeypatch.setattr("agent_dashboard.helper.run_helper", lambda **kwargs: calls.append(kwargs))

    main()

    assert calls == [{
        "server_url": "http://127.0.0.1:8000",
        "host_id": "workstation-a",
    }]
    assert __import__("os").environ["AGENT_DASHBOARD_HOST_ID"] == "workstation-a"


def test_cli_helper_starts_outbound_only_runtime(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", [
        "agent-dashboard", "helper",
        "--host-id", "workstation-a",
        "--main-server", "http://127.0.0.1:8000",
    ])
    monkeypatch.setattr("agent_dashboard.helper.run_helper", lambda **kwargs: calls.append(kwargs))

    main()

    assert calls == [{
        "server_url": "http://127.0.0.1:8000",
        "host_id": "workstation-a",
    }]


def test_cli_options_override_helper_environment(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", [
        "agent-dashboard", "server",
        "--host", "127.0.0.2", "--port", "9001",
        "--db", "/tmp/cli.db", "--host-id", "cli-host",
        "--main-server", "http://127.0.0.1:9000",
    ])
    monkeypatch.setenv("AGENT_DASHBOARD_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("AGENT_DASHBOARD_PORT", "8123")
    monkeypatch.setenv("AGENT_DASHBOARD_DB", "/tmp/env.db")
    monkeypatch.setenv("AGENT_DASHBOARD_HOST_ID", "env-host")
    monkeypatch.setenv("AGENT_DASHBOARD_MAIN_SERVER", "http://127.0.0.1:8000")
    monkeypatch.setattr("agent_dashboard.helper.run_helper", lambda **kwargs: calls.append(kwargs))

    main()

    assert calls == [{
        "server_url": "http://127.0.0.1:9000",
        "host_id": "cli-host",
    }]
    assert __import__("os").environ["AGENT_DASHBOARD_HOST_ID"] == "cli-host"


def test_helper_mode_does_not_create_database_or_start_server(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", [
        "agent-dashboard", "server",
        "--host-id", "workstation-a",
        "--main-server", "http://127.0.0.1:8000",
    ])
    monkeypatch.setattr("agent_dashboard.helper.run_helper", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(
        "agent_dashboard.db.Database.__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("helper must not construct a database")
        ),
    )
    monkeypatch.setattr(
        "agent_dashboard.server.run_server",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("helper must not start a listening server")
        ),
    )

    main()

    assert calls
