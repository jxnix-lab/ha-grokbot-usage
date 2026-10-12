"""Constants for the Grok Bot Usage integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "grokbot_usage"
DEFAULT_NAME: Final = "Grok Bot Usage"
MANUFACTURER: Final = "Cursor"
MODEL: Final = "Grok Bot"

CONF_API_KEY: Final = "api_key"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 300
MIN_SCAN_INTERVAL: Final = 60
MAX_SCAN_INTERVAL: Final = 86_400

# Private, undocumented Cursor endpoint. The path is intentional, including "Sand".
API_URL: Final = (
    "https://api2.cursor.sh/aiserver.v1.DashboardService/GetSandUsageStatus"
)
TOKEN_EXCHANGE_URL: Final = "https://api2.cursor.sh/auth/exchange_user_api_key"
USER_AGENT: Final = "HomeAssistant-grokbot_usage"
REQUEST_TIMEOUT_SECONDS: Final = 30

AUTH_DOCS_URL: Final = "https://cursor.com/docs/cli/reference/authentication"

CONFIGURATION_URL: Final = "https://cursor.com/dashboard"

ERROR_OK: Final = "ok"
ERROR_UNAUTHORIZED: Final = "unauthorized"
ERROR_FORBIDDEN: Final = "forbidden"
ERROR_RATE_LIMITED: Final = "rate_limited"
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_INVALID_RESPONSE: Final = "invalid_response"
