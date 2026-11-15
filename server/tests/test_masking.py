import base64

from deedbook.masking import mask_dict, mask_string


def test_mask_string_strategies():
    assert mask_string("secret_pass", "redact") == "[redacted]"

    key = base64.b64decode("dGVzdC1obWFjLWtleQ==")
    h1 = mask_string("user@example.com", "hash", hmac_key=key, salt="evt1")
    h2 = mask_string("user@example.com", "hash", hmac_key=key, salt="evt1")
    h3 = mask_string("user@example.com", "hash", hmac_key=key, salt="evt2")
    assert len(h1) == 16
    assert h1 == h2
    assert h1 != h3  # Salé par event_id

    assert mask_string("0612345678", "mask", keep=4) == "0612******"
    assert mask_string("123", "mask", keep=4) == "123"


def test_mask_dict_with_glob_rules():
    rules = [
        {"resource": "users", "field": "password_hash", "strategy": "redact"},
        {"resource": "users", "field": "email", "strategy": "hash"},
        {"resource": "*", "field": "*_secret", "strategy": "mask", "keep": 3},
    ]

    data = {
        "password_hash": "$2b$12$...",
        "email": "alice@corp.org",
        "api_secret": "my-top-secret-token",
        "nested": {
            "app_secret": "abcdefghi",
            "normal_field": "hello",
        },
    }

    masked = mask_dict(data, rules, resource_name="users", hmac_key=b"k", salt="e1")
    assert masked["password_hash"] == "[redacted]"
    assert len(masked["email"]) == 16
    assert masked["api_secret"] == "my-****************"
    assert masked["nested"]["app_secret"] == "abc******"
    assert masked["nested"]["normal_field"] == "hello"
