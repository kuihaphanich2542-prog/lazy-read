from app.parse import parse_int


class ConfigError(Exception):
    pass


def load_width(cfg):
    try:
        return parse_int(cfg["width"])
    except ValueError as exc:
        raise ConfigError("width must be an integer") from exc
