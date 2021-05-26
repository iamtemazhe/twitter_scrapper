import pathlib
import yaml
import os

BASE_DIR = pathlib.Path(__file__).parent.parent
DEFAULT_CONFIG_PATH = pathlib.Path(BASE_DIR) / 'config' / 'config.yaml'


def get_config(path: str = None) -> dict:
    env_path = os.environ.get('CONFIG_PATH')
    path = path or env_path or DEFAULT_CONFIG_PATH

    with open(path) as file:
        config = yaml.safe_load(file)

    return config
