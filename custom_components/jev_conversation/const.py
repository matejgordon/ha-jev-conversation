"""Constants for Jev Conversation."""

DOMAIN = "jev_conversation"

CONF_BASE_URL = "base_url"
CONF_MODEL = "model"
CONF_EXECUTE_THRESHOLD = "execute_threshold"
CONF_ASK_THRESHOLD = "ask_threshold"

# OpenRouter works while TypeSafe signups are paused. TypeSafe direct:
# base URL https://api.typesafe.ai, model jev-1.13.0.
DEFAULT_BASE_URL = "https://openrouter.ai/api"
DEFAULT_MODEL = "typesafe/jev-1.13-20260917"
DEFAULT_EXECUTE_THRESHOLD = 0.85
DEFAULT_ASK_THRESHOLD = 0.5
