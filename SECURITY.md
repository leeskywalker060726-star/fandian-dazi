# Security and privacy

Do not commit `.env`, API keys, model settings, databases, user exports or logs.
Report security problems privately using GitHub's security reporting feature if enabled;
do not include credentials or personal conversations in public issues.

The desktop runs a loopback-only service protected by a per-launch secret. Model keys
are encrypted with Windows DPAPI. Chat text and relevant memory are sent only to the
model endpoint the user configures. This hackathon prototype is not a hosted multi-tenant
production service; internet deployment requires additional operational hardening.
