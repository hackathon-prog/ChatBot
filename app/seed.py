"""Create a sample LMS database. Replace with your real DATABASE_URL in production."""

import random
import sqlite3
import sys
from datetime import date, timedelta

SCHEMA = """
CREATE TABLE students (id INTEGER PRIMARY KEY, display_name TEXT, email TEXT, cohort TEXT, enrolled_at TEXT);
CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT, category TEXT);
CREATE TABLE lessons (id INTEGER PRIMARY KEY, course_id INTEGER, title TEXT, position INTEGER);
CREATE TABLE enrollments (id INTEGER PRIMARY KEY, student_id INTEGER, course_id INTEGER, enrolled_at TEXT, completed_at TEXT);
CREATE TABLE lesson_progress (id INTEGER PRIMARY KEY, student_id INTEGER, lesson_id INTEGER, completed_at TEXT, minutes_spent INTEGER);
CREATE TABLE quiz_attempts (id INTEGER PRIMARY KEY, student_id INTEGER, course_id INTEGER, score REAL, attempted_at TEXT);
"""

COURSES = [
    ("Intro to Python", "Programming"),
    ("Data Analysis Basics", "Data"),
    ("Web Fundamentals", "Programming"),
    ("Project Management", "Business"),
    ("Statistics 101", "Data"),
]


def seed_database(url: str, students: int = 200) -> None:
    path = url.removeprefix("sqlite:///")
    rng = random.Random(42)
    today = date.today()
    conn = sqlite3.connect(path)
    drops = "".join(
        f"DROP TABLE IF EXISTS {t};"
        for t in ("students", "courses", "lessons", "enrollments", "lesson_progress", "quiz_attempts")
    )
    conn.executescript(drops + SCHEMA)
    cur = conn.cursor()

    cohorts = ["2025-A", "2025-B", "2026-A"]
    for sid in range(1, students + 1):
        d = today - timedelta(days=rng.randint(30, 400))
        cur.execute(
            "INSERT INTO students VALUES (?,?,?,?,?)",
            (sid, f"Student {sid}", f"s{sid}@example.test", rng.choice(cohorts), d.isoformat()),
        )
    for cid, (title, cat) in enumerate(COURSES, start=1):
        cur.execute("INSERT INTO courses VALUES (?,?,?)", (cid, title, cat))
        for pos in range(1, 9):
            cur.execute("INSERT INTO lessons VALUES (?,?,?,?)", (cid * 100 + pos, cid, f"Lesson {pos}", pos))

    for sid in range(1, students + 1):
        for cid in rng.sample(range(1, len(COURSES) + 1), rng.randint(1, 3)):
            start = today - timedelta(days=rng.randint(10, 300))
            done = rng.random() < 0.55
            end = (start + timedelta(days=rng.randint(7, 60))).isoformat() if done else None
            cur.execute(
                "INSERT INTO enrollments (student_id, course_id, enrolled_at, completed_at) VALUES (?,?,?,?)",
                (sid, cid, start.isoformat(), end),
            )
            reached = 8 if done else rng.randint(0, 7)
            for pos in range(1, reached + 1):
                day = start + timedelta(days=pos * 2)
                cur.execute(
                    "INSERT INTO lesson_progress (student_id, lesson_id, completed_at, minutes_spent) VALUES (?,?,?,?)",
                    (sid, cid * 100 + pos, day.isoformat(), rng.randint(5, 60)),
                )
            for _ in range(rng.randint(0, 3)):
                cur.execute(
                    "INSERT INTO quiz_attempts (student_id, course_id, score, attempted_at) VALUES (?,?,?,?)",
                    (sid, cid, round(rng.gauss(72, 15), 1), (start + timedelta(days=rng.randint(1, 30))).isoformat()),
                )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "sqlite:///lms.db"
    seed_database(target)
    print(f"Seeded {target}")
