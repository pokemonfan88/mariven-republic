import hashlib
import random
from datetime import date


def derive_seed(base_seed: int, schema_version: int, d: date,
                model_name: str, stream_name: str = "default") -> int:
    material = "|".join((
        str(int(base_seed)), str(int(schema_version)), d.isoformat(),
        model_name, stream_name,
    )).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:16], "big")


def make_rng(base_seed: int, schema_version: int, d: date,
             model_name: str, stream_name: str = "default") -> random.Random:
    return random.Random(derive_seed(
        base_seed, schema_version, d, model_name, stream_name,
    ))
