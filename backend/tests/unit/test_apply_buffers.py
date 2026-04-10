"""_apply_buffers() 유닛 테스트 — 순수 함수, DB 불필요."""
import json
import pytest
from app.templates.variables import _apply_buffers


class TestBasicCalculation:
    def test_no_buffers(self):
        m, f, t = _apply_buffers(3, 5, {})
        assert (m, f, t) == (3, 5, 8)

    def test_zero_inputs(self):
        m, f, t = _apply_buffers(0, 0, {})
        assert (m, f, t) == (0, 0, 0)


class TestParticipantBuffer:
    def test_positive_buffer(self):
        m, f, t = _apply_buffers(3, 5, {'_participant_buffer': 10})
        assert t == 18
        assert (m, f) == (3, 5)  # 개별 수는 안 바뀜

    def test_negative_buffer(self):
        m, f, t = _apply_buffers(3, 5, {'_participant_buffer': -2})
        assert t == 6


class TestGenderBuffers:
    def test_male_buffer(self):
        m, f, t = _apply_buffers(3, 5, {'_male_buffer': 2})
        assert (m, f, t) == (5, 5, 10)

    def test_female_buffer(self):
        m, f, t = _apply_buffers(3, 5, {'_female_buffer': 3})
        assert (m, f, t) == (3, 8, 11)

    def test_both_buffers(self):
        m, f, t = _apply_buffers(3, 5, {'_male_buffer': 1, '_female_buffer': 2})
        assert (m, f, t) == (4, 7, 11)

    def test_gender_buffer_with_participant_buffer(self):
        m, f, t = _apply_buffers(3, 5, {
            '_male_buffer': 1, '_female_buffer': 2, '_participant_buffer': 5
        })
        assert (m, f, t) == (4, 7, 16)  # 4+7+5


class TestGenderRatioBuffers:
    def test_female_high(self):
        """female >= male이면 female_high 적용."""
        grb = {'female_high': {'m': 2, 'f': 1}, 'male_high': {'m': 0, 'f': 3}}
        m, f, t = _apply_buffers(3, 5, {'_gender_ratio_buffers': json.dumps(grb)})
        assert (m, f, t) == (5, 6, 11)

    def test_male_high(self):
        """male > female이면 male_high 적용."""
        grb = {'female_high': {'m': 2, 'f': 1}, 'male_high': {'m': 0, 'f': 3}}
        m, f, t = _apply_buffers(7, 3, {'_gender_ratio_buffers': json.dumps(grb)})
        assert (m, f, t) == (7, 6, 13)

    def test_tie_uses_female_high(self):
        """동점(male == female)이면 female_high 적용."""
        grb = {'female_high': {'m': 1, 'f': 0}, 'male_high': {'m': 0, 'f': 1}}
        m, f, t = _apply_buffers(5, 5, {'_gender_ratio_buffers': json.dumps(grb)})
        assert (m, f, t) == (6, 5, 11)

    def test_overrides_gender_buffers(self):
        """gender_ratio_buffers가 있으면 male/female_buffer 무시."""
        grb = {'female_high': {'m': 10, 'f': 10}, 'male_high': {'m': 0, 'f': 0}}
        m, f, t = _apply_buffers(3, 5, {
            '_gender_ratio_buffers': json.dumps(grb),
            '_male_buffer': 100,
            '_female_buffer': 100,
        })
        assert (m, f, t) == (13, 15, 28)  # gender_ratio가 우선

    def test_invalid_json_fallback(self):
        """파싱 실패 시 원본 값 그대로."""
        m, f, t = _apply_buffers(3, 5, {'_gender_ratio_buffers': 'not-json'})
        assert (m, f, t) == (3, 5, 8)

    def test_dict_input(self):
        """문자열이 아닌 dict도 처리."""
        grb = {'female_high': {'m': 1, 'f': 2}, 'male_high': {'m': 0, 'f': 0}}
        m, f, t = _apply_buffers(3, 5, {'_gender_ratio_buffers': grb})
        assert (m, f, t) == (4, 7, 11)


class TestRounding:
    def test_ceil_round_unit_10(self):
        m, f, t = _apply_buffers(3, 5, {'_round_unit': 10, '_round_mode': 'ceil'})
        assert t == 10  # ceil(8/10)*10

    def test_floor_round_unit_10(self):
        m, f, t = _apply_buffers(3, 5, {'_round_unit': 10, '_round_mode': 'floor'})
        assert t == 0  # floor(8/10)*10

    def test_round_round_unit_10(self):
        m, f, t = _apply_buffers(3, 5, {'_round_unit': 10, '_round_mode': 'round'})
        assert t == 10  # round(8/10)*10 = round(0.8)*10

    def test_ceil_is_default(self):
        m, f, t = _apply_buffers(3, 5, {'_round_unit': 10})
        assert t == 10  # default ceil

    def test_round_unit_5(self):
        m, f, t = _apply_buffers(3, 5, {'_round_unit': 5, '_round_mode': 'ceil'})
        assert t == 10  # ceil(8/5)*5 = 2*5

    def test_exact_multiple_no_change(self):
        m, f, t = _apply_buffers(5, 5, {'_round_unit': 10, '_round_mode': 'ceil'})
        assert t == 10

    def test_round_unit_zero_no_rounding(self):
        m, f, t = _apply_buffers(3, 5, {'_round_unit': 0})
        assert t == 8

    def test_rounding_with_buffers(self):
        m, f, t = _apply_buffers(3, 5, {
            '_participant_buffer': 5,
            '_round_unit': 10,
            '_round_mode': 'ceil',
        })
        assert t == 20  # ceil(13/10)*10
