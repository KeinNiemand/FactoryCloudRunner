import os
import signal
import unittest
from unittest.mock import Mock, patch

from runner.training import ShutdownController


class ShutdownTests(unittest.TestCase):
    def test_signal_is_forwarded_to_attached_child(self):
        process = Mock()
        process.poll.return_value = None
        process.pid = 123
        controller = ShutdownController(1)
        controller.attach(process)

        if os.name == "posix":
            with patch("os.killpg") as killpg:
                controller.request(signal.SIGTERM)
                killpg.assert_called_once_with(123, signal.SIGTERM)
        else:
            controller.request(signal.SIGTERM)
            process.send_signal.assert_called_once_with(signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
