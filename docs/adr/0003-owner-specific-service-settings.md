# Owner-specific service settings

Provider API keys and model preferences belong to each signed-in account or
temporary guest session. The product allows both guests and account holders to
use their own services, so a settings change must affect only that owner's
assistants and operations. We chose this boundary over the administrator-only
shared settings proposed during the production interview; it adds credential
storage and model-compatibility work per owner but supports independent provider
choices and usage. This supersedes the application-wide credentials and model
choices portion of ADR-0002; retrieval and storage backend choices remain pending.
