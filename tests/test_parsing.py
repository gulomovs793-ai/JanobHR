from admin_bot.parsing import parse_manual_questions, to_manual_format


def test_plain_question_has_no_flags():
    qs = parse_manual_questions("Yoshingiz nechida?")
    assert len(qs) == 1
    assert "hard_filter" not in qs[0]
    assert "ai_score" not in qs[0]
    assert "voice" not in qs[0]


def test_filter_marker():
    qs = parse_manual_questions("Tajribangiz bormi? | filter")
    assert qs[0]["hard_filter"] is True


def test_uzbek_synonym_markers():
    qs = parse_manual_questions("Rejangiz qanday? | baho\nOvozli javob | ovoz")
    assert qs[0]["ai_score"] is True
    assert qs[1]["voice"] is True


def test_case_insensitive_marker():
    qs = parse_manual_questions("Savol | FILTER")
    assert qs[0]["hard_filter"] is True


def test_multiple_lines_multiple_questions():
    text = "1-savol\n2-savol | score\n3-savol | voice"
    qs = parse_manual_questions(text)
    assert len(qs) == 3
    assert qs[1]["ai_score"] is True
    assert qs[2]["voice"] is True


def test_empty_lines_skipped():
    qs = parse_manual_questions("\n\nSavol\n\n")
    assert len(qs) == 1


def test_roundtrip_to_manual_format():
    original = [
        {"key": "q1", "text": "Filtr savoli", "hard_filter": True},
        {"key": "q2", "text": "Score savoli", "ai_score": True},
        {"key": "q3", "text": "Oddiy savol"},
    ]
    text = to_manual_format(original)
    parsed = parse_manual_questions(text)
    assert parsed[0]["hard_filter"] is True
    assert parsed[1]["ai_score"] is True
    assert "hard_filter" not in parsed[2] and "ai_score" not in parsed[2]
