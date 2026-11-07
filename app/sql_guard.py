"""Fail-closed validator: only a single read-only SELECT/WITH statement passes."""

import re

MAX_SQL_LENGTH = 4000

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|"
    r"pragma|grant|revoke|merge|call|exec|execute|vacuum|copy|into|load_extension|"
    r"set_config|current_setting|dblink|information_schema|pg_[a-z_]+|lo_[a-z_]+)\b",
    re.IGNORECASE,
)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")


class SqlGuardError(ValueError):
    """Raised when a query is not an allowed read-only analytics query."""


def validate_select(sql: str, blocked_columns: frozenset[str]) -> str:
    """Return the cleaned query or raise SqlGuardError."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise SqlGuardError("Empty query.")
    if len(cleaned) > MAX_SQL_LENGTH:
        raise SqlGuardError("Query too long.")

    # Literals are removed first so keywords inside strings do not trigger checks.
    bare = _STRING_LITERAL.sub("''", cleaned)

    if "--" in bare or "/*" in bare or "*/" in bare:
        raise SqlGuardError("Comments are not allowed.")
    if ";" in bare:
        raise SqlGuardError("Only one statement is allowed.")
    if not re.match(r"(select|with)\b", bare, re.IGNORECASE):
        raise SqlGuardError("Only SELECT queries are allowed.")
    if _FORBIDDEN.search(bare):
        raise SqlGuardError("Query contains a forbidden keyword.")

    words = {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", bare)}
    hit = words & {c.lower() for c in blocked_columns}
    if hit:
        raise SqlGuardError(f"Access to restricted column(s) denied: {', '.join(sorted(hit))}.")

    return cleaned
