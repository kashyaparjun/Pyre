from pyre_agents import __version__
from pyre_agents.cli import main


def test_version_present() -> None:
    assert __version__


def test_cli_version_flag(capsys: object, monkeypatch: object) -> None:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    assert isinstance(capsys, CaptureFixture)
    assert isinstance(monkeypatch, MonkeyPatch)

    monkeypatch.setattr("sys.argv", ["pyre-agents", "--version"])
    main()
    captured = capsys.readouterr()
    assert captured.out.strip() == __version__
