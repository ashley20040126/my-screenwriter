from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class ModelConnectionConfig:
    provider: str = "mock"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    default_model: str = "gpt-5-mini"
    writer_model: str = "gpt-5"
    reviewer_model: str = "gpt-5-mini"
    editor_model: str = "gpt-5-mini"
    timeout_seconds: float = 180


class SqliteModelSettingsStore:
    def __init__(self, database_path: str, defaults: ModelConnectionConfig) -> None:
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = str(path)
        self.defaults = defaults
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS app_settings "
                "(key TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def get(self) -> ModelConnectionConfig:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM app_settings WHERE key = 'model_connection'"
            ).fetchone()
        if row is None:
            self.save(self.defaults)
            return self.defaults
        return ModelConnectionConfig(**json.loads(row["payload"]))

    def save(self, config: ModelConnectionConfig) -> None:
        payload = json.dumps(asdict(config), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO app_settings (key, payload) VALUES ('model_connection', ?) "
                "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload",
                (payload,),
            )
