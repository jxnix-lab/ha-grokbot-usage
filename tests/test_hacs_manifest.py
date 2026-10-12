"""Local stand-in for the HACS file schema checks.

The HACS GitHub Action downloads these files from raw.githubusercontent.com
without the workflow token, so it cannot read them while the repository is
private. These tests enforce the same schemas against the checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

import voluptuous as vol
from awesomeversion import AwesomeVersion
from homeassistant.helpers.config_validation import url as url_validator

ROOT = Path(__file__).resolve().parents[1]

HACS_MANIFEST_JSON_SCHEMA = vol.Schema(
    {
        vol.Optional("content_in_root"): bool,
        vol.Optional("filename"): str,
        vol.Optional("hacs"): str,
        vol.Optional("hide_default_branch"): bool,
        vol.Optional("homeassistant"): str,
        vol.Optional("persistent_directory"): str,
        vol.Optional("render_readme"): bool,
        vol.Optional("zip_release"): bool,
        vol.Required("name"): str,
    },
    extra=vol.PREVENT_EXTRA,
)

INTEGRATION_MANIFEST_JSON_SCHEMA = vol.Schema(
    {
        vol.Required("codeowners"): list,
        vol.Required("documentation"): url_validator,
        vol.Required("domain"): str,
        vol.Required("issue_tracker"): url_validator,
        vol.Required("name"): str,
        vol.Required("version"): vol.Coerce(AwesomeVersion),
    },
    extra=vol.ALLOW_EXTRA,
)


def test_hacs_json_matches_hacs_schema() -> None:
    """hacs.json has the required name and only known keys."""
    payload = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))

    HACS_MANIFEST_JSON_SCHEMA(payload)

    assert payload["name"] == "Grok Bot Usage"
    assert payload["render_readme"] is True
    assert payload["homeassistant"] == "2026.1.0"


def test_integration_manifest_matches_hacs_schema() -> None:
    """The integration manifest satisfies the HACS integration schema."""
    manifest_path = ROOT / "custom_components" / "grokbot_usage" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    INTEGRATION_MANIFEST_JSON_SCHEMA(payload)

    assert payload["domain"] == "grokbot_usage"
    assert payload["config_flow"] is True
    assert payload["iot_class"] == "cloud_polling"
    assert payload["version"] == "0.1.1"
    assert all(owner.startswith("@") for owner in payload["codeowners"])
