"""Focused unit tests for the Trusted Device DataChannel ingress guard.

Run: python -m unittest -v test_ingress.py
This test loads peer_session.py with a stub native_connection module, so no DLL or
real WebRTC connection is needed.
"""
import asyncio
import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
PACKAGE_NAME = "lazypc_ingress_testpkg"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE_NAME] = package
native_stub = types.ModuleType(PACKAGE_NAME + ".native_connection")
native_stub.NativePeerConnection = object
sys.modules[native_stub.__name__] = native_stub
spec = importlib.util.spec_from_file_location(
    PACKAGE_NAME + ".peer_session", ROOT / "peer_session.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
PeerConnection = module.PeerConnection


class IngressGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.peer = PeerConnection(signaling=object())
        self.text = []
        self.binary = []
        self.auth = []
        self.closed = []
        self.peer.on_text = self.text.append
        self.peer.on_bytes = self.binary.append
        self.peer.on_hardware_auth_message = self.auth.append
        self.peer.on_session_close = lambda: self.closed.append(True)
        self.peer.send_text = lambda value: self.text.append(value) or True

    async def test_unknown_text_blocked_before_auth(self):
        await self.peer._dispatch_text('{"type":"mouse_move"}')
        await self.peer._dispatch_text('arbitrary text')
        self.assertEqual(self.text, [])

    async def test_binary_blocked_before_auth(self):
        await self.peer._dispatch_bytes(b"\x01\x02\x03")
        self.assertEqual(self.binary, [])

    async def test_legacy_auth_response_on_control_is_blocked(self):
        raw = '{"type":"hw_auth_response","version":1}'
        await self.peer._dispatch_text(raw)
        self.assertEqual(self.auth, [])
        self.assertEqual(self.text, [])

    async def test_pairing_messages_on_control_are_blocked_before_auth(self):
        for kind in ("pair_hello", "pair_response"):
            raw = '{"type":"' + kind + '"}'
            await self.peer._dispatch_text(raw)
        self.assertEqual(self.text, [])
        self.assertEqual(self.auth, [])

    async def test_ping_on_control_is_blocked_before_auth(self):
        await self.peer._dispatch_text("PING")
        self.assertEqual(self.text, [])

    async def test_authorized_text_and_binary_are_forwarded(self):
        self.peer.security_authorized = True
        raw = '{"type":"mouse_move"}'
        await self.peer._dispatch_text(raw)
        await self.peer._dispatch_bytes(b"\x01\x02")
        self.assertEqual(self.text, [raw])
        self.assertEqual(self.binary, [b"\x01\x02"])

    async def test_unknown_hw_auth_type_not_routed_to_auth_handler(self):
        await self.peer._dispatch_text('{"type":"hw_auth_fake"}')
        self.assertEqual(self.auth, [])
        self.assertEqual(self.text, [])

    async def test_v4_auth_channel_has_dedicated_callback(self):
        received = []
        self.peer.on_auth_message = received.append
        raw = '{"type":"auth_response","scope":"session"}'
        await self.peer._dispatch_auth_text(raw)
        self.assertEqual(received, [raw])
        self.assertEqual(self.text, [])
        self.assertEqual(self.auth, [])

    async def test_secure_offer_returns_answer_without_signaling_side_effects(self):
        class FakeTransport:
            def __init__(self):
                self.remote = None
                self.control_created = False
            async def set_remote_description(self, kind, sdp):
                self.remote = (kind, sdp)
            def create_control_channel(self):
                self.control_created = True
            async def create_answer(self):
                return "fully-gathered-answer-sdp"

        fake = FakeTransport()
        async def ensure_started():
            self.peer._transport = fake
            self.peer._started = True
            return fake
        self.peer._ensure_started = ensure_started
        answer = await self.peer.receive_secure_offer("noise-decrypted-offer")
        self.assertEqual(fake.remote, ("offer", "noise-decrypted-offer"))
        self.assertTrue(fake.control_created)
        self.assertEqual(answer, "fully-gathered-answer-sdp")


if __name__ == "__main__":
    unittest.main(verbosity=2)
