from hue_party.models import AudioFrame, ChannelInfo


def af(
    t: float = 0.0,
    beat: bool = False,
    onset: bool = False,
    bpm: float = 120.0,
    volume: float = 0.5,
    low: float = 0.0,
    mid: float = 0.0,
    high: float = 0.0,
) -> AudioFrame:
    return AudioFrame(
        timestamp=t,
        is_beat=beat,
        is_onset=onset,
        tempo_bpm=bpm,
        volume=volume,
        low=low,
        mid=mid,
        high=high,
    )


CHANNELS = [
    ChannelInfo(0, -1.0, 0.6, 0.0),
    ChannelInfo(1, -0.33, 0.9, 0.5),
    ChannelInfo(2, 0.33, 0.9, 0.5),
    ChannelInfo(3, 1.0, 0.6, -0.5),
]
