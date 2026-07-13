from agent_dashboard.cli import main


def test_cli_requires_a_command(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["agent-dashboard", "--help"])
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 0
    assert "tui" in capsys.readouterr().out
