import psycopg2
import pytest


def test_non_local_database_is_refused():
    with pytest.raises(RuntimeError, match="non-local database"):
        psycopg2.connect("postgresql://u:p@db.example.com:5432/x")
    with pytest.raises(RuntimeError, match="non-local database"):
        psycopg2.connect(host="db.example.com", dbname="x")
