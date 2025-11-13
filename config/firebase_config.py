import firebase_admin
from firebase_admin import credentials, db

def init_firebase():
    # Initialize only once
    if not firebase_admin._apps:
        cred = credentials.Certificate("aura-x-firebase-adminsdk.json")
        firebase_admin.initialize_app(cred, {
            "databaseURL": "https://aura-x-6d62c-default-rtdb.firebaseio.com/"
        })

def get_db():
    """Return root reference of the Realtime Database"""
    return db.reference("/")
