import unittest
from unittest.mock import patch

from scripts.start_client import ready, ssh_command


class ClientTunnelTests(unittest.TestCase):
    def test_only_loopback_app_port_is_forwarded_and_host_key_check_remains_enabled(self):
        command = ssh_command("192.168.1.30", "kine", 8765)
        self.assertIn("127.0.0.1:8765:127.0.0.1:8765", command)
        self.assertIn("StrictHostKeyChecking=ask", command)
        self.assertIn("ExitOnForwardFailure=yes", command)
        self.assertIn("ForwardAgent=no", command)
        self.assertEqual(command[1:5], ["-F", "none", "-N", "-T"])
        self.assertEqual(command[-1], "192.168.1.30")
        self.assertNotIn("0.0.0.0", " ".join(command))

    def test_arguments_cannot_inject_a_shell_command_or_ssh_options(self):
        for host in ("-oProxyCommand=evil", "http://192.168.1.30", "server;echo evil", "user@server", "server\nother"):
            with self.assertRaises(ValueError):
                ssh_command(host, "kine")
        for user in ("-option", "user;command", "user@host", "user name"):
            with self.assertRaises(ValueError):
                ssh_command("server", user)
        for port in (0, -1, 65536, True):
            with self.assertRaises(ValueError):
                ssh_command("server", "kine", port)
        self.assertEqual(ssh_command("2001:db8::1", "kine")[-1], "2001:db8::1")

    @patch("scripts.start_client.HTTPConnection")
    def test_readiness_is_bounded_and_never_uses_a_remote_url(self, factory):
        connection = factory.return_value
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"topology":{"camera":"browser_client"},"protocols":[]}'
        self.assertTrue(ready(8765))
        factory.assert_called_once_with("127.0.0.1", 8765, timeout=1)
        response.read.assert_called_once_with(32769)
        response.read.return_value = b"x" * 32769
        self.assertFalse(ready(8765))
        response.read.return_value = b'{"other_app":true}'
        self.assertFalse(ready(8765))
        response.status = 302
        self.assertFalse(ready(8765))
