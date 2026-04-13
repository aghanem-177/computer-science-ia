from flask import (Flask, render_template, request, redirect, url_for,
                     flash, session, g)
import os
from datetime import date
from utils.database import get_db, init_db
from utils.auth import (is_school_email, get_role, hash_password,
                        verify_password, login_required, staff_required)
from utils.matching import calculate_match_score, find_matching_items, generate_ai_description
from utils.translations import get_translation

app = Flask(__name__)
app.secret_key = 'bisc-lost-found-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max upload

CATEGORIES = ['electronics', 'clothing', 'books_stationery', 'bags',
              'sports', 'personal', 'other']
LOCATIONS = ['reception', 'cafeteria', 'library', 'gym', 'playground',
             'classroom', 'hallway', 'parking', 'location_other']


@app.before_request
def before_request():
    lang = session.get('language', 'en')
    g.t = get_translation(lang)
    g.lang = lang
    g.dir = 'rtl' if lang == 'ar' else 'ltr'
    g.categories = CATEGORIES
    g.locations = LOCATIONS


# ──────────────────────── PUBLIC ROUTES ────────────────────────

@app.route('/')
def home():
    db = get_db()
    recent = db.execute(
        "SELECT * FROM items WHERE status='available' ORDER BY created_at DESC LIMIT 6"
    ).fetchall()
    db.close()
    return render_template('home.html', recent_items=recent)


@app.route('/set_language/<lang>')
def set_language(lang):
    if lang in ('en', 'ar'):
        session['language'] = lang
        if 'user_id' in session:
            db = get_db()
            db.execute("UPDATE users SET language=? WHERE id=?",
                       (lang, session['user_id']))
            db.commit()
            db.close()
    return redirect(request.referrer or url_for('home'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if not is_school_email(email):
            flash(g.t.get('school_email_required', 'Use your school email.'), 'danger')
            return redirect(url_for('login'))

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        if user and verify_password(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['email'] = user['email']
            session['role'] = user['role']
            session['language'] = user['language']
            db.close()
            if user['role'] == 'staff':
                return redirect(url_for('staff_dashboard'))
            return redirect(url_for('student_dashboard'))
        else:
            db.close()
            flash('Invalid email or password.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        if not is_school_email(email):
            flash(g.t.get('school_email_required', 'Use your school email.'), 'danger')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('register'))

        role = get_role(email)
        db = get_db()

        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            db.close()
            flash('An account with this email already exists.', 'danger')
            return redirect(url_for('login'))

        db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, hash_password(password), role)
        )
        db.commit()

        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['email'] = user['email']
        session['role'] = user['role']
        session['language'] = user['language']
        db.close()

        flash(f'{g.t["welcome"]}, {name}!', 'success')
        if role == 'staff':
            return redirect(url_for('staff_dashboard'))
        return redirect(url_for('student_dashboard'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


# ──────────────────────── STUDENT ROUTES ────────────────────────

@app.route('/student')
@login_required
def student_dashboard():
    db = get_db()
    my_claims = db.execute(
        """SELECT c.*, i.title as item_title FROM claims c
           JOIN items i ON c.item_id = i.id
           WHERE c.user_id=? ORDER BY c.submitted_at DESC LIMIT 5""",
        (session['user_id'],)
    ).fetchall()
    my_reports = db.execute(
        "SELECT * FROM lost_reports WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
        (session['user_id'],)
    ).fetchall()
    db.close()
    return render_template('student_dashboard.html', claims=my_claims, reports=my_reports)


@app.route('/search')
@login_required
def search():
    keyword = request.args.get('keyword', '').strip()
    category = request.args.get('category', '')
    location = request.args.get('location', '')
    status = request.args.get('status', '')
    sort = request.args.get('sort', 'newest')

    query = "SELECT * FROM items WHERE 1=1"
    params = []

    if keyword:
        query += " AND (title LIKE ? OR description LIKE ?)"
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if category:
        query += " AND category=?"
        params.append(category)
    if location:
        query += " AND location_found=?"
        params.append(location)
    if status:
        query += " AND status=?"
        params.append(status)

    if sort == 'oldest':
        query += " ORDER BY date_found ASC"
    else:
        query += " ORDER BY date_found DESC"

    db = get_db()
    items = db.execute(query, params).fetchall()
    db.close()

    return render_template('search.html', items=items, keyword=keyword,
                           sel_category=category, sel_location=location,
                           sel_status=status, sel_sort=sort)


@app.route('/item/<int:item_id>')
@login_required
def item_details(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        db.close()
        flash('Item not found.', 'danger')
        return redirect(url_for('search'))

    staff = None
    if item['created_by']:
        staff = db.execute("SELECT name FROM users WHERE id=?",
                           (item['created_by'],)).fetchone()
    db.close()
    return render_template('item_details.html', item=item, staff=staff)


@app.route('/claim/<int:item_id>', methods=['GET', 'POST'])
@login_required
def claim_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        db.close()
        flash('Item not found.', 'danger')
        return redirect(url_for('search'))

    if request.method == 'POST':
        desc = request.form['claim_description'].strip()
        if not desc:
            flash('Please describe why this item is yours.', 'danger')
            return redirect(url_for('claim_item', item_id=item_id))

        score = calculate_match_score(item, desc)
        db.execute(
            """INSERT INTO claims (user_id, item_id, claim_description, match_score)
               VALUES (?, ?, ?, ?)""",
            (session['user_id'], item_id, desc, score)
        )
        db.commit()
        db.close()
        flash(g.t['claim_submitted'], 'success')
        return redirect(url_for('my_claims'))

    db.close()
    return render_template('claim_form.html', item=item)


@app.route('/my-claims')
@login_required
def my_claims():
    db = get_db()
    claims = db.execute(
        """SELECT c.*, i.title as item_title, i.image_path
           FROM claims c JOIN items i ON c.item_id = i.id
           WHERE c.user_id=? ORDER BY c.submitted_at DESC""",
        (session['user_id'],)
    ).fetchall()
    db.close()
    return render_template('my_claims.html', claims=claims)


@app.route('/report-lost', methods=['GET', 'POST'])
@login_required
def report_lost():
    if request.method == 'POST':
        title = request.form['title'].strip()
        description = request.form['description'].strip()
        category = request.form['category']
        location = request.form['location_lost']
        date_lost = request.form['date_lost']

        if not all([title, description, category, location, date_lost]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('report_lost'))

        db = get_db()
        db.execute(
            """INSERT INTO lost_reports (user_id, title, description, category,
               location_lost, date_lost) VALUES (?, ?, ?, ?, ?, ?)""",
            (session['user_id'], title, description, category, location, date_lost)
        )
        db.commit()

        # Check for matching found items
        report = db.execute(
            "SELECT * FROM lost_reports WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (session['user_id'],)
        ).fetchone()
        found_items = db.execute(
            "SELECT * FROM items WHERE status='available'"
        ).fetchall()

        matches = find_matching_items(report, found_items)
        db.close()

        if matches:
            flash(g.t['potential_matches'], 'success')
            return render_template('matches.html', matches=matches, report=report)

        flash(g.t['report_submitted'], 'success')
        return redirect(url_for('my_lost_reports'))

    return render_template('report_lost.html', today=date.today().isoformat())


@app.route('/my-lost-reports')
@login_required
def my_lost_reports():
    db = get_db()
    reports = db.execute(
        "SELECT * FROM lost_reports WHERE user_id=? ORDER BY created_at DESC",
        (session['user_id'],)
    ).fetchall()
    db.close()
    return render_template('my_lost_reports.html', reports=reports)


# ──────────────────────── STAFF ROUTES ────────────────────────

@app.route('/staff')
@staff_required
def staff_dashboard():
    db = get_db()
    total_items = db.execute("SELECT COUNT(*) as c FROM items").fetchone()['c']
    pending_claims = db.execute(
        "SELECT COUNT(*) as c FROM claims WHERE status='pending'"
    ).fetchone()['c']
    returned = db.execute(
        "SELECT COUNT(*) as c FROM items WHERE status='returned'"
    ).fetchone()['c']
    recent = db.execute(
        "SELECT * FROM items ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    db.close()
    return render_template('staff_dashboard.html', total_items=total_items,
                           pending_claims=pending_claims, returned=returned,
                           recent=recent)


@app.route('/staff/add-item', methods=['GET', 'POST'])
@staff_required
def add_item():
    if request.method == 'POST':
        title = request.form['title'].strip()
        description = request.form['description'].strip()
        category = request.form['category']
        location = request.form['location_found']
        date_found = request.form['date_found']

        if not all([title, description, category, location, date_found]):
            flash('All fields are required.', 'danger')
            return redirect(url_for('add_item'))

        image_path = None
        ai_desc = None
        if 'image' in request.files:
            file = request.files['image']
            if file.filename:
                filename = f"{date.today().isoformat()}_{file.filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                image_path = f"uploads/{filename}"
                ai_desc = generate_ai_description(file.filename)

        db = get_db()
        db.execute(
            """INSERT INTO items (title, description, category, location_found,
               date_found, image_path, ai_description, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, category, location, date_found,
             image_path, ai_desc, session['user_id'])
        )
        db.commit()

        # Check if any lost reports match this new item
        new_item = db.execute(
            "SELECT * FROM items ORDER BY id DESC LIMIT 1"
        ).fetchone()
        lost_reports = db.execute(
            "SELECT lr.*, u.email, u.name FROM lost_reports lr "
            "JOIN users u ON lr.user_id = u.id WHERE lr.status='active'"
        ).fetchall()

        match_count = 0
        for report in lost_reports:
            matches = find_matching_items(report, [new_item])
            if matches:
                match_count += 1
                db.execute(
                    "UPDATE lost_reports SET notified=1 WHERE id=?",
                    (report['id'],)
                )

        db.commit()
        db.close()

        msg = g.t['item_added']
        if match_count > 0:
            msg += f" ({match_count} potential match(es) with lost reports!)"
        flash(msg, 'success')
        return redirect(url_for('staff_dashboard'))

    return render_template('add_item.html', today=date.today().isoformat())


@app.route('/staff/edit-item/<int:item_id>', methods=['GET', 'POST'])
@staff_required
def edit_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        db.close()
        flash('Item not found.', 'danger')
        return redirect(url_for('staff_dashboard'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        description = request.form['description'].strip()
        category = request.form['category']
        location = request.form['location_found']
        date_found = request.form['date_found']
        status = request.form['status']

        image_path = item['image_path']
        ai_desc = item['ai_description']
        if 'image' in request.files:
            file = request.files['image']
            if file.filename:
                filename = f"{date.today().isoformat()}_{file.filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                image_path = f"uploads/{filename}"
                ai_desc = generate_ai_description(file.filename)

        db.execute(
            """UPDATE items SET title=?, description=?, category=?, location_found=?,
               date_found=?, status=?, image_path=?, ai_description=? WHERE id=?""",
            (title, description, category, location, date_found, status,
             image_path, ai_desc, item_id)
        )
        db.commit()
        db.close()
        flash(g.t['item_updated'], 'success')
        return redirect(url_for('staff_dashboard'))

    db.close()
    return render_template('edit_item.html', item=item,
                           today=date.today().isoformat())


@app.route('/staff/delete-item/<int:item_id>', methods=['POST'])
@staff_required
def delete_item(item_id):
    db = get_db()
    db.execute("DELETE FROM claims WHERE item_id=?", (item_id,))
    db.execute("DELETE FROM items WHERE id=?", (item_id,))
    db.commit()
    db.close()
    flash(g.t['item_deleted'], 'success')
    return redirect(url_for('staff_dashboard'))


@app.route('/staff/claims')
@staff_required
def manage_claims():
    status_filter = request.args.get('status', '')
    query = """SELECT c.*, i.title as item_title, i.image_path,
               u.name as student_name, u.email as student_email
               FROM claims c
               JOIN items i ON c.item_id = i.id
               JOIN users u ON c.user_id = u.id"""
    params = []
    if status_filter:
        query += " WHERE c.status=?"
        params.append(status_filter)
    query += " ORDER BY c.submitted_at DESC"

    db = get_db()
    claims = db.execute(query, params).fetchall()
    db.close()
    return render_template('claims_manage.html', claims=claims,
                           sel_status=status_filter)


@app.route('/staff/claim/<int:claim_id>/<action>', methods=['POST'])
@staff_required
def review_claim(claim_id, action):
    if action not in ('approve', 'reject'):
        flash('Invalid action.', 'danger')
        return redirect(url_for('manage_claims'))

    staff_note = request.form.get('staff_note', '').strip()
    db = get_db()

    if action == 'approve':
        db.execute("UPDATE claims SET status='approved', staff_note=? WHERE id=?",
                   (staff_note, claim_id))
        claim = db.execute("SELECT item_id FROM claims WHERE id=?",
                           (claim_id,)).fetchone()
        if claim:
            db.execute("UPDATE items SET status='claimed' WHERE id=?",
                       (claim['item_id'],))
    else:
        db.execute("UPDATE claims SET status='rejected', staff_note=? WHERE id=?",
                   (staff_note, claim_id))

    db.commit()
    db.close()
    flash(f'Claim {action}d.', 'success')
    return redirect(url_for('manage_claims'))


@app.route('/staff/reports')
@staff_required
def reports():
    db = get_db()
    total = db.execute("SELECT COUNT(*) as c FROM items").fetchone()['c']
    returned = db.execute(
        "SELECT COUNT(*) as c FROM items WHERE status='returned'"
    ).fetchone()['c']
    claimed = db.execute(
        "SELECT COUNT(*) as c FROM items WHERE status='claimed'"
    ).fetchone()['c']
    rate = round((returned / total * 100), 1) if total > 0 else 0

    by_category = db.execute(
        "SELECT category, COUNT(*) as count FROM items GROUP BY category ORDER BY count DESC"
    ).fetchall()
    by_location = db.execute(
        "SELECT location_found, COUNT(*) as count FROM items GROUP BY location_found ORDER BY count DESC"
    ).fetchall()
    by_month = db.execute(
        """SELECT strftime('%Y-%m', date_found) as month, COUNT(*) as count
           FROM items GROUP BY month ORDER BY month DESC LIMIT 12"""
    ).fetchall()

    db.close()
    return render_template('reports.html', total=total, returned=returned,
                           claimed=claimed, rate=rate, by_category=by_category,
                           by_location=by_location, by_month=by_month)


@app.route('/staff/all-items')
@staff_required
def all_items():
    db = get_db()
    items = db.execute("SELECT * FROM items ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template('all_items.html', items=items)


# ──────────────────────── INIT & RUN ────────────────────────

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
