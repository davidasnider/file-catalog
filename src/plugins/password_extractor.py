import logging
from typing import Dict, Any

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.llm.factory import get_llm_provider
from src.core.analyzer_names import (
    TEXT_EXTRACTOR_NAME,
    PASSWORD_EXTRACTOR_NAME,
    ROUTER_NAME,
)

logger = logging.getLogger(__name__)


@register_analyzer(
    name=PASSWORD_EXTRACTOR_NAME,
    depends_on=[TEXT_EXTRACTOR_NAME, ROUTER_NAME],
    version="1.0",
)
class PasswordExtractorPlugin(AnalyzerBase):
    """
    Extremely high-precision analyzer for authentication credentials.
    Designed to have near-zero false positives by using strict filtering.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        category = context.get(ROUTER_NAME, {}).get("category", "")
        # Don't run on media files
        if category in ["Image", "Video", "Audio"]:
            return False

        from src.core.text_utils import get_all_extracted_text

        extracted_text = get_all_extracted_text(context)

        # Only run if there is enough text to potentially contain credentials
        # and if the text contains keywords that might indicate passwords.
        text_lower = extracted_text.lower()
        keywords = [
            "password",
            "passcode",
            "pin:",
            "secret key",
            "login",
            "credentials",
        ]
        return any(k in text_lower for k in keywords)

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Extracting passwords for {file_path}")

        from src.core.text_utils import get_all_extracted_text

        extracted_text = get_all_extracted_text(context)
        sample_text = extracted_text[:10000]  # Focus on the first 10k chars

        llm = get_llm_provider(is_vision=False, n_ctx=4096)
        if not llm or llm in ("MISSING_MODEL", "MISSING_LIBRARY"):
            return {
                "passwords": [],
                "skipped": True,
                "error": "LLM Provider unavailable",
            }

        prompt = f"""
        You are a security auditor identifying ONLY actual authentication passwords and PINs.

        TEXT TO ANALYZE:
        ---
        {sample_text}
        ---

        INSTRUCTIONS:
        1. Identify strings that are clearly authentication passwords, PINs, or passcodes.
        2. MANDATORY: The string must be explicitly labeled (e.g., 'Password: mysecret123') or be a high-entropy string in a security context.
        3. EXCLUSION RULES:
           - NEVER extract timestamps (e.g., '12:30', '0:45').
           - NEVER extract durations or scores.
           - NEVER extract headers, labels, or the word 'Password' itself.
           - NEVER extract common English phrases.
        4. If no ACTUAL passwords are found, return an empty list.
        5. Respond with LITERALLY ONLY valid JSON.

        Desired Output Format:
        {{
          "passwords": ["actual_password_here"]
        }}
        """

        try:
            response = await llm.generate(
                prompt,
                max_tokens=150,
                temperature=0.0,
                response_format={
                    "type": "json_object",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "passwords": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["passwords"],
                    },
                },
            )

            from src.core.text_utils import repair_and_load_json

            parsed = repair_and_load_json(response)

            if not parsed or not isinstance(parsed.get("passwords"), list):
                return {"passwords": [], "skipped": False}

            # Final sanity check: remove hallucinations or generic labels
            actual_passwords = []
            forbidden = [
                "password",
                "passcode",
                "pin",
                "secret",
                "unknown",
                "n/a",
                "none",
            ]
            for p in parsed["passwords"]:
                p_clean = p.strip()
                # If it's just a common label or empty, skip it
                if p_clean.lower() in forbidden or len(p_clean) < 2:
                    continue
                # If it's a timestamp (H:MM or HH:MM), skip it
                if ":" in p_clean and all(c.isdigit() or c == ":" for c in p_clean):
                    continue
                actual_passwords.append(p_clean)

            return {"passwords": actual_passwords, "skipped": False}
        except Exception as e:
            logger.error(f"Failed to extract passwords for {file_path}: {e}")
            return {"passwords": [], "skipped": True, "error": str(e)}
