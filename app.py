import os
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "lost_found.db"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = "campus-lost-found-demo"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                location TEXT NOT NULL,
                date TEXT NOT NULL,
                image TEXT,
                type TEXT NOT NULL CHECK(type IN ('Lost', 'Found')),
                status TEXT NOT NULL DEFAULT 'Open',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                claimant_name TEXT NOT NULL,
                claimant_email TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES items(id)
            );
            """
        )


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(file):
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename):
        raise ValueError("Please upload a PNG, JPG, GIF, or WEBP image.")
    safe_name = secure_filename(file.filename)
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    file.save(UPLOAD_DIR / filename)
    return f"uploads/{filename}"


@app.route("/")
def login():
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login_user():
    return redirect(url_for("dashboard"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        flash("Account created. You can now explore the board.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/dashboard")
def dashboard():
    with get_db() as connection:
        totals = connection.execute(
            """SELECT
                (SELECT COUNT(*) FROM items) AS total,
                (SELECT COUNT(*) FROM items WHERE type = 'Lost') AS lost,
                (SELECT COUNT(*) FROM items WHERE type = 'Found') AS found,
                (SELECT COUNT(*) FROM claims WHERE status = 'Pending') AS pending
            """
        ).fetchone()
        latest = connection.execute(
            "SELECT * FROM items ORDER BY id DESC LIMIT 4"
        ).fetchall()
    return render_template("dashboard.html", totals=totals, latest=latest)


@app.route("/report/<item_type>", methods=["GET", "POST"])
def report_item(item_type):
    if item_type not in {"lost", "found"}:
        return "Not found", 404
    display_type = item_type.title()
    if request.method == "POST":
        try:
            image = save_image(request.files.get("image"))
        except ValueError as error:
            flash(str(error), "error")
            return render_template("report.html", item_type=display_type)
        values = (
            request.form["item_name"].strip(),
            request.form["category"].strip(),
            request.form["description"].strip(),
            request.form["location"].strip(),
            request.form["date"],
            image,
            display_type,
            "Open",
            datetime.now().isoformat(timespec="seconds"),
        )
        with get_db() as connection:
            connection.execute(
                """INSERT INTO items
                (item_name, category, description, location, date, image, type, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
        flash(f"{display_type} item reported successfully.", "success")
        return redirect(url_for("items"))
    return render_template("report.html", item_type=display_type)


@app.route("/items")
def items():
    with get_db() as connection:
        results = connection.execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    return render_template("items.html", items=results, title="All items")


@app.route("/search")
def search():
    keyword = request.args.get("keyword", "").strip()
    item_type = request.args.get("type", "").strip()
    location = request.args.get("location", "").strip()
    status = request.args.get("status", "").strip()
    query = "SELECT * FROM items WHERE 1 = 1"
    values = []
    if keyword:
        query += " AND (item_name LIKE ? OR category LIKE ? OR description LIKE ?)"
        values.extend([f"%{keyword}%"] * 3)
    if item_type in {"Lost", "Found"}:
        query += " AND type = ?"
        values.append(item_type)
    if location:
        query += " AND location LIKE ?"
        values.append(f"%{location}%")
    if status in {"Open", "Claimed"}:
        query += " AND status = ?"
        values.append(status)
    query += " ORDER BY id DESC"
    with get_db() as connection:
        results = connection.execute(query, values).fetchall()
    filters = {"keyword": keyword, "type": item_type, "location": location, "status": status}
    return render_template("search.html", items=results, filters=filters, title="Search items")


@app.route("/claim/<int:item_id>", methods=["GET", "POST"])
def claim(item_id):
    with get_db() as connection:
        item = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return "Item not found", 404
        if request.method == "POST":
            connection.execute(
                """INSERT INTO claims
                (item_id, claimant_name, claimant_email, reason, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (item_id, request.form["name"].strip(), request.form["email"].strip(), request.form["reason"].strip(), datetime.now().isoformat(timespec="seconds")),
            )
            connection.execute("UPDATE items SET status = 'Claimed' WHERE id = ?", (item_id,))
            flash("Claim request sent for admin review.", "success")
            return redirect(url_for("claims"))
    return render_template("claim.html", item=item)


@app.route("/claims")
def claims():
    with get_db() as connection:
        claim_rows = connection.execute(
            """SELECT claims.*, items.item_name, items.image, items.type
            FROM claims JOIN items ON items.id = claims.item_id
            ORDER BY claims.id DESC"""
        ).fetchall()
    return render_template("claims.html", claims=claim_rows)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    with get_db() as connection:
        if request.method == "POST":
            claim_id = request.form["claim_id"]
            new_status = request.form["status"]
            if new_status in {"Pending", "Approved", "Rejected"}:
                connection.execute("UPDATE claims SET status = ? WHERE id = ?", (new_status, claim_id))
                if new_status == "Rejected":
                    connection.execute(
                        "UPDATE items SET status = 'Open' WHERE id = (SELECT item_id FROM claims WHERE id = ?)",
                        (claim_id,),
                    )
                flash("Claim status updated.", "success")
                return redirect(url_for("admin"))
        claim_rows = connection.execute(
            """SELECT claims.*, items.item_name, items.location, items.image
            FROM claims JOIN items ON items.id = claims.item_id
            ORDER BY CASE claims.status WHEN 'Pending' THEN 0 ELSE 1 END, claims.id DESC"""
        ).fetchall()
        item_rows = connection.execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    return render_template("admin.html", claims=claim_rows, items=item_rows)


init_db()

if __name__ == "__main__":
    app.run(debug=True)
