import asyncio
import struct
import time

from typing import Callable, Optional

from webrtc.video_track import DesktopVideoTrack

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
        self.channel: Optional[RTCDataChannel] = None

        self.on_text: Optional[Callable[[str], None]] = None
        self.on_bytes: Optional[Callable[[bytes], None]] = None

        self.cursor_position_provider = None
        self._cursor_sync_task = None

        self.on_disconnected = None

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

        print("[WEBRTC] VideoTrack added")

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

            if state in ("failed", "disconnected"):

                if self.on_disconnected is not None:
                    await self.on_disconnected()


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


            channel.send(
                "PING"
            )


            print(
                "[DATA] TX -> PING"
            )


            # ====================================================
            # START CURSOR SYNC
            # ====================================================


            if (

                self._cursor_sync_task is None

                or

                self._cursor_sync_task.done()

            ):


                self._cursor_sync_task = (

                    asyncio.create_task(

                        self._cursor_sync_loop()
                    )
                )


                print(

                    "[CURSOR] Sync started"
                )


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


            print(

                f"[DATA] RX -> {text}"
            )


            if text == "PING":


                channel.send(
                    "PONG"
                )


                print(
                    "[DATA] TX -> PONG"
                )


            if self.on_text:


                self.on_text(
                    text
                )


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


                if (

                    self.channel is None

                    or

                    self.channel.readyState != "open"

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


                self.channel.send(
                    packet
                )


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
    # CREATE OFFER
    # ================================================================

    async def create_offer(self):

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

        print("=" * 80)
        print("LOCAL OFFER SDP")
        print("=" * 80)
        print(self.pc.localDescription.sdp)
        print("=" * 80)

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


        print(
            "=" * 80
        )

        print(
            "ANSWER SDP"
        )

        print(
            "=" * 80
        )

        print(
            sdp
        )

        print(
            "=" * 80
        )


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
                "[ICE] Candidate received"
            )



        elif message_type == "client_disconnected":

            print("[SIGNALING] Client disconnected")

            if self.on_disconnected is not None:
                await self.on_disconnected()


    # ================================================================
    # SEND TEXT
    # ================================================================


    def send_text(

        self,

        text: str
    ):


        if (

            self.channel

            and

            self.channel.readyState == "open"

        ):


            self.channel.send(
                text
            )


    # ================================================================
    # SEND BYTES
    # ================================================================


    def send_bytes(

        self,

        data: bytes
    ):


        if (

            self.channel

            and

            self.channel.readyState == "open"

        ):


            self.channel.send(
                data
            )

    async def stop_session(self):

        if self.pc is None:
            return

        print("[WEBRTC] Stopping session")

        if self._cursor_sync_task is not None:

            if not self._cursor_sync_task.done():

                self._cursor_sync_task.cancel()

                try:
                    await self._cursor_sync_task
                except asyncio.CancelledError:
                    pass

            self._cursor_sync_task = None

        try:

            if self.video is not None:
                self.video.stop()

        except Exception as e:

            print("[VIDEO] Stop error:", e)

        try:

            if self.channel is not None:
                self.channel.close()

        except Exception:
            pass

        try:
            print("[DEBUG] before pc.close")
            await self.pc.close()
            print("[DEBUG] after pc.close")
        except Exception:
            print("[DEBUG] pc.close exception:", e)
            pass
        print("[DEBUG] before destroy")

        self.pc = None
        self.video = None
        self.video_sender = None
        self.channel = None

        print("[WEBRTC] Session destroyed")

    # ================================================================
    # CLOSE
    # ================================================================


    async def close(
        self
    ):


        print(

            "[WEBRTC] Closing PeerConnection"
        )
        total = time.perf_counter()

        # ========================================================
        # STOP CURSOR SYNC
        # ========================================================


        if self._cursor_sync_task is not None:


            if not self._cursor_sync_task.done():


                self._cursor_sync_task.cancel()


                try:

                    t = time.perf_counter()
                    await self._cursor_sync_task
                    print(f"[TIME] cursor stop: {time.perf_counter() - t:.3f}s")


                except asyncio.CancelledError:


                    pass


            self._cursor_sync_task = None


        # ========================================================
        # STOP VIDEO
        # ========================================================


        try:

            t = time.perf_counter()
            self.video.stop()
            print(f"[TIME] video.stop(): {time.perf_counter() - t:.3f}s")


        except Exception as e:


            print(

                "[VIDEO] Stop error:",

                e
            )


        # ========================================================
        # CLOSE DATA CHANNEL
        # ========================================================


        if self.channel:
            t = time.perf_counter()
            self.channel.close()
            print(f"[TIME] channel.close(): {time.perf_counter() - t:.3f}s")


        # ========================================================
        # CLOSE PEER CONNECTION
        # ========================================================

        print("[DEBUG] before pc.close")

        t = time.perf_counter()

        await self.pc.close()

        print("[DEBUG] after pc.close")

        print(f"[TIME] pc.close(): {time.perf_counter() - t:.3f}s")