"""room_grade.py 등급 유틸 단위 테스트 (DB 불필요)."""
from app.services.room_grade import (
    grade_of_room,
    grade_of_biz_item,
    is_valid_grade,
    ROOM_GRADE_LABELS,
    GRADE_MIN,
    GRADE_MAX,
)


class _Stub:
    """ORM 객체 mock — grade 속성만 필요."""
    def __init__(self, grade):
        self.grade = grade


class TestGradeOfRoom:
    def test_returns_grade_when_set(self):
        assert grade_of_room(_Stub(grade=3)) == 3

    def test_returns_none_when_grade_null(self):
        assert grade_of_room(_Stub(grade=None)) is None

    def test_returns_none_when_room_none(self):
        assert grade_of_room(None) is None


class TestGradeOfBizItem:
    def test_returns_grade_when_set(self):
        assert grade_of_biz_item(_Stub(grade=2)) == 2

    def test_returns_none_when_grade_null(self):
        assert grade_of_biz_item(_Stub(grade=None)) is None

    def test_returns_none_when_biz_item_none(self):
        assert grade_of_biz_item(None) is None


class TestIsValidGrade:
    def test_valid_range(self):
        for v in range(GRADE_MIN, GRADE_MAX + 1):
            assert is_valid_grade(v), f"grade={v} should be valid"

    def test_zero_rejected(self):
        assert not is_valid_grade(0)

    def test_six_rejected(self):
        assert not is_valid_grade(6)

    def test_negative_rejected(self):
        assert not is_valid_grade(-1)

    def test_string_rejected(self):
        assert not is_valid_grade("3")

    def test_float_rejected(self):
        # 3.0 은 int 가 아니므로 거부
        assert not is_valid_grade(3.0)

    def test_none_rejected(self):
        assert not is_valid_grade(None)

    def test_bool_rejected(self):
        # Python 에서 True/False 는 int 의 subclass — 1/0 으로 해석되면 위험.
        # is_valid_grade 는 bool 을 명시적으로 거부해야 한다.
        assert not is_valid_grade(True)
        assert not is_valid_grade(False)


class TestLabels:
    def test_all_grades_have_label(self):
        for g in range(GRADE_MIN, GRADE_MAX + 1):
            assert g in ROOM_GRADE_LABELS

    def test_label_ordering_matches_grade(self):
        # 라벨 자체는 비교 안 하지만 등급 5단계 = 5개 라벨 보장
        assert len(ROOM_GRADE_LABELS) == GRADE_MAX - GRADE_MIN + 1
