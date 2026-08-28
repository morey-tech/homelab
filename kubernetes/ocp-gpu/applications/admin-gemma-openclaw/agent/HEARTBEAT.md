# HEARTBEAT.md - Health Checks

## Every Heartbeat
- Verify workspace files are present and readable
- Check that skills directory exists and skills are installed
- Confirm .env is loadable (source it silently)

## Reporting
Heartbeat turns should usually end with NO_REPLY unless there is
something that requires the user's attention.

Only send a direct heartbeat message when something is broken and
the user needs to intervene.
