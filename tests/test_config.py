from app.config import Settings, get_settings


def test_timezone():
    settings = get_settings()
    assert settings.timezone == "Europe/Berlin"


def test_app_env_is_set():
    settings = get_settings()
    assert settings.app_env != ""


def test_database_url_normalizes_postgres_scheme():
    s = Settings(database_url="postgres://u:p@h:5432/db")
    assert s.database_url.startswith("postgresql+psycopg://")


def test_database_url_normalizes_postgresql_scheme():
    s = Settings(database_url="postgresql://u:p@h:5432/db")
    assert s.database_url.startswith("postgresql+psycopg://")


def test_database_url_leaves_correct_scheme_unchanged():
    url = "postgresql+psycopg://sport:sport@localhost:5432/sportdb"
    s = Settings(database_url=url)
    assert s.database_url == url


def test_whoscored_defaults():
    s = Settings(_env_file=None)
    assert s.whoscored_enabled is True
    assert s.whoscored_headless is True
    assert s.whoscored_browser_path is None
    assert s.whoscored_data_dir is None
    assert s.whoscored_lock_timeout_seconds == 1800
    assert s.whoscored_league_list == ["GER-Bundesliga"]


def test_whoscored_league_list_splits_and_strips():
    s = Settings(whoscored_leagues=" GER-Bundesliga , ENG-Premier League ,,")
    assert s.whoscored_league_list == ["GER-Bundesliga", "ENG-Premier League"]


def test_api_football_settings_removed():
    s = Settings()
    assert not hasattr(s, "api_football_key")
    assert not hasattr(s, "api_football_base_url")
