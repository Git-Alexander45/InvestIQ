from investiq import desktop


def test_first_start_creates_private_settings_and_keeps_them(tmp_path):
    env_file = desktop.ensure_home(tmp_path)
    values = desktop.read_env(env_file)
    assert values["INVESTIQ_ENV"] == "production"
    assert values["INVESTIQ_DATABASE_URL"].startswith("sqlite:///") and values["INVESTIQ_DATABASE_URL"].endswith(
        "data/investiq.sqlite3")
    assert len(values["INVESTIQ_API_TOKEN"]) >= 40
    assert values["ANTHROPIC_API_KEY"] == "" and values["INVESTIQ_API_HOST"] == "127.0.0.1"
    assert (tmp_path / "backups").is_dir() and (tmp_path / "outbox").is_dir()
    # A second start never replaces the owner's settings or token.
    env_file.write_text(env_file.read_text() + "INVESTIQ_FMP_API_KEY=mine\n")
    desktop.ensure_home(tmp_path)
    again = desktop.read_env(env_file)
    assert again["INVESTIQ_API_TOKEN"] == values["INVESTIQ_API_TOKEN"] and again["INVESTIQ_FMP_API_KEY"] == "mine"


def test_app_home_and_bundle_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIQ_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("INVESTIQ_BUNDLE_DIR", str(tmp_path / "b"))
    assert desktop.app_home() == tmp_path / "h" and desktop.bundle_dir() == tmp_path / "b"


def test_scheduled_task_is_skipped_off_windows(tmp_path):
    import os

    if os.name != "nt":
        assert desktop.register_task(tmp_path / "InvestIQ-Background.exe").startswith("skipped")
