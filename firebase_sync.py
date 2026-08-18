"""
Janob HR Bot — ixtiyoriy Firebase Firestore sinxronizatsiyasi.
FIREBASE_CREDENTIALS_PATH bo'sh bo'lsa, hech narsa qilmaydi.
"""
import asyncio
import logging

from config import FIREBASE_CREDENTIALS_PATH

logger = logging.getLogger("janob_hr_bot")

_firebase_app = None


def _get_client():
    global _firebase_app

    import firebase_admin
    from firebase_admin import credentials, firestore

    if _firebase_app is None:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        _firebase_app = firebase_admin.initialize_app(cred)

    return firestore.client()


async def push_application(app_id: int, data: dict):
    if not FIREBASE_CREDENTIALS_PATH:
        return

    def _write():
        client = _get_client()
        client.collection("applications").document(str(app_id)).set(data)

    await asyncio.get_running_loop().run_in_executor(None, _write)
