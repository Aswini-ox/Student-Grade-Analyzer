import importlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import template_rendered


class StudentGradeAnalyzerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.import_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.import_directory.cleanup)
        import_database = str(Path(cls.import_directory.name) / "import.db")
        with patch.dict(os.environ, {"STUDENT_GRADE_DB": import_database}):
            cls.module = importlib.import_module("app")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "students.db")
        self.app = self.module.create_app({
            "TESTING": True,
            "DATABASE": self.database,
            "SECRET_KEY": "unittest-secret",
        })
        self.client = self.app.test_client()
        self.contexts = []
        template_rendered.connect(self.capture_context, self.app, weak=False)
        self.addCleanup(template_rendered.disconnect, self.capture_context, self.app)
        self.client.get("/students/new")
        with self.client.session_transaction() as session:
            self.token = session["csrf_token"]

    def capture_context(self, sender, template, context, **extra):
        self.contexts.append(context)

    def form(self, roll="TEST001", mark="50", **overrides):
        data = {
            "csrf_token": self.token,
            "name": "Test Student",
            "roll_number": roll,
            "department": "Computing",
            "semester": "2",
        }
        data.update({subject: mark for subject in self.module.SUBJECTS})
        data.update(overrides)
        return data

    def rows(self, query, parameters=()):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute(query, parameters)]
        finally:
            connection.close()

    def add_student(self, **fields):
        data = self.form(**fields)
        response = self.client.post("/students/new", data=data)
        self.assertEqual(response.status_code, 302)
        return self.rows("SELECT * FROM students WHERE roll_number = ?", (data["roll_number"],))[0]

    def test_page_routes_and_missing_students(self):
        for path in ("/", "/students", "/students/new", "/students/1", "/students/1/edit",
                     "/analytics", "/reports", "/settings"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        for path in ("/students/99999", "/students/99999/edit", "/students/99999/report.pdf"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.contexts[-1]["stats"]["total"], 8)

    def test_csrf_is_required_for_all_changes(self):
        for path in ("/students/new", "/students/1/edit", "/students/1/delete",
                     "/settings", "/settings/clear-demo"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 400)
        self.assertEqual(self.client.post("/students/1/delete", data={"csrf_token": "wrong"}).status_code, 400)
        self.assertEqual(len(self.rows("SELECT id FROM students")), 8)

    def test_grade_thresholds_and_pass_rule(self):
        cases = (
            ("0", "F", "FAIL"), ("34.99", "F", "FAIL"), ("35", "F", "PASS"),
            ("49.99", "F", "PASS"), ("50", "D", "PASS"), ("59.99", "D", "PASS"),
            ("60", "C", "PASS"), ("69.99", "C", "PASS"), ("70", "B", "PASS"),
            ("79.99", "B", "PASS"), ("80", "A", "PASS"), ("89.99", "A", "PASS"),
            ("90", "A+", "PASS"), ("100", "A+", "PASS"),
        )
        for index, (mark, grade, result) in enumerate(cases):
            with self.subTest(mark=mark):
                student = self.add_student(roll=f"GRADE-{index}", mark=mark)
                self.assertEqual((student["grade"], student["result"]), (grade, result))
        mixed = self.add_student(roll="MIXED", mark="100", python="34.99")
        self.assertEqual((mixed["grade"], mixed["result"]), ("A", "FAIL"))
        near_grade = self.add_student(roll="NEAR-GRADE", mark="90", python="89.99")
        self.assertEqual((near_grade["average"], near_grade["grade"]), (89.998, "A"))

    def test_optional_valid_and_invalid_email(self):
        omitted = self.add_student(roll="NO-EMAIL")
        blank = self.add_student(roll="BLANK-EMAIL", email="   ")
        valid = self.add_student(roll="VALID-EMAIL", email="student+test@example.com")
        self.assertEqual((omitted["email"], blank["email"]), ("", ""))
        self.assertEqual(valid["email"], "student+test@example.com")
        for email in ("invalid", "user@@example.com", ".user@example.com", "user@example..com"):
            with self.subTest(email=email):
                response = self.client.post("/students/new", data=self.form(roll="BAD-EMAIL", email=email))
                self.assertEqual(response.status_code, 200)
                self.assertIn("email", self.contexts[-1]["errors"])
                self.assertEqual(self.rows("SELECT id FROM students WHERE roll_number = 'BAD-EMAIL'"), [])

    def test_mark_precision_and_scientific_notation(self):
        for index, (mark, expected) in enumerate((("0", 0), ("100", 100), ("34.99", 34.99),
                                                  ("1e-2", 0.01), ("1.234e1", 12.34))):
            with self.subTest(mark=mark):
                student = self.add_student(roll=f"MARK-{index}", python=mark)
                self.assertEqual(student["python"], expected)
        for mark in ("1.234", "1.230", "99.999", "1e-3", "100.01", "-0.01", "NaN", "Infinity", ""):
            with self.subTest(mark=mark):
                response = self.client.post("/students/new", data=self.form(roll="BAD-MARK", python=mark))
                self.assertEqual(response.status_code, 200)
                self.assertIn("python", self.contexts[-1]["errors"])
                self.assertEqual(self.rows("SELECT id FROM students WHERE roll_number = 'BAD-MARK'"), [])
        response = self.client.post("/students/1/edit", data=self.form(roll="DEMO001", python="89.999"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("python", self.contexts[-1]["errors"])
        self.assertEqual(self.rows("SELECT python, is_demo FROM students WHERE id = 1")[0],
                         {"python": 91, "is_demo": 1})

    def test_semester_validation(self):
        for index, (value, expected) in enumerate((("1", 1), ("1.0", 1), ("1e0", 1), ("1.2e1", 12))):
            with self.subTest(value=value):
                student = self.add_student(roll=f"SEM-{index}", semester=value)
                self.assertEqual(student["semester"], expected)
        for value in ("1.1", "0", "13", "NaN", ""):
            with self.subTest(value=value):
                response = self.client.post("/students/new", data=self.form(roll="BAD-SEM", semester=value))
                self.assertEqual(response.status_code, 200)
                self.assertIn("semester", self.contexts[-1]["errors"])

    def test_case_insensitive_duplicate_rolls(self):
        student = self.add_student(roll="Straße")
        response = self.client.post("/students/new", data=self.form(roll="STRASSE"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("roll_number", self.contexts[-1]["errors"])
        response = self.client.post(f"/students/{student['id']}/edit", data=self.form(roll="demo001"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("roll_number", self.contexts[-1]["errors"])
        self.assertEqual(self.rows("SELECT roll_number FROM students WHERE id = ?", (student["id"],))[0]["roll_number"], "Straße")

    def test_student_create_read_edit_delete(self):
        student = self.add_student(roll="CRUD", name="Original Name", mark="70")
        student_id = student["id"]
        response = self.client.get(f"/students/{student_id}")
        self.assertIn(b"Original Name", response.data)
        response = self.client.post(f"/students/{student_id}/edit", data=self.form(roll="CRUD", name="Updated Name", mark="80"))
        self.assertEqual(response.status_code, 302)
        updated = self.rows("SELECT name, grade, result FROM students WHERE id = ?", (student_id,))[0]
        self.assertEqual(updated, {"name": "Updated Name", "grade": "A", "result": "PASS"})
        self.assertIn(b"Updated Name", self.client.get(f"/students/{student_id}").data)
        response = self.client.post(f"/students/{student_id}/delete", data={"csrf_token": self.token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(f"/students/{student_id}").status_code, 404)
        self.assertEqual(self.client.post(f"/students/{student_id}/delete", data={"csrf_token": self.token}).status_code, 404)

    def test_search_filters_and_safe_sorting(self):
        self.add_student(roll="FILTER-PASS", name="Filter Alice", mark="90")
        self.add_student(roll="FILTER-FAIL", name="Filter Bob", mark="90", python="34.99")
        response = self.client.get("/students", query_string={"q": "filter", "grade": "A+", "result": "PASS"})
        self.assertEqual(response.status_code, 200)
        context = self.contexts[-1]
        self.assertEqual([row["roll_number"] for row in context["records"]], ["FILTER-PASS"])
        self.assertEqual(context["pagination"]["total"], 1)
        self.client.get("/students", query_string={"q": "%", "sort": "name; DROP TABLE students", "direction": "invalid"})
        context = self.contexts[-1]
        self.assertEqual(context["pagination"]["total"], 0)
        self.assertEqual((context["filters"]["sort"], context["filters"]["direction"]), ("name", "asc"))
        self.assertEqual(len(self.rows("SELECT id FROM students")), 10)

    def test_academic_grade_sort_and_pagination(self):
        for index, mark in enumerate(("90", "80", "70", "60", "50", "35", "91", "81", "71", "61", "51", "36")):
            self.add_student(roll=f"SORT-{index}", mark=mark)
        ascending = ["A+", "A+", "A", "A", "B", "B", "C", "C", "D", "D", "F", "F"]
        for direction, expected in (("asc", ascending), ("desc", list(reversed(ascending)))):
            grades = []
            for page in (1, 2):
                response = self.client.get("/students", query_string={"q": "SORT-", "sort": "grade",
                                                                      "direction": direction, "page": page})
                self.assertEqual(response.status_code, 200)
                context = self.contexts[-1]
                self.assertEqual((context["pagination"]["total"], context["pagination"]["pages"]), (12, 2))
                grades.extend(row["grade"] for row in context["records"])
            self.assertEqual(grades, expected)

    def test_settings_demo_clearing_and_restart_persistence(self):
        regular = self.add_student(roll="REGULAR")
        response = self.client.post("/students/1/edit", data=self.form(roll="DEMO001", name="Edited Demo"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.rows("SELECT is_demo FROM students WHERE id = 1")[0]["is_demo"], 0)
        response = self.client.post("/settings", data={"csrf_token": self.token, "school_name": ""})
        self.assertEqual(response.status_code, 200)
        response = self.client.post("/settings", data={"csrf_token": self.token, "school_name": "Example School"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post("/settings/clear-demo", data={"csrf_token": self.token})
        self.assertEqual(response.status_code, 302)
        students = self.rows("SELECT id, name, is_demo FROM students ORDER BY id")
        self.assertEqual([row["id"] for row in students], [1, regular["id"]])
        self.assertTrue(all(row["is_demo"] == 0 for row in students))
        restarted = self.module.create_app({"TESTING": True, "DATABASE": self.database, "SECRET_KEY": "unittest-secret"})
        self.assertEqual(restarted.test_client().get("/students/1").status_code, 200)
        self.assertEqual(self.rows("SELECT id, name, is_demo FROM students ORDER BY id"), students)
        self.assertEqual(self.rows("SELECT value FROM settings WHERE key = 'school_name'")[0]["value"], "Example School")

    def test_pdf_contains_precise_values(self):
        student = self.add_student(roll="PDF", mark="90", python="89.99")
        response = self.client.get(f"/students/{student['id']}/report.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertIn("attachment", response.headers["Content-Disposition"])
        with patch("reportlab.rl_config.pageCompression", 0):
            uncompressed = self.client.get(f"/students/{student['id']}/report.pdf")
        for expected in (b"(89.99)", b"(90.00)", b"(449.99)", b"(89.998%)", b"(PASS)"):
            with self.subTest(expected=expected):
                self.assertIn(expected, uncompressed.data)


if __name__ == "__main__":
    unittest.main()
