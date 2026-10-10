import unittest
from unittest.mock import patch

from adc_evidence.ingestion.http import fetch_bytes


class HttpRequestTests(unittest.TestCase):
    def test_fetch_bytes_uses_post_data_when_supplied(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b"ok"

        with patch("adc_evidence.ingestion.http.urlopen", return_value=Response()) as opened:
            result = fetch_bytes(
                "https://example.test/search",
                data=b"term=long-query",
            )

        self.assertEqual(result, b"ok")
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b"term=long-query")


if __name__ == "__main__":
    unittest.main()
