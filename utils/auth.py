from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask import session, redirect, url_for, flash

SCHOOL_DOMAIN = "bisc.edu.eg"

STAFF_EMAILS = [
    "admin@bisc.edu.eg",
    "reception@bisc.edu.eg",
    "lostfound@bisc.edu.eg",
]


def is_school_email(email):
    return email.lower().endswith("@" + SCHOOL_DOMAIN)


def get_role(email):
    if email.lower() in STAFF_EMAILS:
        return "staff"
    return "student"


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for('login'))
        if session.get('role') != 'staff':
            flash("Staff access only.", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated
