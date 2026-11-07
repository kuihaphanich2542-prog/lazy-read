from app.config import load_width


def normalize(raw):
    """Turn a raw form dict into a validated width."""
    width = raw.get("width", "0")
    width = str(width).strip() + "px"
    cfg = {"width": width}
    return load_width(cfg)
