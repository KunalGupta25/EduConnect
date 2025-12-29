from database import get_db_connection
import cv2
import face_recognition
import numpy as np
import pickle

def load_known_faces():
    """Load all registered faces from DB"""
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, student_id, first_name, last_name, face_encoding FROM students WHERE face_encoding IS NOT NULL")
    students = cursor.fetchall()
    cursor.close()
    db.close()

    known_encodings = []
    known_ids = []
    
    for s in students:
        encoding = pickle.loads(s["face_encoding"])  # deserialize
        known_encodings.append(encoding)
        # include both DB id and permanent student_id
        known_ids.append((s["id"], s["student_id"], f"{s['first_name']} {s['last_name']}"))

    return known_encodings, known_ids


def mark_attendance_from_camera():
    known_encodings, known_ids = load_known_faces()
    marked_students = set()  # ✅ to store already marked (DB id)

    cap = cv2.VideoCapture(0)  # Webcam
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Detect faces
        face_locations = face_recognition.face_locations(rgb_frame)
        encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        for encoding, (top, right, bottom, left) in zip(encodings, face_locations):
            matches = face_recognition.compare_faces(known_encodings, encoding, tolerance=0.5)
            face_distances = face_recognition.face_distance(known_encodings, encoding)

            best_match_index = np.argmin(face_distances)

            if matches[best_match_index]:
                db_id, enrollment_no, name = known_ids[best_match_index]

                if db_id not in marked_students:  # ✅ mark only once
                    db = get_db_connection()
                    cursor = db.cursor()
                    cursor.execute(
                        "INSERT INTO attendance (student_id, enrollment_no, name, status) VALUES (%s, %s, %s, %s)",
                        (db_id, enrollment_no, name, "Present")
                    )
                    db.commit()
                    cursor.close()
                    db.close()

                    marked_students.add(db_id)  # ✅ remember marked student

                # Draw rectangle & name
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
                cv2.putText(frame, name, (left, top-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

        cv2.imshow("Attendance System", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    mark_attendance_from_camera()