import firebase_admin
from firebase_admin import credentials, db
import os
import json

def init_firebase():
    # Initialize only once
    if not firebase_admin._apps:

        # 🔹 Read Firebase admin key JSON from Render environment variable
        firebase_key = os.getenv("FIREBASE_ADMIN_KEY")

        if not firebase_key:
            raise Exception("FIREBASE_ADMIN_KEY missing in environment variables!")

        # 🔹 Convert JSON string to Python dict
        firebase_key_dict = json.loads(firebase_key)

        # 🔹 Initialize Firebase app
        cred = credentials.Certificate(firebase_key_dict)

        firebase_admin.initialize_app(cred, {
            "databaseURL": os.getenv("FIREBASE_DB_URL")
        })

def get_db():
    """Return root reference of the Realtime Database"""
    return db.reference("/")
