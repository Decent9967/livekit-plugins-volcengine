import pytest

from livekit.plugins.volcengine import TTS


def make(**kwargs):
    return TTS(api_key="test", speaker="voice", **kwargs)


@pytest.mark.parametrize(
    "options",
    [
        {"pitch": 13},
        {"pitch": True},
        {"disable_emoji_filter": 1},
        {"max_length_to_filter_parenthesis": -1},
        {"explicit_language": "english"},
        {"explicit_dialect": "unknown"},
        {"latex_parser": "v1"},
        {"latex_parser": "v2", "disable_markdown_filter": False},
        {"pronunciation_dict": {"tone": ["a/x", "a/y"]}},
        {"pronunciation_dict": {"tone": ["longerthan9/x"]}},
        {"pronunciation_dict": {"tone": ["a b/x"]}},
        {"pronunciation_dict": {"tone": ["/x"]}},
        {"pronunciation_dict": {"tone": ["a/"]}},
        {"pronunciation_dict": {"tone": ["invalid"]}},
        {"pronunciation_dict": {"tone": [f"{i}/x" for i in range(5001)]}},
        {"section_id": ""},
    ],
)
def test_invalid_controls_fail_before_network(options):
    with pytest.raises(ValueError):
        make(**options)


def test_effective_additions_conflicts_are_validated():
    with pytest.raises(ValueError):
        make(additions={"latex_parser": "v2", "disable_markdown_filter": False})
    with pytest.raises(ValueError):
        make(additions={"pitch": 2, "post_process": {"pitch": 13}})


def test_new_options_are_omitted_by_default():
    from livekit.plugins.volcengine._tts_options import TTSOptions

    request = TTSOptions("voice").request("Price $29.99, save 20%")
    assert request["text"] == "Price $29.99, save 20%"
    assert "additions" not in request
    assert "enable_subtitle" not in request["audio_params"]


def test_nested_controls_are_snapshotted_and_named_values_win():
    from livekit.plugins.volcengine._tts_options import TTSOptions

    dictionary = {"tone": ["omg/oh my god"]}
    additions = {"post_process": {"pitch": 8, "future": True}, "disable_emoji_filter": True}
    options = TTSOptions(
        "voice",
        pronunciation_dict=dictionary,
        additions=additions,
        pitch=0,
        disable_emoji_filter=False,
    )
    dictionary["tone"].append("x/y")
    additions["post_process"]["future"] = False
    import json

    result = json.loads(options.request()["additions"])
    assert result["pronunciation_dict"] == {"tone": ["omg/oh my god"]}
    assert result["post_process"] == {"pitch": 0, "future": True}
    assert result["disable_emoji_filter"] is False
    result["pronunciation_dict"]["tone"].append("z/w")
    assert json.loads(options.request()["additions"])["pronunciation_dict"] == {
        "tone": ["omg/oh my god"]
    }


@pytest.mark.parametrize(
    "options",
    [
        {"enable_subtitle": 1},
        {"pitch": -13},
        {"pronunciation_dict": {"tone": "a/x"}},
        {"pronunciation_dict": {"tone": [3]}},
        {"pronunciation_dict": {"tone": ["a\tb/x"]}},
        {"additions": {"post_process": []}},
    ],
)
def test_invalid_nested_controls(options):
    with pytest.raises(ValueError):
        make(**options)
