# Student Grade Analyzer

A local Flask and SQLite application for managing student marks, viewing analytics, and downloading PDF reports.

## Windows PowerShell setup

Install Python 3.10 or newer from python.org, including the Python launcher. Open PowerShell in the `Student_Grade_Analyzer` folder and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000` in your browser. Keep PowerShell open while using the app; press `Ctrl+C` to stop it. On later runs, start it again with `.\.venv\Scripts\python.exe app.py`. Activation is not required.

## Using the app

- Add students with a unique roll number, department, semester (1–12), and marks for Python, Java, SQL, Mathematics, and English. Email is optional; if supplied, it must be valid. Each mark must be from 0 to 100 with at most two decimal places. Scientific notation is accepted when the resulting decimal has at most two decimal places. Semester must be a whole number; forms such as `1.0` and `1e0` are accepted.
- Search, filter, sort, and page through records. Grade sorting uses academic order: ascending A+, A, B, C, D, F; descending reverses it. Open a student to edit, delete, or download their PDF report. PDF marks and totals use two decimal places; averages use three.
- View summaries on the dashboard and analytics pages. Update the school name or remove the sample records in Settings.
- Total is out of 500. Average and percentage are the raw total divided by five. Grades use the unrounded percentage: A+ ≥90, A ≥80, B ≥70, C ≥60, D ≥50, otherwise F. A student passes only when every subject is at least 35; therefore an F grade can still be a pass.

PDF reports use built-in fonts that may not render non-Latin characters correctly; check downloaded reports.

Data and settings persist in `database/students.db`. Keep the project on a local filesystem: some network-mounted filesystems do not support SQLite locking and cause a `database is locked` error. Eight clearly flagged sample records are inserted only when the database is first initialized. Saving an edit to a sample record makes it a regular student record, so Clear demo data will not remove it. Clearing demo records does not make them reappear, even after a restart. To back up your data, stop the app and copy `database/students.db` to a safe location. Deleting the database starts a fresh database with sample records and removes your saved data.

## Running tests

After installing the requirements, run this command in PowerShell from the project folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

The tests use temporary SQLite databases and do not modify your saved student records.

## Configuration and safety

By default the app generates a random session secret at startup; sessions and CSRF tokens reset when it restarts. To keep sessions across restarts, set a long random `SECRET_KEY` environment variable before starting the app, and keep it private. Optionally set `STUDENT_GRADE_DB` to an absolute SQLite file path before starting. Changes to environment variables require restarting the app.

The built-in server listens only on `127.0.0.1`. This is a local, single-user demonstration: it has no login, authorization, encryption at rest, or production deployment hardening. Anyone with access to the computer, database, or local server can view or change student data. Do not expose it to the internet or use it for sensitive student records without adding appropriate security and access controls.
