"""find_unreplaced_vars() 유닛 테스트 — 순수 함수, DB 불필요."""
from app.services.sms_sender import find_unreplaced_vars


class TestFindUnreplacedVars:
    def test_no_vars(self):
        assert find_unreplaced_vars("안녕하세요 김철수님") == []

    def test_single_var(self):
        assert find_unreplaced_vars("비밀번호: {{room_password}}") == ["room_password"]

    def test_multiple_vars(self):
        result = find_unreplaced_vars("{{customer_name}}님 {{room_num}}호")
        assert result == ["customer_name", "room_num"]

    def test_single_braces_ignored(self):
        assert find_unreplaced_vars("{이건 아님}") == []

    def test_triple_braces(self):
        result = find_unreplaced_vars("{{{var}}}")
        assert "var" in result

    def test_empty_string(self):
        assert find_unreplaced_vars("") == []

    def test_mixed_replaced_and_unreplaced(self):
        text = "김철수님 {{building}} {{room_num}}호 비밀번호 1234"
        result = find_unreplaced_vars(text)
        assert result == ["building", "room_num"]

    def test_no_match_on_spaces(self):
        """{{변수명}} 안에 공백이 있으면 매칭 안 됨."""
        assert find_unreplaced_vars("{{ room_num }}") == []

    def test_korean_var_name(self):
        """Python3의 \\w는 유니코드 포함이므로 한글 변수명도 감지됨."""
        assert find_unreplaced_vars("{{한글변수}}") == ["한글변수"]
