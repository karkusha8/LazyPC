import struct


# ================================================================
# VIDEO
# ================================================================

PACKET_VIDEO = 0x01
PACKET_VIDEO_INFO = 0x02


# ================================================================
# MOUSE / GESTURES
# ================================================================

PACKET_TAP = 0x40
PACKET_DOUBLE_TAP = 0x41
PACKET_DRAG_START = 0x42
PACKET_DRAG_MOVE = 0x43
PACKET_DRAG_END = 0x44
PACKET_MOVE = 0x45
PACKET_RIGHT_CLICK = 0x46
PACKET_SCROLL = 0x47


# ================================================================
# KEYBOARD
# ================================================================

PACKET_TEXT = 0x50
PACKET_KEY = 0x51
PACKET_SHORTCUT = 0x52
PACKET_LANG_SET = 0x53
PACKET_MODIFIER = 0x54


# ================================================================
# CURSOR
# ================================================================

PACKET_CURSOR_POSITION = 0x60


# ================================================================
# LANGUAGE
# ================================================================

LANG_EN = 0
LANG_RU = 1


# ================================================================
# VIDEO PACKETS
# ================================================================

VIDEO_HEADER = struct.Struct("!BIHH")

MAX_PACKET_SIZE = 1200

MAX_VIDEO_PAYLOAD = (
    MAX_PACKET_SIZE
    - VIDEO_HEADER.size
)


def build_video_packets(
    frame_id: int,
    encoded_frame: bytes
):

    packets = []

    packet_count = (
        len(encoded_frame)
        + MAX_VIDEO_PAYLOAD
        - 1
    ) // MAX_VIDEO_PAYLOAD

    for packet_id in range(packet_count):

        start = (
            packet_id
            * MAX_VIDEO_PAYLOAD
        )

        end = (
            start
            + MAX_VIDEO_PAYLOAD
        )

        payload = encoded_frame[
            start:end
        ]

        header = VIDEO_HEADER.pack(
            PACKET_VIDEO,
            frame_id,
            packet_id,
            packet_count,
        )

        packets.append(
            header + payload
        )

    return packets


def parse_video_packet(
    packet: bytes
):

    (
        packet_type,
        frame_id,
        packet_id,
        packet_count

    ) = VIDEO_HEADER.unpack(

        packet[
            :VIDEO_HEADER.size
        ]
    )

    payload = packet[
        VIDEO_HEADER.size:
    ]

    return (
        packet_type,
        frame_id,
        packet_id,
        packet_count,
        payload,
    )