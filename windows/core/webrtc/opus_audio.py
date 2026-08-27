from __future__ import annotations

from aiortc.codecs.opus import OpusEncoder as _AiortcOpusEncoder


# ================================================================
# LazyPC Opus configuration
# ================================================================

OPUS_INITIAL_BITRATE = 128_000
OPUS_MIN_BITRATE = 64_000
OPUS_MAX_BITRATE = 192_000


class OpusAudioEncoder(_AiortcOpusEncoder):
    """
    LazyPC Opus encoder for system audio.

    48 kHz stereo
    Music/audio optimized mode
    128 kbps initial bitrate
    Dynamic bitrate support through aiortc REMB
    """

    def __init__(self) -> None:
        super().__init__()

        self._target_bitrate = OPUS_INITIAL_BITRATE

        # aiortc creates libopus here with:
        #   96 kbps
        #   application=voip
        #
        # Replace that configuration for system audio.
        self.codec.bit_rate = OPUS_INITIAL_BITRATE

        self.codec.format = "s16"
        self.codec.layout = "stereo"
        self.codec.sample_rate = 48_000

        # IMPORTANT:
        # "audio" is optimized for music / mixed content,
        # unlike "voip", which is optimized for speech.
        self.codec.options = {
            "application": "audio",
        }

        print(
            "[AUDIO][OPUS] Encoder created: "
            "48 kHz stereo, "
            f"{OPUS_INITIAL_BITRATE / 1000:.0f} kbps, "
            "application=audio"
        )

    @property
    def target_bitrate(self) -> int:
        return self._target_bitrate

    @target_bitrate.setter
    def target_bitrate(self, bitrate: int) -> None:
        bitrate = max(
            OPUS_MIN_BITRATE,
            min(int(bitrate), OPUS_MAX_BITRATE),
        )

        if bitrate == self._target_bitrate:
            return

        old = self._target_bitrate
        self._target_bitrate = bitrate

        # libopus accepts runtime bitrate changes.
        self.codec.bit_rate = bitrate

        print(
            "[AUDIO][OPUS] Bitrate changed: "
            f"{old / 1000:.0f} -> "
            f"{bitrate / 1000:.0f} kbps"
        )