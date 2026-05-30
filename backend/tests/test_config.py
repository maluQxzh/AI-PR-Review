from app.config import BACKEND_DIR, REPO_DIR, Settings


def test_settings_loads_root_and_backend_env_files():
    env_files = Settings.model_config["env_file"]

    assert env_files == (REPO_DIR / ".env", BACKEND_DIR / ".env")
