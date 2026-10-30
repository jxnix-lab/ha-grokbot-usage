# Changelog

## 0.1.4

- Retry transient HTTP/server and transport failures without requesting reauthentication.
- Require at least three consecutive 401/403 or equivalent API auth failures spanning at least 15 minutes before requesting reauthentication. Reset the streak on success or any non-auth failure so outage-related auth errors cannot immediately disable polling.
- Keep initial setup and owner-initiated credential validation immediate. An entry already waiting for reauthentication still needs owner reauthentication once after updating.

After merging, publish GitHub release/tag `0.1.4`, download 0.1.4 in HACS, and schedule a Home Assistant restart to load the update.
