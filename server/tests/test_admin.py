from deedbook.admin import APP_NAME_RE, role_dsn


def test_role_dsn_rebuilds_url():
    base = "postgresql://admin:secret@db.example.com:5433/mydb"
    url = role_dsn(base, "deedbook_ingest", "p@ss/word")
    assert url == "postgresql://deedbook_ingest:p%40ss%2Fword@db.example.com:5433/mydb"


def test_role_dsn_keyword_conninfo():
    base = "host=localhost port=5434 dbname=deedbook user=admin password=x"
    url = role_dsn(base, "deedbook_read", "pw")
    assert url == "postgresql://deedbook_read:pw@localhost:5434/deedbook"


def test_app_name_validation():
    assert APP_NAME_RE.match("monapp")
    assert APP_NAME_RE.match("mon-app_2")
    assert not APP_NAME_RE.match("MonApp")
    assert not APP_NAME_RE.match("-bad")
    assert not APP_NAME_RE.match("a" * 64)
