import utils


def fmt(**kw):
    return {"vcodec": "none", "acodec": "none", "ext": "mp4", **kw}


def test_picks_the_tallest_progressive_and_the_best_audio_only():
    formats = [
        fmt(format_id="360", vcodec="avc1", acodec="mp4a", height=360, tbr=500),
        fmt(format_id="720", vcodec="avc1", acodec="mp4a", height=720, tbr=1500),
        fmt(format_id="a-low", acodec="opus", abr=48),
        fmt(format_id="a-high", acodec="opus", abr=160),
        fmt(format_id="720-video-only", vcodec="avc1", height=1080),
    ]
    av, audio = utils.pick_best(formats)
    assert av["format_id"] == "720"
    assert audio["format_id"] == "a-high"


def test_breaks_a_height_tie_by_bitrate():
    formats = [
        fmt(format_id="lo", vcodec="v", acodec="a", height=720, tbr=900),
        fmt(format_id="hi", vcodec="v", acodec="a", height=720, tbr=1800),
    ]
    assert utils.pick_best(formats)[0]["format_id"] == "hi"


def test_skips_mhtml_storyboards():
    formats = [fmt(format_id="sb", vcodec="v", acodec="a", ext="mhtml", height=90)]
    assert utils.pick_best(formats) == (None, None)


def test_returns_none_for_the_missing_side():
    only_audio = [fmt(format_id="a", acodec="opus", abr=64)]
    av, audio = utils.pick_best(only_audio)
    assert av is None and audio["format_id"] == "a"
    only_av = [fmt(format_id="v", vcodec="v", acodec="a", height=480)]
    av, audio = utils.pick_best(only_av)
    assert av["format_id"] == "v" and audio is None


def test_tolerates_missing_numbers():
    formats = [fmt(format_id="x", vcodec="v", acodec="a", height=None, tbr=None)]
    assert utils.pick_best(formats)[0]["format_id"] == "x"


def test_empty_input():
    assert utils.pick_best([]) == (None, None)
