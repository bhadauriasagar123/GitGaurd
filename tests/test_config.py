import pytest

from app.core.config import Settings


def prod(**kw):
    base = dict(env="production", api_keys="k" * 24 + ":admin:acme", enc_key="a" * 64,
                database_url="postgresql+asyncpg://u:p@h/db", redis_url="rediss://h:6379")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_production_valid_config():
    s = prod()
    assert s.is_prod and s.key_ring()[0]["role"] == "admin" and "k" * 24 not in str(s.key_ring())  # keys stored hashed only


@pytest.mark.parametrize("override", [{"api_keys": ""}, {"enc_key": "short"}, {"redis_url": "fakeredis://"},
                                      {"database_url": "sqlite+aiosqlite:///x.db"}])
def test_production_refuses_insecure_defaults(override):
    with pytest.raises(ValueError):
        prod(**override)


def test_weak_or_malformed_keys_rejected_in_production():
    with pytest.raises(ValueError):
        prod(api_keys="short:admin:acme").key_ring()
    with pytest.raises(ValueError):
        prod(api_keys="k" * 24 + ":root:acme").key_ring()
    with pytest.raises(ValueError):
        prod(api_keys="k" * 24 + ":admin").key_ring()
