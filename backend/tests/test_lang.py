from clipper import lang


def test_tokenize_keeps_latin_words_and_apostrophes():
    assert lang.tokenize("Don't stop, believe me!") == ["don't", "stop", "believe", "me"]


def test_tokenize_splits_han_and_kana_per_character():
    assert lang.tokenize("你好世界") == ["你", "好", "世", "界"]
    assert lang.tokenize("こんにちは") == list("こんにちは")


def test_tokenize_keeps_devanagari_marks_attached():
    tokens = lang.tokenize("नमस्ते दुनिया")
    assert len(tokens) == 2
    assert all(len(token) > 2 for token in tokens)


def test_tokenize_handles_arabic_and_cyrillic():
    assert lang.tokenize("Привет, мир") == ["привет", "мир"]
    assert len(lang.tokenize("مرحبا بالعالم")) == 2


def test_display_width_counts_wide_glyphs_twice():
    assert lang.display_width("abc") == 3
    assert lang.display_width("你好") == 4
    assert lang.display_width("a你") == 3


def test_join_tokens_omits_spaces_without_them():
    assert lang.join_tokens(["你好", "世界"], "zh") == "你好世界"
    assert lang.join_tokens(["hello", "world"], "en") == "hello world"


def test_ends_sentence_understands_more_than_ascii():
    assert lang.ends_sentence("done.")
    assert lang.ends_sentence("完了。")
    assert lang.ends_sentence("کیا؟")
    assert lang.ends_sentence("done.)")
    assert not lang.ends_sentence("word")


def test_normalise_accepts_bcp47_tags():
    assert lang.normalise("zh-Hans") == "zh"
    assert lang.normalise("pt_BR") == "pt"
    assert lang.normalise("EN") == "en"
    assert lang.normalise("") == "auto"
    assert lang.normalise(None) == "auto"
    assert lang.base("pt-BR") == "pt"


def test_script_detection_and_fonts():
    assert lang.script_of("hello there") == "latin"
    assert lang.script_of("こんにちは世界") == "kana"
    assert lang.script_of("你好") == "han"
    assert lang.script_of("12345") == "none"
    assert lang.script_for_language("hi") == "devanagari"
    assert lang.is_rtl("ar") and lang.is_rtl("he")
    assert not lang.is_rtl("en")
    assert lang.font_for("han")[0] == "Microsoft YaHei"
    assert lang.font_for("thai") == ["Leelawadee UI"]
    assert lang.font_for("unknown") == ["Segoe UI"]


def test_catalog_covers_the_picker_codes():
    catalog = {entry["code"]: entry for entry in lang.catalog()}
    assert {"en", "hi", "zh", "ja", "ar", "auto"} <= set(catalog)
    assert catalog["ja"]["script"] == "kana"
    assert catalog["ar"]["rtl"] is True
