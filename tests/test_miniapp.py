import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from aiohttp import web

from miniapp_api import verify_init_data

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


def signed_init_data(user_id: int, *, auth_date: int | None = None) -> str:
    values = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AA-test",
        "user": json.dumps({"id": user_id, "first_name": "Ali"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class MiniAppSecurityTests(unittest.TestCase):
    def test_valid_telegram_signature(self):
        result = verify_init_data(signed_init_data(777), TOKEN)
        self.assertEqual(result["user_id"], 777)

    def test_modified_user_is_rejected(self):
        data = signed_init_data(777).replace("777", "999")
        with self.assertRaises(web.HTTPUnauthorized):
            verify_init_data(data, TOKEN)

    def test_expired_session_is_rejected(self):
        with self.assertRaises(web.HTTPUnauthorized):
            verify_init_data(signed_init_data(777, auth_date=1), TOKEN, now=10_000)

    def test_wrong_bot_token_is_rejected(self):
        with self.assertRaises(web.HTTPUnauthorized):
            verify_init_data(signed_init_data(777), TOKEN + "x")


if __name__ == "__main__":
    unittest.main()
