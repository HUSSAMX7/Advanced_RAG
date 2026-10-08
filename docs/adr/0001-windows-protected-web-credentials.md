# Windows-protected web credentials

Status: accepted.

The local web application needs persistent provider keys entered through its
Settings page. Keeping them in browser storage or a plaintext configuration
file would expose them unnecessarily. This deployment runs under one Windows
user account and serves only the local machine.

Use user-scoped Windows DPAPI for the credential payload. Persist public model
and provider choices separately in the same atomically replaced settings file.
Return only credential-presence flags to the browser. Existing environment
configuration is an initial source, not rewritten by the web interface.

DPAPI avoids managing a separate encryption password or storing an encryption
key beside the ciphertext. The tradeoff is account and platform dependence:
moving the preferences file to another Windows account or another operating
system requires entering the provider keys again. Do not silently fall back to
plaintext credentials on unsupported platforms.
