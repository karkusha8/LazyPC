import asyncio
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
        self.channel: Optional[RTCDataChannel] = None

        self.on_text: Optional[Callable[[str], None]] = None
        self.on_bytes: Optional[Callable[[bytes], None]] = None

        self.cursor_position_provider = None
        self._cursor_sync_task = None
        self._stats_task = None

        self.on_disconnected = None
        self._stopping = False
        self._stats_task = None

        # Video pipeline diagnostics. Counts frames returned by DesktopVideoTrack
        # before aiortc encoding/packetization.
        self._video_track_frames = 0
        self._video_track_bytes = 0
        self._video_track_last_pts = None
        self._video_track_last_t = None
        self._video_track_max_gap_ms = 0.0
        self._video_track_last_log = time.monotonic()

        # ================================================================
        # SESSION-WIDE DIAGNOSTIC ACCUMULATORS
        # ================================================================
        # These are real running statistics, not (min + max) / 2.
        # We print min / max / arithmetic mean when the session stops.
        self._diag_session_started = time.monotonic()
        self._diag_rtt = {}
        self._diag_loop_delay = []

    @staticmethod
    def _diag_add_sample(store, key, value_ms):
        if value_ms is None:
            return
        try:
            value_ms = float(value_ms)
        except (TypeError, ValueError):
            return
        if value_ms < 0:
            return
        item = store.setdefault(
            key,
            {"count": 0, "sum": 0.0, "min": float("inf"), "max": 0.0},
        )
        item["count"] += 1
        item["sum"] += value_ms
        item["min"] = min(item["min"], value_ms)
        item["max"] = max(item["max"], value_ms)

    def _print_diagnostic_summary(self):
        duration = max(
            time.monotonic() - self._diag_session_started,
            0.0,
        )

        print("=")
        print("=" * 80)
        print("[DIAG][SUMMARY] SESSION DIAGNOSTICS")
        print("=" * 80)
        print(f"[DIAG][SUMMARY] duration={duration:.1f}s")

        if self._diag_rtt:
            print("[DIAG][SUMMARY] RTT statistics (real arithmetic mean):")
            for key, item in self._diag_rtt.items():
                if item["count"] <= 0:
                    continue
                avg = item["sum"] / item["count"]
                print(
                    f"[DIAG][RTT] {key}: "
                    f"min={item['min']:.1f}ms "
                    f"avg={avg:.1f}ms "
                    f"max={item['max']:.1f}ms "
                    f"samples={item['count']}"
                )
        else:
            print("[DIAG][RTT] no RTT samples collected")

        if self._diag_loop_delay:
            avg_loop = sum(self._diag_loop_delay) / len(self._diag_loop_delay)
            print(
                "[DIAG][LOOP] "
                f"min={min(self._diag_loop_delay):.1f}ms "
                f"avg={avg_loop:.1f}ms "
                f"max={max(self._diag_loop_delay):.1f}ms "
                f"samples={len(self._diag_loop_delay)}"
            )
        else:
            print("[DIAG][LOOP] no loop-delay samples collected")

        print("=" * 80)
        print("[DIAG][SUMMARY] END")
        print("=" * 80)
        print("=")

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

        # Wrap recv() only for diagnostics; the underlying DesktopVideoTrack
        # and its capture/encoder implementation remain untouched.
        original_video_recv = self.video.recv

        async def _diagnostic_video_recv():
            started = time.monotonic()
            frame = await original_video_recv()
            now = time.monotonic()
            self._video_track_frames += 1
            self._video_track_last_t = now
            try:
                self._video_track_bytes += int(frame.width * frame.height * 3 // 2)
            except Exception:
                pass
            gap_ms = (now - started) * 1000.0
            if gap_ms > self._video_track_max_gap_ms:
                self._video_track_max_gap_ms = gap_ms
            return frame

        self.video.recv = _diagnostic_video_recv

        self.video_sender = self.pc.addTrack(
            self.video
        )

        self.audio = SystemAudioTrack()

        self.audio_sender = self.pc.addTrack(
            self.audio
        )

        print("[WEBRTC] VideoTrack added")

        self._prefer_h264()

        self._register_events()

        self._stats_task = asyncio.create_task(
            self._webrtc_diagnostics_loop()
        )


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


    async def _webrtc_diagnostics_loop(self):
        """Periodic WebRTC diagnostics plus session-wide RTT statistics."""
        last_t = time.monotonic()
        last_bytes = {}
        last_packets = {}
        last_log = time.monotonic()

        try:
            while self.pc is not None and not self._stopping:
                await asyncio.sleep(0.5)

                now = time.monotonic()
                loop_delay_ms = (now - last_t - 0.5) * 1000.0
                last_t = now

                # Keep all samples so the final average is a real arithmetic
                # mean across the whole session.
                self._diag_loop_delay.append(loop_delay_ms)

                if loop_delay_ms > 100.0:
                    print(
                        f"[WEBRTC][STALL] asyncio loop delayed "
                        f"{loop_delay_ms:.1f}ms"
                    )

                try:
                    stats = await self.pc.getStats()
                except Exception as exc:
                    print(f"[WEBRTC][STATS] getStats error: {exc}")
                    continue

                if now - last_log < 1.0:
                    continue
                last_log = now

                lines = []

                for report in stats.values():
                    typ = getattr(report, "type", "")

                    if (
                        typ == "candidate-pair"
                        and getattr(report, "state", None) == "succeeded"
                    ):
                        rtt = getattr(
                            report,
                            "currentRoundTripTime",
                            None,
                        )
                        out = getattr(
                            report,
                            "availableOutgoingBitrate",
                            None,
                        )
                        inc = getattr(
                            report,
                            "availableIncomingBitrate",
                            None,
                        )

                        if rtt is not None:
                            rtt_ms = rtt * 1000.0
                            self._diag_add_sample(
                                self._diag_rtt,
                                "ICE/candidate-pair",
                                rtt_ms,
                            )
                            lines.append(
                                f"PAIR rtt={rtt_ms:.1f}ms "
                            )
                        else:
                            lines.append("PAIR ")

                        if out is not None:
                            lines[-1] += (
                                f"avail_out={out / 1e6:.2f}Mbps "
                            )
                        if inc is not None:
                            lines[-1] += (
                                f"avail_in={inc / 1e6:.2f}Mbps"
                            )

                    elif typ == "outbound-rtp":
                        kind = getattr(
                            report,
                            "kind",
                            getattr(report, "mediaType", "?"),
                        )
                        sid = getattr(
                            report,
                            "ssrc",
                            id(report),
                        )
                        b = getattr(
                            report,
                            "bytesSent",
                            0,
                        ) or 0
                        p = getattr(
                            report,
                            "packetsSent",
                            0,
                        ) or 0

                        db = b - last_bytes.get(sid, b)
                        dp = p - last_packets.get(sid, p)

                        last_bytes[sid] = b
                        last_packets[sid] = p

                        extra = ""

                        fe = getattr(
                            report,
                            "framesEncoded",
                            None,
                        )
                        fr = getattr(
                            report,
                            "framesSent",
                            None,
                        )
                        retrans = getattr(
                            report,
                            "retransmittedPacketsSent",
                            None,
                        )

                        if fe is not None:
                            extra += f" framesEncoded={fe}"
                        if fr is not None:
                            extra += f" framesSent={fr}"
                        if retrans is not None:
                            extra += f" retrans={retrans}"

                        lines.append(
                            f"OUT {kind} "
                            f"bitrate={db * 8 / 1e6:.2f}Mbps "
                            f"packets/s={dp} "
                            f"total={b / 1024 / 1024:.1f}MB"
                            f"{extra}"
                        )

                    elif typ == "remote-inbound-rtp":
                        kind = getattr(
                            report,
                            "kind",
                            getattr(report, "mediaType", "?"),
                        )
                        rrtt = getattr(
                            report,
                            "roundTripTime",
                            None,
                        )
                        frac = getattr(
                            report,
                            "fractionLost",
                            None,
                        )

                        if rrtt is not None:
                            rtt_ms = rrtt * 1000.0
                            self._diag_add_sample(
                                self._diag_rtt,
                                f"remote-{kind}",
                                rtt_ms,
                            )
                            lines.append(
                                f"REMOTE {kind} "
                                f"rtt={rtt_ms:.1f}ms "
                            )
                        else:
                            lines.append(
                                f"REMOTE {kind} "
                            )

                        if frac is not None:
                            lines[-1] += (
                                f"loss={frac * 100:.2f}%"
                            )

                # Track-side production stats.
                track_frames = self._video_track_frames
                now2 = time.monotonic()

                prev_frames = getattr(
                    self,
                    "_diag_prev_track_frames",
                    track_frames,
                )
                prev_t = getattr(
                    self,
                    "_diag_prev_track_t",
                    now2,
                )

                fps = (
                    (track_frames - prev_frames)
                    / max(now2 - prev_t, 1e-6)
                )

                self._diag_prev_track_frames = track_frames
                self._diag_prev_track_t = now2

                print(
                    f"[WEBRTC][STATS] loop_delay="
                    f"{loop_delay_ms:.1f}ms"
                )
                print(
                    "[VIDEO][TRACK] "
                    f"frames={track_frames} "
                    f"fps={fps:.1f} "
                    f"max_recv_wait="
                    f"{self._video_track_max_gap_ms:.1f}ms"
                )

                self._video_track_max_gap_ms = 0.0

                for line in lines:
                    print(
                        f"[WEBRTC][STATS] {line}"
                    )

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(
                f"[WEBRTC][STATS] diagnostics stopped: {exc}"
            )


    def _register_events(
        self
    ):

        @self.pc.on("connectionstatechange")
        async def _():

            state = self.pc.connectionState

            print("[WEBRTC] Connection state:", state)
            sctp = getattr(self.pc, "sctp", None)
            dtls = getattr(sctp, "transport", None) if sctp is not None else None
            if dtls is not None:
                print("[WEBRTC] DTLS state:", getattr(dtls, "state", "unknown"))

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
            print("[DATA] Send error:", e)
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


            if self._safe_channel_send("PING"):
                print("[DATA] TX -> PING")


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


                if self._safe_channel_send("PONG"):
                    print("[DATA] TX -> PONG")


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

        print("[WEBRTC] Stopping session")

        if self._stats_task is not None:
            if not self._stats_task.done():
                self._stats_task.cancel()
                try:
                    await self._stats_task
                except asyncio.CancelledError:
                    pass
            self._stats_task = None

        # Print one compact final report after the test is stopped.
        # This is intentionally done here so the user can simply run a test,
        # stop LazyPC, and paste the final summary.
        self._print_diagnostic_summary()

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
            print("[DATA] channel.close error:", e)

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
            print("[DEBUG] pc.close exception:", e)

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
            print("[VIDEO] Stop error:", e)

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
            print("[AUDIO] close_capture error:", e)

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