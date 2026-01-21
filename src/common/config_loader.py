import yaml
import os

class Config:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        # プロジェクトルートからの相対パスでconfig.yamlを探す
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(base_dir, "config", "config.yaml")
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found at {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

    @property
    def db_path(self):
        return self._data["system"]["db_path"]

    @property
    def polling_interval(self):
        return self._data["polling"]["interval_seconds"]
    
    @property
    def retention_minutes(self):
        return self._data["system"]["retention_minutes"]
    
    @property
    def web_port(self):
        return self._data["system"]["web_port"]

    @property
    def web_host(self):
        return self._data["system"]["web_host"]

    @property
    def web_reload(self):
        return self._data["system"]["web_reload"]

    @property
    def log_level(self):
        return self._data["system"]["log_level"]

    @property
    def polling_timeout(self):
        return self._data["polling"]["timeout"]


# どこからでも import config で使えるようにインスタンス化しておく
config = Config()