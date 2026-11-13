import unittest

from vncrcc import privacy


class RedactTests(unittest.TestCase):
    def setUp(self):
        privacy._reset_for_tests("test-secret")

    def test_names_and_cids_removed(self):
        payload = {
            "aircraft": {"list": [{"cid": 1286311, "name": "Jane Pilot", "callsign": "N123", "flight_plan": {"route": "DCT"}}]},
            "controllers": {"controllers": [{"cid": "1000001", "realName": "Joe Controller", "callsign": "DC_CTR"}]},
            "p56": {"history": {
                "events": [{"cid": "1286311", "identifier": "1286311", "name": "Jane Pilot", "recorded_at": 1.0}],
                "current_inside": {"1286311": {"callsign": "N123", "name": "Jane Pilot"}},
            }},
            "history": {"data": {"1286311": [{"lat": 1, "lon": 2}]}},
            "zone": {"name": "P-56A"},
        }
        out = privacy.redact(payload)
        text = repr(out)
        self.assertNotIn("1286311", text)
        self.assertNotIn("1000001", text)
        self.assertNotIn("Jane Pilot", text)
        self.assertNotIn("Joe Controller", text)
        # Non-person names are kept.
        self.assertEqual(out["zone"]["name"], "P-56A")
        tok = out["aircraft"]["list"][0]["cid"]
        self.assertTrue(tok.startswith(privacy.TOKEN_PREFIX))
        # Same CID -> same token everywhere, so the UI can still match things up.
        self.assertEqual(out["p56"]["history"]["events"][0]["cid"], tok)
        self.assertIn(tok, out["p56"]["history"]["current_inside"])
        self.assertIn(tok, out["history"]["data"])
        self.assertEqual(privacy.resolve(tok), "1286311")
        # Input is not mutated (it may be a shared cache).
        self.assertEqual(payload["aircraft"]["list"][0]["cid"], 1286311)

    def test_callsign_identifier_untouched(self):
        out = privacy.redact({"identifier": "N123", "callsign": "N123"})
        self.assertEqual(out["identifier"], "N123")

    def test_unknown_token_does_not_resolve(self):
        self.assertIsNone(privacy.resolve("id-000000000000"))
        self.assertIsNone(privacy.resolve("1286311"))


if __name__ == "__main__":
    unittest.main()
