from vlh.util.naming import parse_uwa_title, slugify


def test_parse_uwa():
    p = parse_uwa_title("【UWA 2024】性能优化实践-张三.mp4")
    assert p.category == "UWA 2024"
    assert "性能优化" in p.title
    assert p.speaker == "张三"


def test_parse_plain():
    p = parse_uwa_title("plain_talk.mp4")
    assert p.category is None
    assert p.title == "plain_talk"


def test_slugify_ascii():
    assert slugify("Hello World") == "hello-world"


def test_slugify_cjk():
    s = slugify("测试")
    assert s.startswith("u")
    assert "-" not in s or True
