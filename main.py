from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, jsonify
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from modules.database import get_db_connection, create_tables
from modules.register import get_face_encoding
from flask_socketio import SocketIO, emit, join_room
import datetime
import face_recognition
import base64
import cv2
import numpy as np
import pickle
import math

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app, cors_allowed_origins="*")

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculates the distance between two geographical points using the Haversine formula.
    """
    R = 6371000  # Radius of Earth in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance

def teacher_required(f):
    """Decorator to restrict access to teacher users."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session or session['user'].get('role') != 'teacher':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in as a teacher to continue.', 'info')
            return redirect(url_for('auth'))
        # Join the teacher to a personal room for real-time alerts
        try:
            join_room(session['user']['id'])
        except Exception:
            pass
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    """Decorator to restrict access to student users."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user')
        if not user or user.get('role') != 'student':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in as a student to continue.', 'info')
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def index():
    """Redirects to the appropriate dashboard if a user is logged in, otherwise to the auth page."""
    if "user" in session:
        if session["user"]["role"] == "teacher":
            return redirect(url_for("dashboard"))
        elif session["user"]["role"] == "student":
            return redirect(url_for("student_dashboard"))
    return render_template("index.html")

@app.route("/auth")
def auth():
    """Renders the authentication page for login and registration."""
    return render_template("auth.html")

# Teacher registration route
@app.route("/register/teacher", methods=["POST"])
def register_teacher():
    """Handles teacher registration form submission."""
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    password = request.form.get("password")
    confirm_password = request.form.get("confirm_password")
    school_name = request.form.get("school_name")

    if password != confirm_password:
        flash("Passwords do not match!", "danger")
        return redirect(url_for("auth"))

    hashed_password = generate_password_hash(password)

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            INSERT INTO teachers (first_name, last_name, email, password, school_name)
            VALUES (%s, %s, %s, %s, %s)
        """, (first_name, last_name, email, hashed_password, school_name))
        db.commit()
        flash("Teacher registered successfully!", "success")
        return redirect(url_for("auth"))
    except Exception as e:
        flash(f"Error: {e}", "danger")
        return redirect(url_for("auth"))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

# Student registration route
@app.route("/register/student", methods=["POST"])
def register_student():
    """Handles student registration form submission."""
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    password = request.form.get("password")
    confirm_password = request.form.get("confirm_password")
    student_id = request.form.get("student_id")
    face_image = request.files.get("face_image")
    face_encoding = None
    face_data_to_save = None
    face_encoding_bytes = None

    if face_image:
        try:
            face_encoding = get_face_encoding(face_image)
            if face_encoding is None:
                flash("No face detected in uploaded photo. Try again.", "danger")
                return redirect(url_for("auth"))

            face_encoding_bytes = pickle.dumps(np.array(face_encoding, dtype=np.float64))

            face_image.seek(0)
            face_data_to_save = face_image.read()
        except Exception as e:
            print(f"Error processing face image: {e}")
            flash("Error processing face photo. Try again.", "danger")
            return redirect(url_for("auth"))

    if password != confirm_password:
        flash("Passwords do not match!", "danger")
        return redirect(url_for("auth"))

    hashed_password = generate_password_hash(password)

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            INSERT INTO students (first_name, last_name, email, password, student_id, face_data, face_encoding)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (first_name, last_name, email, hashed_password, student_id, face_data_to_save, face_encoding_bytes))
        db.commit()
        flash("Student registered successfully!", "success")
        return redirect(url_for("auth"))
    except Exception as e:
        flash(f"Error: {e}", "danger")
        return redirect(url_for("auth"))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

# Teacher login route
@app.route("/login/teacher", methods=["POST"])
def login_teacher():
    """Handles teacher login and session management."""
    try:
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            flash("Please enter both email and password", "danger")
            return redirect(url_for("auth"))

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM teachers WHERE email=%s", (email,))
        user = cursor.fetchone()

        if not user or not check_password_hash(user["password"], password):
            flash("Incorrect email or password!", "danger")
            return redirect(url_for("auth"))

        session.clear()
        session["user"] = {
            "id": user["id"],
            "role": "teacher",
            "name": user["first_name"]
        }
        session.modified = True
        return redirect(url_for("dashboard"))
    except Exception as e:
        print(f"Login error: {e}")
        flash("An error occurred during login", "danger")
        return redirect(url_for("auth"))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

# Student login route
@app.route("/login/student", methods=["POST"])
def login_student():
    """Handles student login and session management."""
    email = request.form.get("email")
    password = request.form.get("password")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM students WHERE email=%s", (email,))
    user = cursor.fetchone()
    cursor.close()
    db.close()

    if not user or not check_password_hash(user["password"], password):
        flash("Incorrect email or password!", "danger")
        return redirect(url_for("auth"))

    session["user"] = {"id": user["id"], "role": "student", "name": user["first_name"]}
    flash("Logged in successfully!", "success")
    return redirect(url_for("student_dashboard"))

@app.route("/student-dashboard")
@student_required
def student_dashboard():
    """Renders the student dashboard."""
    return render_template("student_dashboard.html", student_name=session['user']['name'])

@app.route("/dashboard")
@teacher_required
def dashboard():
    """Renders the teacher dashboard with summary statistics."""
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # Get total number of students
        cursor.execute("SELECT COUNT(*) as total FROM students")
        total_students_result = cursor.fetchone()
        total_students = total_students_result['total'] if total_students_result else 0

        # Get number of present students today
        cursor.execute("""
            SELECT COUNT(DISTINCT student_id) as present
            FROM attendance
            WHERE DATE(marked_at) = CURDATE()
            AND status = 'Present'
        """)
        present_today_result = cursor.fetchone()
        present_today = present_today_result['present'] if present_today_result else 0
        
        # Calculate attendance percentage
        attendance_percentage = (present_today / total_students * 100) if total_students > 0 else 0
        
        # Get recent attendance records
        cursor.execute("""
            SELECT CONCAT(s.first_name, ' ', s.last_name) as name, s.student_id as enrollment_no,
            a.status, a.marked_at as timestamp
            FROM attendance a
            JOIN students s ON a.student_id = s.id
            WHERE DATE(a.marked_at) = CURDATE()
            ORDER BY a.marked_at DESC
            LIMIT 5
        """)
        recent_records = cursor.fetchall()
        
        return render_template(
            "dashboard.html",
            teacher_name=session['user']['name'],
            teacher_id=session['user']['id'],
            total_students=total_students,
            present_today=present_today,
            attendance_percentage=round(attendance_percentage, 1),
            recent_records=recent_records
        )
    except Exception as e:
        print(f"Dashboard error: {e}")
        flash("Error loading dashboard data", "danger")
        return redirect(url_for("auth"))
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

# Logout route
@app.route("/logout")
def logout():
    """Clears the user session and logs them out."""
    session.pop("user", None)
    flash("Logged out successfully!", "success")
    return redirect(url_for("auth"))

# API Routes
@app.route('/api/verify-face', methods=['POST'])
@student_required
def verify_face():
    """Verifies a student's face and marks attendance."""
    try:
        data = request.get_json()
        image_data_url = data.get('image')
        timestamp_str = data.get('timestamp')
        is_offline = data.get('is_offline', False)
        student_latitude = data.get('latitude')
        student_longitude = data.get('longitude')

        if not image_data_url or not timestamp_str:
            return jsonify({'success': False, 'error': 'Missing image or timestamp'}), 400

        user = session.get('user')
        student_id = user.get('id')

        # Decode the base64 image
        image_data = base64.b64decode(image_data_url.split(',')[1])
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Get the face encoding of the captured image
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        face_encodings = face_recognition.face_encodings(rgb_img)
        if not face_encodings:
            return jsonify({'success': False, 'error': 'No face detected in the captured image.'})
        captured_face_encoding = face_encodings[0]

        # Get the student's stored face encoding
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT face_encoding FROM students WHERE id = %s", (student_id,))
        student = cursor.fetchone()

        if not student:
            return jsonify({'success': False, 'error': 'Student not found.'})

        if 'face_encoding' not in student or student['face_encoding'] is None:
            return jsonify({'success': False, 'error': 'No face data registered for this student.'})

        stored_face_encoding = pickle.loads(student['face_encoding'])
        
        # Compare faces with a stricter threshold to avoid false positives
        distance = face_recognition.face_distance([stored_face_encoding], captured_face_encoding)[0]
        MATCH_THRESHOLD = 0.45  # stricter than default (~0.6)
        if distance <= MATCH_THRESHOLD:
            # Geolocation check (if coordinates provided)
            if student_latitude is not None and student_longitude is not None:
                # Find the nearest teacher with a set location
                cursor.execute("SELECT id, latitude, longitude FROM teachers WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
                teachers = cursor.fetchall()
                nearest_teacher_id = None
                nearest_distance = None
                for t in teachers or []:
                    try:
                        dist = haversine_distance(
                            float(student_latitude), float(student_longitude),
                            float(t['latitude']), float(t['longitude'])
                        )
                    except Exception:
                        continue
                    if nearest_distance is None or dist < nearest_distance:
                        nearest_distance = dist
                        nearest_teacher_id = t['id']
                if nearest_teacher_id is not None and nearest_distance is not None:
                    if nearest_distance > 100:  # 100 meters radius
                        alert_message = f"Attendance not marked for {user.get('name')} (ID: {student_id}). Student is {nearest_distance:.2f} meters away from the teacher's location."
                        socketio.emit('attendance_alert', {'type': 'geolocation', 'message': alert_message}, room=nearest_teacher_id)
                        return jsonify({'success': False, 'error': f'You are {nearest_distance:.2f} meters away from the designated attendance area. Attendance not marked.'})

            timestamp = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            
            if is_offline:
                return jsonify({'success': True, 'offline': True})

            cursor.execute("SELECT student_id, first_name, last_name FROM students WHERE id = %s", (student_id,))
            student_details = cursor.fetchone()
            enrollment_no = student_details['student_id']
            name = f"{student_details['first_name']} {student_details['last_name']}"

            cursor.execute("""
                INSERT INTO attendance (student_id, enrollment_no, name, status, marked_at)
                VALUES (%s, %s, %s, 'Present', %s)
            """, (student_id, enrollment_no, name, timestamp))
            db.commit()
            return jsonify({'success': True, 'offline': False})
        else:
            return jsonify({'success': False, 'error': 'Face not recognized'})

    except Exception as e:
        print(f"Error verifying face: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/sync-attendance', methods=['POST'])
def sync_attendance():
    """Syncs offline attendance records to the database with face re-verification and optional geofence check."""
    try:
        records = request.get_json()
        if not records:
            return jsonify({'success': False, 'error': 'No records to sync'}), 400

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        
        synced_count = 0
        skipped_invalid = 0
        MATCH_THRESHOLD = 0.45

        for record in records:
            try:
                student_id = record.get('student_id')
                timestamp_str = record.get('timestamp')
                image_data_url = record.get('image')
                student_latitude = record.get('latitude')
                student_longitude = record.get('longitude')

                if not all([student_id, timestamp_str, image_data_url]):
                    skipped_invalid += 1
                    continue

                timestamp = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

                # Avoid duplicate for the day
                cursor.execute(
                    """
                    SELECT id FROM attendance
                    WHERE student_id = %s AND DATE(marked_at) = %s
                    """,
                    (student_id, timestamp.date()),
                )
                if cursor.fetchone():
                    continue

                # Decode image from base64
                try:
                    image_data = base64.b64decode(image_data_url.split(',')[1])
                    nparr = np.frombuffer(image_data, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                except Exception:
                    skipped_invalid += 1
                    continue

                # Compute captured encoding
                rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                face_encodings = face_recognition.face_encodings(rgb_img)
                if not face_encodings:
                    skipped_invalid += 1
                    continue
                captured_face_encoding = face_encodings[0]

                # Fetch stored encoding for this student
                cursor.execute("SELECT face_encoding, first_name, last_name, student_id AS enrollment_no FROM students WHERE id = %s", (student_id,))
                student_row = cursor.fetchone()
                if not student_row or not student_row.get('face_encoding'):
                    skipped_invalid += 1
                    continue

                stored_face_encoding = pickle.loads(student_row['face_encoding'])
                distance = face_recognition.face_distance([stored_face_encoding], captured_face_encoding)[0]
                if distance > MATCH_THRESHOLD:
                    # Not the registered face
                    skipped_invalid += 1
                    continue

                # Optional geofence check using recorded coordinates, if available
                if student_latitude is not None and student_longitude is not None:
                    cursor.execute("SELECT id, latitude, longitude FROM teachers WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
                    teachers = cursor.fetchall()
                    nearest_distance = None
                    for t in teachers or []:
                        try:
                            dist = haversine_distance(
                                float(student_latitude), float(student_longitude),
                                float(t['latitude']), float(t['longitude'])
                            )
                        except Exception:
                            continue
                        if nearest_distance is None or dist < nearest_distance:
                            nearest_distance = dist
                    if nearest_distance is not None and nearest_distance > 100:
                        # Outside geofence; skip
                        skipped_invalid += 1
                        continue

                # Insert attendance
                cursor.execute(
                    """
                    INSERT INTO attendance (student_id, enrollment_no, name, status, marked_at)
                    VALUES (%s, %s, %s, 'Present', %s)
                    """,
                    (
                        student_id,
                        student_row['enrollment_no'],
                        f"{student_row['first_name']} {student_row['last_name']}",
                        timestamp,
                    ),
                )
                synced_count += 1
            except Exception:
                skipped_invalid += 1
                continue

        db.commit()
        return jsonify({'success': True, 'synced_count': synced_count, 'skipped': skipped_invalid})

    except Exception as e:
        print(f"Error syncing attendance: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route("/api/get-student-id")
@student_required
def get_student_id():
    """Returns the ID of the logged-in student."""
    user = session.get('user')
    return jsonify({'student_id': user.get('id')})

@app.route("/api/student-monthly-stats")
@student_required
def student_monthly_stats():
    """Provides monthly attendance statistics for a student."""
    try:
        student_id = session['user']['id']
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        today = datetime.date.today()
        first_day_of_month = today.replace(day=1)
        # Handle December edge case
        if today.month == 12:
            last_day_of_month = today.replace(day=31, month=12, year=today.year)
        else:
            last_day_of_month = today.replace(day=1, month=today.month + 1) - datetime.timedelta(days=1)
        
        total_days_in_month = (last_day_of_month - first_day_of_month).days + 1

        cursor.execute("""
            SELECT COUNT(DISTINCT DATE(marked_at)) as present_days
            FROM attendance
            WHERE student_id = %s
            AND MONTH(marked_at) = %s
            AND YEAR(marked_at) = %s
            AND status = 'Present'
        """, (student_id, today.month, today.year))
        present_days = cursor.fetchone()['present_days']

        absent_days = total_days_in_month - present_days

        percentage = 0
        if total_days_in_month > 0:
            percentage = round((present_days / total_days_in_month) * 100)

        return jsonify({
            'success': True,
            'percentage': percentage,
            'present_days': present_days,
            'absent_days': absent_days
        })

    except Exception as e:
        print(f"Error getting student monthly stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/summary')
@teacher_required
def get_summary():
    """Provides a summary of today's attendance for the teacher dashboard."""
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) as total FROM students")
        total_students_result = cursor.fetchone()
        total_students = int(total_students_result['total']) if total_students_result else 0
        
        cursor.execute("""
            SELECT COUNT(DISTINCT student_id) as present
            FROM attendance
            WHERE DATE(marked_at) = CURDATE() AND status = 'Present'
        """)
        present_count_result = cursor.fetchone()
        present_count = int(present_count_result['present']) if present_count_result else 0
        
        absent_count = total_students - present_count
        attendance_rate = round((present_count / total_students * 100) if total_students > 0 else 0)
        
        return jsonify({
            'total': total_students,
            'present': present_count,
            'absent': absent_count,
            'rate': attendance_rate
        })
    except Exception as e:
        print(f"Error getting summary: {e}")
        return jsonify({
            'total': 0,
            'present': 0,
            'absent': 0,
            'rate': 0
        })
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/get-present-students')
@teacher_required
def get_present_students():
    """Returns a list of students based on their attendance status for today."""
    status = request.args.get('status', 'Present')
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    try:
        if status == 'Present':
            cursor.execute("""
                SELECT s.first_name, s.last_name, s.student_id AS enrollment_no, MAX(a.marked_at) as marked_at
                FROM students s
                JOIN attendance a ON s.id = a.student_id
                WHERE DATE(a.marked_at) = CURDATE() AND a.status = 'Present'
                GROUP BY s.id, s.first_name, s.last_name, s.student_id
                ORDER BY marked_at DESC
            """)
        else:
            cursor.execute("""
                SELECT s.first_name, s.last_name, s.student_id AS enrollment_no, NULL as marked_at
                FROM students s
                LEFT JOIN attendance a ON s.id = a.student_id AND DATE(a.marked_at) = CURDATE() AND a.status = 'Present'
                WHERE a.id IS NULL
            """)
        
        students = []
        for row in cursor.fetchall():
            students.append({
                'name': f"{row['first_name']} {row['last_name']}".strip(),
                'enrollment_no': row['enrollment_no'],
                'check_in_time': row['marked_at'].strftime('%I:%M %p') if row and row.get('marked_at') else ''
            })
        return jsonify(students)
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/mark-attendance', methods=['POST'])
@teacher_required
def mark_attendance():
    """Manually marks a student as present."""
    enrollment_no = request.json.get('enrollment_no')

    db = get_db_connection()
    cursor = db.cursor(buffered=True, dictionary=True)

    try:
        cursor.execute("SELECT id, first_name, last_name FROM students WHERE student_id = %s", (enrollment_no,))
        student = cursor.fetchone()

        if not student:
            return jsonify({'error': 'Student not found'}), 404

        cursor.execute("""
            INSERT INTO attendance (student_id, enrollment_no, name, status, marked_at)
            VALUES (%s, %s, %s, 'Present', NOW())
        """, (
            student['id'],
            enrollment_no,
            f"{student['first_name']} {student['last_name']}"
        ))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/mark-all-present', methods=['POST'])
@teacher_required
def mark_all_present():
    """Forces everyone to Present for today: removes today's records and inserts Present for all students."""
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    try:
        # Remove today's attendance records (Present/Absent) to reset state
        cursor.execute("DELETE FROM attendance WHERE DATE(marked_at) = CURDATE()")
        # Insert Present for all students
        cursor.execute(
            """
            INSERT INTO attendance (student_id, enrollment_no, name, status, marked_at)
            SELECT
                s.id,
                s.student_id,
                CONCAT(s.first_name, ' ', s.last_name) AS name,
                'Present',
                NOW()
            FROM students s
            """
        )
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"Error marking all present: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/mark-all-absent', methods=['POST'])
@teacher_required
def mark_all_absent():
    """Forces everyone to Absent for today: removes today's records and inserts Absent for all students."""
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        # Remove today's attendance records (Present/Absent) to reset state
        cursor.execute("DELETE FROM attendance WHERE DATE(marked_at) = CURDATE()")
        # Insert Absent for all students
        cursor.execute(
            """
            INSERT INTO attendance (student_id, enrollment_no, name, status, marked_at)
            SELECT
                s.id,
                s.student_id,
                CONCAT(s.first_name, ' ', s.last_name) AS name,
                'Absent',
                NOW()
            FROM students s
            """
        )
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        print(f"Error marking all absent: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/manual-attendance-requests')
@teacher_required
def get_manual_attendance_requests():
    """Retrieves all pending manual attendance requests."""
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT r.id, s.id as student_id, s.first_name, s.last_name, s.student_id AS enrollment_no
            FROM manual_attendance_requests r
            JOIN students s ON r.student_id = s.id
            ORDER BY r.requested_at DESC
        """)
        requests = cursor.fetchall()
        return jsonify(requests)
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/handle-manual-attendance-request', methods=['POST'])
@teacher_required
def handle_manual_attendance_request():
    """Approves or ignores a manual attendance request."""
    request_id = request.json.get('request_id')
    action = request.json.get('action')

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:
        if action == 'approve':
            cursor.execute("SELECT student_id FROM manual_attendance_requests WHERE id = %s", (request_id,))
            result = cursor.fetchone()
            if not result:
                return jsonify({'error': 'Request not found'}), 404
            student_id = result['student_id']

            cursor.execute("SELECT id, first_name, last_name, student_id FROM students WHERE id = %s", (student_id,))
            student = cursor.fetchone()

            cursor.execute("""
                INSERT INTO attendance (student_id, enrollment_no, name, status, marked_at)
                VALUES (%s, %s, %s, 'Present', NOW())
            """, (
                student['id'],
                student['student_id'],
                f"{student['first_name']} {student['last_name']}"
            ))

        cursor.execute("DELETE FROM manual_attendance_requests WHERE id = %s", (request_id,))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/request-manual-attendance', methods=['POST'])
@student_required
def request_manual_attendance():
    """Allows a student to request manual attendance marking."""
    student_id = session['user']['id']
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO manual_attendance_requests (student_id) VALUES (%s)", (student_id,))
        db.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/alerts')
@teacher_required
def get_alerts():
    """Placeholder API route for fetching alerts."""
    alerts = [
        {
            'type': 'info',
            'message': '80% of students have checked in.'
        },
        {
            'type': 'warning',
            'message': 'Face recognition failed for 3 students.'
        }
    ]
    return jsonify(alerts)

@app.route('/api/set-teacher-location', methods=['POST'])
@teacher_required
def set_teacher_location():
    """Allows a teacher to set their current location for geolocation checks."""
    try:
        data = request.get_json()
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        teacher_id = session['user']['id']

        if not all([latitude, longitude]):
            return jsonify({'error': 'Latitude and longitude are required'}), 400

        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE teachers SET latitude = %s, longitude = %s WHERE id = %s",
            (latitude, longitude, teacher_id)
        )
        db.commit()
        return jsonify({'success': True, 'message': 'Teacher location updated successfully'})
    except Exception as e:
        print(f"Error setting teacher location: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()

@app.route('/api/student-details/<int:student_id>')
@teacher_required
def get_student_details(student_id):
    """Retrieves details for a specific student."""
    db = get_db_connection()
    # Use buffered cursor to avoid 'Unread result found' when not consuming all rows
    cursor = db.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("""
            SELECT s.first_name, s.last_name, s.student_id AS enrollment_no, a.status
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id AND DATE(a.marked_at) = CURDATE()
            WHERE s.id = %s
            ORDER BY a.marked_at DESC
            LIMIT 1
        """, (student_id,))
        student = cursor.fetchone()
        
        if not student:
            return jsonify({'error': 'Student not found'}), 404

        return jsonify(student)
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'db' in locals(): db.close()


if __name__ == "__main__":
    create_tables()
    # Use SocketIO to run the app so websocket events work properly
    socketio.run(app, debug=True)

