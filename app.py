import hmac
import io
import math
import os
import re
import secrets
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.sax.saxutils import escape

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SUBJECTS = ("python", "java", "sql", "mathematics", "english")
SUBJECT_LABELS = {"python": "Python", "java": "Java", "sql": "SQL", "mathematics": "Mathematics", "english": "English"}
GRADES = ("A+", "A", "B", "C", "D", "F")
FIELDS = ("name", "roll_number", "email", "department", "semester", *SUBJECTS)
SORT_COLUMNS = {name: name for name in ("roll_number", "name", "department", "total", "average", "grade", "result")}
SORT_COLUMNS["grade"] = "CASE grade WHEN 'A+' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 WHEN 'D' THEN 4 WHEN 'F' THEN 5 ELSE 6 END"
NUMBER_PATTERN = r"-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
PER_PAGE = 10
DEMO_STUDENTS = (
    ("Aarav Sharma", "DEMO001", "aarav@example.com", "Computer Science", 3, 91, 88, 93, 86, 90),
    ("Diya Patel", "DEMO002", "diya@example.com", "Computer Science", 3, 78, 85, 80, 76, 82),
    ("Rohan Mehta", "DEMO003", "rohan@example.com", "Information Technology", 2, 72, 68, 75, 71, 74),
    ("Ananya Rao", "DEMO004", "ananya@example.com", "Information Technology", 4, 96, 94, 92, 95, 97),
    ("Kabir Singh", "DEMO005", "kabir@example.com", "Computer Science", 2, 62, 59, 64, 61, 66),
    ("Meera Nair", "DEMO006", "meera@example.com", "Data Science", 4, 53, 55, 58, 51, 56),
    ("Arjun Kumar", "DEMO007", "arjun@example.com", "Data Science", 1, 41, 39, 44, 38, 42),
    ("Isha Verma", "DEMO008", "isha@example.com", "Computer Science", 1, 70, 32, 65, 60, 68),
)


def calculate_marks(marks):
    values = [Decimal(str(marks[subject])) for subject in SUBJECTS]
    total = sum(values, Decimal(0))
    percentage = total / Decimal(len(SUBJECTS))
    grade = next((label for minimum, label in ((90, "A+"), (80, "A"), (70, "B"), (60, "C"), (50, "D")) if percentage >= minimum), "F")
    return {
        "total": float(total),
        "average": float(percentage),
        "percentage": float(percentage),
        "grade": grade,
        "result": "PASS" if all(value >= 35 for value in values) else "FAIL",
    }


def connect_database(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def get_db():
    if "db" not in g:
        g.db = connect_database(g.app_database)
    return g.db


def insert_student(db, student, is_demo=0):
    computed = calculate_marks(student)
    db.execute(
        """INSERT INTO students
        (name, roll_number, roll_key, email, department, semester, python, java, sql, mathematics, english,
         total, average, percentage, grade, result, is_demo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (student["name"], student["roll_number"], student["roll_number"].casefold(), student["email"],
         student["department"], student["semester"], *(student[s] for s in SUBJECTS),
         computed["total"], computed["average"], computed["percentage"], computed["grade"], computed["result"], is_demo),
    )


def initialize_database(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = connect_database(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, roll_number TEXT NOT NULL, roll_key TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL, department TEXT NOT NULL, semester INTEGER NOT NULL,
            python REAL NOT NULL, java REAL NOT NULL, sql REAL NOT NULL,
            mathematics REAL NOT NULL, english REAL NOT NULL,
            total REAL NOT NULL, average REAL NOT NULL, percentage REAL NOT NULL,
            grade TEXT NOT NULL, result TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0
        )""")
        db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        initialized = db.execute("SELECT value FROM settings WHERE key = 'initialized'").fetchone()
        if not initialized:
            for row in DEMO_STUDENTS:
                insert_student(db, dict(zip(FIELDS, row)), is_demo=1)
            db.execute("INSERT INTO settings (key, value) VALUES ('initialized', '1')")
            db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('school_name', 'Student Grade Analyzer')")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def valid_email(value):
    parts = value.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    if not local or len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        return False
    allowed = "!#$%&'*+/=?^_`{|}~.-"
    if any(not char.isalnum() and char not in allowed for char in local):
        return False
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = domain.split(".")
    return len(domain) <= 253 and len(labels) >= 2 and all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in labels
    )


def validate_student(form):
    student = {field: str(form.get(field, "")).strip() for field in FIELDS}
    errors = {}
    limits = {"name": 100, "roll_number": 50, "email": 254, "department": 100}
    for field, limit in limits.items():
        value = student[field]
        if not value and field != "email":
            errors[field] = "This field is required."
        elif len(value) > limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
            errors[field] = f"Enter at most {limit} characters without control characters."
    if student["email"] and "email" not in errors and not valid_email(student["email"]):
        errors["email"] = "Enter a valid email address."
    try:
        if not re.fullmatch(NUMBER_PATTERN, student["semester"]):
            raise ValueError
        semester = Decimal(student["semester"])
        if not semester.is_finite() or not 1 <= semester <= 12 or semester != semester.to_integral_value():
            raise ValueError
        student["semester"] = int(semester)
    except (InvalidOperation, ValueError, OverflowError):
        errors["semester"] = "Enter a whole-number semester from 1 to 12."
    for subject in SUBJECTS:
        try:
            if not re.fullmatch(NUMBER_PATTERN, student[subject]):
                raise ValueError
            value = Decimal(student[subject])
            if not value.is_finite() or not Decimal(0) <= value <= Decimal(100) or value.as_tuple().exponent < -2:
                raise ValueError
            student[subject] = float(value)
        except (InvalidOperation, ValueError, OverflowError):
            errors[subject] = "Enter a number from 0 to 100 with at most 2 decimal places."
    return student, errors


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def summary(db):
    row = db.execute("""SELECT COUNT(*) AS total, COALESCE(AVG(average), 0) AS average,
        COALESCE(SUM(CASE WHEN result = 'PASS' THEN 1 ELSE 0 END), 0) AS passed,
        COALESCE(SUM(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END), 0) AS failed,
        COALESCE(AVG(python), 0) AS python, COALESCE(AVG(java), 0) AS java,
        COALESCE(AVG(sql), 0) AS sql, COALESCE(AVG(mathematics), 0) AS mathematics,
        COALESCE(AVG(english), 0) AS english FROM students""").fetchone()
    counts = {grade: 0 for grade in GRADES}
    for item in db.execute("SELECT grade, COUNT(*) AS n FROM students GROUP BY grade"):
        if item["grade"] in counts:
            counts[item["grade"]] = item["n"]
    stats = {key: row[key] for key in ("total", "average", "passed", "failed")}
    stats["pass_rate"] = stats["passed"] * 100 / stats["total"] if stats["total"] else 0
    averages = {SUBJECT_LABELS[subject]: row[subject] for subject in SUBJECTS}
    return stats, counts, averages


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("STUDENT_GRADE_DB") or str(Path(app.root_path) / "database" / "students.db"),
        MAX_CONTENT_LENGTH=1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)
    initialize_database(app.config["DATABASE"])

    @app.url_defaults
    def student_url_defaults(endpoint, values):
        if endpoint in {"edit_student", "delete_student", "student_details", "download_pdf"} and "id" in values and "student_id" not in values:
            values["student_id"] = values.pop("id")

    @app.before_request
    def prepare_request():
        g.app_database = app.config["DATABASE"]
        if request.method == "POST":
            expected = session.get("csrf_token", "")
            submitted = request.form.get("csrf_token", "")
            if not expected or not submitted or not hmac.compare_digest(expected.encode("utf-8"), submitted.encode("utf-8")):
                abort(400, description="Invalid or missing CSRF token. Reload the page and try again.")

    @app.teardown_appcontext
    def close_database(error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def shared_context():
        db = get_db()
        stats, grade_counts, subject_averages = summary(db)
        row = db.execute("SELECT value FROM settings WHERE key = 'school_name'").fetchone()
        return {"stats": stats, "grade_counts": grade_counts, "subject_averages": subject_averages,
                "school_name": row["value"] if row else "Student Grade Analyzer", "csrf_token": csrf_token}

    def student_or_404(student_id):
        row = get_db().execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if row is None:
            abort(404)
        student = dict(row)
        student.pop("roll_key", None)
        return student

    def student_list(rows):
        students = []
        for row in rows:
            student = dict(row)
            student.pop("roll_key", None)
            students.append(student)
        return students

    @app.get("/")
    def dashboard():
        db = get_db()
        recent = student_list(db.execute("SELECT * FROM students ORDER BY id DESC LIMIT 5").fetchall())
        stats, counts, averages = summary(db)
        return render_template("dashboard.html", recent_students=recent, stats=stats,
                               grade_counts=counts, subject_averages=averages)

    @app.route("/students/new", methods=["GET", "POST"])
    def add_student():
        student = {field: "" for field in FIELDS}
        errors = {}
        if request.method == "POST":
            student, errors = validate_student(request.form)
            db = get_db()
            if not errors:
                try:
                    insert_student(db, student)
                    db.commit()
                except sqlite3.IntegrityError:
                    db.rollback()
                    errors["roll_number"] = "That roll number is already in use."
            if not errors:
                flash("Student added successfully.", "success")
                return redirect(url_for("student_records"))
            flash("Please correct the errors below.", "error")
            student = {field: request.form.get(field, "").strip() for field in FIELDS}
        return render_template("add_student.html", student=student, errors=errors, is_edit=False)

    @app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
    def edit_student(student_id):
        existing = student_or_404(student_id)
        student = existing
        errors = {}
        if request.method == "POST":
            student, errors = validate_student(request.form)
            if not errors:
                computed = calculate_marks(student)
                db = get_db()
                try:
                    db.execute("""UPDATE students SET name=?, roll_number=?, roll_key=?, email=?, department=?,
                        semester=?, python=?, java=?, sql=?, mathematics=?, english=?, total=?, average=?,
                        percentage=?, grade=?, result=?, is_demo=0 WHERE id=?""",
                        (student["name"], student["roll_number"], student["roll_number"].casefold(), student["email"],
                         student["department"], student["semester"], *(student[s] for s in SUBJECTS),
                         computed["total"], computed["average"], computed["percentage"], computed["grade"],
                         computed["result"], student_id))
                    db.commit()
                except sqlite3.IntegrityError:
                    db.rollback()
                    errors["roll_number"] = "That roll number is already in use."
            if not errors:
                flash("Student updated successfully.", "success")
                return redirect(url_for("student_details", student_id=student_id))
            flash("Please correct the errors below.", "error")
            student = {field: request.form.get(field, "").strip() for field in FIELDS}
            student["id"] = student_id
        return render_template("add_student.html", student=student, errors=errors, is_edit=True)

    @app.get("/students")
    def student_records():
        q = request.args.get("q", "").strip()[:100]
        grade = request.args.get("grade", "").strip().upper()
        result = request.args.get("result", "").strip().upper()
        sort = request.args.get("sort", "name").strip().lower()
        direction = request.args.get("direction", "asc").strip().lower()
        grade = grade if grade in GRADES else ""
        result = result if result in ("PASS", "FAIL") else ""
        sort = sort if sort in SORT_COLUMNS else "name"
        direction = direction if direction in ("asc", "desc") else "asc"
        filters = {"q": q, "grade": grade, "result": result, "sort": sort, "direction": direction}
        conditions = []
        parameters = []
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("(name LIKE ? ESCAPE '\\' OR roll_number LIKE ? ESCAPE '\\' OR department LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\')")
            parameters.extend([f"%{escaped}%"] * 4)
        if grade:
            conditions.append("grade = ?")
            parameters.append(grade)
        if result:
            conditions.append("result = ?")
            parameters.append(result)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        db = get_db()
        total = db.execute("SELECT COUNT(*) FROM students" + where, parameters).fetchone()[0]
        pages = max(1, math.ceil(total / PER_PAGE))
        try:
            page = int(request.args.get("page", "1"))
        except (ValueError, TypeError):
            page = 1
        page = min(max(page, 1), pages)
        offset = (page - 1) * PER_PAGE
        query = "SELECT * FROM students" + where + f" ORDER BY {SORT_COLUMNS[sort]} COLLATE NOCASE {direction.upper()}, id ASC LIMIT ? OFFSET ?"
        records = student_list(db.execute(query, (*parameters, PER_PAGE, offset)).fetchall())
        pagination = {"page": page, "pages": pages, "total": total, "start": offset + 1 if total else 0,
                      "end": offset + len(records), "per_page": PER_PAGE}
        return render_template("student_records.html", records=records, pagination=pagination, filters=filters)

    @app.post("/students/<int:student_id>/delete")
    def delete_student(student_id):
        student_or_404(student_id)
        db = get_db()
        db.execute("DELETE FROM students WHERE id = ?", (student_id,))
        db.commit()
        flash("Student deleted successfully.", "success")
        return redirect(url_for("student_records"))

    @app.get("/students/<int:student_id>")
    def student_details(student_id):
        return render_template("student_details.html", student=student_or_404(student_id))

    @app.get("/students/<int:student_id>/report.pdf")
    def download_pdf(student_id):
        student = student_or_404(student_id)
        school = get_db().execute("SELECT value FROM settings WHERE key = 'school_name'").fetchone()
        school_name = school["value"] if school else "Student Grade Analyzer"
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=(8.5 * inch, 11 * inch), rightMargin=54, leftMargin=54, topMargin=48, bottomMargin=48)
        styles = getSampleStyleSheet()
        styles["Title"].alignment = TA_CENTER
        story = [Paragraph(escape(school_name), styles["Title"]), Spacer(1, 12),
                 Paragraph("Student Performance Report", styles["Heading2"]), Spacer(1, 8)]
        details = [("Name", student["name"]), ("Roll number", student["roll_number"]),
                   ("Email", student["email"]), ("Department", student["department"]), ("Semester", student["semester"])]
        rows = [[Paragraph(escape(str(label)), styles["Normal"]), Paragraph(escape(str(value)), styles["Normal"])] for label, value in details]
        details_table = Table(rows, colWidths=[140, 340], hAlign="LEFT")
        details_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story.extend([details_table, Spacer(1, 15)])
        marks_rows = [["Subject", "Marks / 100"]] + [[SUBJECT_LABELS[s], f"{student[s]:.2f}"] for s in SUBJECTS]
        marks_rows += [["Total / 500", f"{student['total']:.2f}"], ["Average / Percentage", f"{student['average']:.3f}%"],
                       ["Grade", student["grade"]], ["Result", student["result"]]]
        marks_table = Table(marks_rows, colWidths=[300, 180], hAlign="LEFT")
        marks_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#163b59")),
                                         ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                         ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                                         ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                                         ("TOPPADDING", (0, 0), (-1, -1), 8)]))
        story.append(marks_table)
        doc.build(story)
        buffer.seek(0)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"student-{student_id}-report.pdf")

    @app.get("/analytics")
    def analytics():
        return render_template("analytics.html")

    @app.get("/reports")
    def reports():
        students = student_list(get_db().execute("SELECT * FROM students ORDER BY name COLLATE NOCASE, id").fetchall())
        return render_template("reports.html", students=students)

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        if request.method == "POST":
            school_name = request.form.get("school_name", "").strip()
            if not school_name or len(school_name) > 100 or any(ord(char) < 32 or ord(char) == 127 for char in school_name):
                flash("Enter a school name of 1 to 100 characters without control characters.", "error")
            else:
                db = get_db()
                db.execute("INSERT INTO settings (key, value) VALUES ('school_name', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (school_name,))
                db.commit()
                flash("Settings saved successfully.", "success")
                return redirect(url_for("settings"))
        return render_template("settings.html")

    @app.post("/settings/clear-demo")
    def clear_demo_data():
        db = get_db()
        count = db.execute("DELETE FROM students WHERE is_demo = 1").rowcount
        db.commit()
        flash(f"Removed {count} demo student(s).", "success")
        return redirect(url_for("settings"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
