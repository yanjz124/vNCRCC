import os
import tempfile
import unittest

from vncrcc.storage import Storage


class TestStorage(unittest.TestCase):
    def test_save_and_get_latest_snapshot(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            s = Storage(path)
            data = {"pilots": [{"callsign": "ABC123", "altitude": 1000}]}
            sid = s.save_snapshot(data, 12345.0)
            self.assertIsInstance(sid, int)
            latest = s.get_latest_snapshot()
            self.assertIsNotNone(latest)
            self.assertIn("data", latest)
            self.assertEqual(latest["fetched_at"], 12345.0)
            self.assertEqual(len(latest["data"]["pilots"]), 1)
        finally:
            try:
                os.remove(path)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
