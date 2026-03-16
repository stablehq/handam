"""
Rule-based response engine with regex pattern matching
"""
import re
import yaml
from typing import Optional, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class RuleEngine:
    """Rule-based auto-response engine"""

    def __init__(self, rules_file: str = "app/rules/rules.yaml"):
        self.rules_file = Path(rules_file)
        self.rules = []
        self.load_rules()

    def _validate_regex(self, pattern: str) -> bool:
        """M17: Regex 패턴 유효성 검증 (ReDoS 방어)"""
        if len(pattern) > 500:
            logger.warning(f"Regex pattern too long (>{len(pattern)} chars), rejecting: {pattern[:50]}...")
            return False
        try:
            re.compile(pattern)
            return True
        except re.error as e:
            logger.warning(f"Invalid regex pattern: {e}")
            return False

    def load_rules(self):
        """Load rules from YAML file"""
        if not self.rules_file.exists():
            logger.info(f"Rules file not found at {self.rules_file}, starting with empty rules")
            self.rules = []
            return
        try:
            with open(self.rules_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                raw_rules = data.get("rules", []) if data else []
                # M17: 로딩 시 regex 사전 검증
                self.rules = [r for r in raw_rules if self._validate_regex(r.get("pattern", ""))]
                skipped = len(raw_rules) - len(self.rules)
                if skipped:
                    logger.warning(f"Skipped {skipped} rules with invalid/unsafe regex patterns")
                # Sort by priority (descending)
                self.rules.sort(key=lambda x: x.get("priority", 0), reverse=True)
                logger.info(f"Loaded {len(self.rules)} rules from {self.rules_file}")
        except Exception as e:
            logger.error(f"Failed to load rules: {e}")
            self.rules = []

    def reload_rules(self):
        """Hot reload rules from file"""
        logger.info("Reloading rules...")
        self.load_rules()

    def match(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Match message against rules.
        Returns: {
            "response": str,
            "confidence": float,
            "rule_name": str,
            "needs_review": bool
        } or None if no match
        """
        for rule in self.rules:
            if not rule.get("active", True):
                continue

            pattern = rule.get("pattern", "")
            # M17: 매칭 시 안전 검증 (길이 초과 패턴 스킵)
            if len(pattern) > 500:
                logger.warning(f"Regex pattern too long, skipping: {pattern[:50]}...")
                continue
            try:
                if re.search(pattern, message, re.IGNORECASE):
                    logger.info(
                        f"✅ Rule matched: '{rule.get('name')}' for message: '{message}'"
                    )
                    return {
                        "response": rule.get("response", ""),
                        "confidence": 0.95,  # High confidence for rule-based
                        "rule_name": rule.get("name"),
                        "needs_review": False,
                        "source": "rule",
                    }
            except re.error as e:
                logger.error(f"Invalid regex pattern in rule '{rule.get('name')}': {e}")
                continue

        logger.info(f"❌ No rule matched for message: '{message}'")
        return None
