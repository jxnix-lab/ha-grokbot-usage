# Grok Bot Usage

Home Assistant custom integration that polls Cursor for Grok Bot weekly usage and exposes it as sensors. The weekly usage percentage uses `state_class: measurement`, so the recorder keeps long-term statistics and usage builds a time series.

The integration talks to a private, undocumented endpoint:

`POST https://api2.cursor.sh/aiserver.v1.DashboardService/GetSandUsageStatus`

The user API key is first exchanged at `POST https://api2.cursor.sh/auth/exchange_user_api_key` with an empty JSON body and a Bearer header, following Cursor's SDK authentication flow. The returned short-lived access token is then sent as a Bearer token to the usage endpoint. Tokens are kept only in memory for that poll; each poll exchanges the key again to avoid expired-token failures. Session tokens and cookies are not read or forwarded. If a pasted value looks like a session cookie, setup is rejected before any request is sent.

Home Assistant 2026.1.0 or newer is required.

## Sensors

| Entity | Type | Notes |
| --- | --- | --- |
| Weekly usage | Sensor, `%` | `state_class: measurement`. Extra attributes: `has_non_zero_included_limit`, `uses_pooled_enterprise_allowance`. |
| Period start | Sensor, timestamp | Current usage period start. |
| Next reset | Sensor, timestamp | Next reset time. |
| Available usage | Binary sensor | On when the account still has included usage. |
| API error | Diagnostic sensor | `ok` after a successful poll, otherwise a short error message. Attribute `code` is a stable token such as `unauthorized` or `forbidden`. |
| Last successful update | Diagnostic sensor, timestamp | Stays available after a later poll fails. |

The response shape can change. Missing fields become `unknown` instead of failing the whole update. HTTP 401 and HTTP 403 mark the config entry as needing reauthentication.

## Installation

### HACS custom repository

1. In Home Assistant, open **HACS → Integrations**.
2. Open the overflow menu and choose **Custom repositories**.
3. Add `https://github.com/jxnix-lab/ha-grokbot-usage` with category **Integration**.
4. In the HACS integration list, open **Grok Bot Usage** and download it.
5. Restart Home Assistant.

Until a GitHub release is published, HACS installs the default branch. After a release is published, HACS installs that release.

A later HACS default-store submission needs a public repository, a GitHub description, repository topics, and a published release. Custom-repository installation does not need those.

### Manual

Copy `custom_components/grokbot_usage` into the `custom_components` directory of your Home Assistant configuration, then restart Home Assistant.

## Setup

1. Create a **user API key** in the [Cursor dashboard](https://cursor.com/dashboard), as described in [Cursor authentication docs](https://cursor.com/docs/cli/reference/authentication). A team admin key (`admin:*`) is not a user API key and cannot be used here.
2. In Home Assistant, go to **Settings → Devices & services → Add integration**.
3. Choose **Grok Bot Usage** and paste the user API key.

The config flow exchanges the key and calls the usage endpoint before the entry is created.

- Missing key: enter a user API key; no request is sent.

- HTTP 401: the key was rejected. Use a Cursor user API key, not a session token.
- HTTP 403: the key authenticated but is not allowed to read usage.
- Other connection or response failures stay on the form with an error, and no entry is created.

The key is stored in the config entry. Diagnostics redact it. It is not written to options, logs, or the unique id (the unique id is a hash prefix).

To change the key later, start reauthentication from the integration entry. To change the poll interval, open **Configure** on the integration entry.

## Options

| Option | Default | Range |
| --- | --- | --- |
| Poll interval | 300 seconds (5 minutes) | 60–86400 seconds |

Changing the interval reloads the integration.

## Development

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pytest
ruff check custom_components tests
ruff format --check custom_components tests
```

Tests mock the usage endpoint. They do not call Cursor.

## License

MIT. See [LICENSE](LICENSE).
