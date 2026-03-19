"""
Template Renderer - Dynamic message generation with variable substitution
Ported from stable-clasp-main/function_replaceMessage.js and password generation
"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
import random
import re
import logging

from app.db.models import MessageTemplate

logger = logging.getLogger(__name__)


class TemplateRenderer:
    """
    Renders message templates with variable substitution

    Ported from: stable-clasp-main/function_replaceMessage.js
    """

    def __init__(self, db: Session):
        self.db = db

    def render(self, template_key: str, variables: Dict[str, Any]) -> str:
        """
        Render template with variable substitution

        Args:
            template_key: Template key to look up
            variables: Dictionary of variables to substitute

        Returns:
            Rendered message string

        Ported from: stable-clasp-main/function_replaceMessage.js
        """
        # Get template from database
        template = self.db.query(MessageTemplate).filter_by(
            template_key=template_key,
            is_active=True
        ).first()

        if not template:
            logger.error(f"Template '{template_key}' not found")
            return f"[Template '{template_key}' not found]"

        # Start with template content
        result = template.content

        # Replace variables (format: {{variableName}})
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, str(value))

        # Check for unreplaced variables (undefined detection)
        unreplaced = re.findall(r'\{\{(\w+)\}\}', result)
        if unreplaced:
            logger.warning(f"Undefined variables in template '{template_key}': {unreplaced}")

        return result

    @staticmethod
    def generate_room_password(room_number: str) -> str:
        """
        Generate room password based on room number

        Args:
            room_number: Room number (e.g., "A101", "B205")

        Returns:
            Generated password string

        Ported from: stable-clasp-main/00_main.js:106-121
        """
        if not room_number or len(room_number) < 2:
            logger.warning(f"Invalid room number: {room_number}")
            return "0000"

        try:
            # Extract building letter and room number
            letter = room_number[0].upper()
            number = int(room_number[1:])

            # Calculate base password (from line 110-114)
            if letter == 'A':
                password = number * 4
            elif letter == 'B':
                password = number * 5
            else:
                logger.warning(f"Unknown building letter: {letter}")
                return "0000"

            # Add random digit and leading zero (from line 117-120)
            random_digit = random.randint(0, 9)
            final_password = f"{random_digit}0{password}"

            logger.debug(f"Generated password for {room_number}: {final_password}")
            return final_password

        except Exception as e:
            logger.error(f"Error generating password for {room_number}: {e}")
            return "0000"

    def get_template(self, template_key: str) -> Optional[MessageTemplate]:
        """Get template by key"""
        return self.db.query(MessageTemplate).filter_by(
            template_key=template_key,
            is_active=True
        ).first()

