import asyncio
import inspect
import json
import struct
import time

from typing import Callable, Optional


from webrtc.video_track import DesktopVideoTrack
from audio.audio_track import SystemAudioTrack

from aiortc import (
    RTCConfiguration,
    RTCDataChannel,
    RTCIceCandidate,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)

from aiortc.rtcrtpsender import RTCRtpSender

# LazyPC NVENC integration.
# RTCRtpSender does not look up H264Encoder dynamically; it calls the
# module-level get_encoder(codec). Patch that function instead.
from webrtc.encoder_factory import get_encoder as lazy_get_encoder
import aiortc.rtcrtpsender as _rtcrtpsender
import aiortc.codecs as _codecs


_rtcrtpsender.get_encoder = lazy_get_encoder
_codecs.get_encoder = lazy_get_encoder



# ================================================================
# CURSOR PROTOCOL
# ================================================================


PACKET_CURSOR_POSITION = 0x60


class PeerConnection:

    def __init__(self, signaling):

        self.signaling = signaling

        self.pc: Optional[RTCPeerConnection] = None
        self.video: Optional[DesktopVideoTrack] = None
        self.video_sender = None

        self.audio: Optional[SystemAudioTrack] = None
        self.audio_sender = None

        self.channel: Optional[RTCDataChannel] = None

        self.on_text: Optional[Callable[[str], None]] = None
        self.on_bytes: Optional[Callable[[bytes], None]] = None

        self.cursor_position_provider = None
        self._cursor_sync_task = None

        self.on_disconnected = None
        self._stopping = False
        self._disconnect_task = None
        self.on_session_close = None
        self.on_channel_open = None
        self.on_hardware_auth_message = None
        self.security_authorized = False
    async def start_session(self):

        if self.pc is not None:
            return

        print("[WEBRTC] Creating new session")

        self.pc = RTCPeerConnection(
            RTCConfiguration(
                iceServers=[
                    RTCIceServer(
                        urls=[
                            "stun:stun.l.google.com:19302"
                        ]
                    )
                ]
            )
        )

        self.video = DesktopVideoTrack()

        self.video_sender = self.pc.addTrack(
            self.video
        )

        self.audio = SystemAudioTrack()

        self.audio_sender = self.pc.addTrack(
            self.audio
        )

        # Security gate: tracks are negotiated, but media is muted until
        # Stage 3 Hardware-Bound WebRTC Authentication succeeds.
        self.video_sender.replaceTrack(None)
        self.audio_sender.replaceTrack(None)

        self.security_authorized = False

        print("[WEBRTC] VideoTrack added (media gated)")

        self._prefer_h264()

        self._register_events()


    def _prefer_h264(
        self
    ):


        print(
            "[WEBRTC] Configuring H264 codec preference"
        )


        capabilities = (

            RTCRtpSender.getCapabilities(
                "video"
            )
        )


        h264_codecs = [

            codec

            for codec in capabilities.codecs

            if codec.mimeType.lower()
            == "video/h264"
        ]


        if not h264_codecs:


            raise RuntimeError(

                "H264 codec is not supported by aiortc"
            )


        print(

            f"[WEBRTC] Found "

            f"{len(h264_codecs)} H264 codec(s)"
        )


        for codec in h264_codecs:


            print(

                "[WEBRTC] H264 codec:",

                codec.mimeType,

                codec.clockRate,

                codec.parameters
            )


        video_transceiver = None


        for transceiver in (

            self.pc.getTransceivers()
        ):


            if (

                transceiver.sender

                ==

                self.video_sender

            ):


                video_transceiver = (

                    transceiver
                )


                break


        if video_transceiver is None:


            raise RuntimeError(

                "Video transceiver not found"
            )


        video_transceiver.setCodecPreferences(

            h264_codecs
        )


        print(

            "[WEBRTC] H264 codec preference applied"
        )


    # ================================================================
    # EVENTS
    # ================================================================
    def _register_events(
        self
    ):

        @self.pc.on("connectionstatechange")
        async def _():

            state = self.pc.connectionState

            print("[WEBRTC] Connection state:", state)

            if self._stopping:
                return
            sctp = getattr(self.pc, "sctp", None)
            dtls = getattr(sctp, "transport", None) if sctp is not None else None
            if dtls is not None:
                print("[WEBRTC] DTLS state:", getattr(dtls, "state", "unknown"))

            if state == "connected":
                self._cancel_disconnect_watch()

            elif state in ("disconnected", "failed"):
                # A transport failure is not enough to declare the session
                # intentionally closed. Give ICE/WebRTC time to recover.
                self._schedule_disconnect_watch()

            elif state == "closed":
                self._cancel_disconnect_watch()

                # Normally a graceful remote close is preceded by
                # SESSION_CLOSE on the DataChannel. If the peer is already
                # gone (for example the process was killed), there is no
                # such message and we simply treat this as a transport loss.
                self._schedule_disconnect_watch()


        @self.pc.on(
            "iceconnectionstatechange"
        )
        async def _():


            print(

                "[WEBRTC] ICE state:",

                self.pc.iceConnectionState
            )


        @self.pc.on(
            "icecandidate"
        )
        async def _(candidate):


            if candidate is not None:


                print(

                    "[ICE] Local candidate generated"
                )


                await self.signaling.send_candidate(

                    candidate
                )


        @self.pc.on(
            "datachannel"
        )
        def _(channel):


            self.channel = channel


            self._bind_channel(
                channel
            )


    def _cancel_disconnect_watch(self):
        task = self._disconnect_task
        self._disconnect_task = None

        if task is not None and not task.done():
            task.cancel()

    def _schedule_disconnect_watch(self):
        task = self._disconnect_task

        if task is not None and not task.done():
            return

        self._disconnect_task = asyncio.create_task(
            self._disconnect_watchdog()
        )

    async def _disconnect_watchdog(self):
        try:
            # aiortc can recover a temporary network loss by itself. Give it
            # a short grace period before destroying the session.
            await asyncio.sleep(15.0)

            if self.pc is None or self._stopping:
                return

            state = self.pc.connectionState

            if state in ("disconnected", "failed", "closed"):
                print("[WEBRTC] Connection timeout -> ending session")
                if self.on_disconnected is not None:
                    await self.on_disconnected()

        except asyncio.CancelledError:
            pass
        finally:
            if self._disconnect_task is asyncio.current_task():
                self._disconnect_task = None

    # ================================================================
    # SAFE DATA CHANNEL SEND
    # ================================================================

    def _data_transport_ready(self):
        """Return True only while SCTP/DTLS is actually usable."""
        if self.pc is None:
            return False

        if self.pc.connectionState != "connected":
            return False

        sctp = getattr(self.pc, "sctp", None)
        if sctp is None:
            return False

        dtls = getattr(sctp, "transport", None)
        if dtls is None:
            return False

        return getattr(dtls, "state", None) == "connected"


    def _safe_channel_send(self, data):
        channel = self.channel

        if channel is None or channel.readyState != "open":
            return False

        if not self._data_transport_ready():
            return False

        try:
            channel.send(data)
            return True
        except (ConnectionError, OSError) as e:
            # The transport can change state between the checks above and
            # aiortc scheduling the SCTP transmission. Do not let this
            # transient condition break the agent.
            print("[DATA] Send skipped: transport not connected")
            return False
        except Exception as e:
            print("[DATA] Send error")
            return False


    # ================================================================
    # DATA CHANNEL
    # ================================================================


    def _bind_channel(

        self,

        channel: RTCDataChannel
    ):


        @channel.on(
            "open"
        )
        def _():


            print(
                "[DATA] OPEN"
            )


            print("[SECURITY] Stage 3 required before media/input")

            if self.on_channel_open is not None:
                self.on_channel_open()


        @channel.on(
            "close"
        )
        def _():


            print(
                "[DATA] CLOSED"
            )


            if (

                self._cursor_sync_task is not None

                and

                not self._cursor_sync_task.done()

            ):


                self._cursor_sync_task.cancel()


        @channel.on(
            "message"
        )
        def _(message):


            if isinstance(
                message,
                bytes
            ):


                print(

                    f"[DATA] BYTES {len(message)}"
                )


                if self.on_bytes:


                    self.on_bytes(
                        message
                    )


                return


            text = str(
                message
            )


            print("[DATA] Text message received")


            try:
                control = json.loads(text)
            except Exception:
                control = None

            if (
                isinstance(control, dict)
                and str(control.get("type", "")).startswith("hw_auth_")
            ):
                if self.on_hardware_auth_message is not None:
                    self.on_hardware_auth_message(text)
                return

            if text == "SESSION_CLOSE":
                print("[WEBRTC] Remote requested session close")
                if self.on_session_close is not None:
                    asyncio.create_task(self.on_session_close())
                return

            if text == "PING":
                if self._safe_channel_send("PONG"):
                    print("[DATA] TX -> PONG")

            if self.on_text:
                result = self.on_text(text)

                if inspect.isawaitable(result):
                    asyncio.create_task(result)


    # ================================================================
    # CURSOR SYNC LOOP
    # ================================================================


    async def _cursor_sync_loop(
        self
    ):


        last_x = None

        last_y = None


        try:


            while True:


                await asyncio.sleep(

                    1.0 / 60.0
                )


                if not self.security_authorized:
                    continue

                if (

                    self.channel is None

                    or

                    self.channel.readyState != "open"

                    or

                    not self._data_transport_ready()

                ):


                    continue


                if (

                    self.cursor_position_provider

                    is None

                ):


                    continue


                position = (

                    self.cursor_position_provider()
                )


                if position is None:


                    continue


                x, y = position


                # ====================================================
                # SEND ONLY IF CURSOR MOVED
                # ====================================================


                if (

                    last_x is not None

                    and

                    last_y is not None

                    and

                    abs(x - last_x) < 0.000001

                    and

                    abs(y - last_y) < 0.000001

                ):


                    continue


                last_x = x

                last_y = y


                packet = struct.pack(

                    ">Bff",

                    PACKET_CURSOR_POSITION,

                    x,

                    y
                )


                self._safe_channel_send(packet)


        except asyncio.CancelledError:


            print(

                "[CURSOR] Sync stopped"
            )


            raise


        except Exception as e:


            print(

                "[CURSOR] Sync error:",

                e
            )


    # ================================================================
    # STAGE 3 SECURITY GATE
    # ================================================================

    def authorize_hardware_session(self):
        if self.pc is None:
            raise RuntimeError("Cannot authorize without PeerConnection")

        if self.video_sender is not None and self.video is not None:
            self.video_sender.replaceTrack(self.video)

        if self.audio_sender is not None and self.audio is not None:
            self.audio_sender.replaceTrack(self.audio)

        self.security_authorized = True
        print("[SECURITY] Stage 3 PASS -> media/input gate opened")

        if (
            self._cursor_sync_task is None
            or self._cursor_sync_task.done()
        ):
            self._cursor_sync_task = asyncio.create_task(
                self._cursor_sync_loop()
            )
            print("[CURSOR] Sync started after Stage 3")

    def revoke_hardware_session(self):
        self.security_authorized = False

        if self.video_sender is not None:
            self.video_sender.replaceTrack(None)

        if self.audio_sender is not None:
            self.audio_sender.replaceTrack(None)

        if (
            self._cursor_sync_task is not None
            and not self._cursor_sync_task.done()
        ):
            self._cursor_sync_task.cancel()

        self._cursor_sync_task = None
        print("[SECURITY] Stage 3 revoked -> media/input gate closed")


    # ================================================================
    # CREATE OFFER
    # ================================================================

    async def create_offer(self):

        if self.pc is not None:
            state = self.pc.connectionState

            # Reconnecting the signaling WebSocket must not renegotiate an
            # already healthy WebRTC session.
            if state in (
                "new",
                "connecting",
                "connected",
                "checking",
                "disconnected",
            ):
                print(
                    f"[WEBRTC] Existing session state={state}; "
                    "no new offer needed"
                )
                return

            # A failed/closed PeerConnection can be replaced safely.
            await self.stop_session()

        if self.pc is None:
            await self.start_session()

        if self.channel is None:
            self.channel = self.pc.createDataChannel(
                "control"
            )

            self._bind_channel(
                self.channel
            )

        print("[WEBRTC] Creating offer")

        offer = await self.pc.createOffer()

        await self.pc.setLocalDescription(
            offer
        )

        print("[WEBRTC] Local offer created")
        if "H264" in self.pc.localDescription.sdp:

            print("[WEBRTC] H264 present in Offer SDP")

        else:

            print("[WEBRTC] WARNING: H264 NOT FOUND IN OFFER SDP")

        await self.signaling.send_offer(
            self.pc.localDescription.sdp
        )


    # ================================================================
    # RECEIVE OFFER
    # ================================================================


    async def receive_offer(

        self,

        sdp: str
    ):


        print(

            "[WEBRTC] Remote Offer received"
        )


        await self.pc.setRemoteDescription(

            RTCSessionDescription(

                sdp=sdp,

                type="offer"
            )
        )


        answer = (

            await self.pc.createAnswer()
        )


        await self.pc.setLocalDescription(

            answer
        )


        await self.signaling.send_answer(

            self.pc.localDescription.sdp
        )


    # ================================================================
    # RECEIVE ANSWER
    # ================================================================


    async def receive_answer(

        self,

        sdp: str
    ):


        print("[WEBRTC] Remote answer received")

        await self.pc.setRemoteDescription(

            RTCSessionDescription(

                sdp=sdp,

                type="answer",
            )
        )


        print(

            "[WEBRTC] Remote Answer applied"
        )


    # ================================================================
    # ADD CANDIDATE
    # ================================================================


    async def add_candidate(

        self,

        candidate: RTCIceCandidate
    ):


        await self.pc.addIceCandidate(

            candidate
        )


    # ================================================================
    # SIGNALING
    # ================================================================


    async def handle_signaling(

        self,

        message: dict
    ):


        message_type = (

            message["type"]
        )

        if message_type == "create_session":

            print("[SIGNALING] Create session requested")

            await self.create_offer()

        elif message_type == "offer":

            await self.receive_offer(
                message["sdp"]
            )

        elif message_type == "answer":

            await self.receive_answer(
                message["sdp"]
            )

        elif message_type == "candidate":

            print(
                "[ICE] Remote candidate received"
            )





    # ================================================================
    # SEND TEXT
    # ================================================================


    def send_text(

        self,

        text: str
    ):


        self._safe_channel_send(text)


    # ================================================================
    # SEND BYTES
    # ================================================================


    def send_bytes(

        self,

        data: bytes
    ):


        self._safe_channel_send(data)

    async def stop_session(self):
        if self.pc is None:
            return

        if self._stopping:
            print("[WEBRTC] stop_session already running")
            return

        self._stopping = True
        self.security_authorized = False
        self._cancel_disconnect_watch()

        print("[WEBRTC] Stopping session")

        # ================================================================
        # STOP CURSOR SYNC
        # ================================================================

        if self._cursor_sync_task is not None:
            if not self._cursor_sync_task.done():
                self._cursor_sync_task.cancel()

                try:
                    await self._cursor_sync_task
                except asyncio.CancelledError:
                    pass

            self._cursor_sync_task = None

        # Сохраняем ссылки.
        # После pc.close() self.pc может быть уничтожен.
        pc = self.pc
        video = self.video
        audio = self.audio
        channel = self.channel

        # ================================================================
        # CLOSE DATA CHANNEL
        # ================================================================

        try:
            if channel is not None:
                t = time.perf_counter()

                print("[TIME] channel.close(): begin")

                channel.close()

                print(
                    f"[TIME] channel.close(): "
                    f"{time.perf_counter() - t:.3f}s"
                )

        except Exception as e:
            print("[DATA] channel.close error")

        # ================================================================
        # CLOSE WEBRTC FIRST
        # ================================================================

        try:
            print("[DEBUG] before pc.close")

            t = time.perf_counter()

            await pc.close()

            print("[DEBUG] after pc.close")

            print(
                f"[TIME] pc.close(): "
                f"{time.perf_counter() - t:.3f}s"
            )

        except Exception as e:
            print("[DEBUG] pc.close exception")

        # ================================================================
        # NOW TRACKS ARE NO LONGER USED BY WEBRTC
        # ================================================================

        # ------------------------------------------------
        # VIDEO
        # ------------------------------------------------

        try:
            if video is not None:
                t = time.perf_counter()

                print("[TIME] video.stop(): begin")

                video.stop()

                print(
                    f"[TIME] video.stop(): "
                    f"{time.perf_counter() - t:.3f}s"
                )

        except Exception as e:
            print("[VIDEO] Stop error")

        # ------------------------------------------------
        # AUDIO CAPTURE
        # ------------------------------------------------

        try:
            if audio is not None:
                t = time.perf_counter()

                print("[TIME] audio.close_capture(): begin")

                audio.close_capture()

                print(
                    f"[TIME] audio.close_capture(): "
                    f"{time.perf_counter() - t:.3f}s"
                )

        except Exception as e:
            print("[AUDIO] close_capture error")

        # ================================================================
        # DESTROY SESSION
        # ================================================================

        print("[DEBUG] before destroy")

        self.pc = None

        self.video = None
        self.video_sender = None

        self.audio = None
        self.audio_sender = None

        self.channel = None

        print("[WEBRTC] Session destroyed")

        self._stopping = False

    # ================================================================
    # CLOSE
    # ================================================================


    async def close(
        self
    ):
        print("[WEBRTC] Closing PeerConnection")
        await self.stop_session()