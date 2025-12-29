import cv2
import face_recognition
import numpy as np
import io
import pickle
from modules.database import get_db_connection

def get_face_encoding(image_input):
    """
    Takes either a Flask FileStorage image, numpy array, or raw bytes,
    extracts face encoding and returns it (or None if no face).
    """
    if isinstance(image_input, np.ndarray):
        # Already a numpy array (OpenCV image)
        img = image_input
    else:
        # Assume it's a FileStorage or has read() method
        try:
            file_bytes = image_input.read()
            nparr = np.frombuffer(file_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            # Reset file pointer for future reads
            if hasattr(image_input, 'seek'):
                image_input.seek(0)
        except Exception as e:
            print(f"Error reading image: {e}")
            return None
    
    if img is None:
        print("Failed to decode image")
        return None
        
    # Convert BGR → RGB
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Detect and encode
    face_locations = face_recognition.face_locations(rgb_img)
    encodings = face_recognition.face_encodings(rgb_img, face_locations)

    if len(encodings) > 0:
        return encodings[0]  # Return the raw numpy array
    return None


def register_student_face(student_id, photo_blob):
    """
    student_id: Unique student ID
    photo_blob: Image BLOB from DB (saved during registration)
    """

    # Convert BLOB to numpy array
    image_array = np.frombuffer(photo_blob, np.uint8)
    img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    # Convert BGR (cv2) to RGB (face_recognition format)
    rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Detect face & encode
    face_locations = face_recognition.face_locations(rgb_img)
    if len(face_locations) == 0:
        print("⚠️ No face detected in uploaded photo.")
        return False

    encodings = face_recognition.face_encodings(rgb_img, face_locations)

    if len(encodings) > 0:
        encoding = encodings[0]  # Take the first face found
        encoding_blob = pickle.dumps(encoding)  # serialize numpy array

        # Save encoding in DB
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("UPDATE students SET face_encoding=%s WHERE id=%s", (encoding_blob, student_id))
        db.commit()
        cursor.close()
        db.close()

        print("✅ Face registered successfully")
        return True

    return False
