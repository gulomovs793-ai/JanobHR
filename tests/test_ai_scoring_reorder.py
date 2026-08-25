from services.ai_scoring import _reorder_questions


def test_filter_moved_to_front():
    qs = [
        {"key": "a", "text": "Oddiy savol"},
        {"key": "f", "text": "Filtr", "hard_filter": True},
        {"key": "b", "text": "Boshqa savol"},
    ]
    out = _reorder_questions(qs)
    assert out[0]["key"] == "f"


def test_salary_moved_to_end():
    qs = [
        {"key": "salary", "text": "Kutayotgan oylik maoshingiz qancha?"},
        {"key": "a", "text": "Oddiy savol"},
        {"key": "b", "text": "Boshqa savol"},
    ]
    out = _reorder_questions(qs)
    assert out[-1]["key"] == "salary"


def test_filter_and_salary_both_repositioned():
    qs = [
        {"key": "salary", "text": "Ish haqi haqida savol"},
        {"key": "mid", "text": "O'rta savol"},
        {"key": "filter", "text": "Tajribangiz bormi?", "hard_filter": True},
    ]
    out = _reorder_questions(qs)
    assert out[0]["key"] == "filter"
    assert out[-1]["key"] == "salary"
    assert out[1]["key"] == "mid"


def test_no_special_questions_keeps_order():
    qs = [{"key": "x", "text": "1"}, {"key": "y", "text": "2"}]
    assert _reorder_questions(qs) == qs
