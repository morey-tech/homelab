# TOOLS.md - Environment & Tools

Environment-specific values. Skills define how tools work; this file
holds lookup values and security notes.

## Secrets and Config
- Workspace .env: ~/.openclaw/workspace-admin-gemma/.env
- NEVER cat, echo, or display .env contents
- Source .env silently, then use variables in commands

## Skills
Check the skills directory for installed skills:
`ls ~/.openclaw/skills/`

Each skill has a SKILL.md with usage instructions. Use skills when
they match the user's request.

## A2A Notes
- If the A2A skill is installed, check `MEMORY.md` before contacting peers
- Keep the `Known A2A Peers` table current when you verify useful peers
- Prefer verified peer URLs over guessing namespaces from memory
