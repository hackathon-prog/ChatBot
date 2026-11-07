import pytest

from app.sql_guard import SqlGuardError, validate_select

BLOCKED = frozenset({"email", "password_hash"})


def test_accepts_plain_select():
    assert validate_select("SELECT COUNT(*) FROM students;", BLOCKED) == "SELECT COUNT(*) FROM students"


def test_accepts_cte():
    sql = "WITH t AS (SELECT 1 AS x) SELECT x FROM t"
    assert validate_select(sql, BLOCKED) == sql


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM students",
        "UPDATE students SET cohort='x'",
        "INSERT INTO students VALUES (1)",
        "DROP TABLE students",
        "SELECT 1; DROP TABLE students",
        "SELECT 1 -- comment",
        "SELECT 1 /* c */",
        "PRAGMA table_info(students)",
        "ATTACH DATABASE 'x.db' AS x",
        "SELECT * FROM students INTO OUTFILE '/tmp/x'",
        "",
        "   ",
    ],
)
def test_rejects_non_read_queries(sql):
    with pytest.raises(SqlGuardError):
        validate_select(sql, BLOCKED)


def test_rejects_blocked_column():
    with pytest.raises(SqlGuardError):
        validate_select("SELECT email FROM students", BLOCKED)


def test_keyword_inside_string_literal_is_allowed():
    sql = "SELECT COUNT(*) FROM courses WHERE title = 'Drop shipping 101'"
    assert validate_select(sql, BLOCKED) == sql


def test_rejects_too_long_query():
    with pytest.raises(SqlGuardError):
        validate_select("SELECT " + "1," * 5000 + "1", BLOCKED)
