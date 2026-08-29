import unittest
import urllib.error
from unittest.mock import patch

from nju_agent.model import ChatClient, ModelError


class ChatClientTests(unittest.TestCase):
    def test_windows_socket_permission_error_has_actionable_message(self) -> None:
        client = ChatClient(api_key="test", base_url="https://example.invalid/v1", model="test", max_retries=0)
        blocked = urllib.error.URLError(PermissionError(10013, "socket access forbidden"))

        with patch("nju_agent.model.urllib.request.urlopen", side_effect=blocked):
            with self.assertRaisesRegex(ModelError, "Windows.*WinError 10013"):
                client.complete([], [])


if __name__ == "__main__":
    unittest.main()
