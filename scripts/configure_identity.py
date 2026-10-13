"""Write first-feature configuration without displaying or replacing private keys.

Public project values can be supplied as arguments. The server encryption key
is generated locally and never printed. SMTP credentials belong in Supabase's
dashboard, not in this application or chat.
"""

import argparse
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from dotenv import dotenv_values


def configure(path, *, url=None, public_key=None):
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    values = dotenv_values(path) if path.exists() else {}
    updates = {"WEB_IDENTITY_ENABLED": "true"}
    if url:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("Use the HTTPS Supabase project URL from its dashboard.")
        updates["SUPABASE_URL"] = url.rstrip("/")
    if public_key:
        if any(character.isspace() for character in public_key) or public_key.startswith(
            "sb_secret_"
        ):
            raise ValueError("Use only the publishable/anon key, never a secret key.")
        updates["SUPABASE_PUBLISHABLE_KEY"] = public_key
    if not values.get("WEB_CREDENTIAL_ENCRYPTION_KEY"):
        updates["WEB_CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    text = original
    for name, value in updates.items():
        pattern = rf"^[ \t]*(?:export[ \t]+)?{re.escape(name)}[ \t]*=.*$"
        text, count = re.subn(pattern, f"{name}={value}", text, flags=re.MULTILINE)
        if count == 0:
            text = text.rstrip("\n") + ("\n" if text else "") + f"{name}={value}\n"
    descriptor, temporary = tempfile.mkstemp(prefix="identity-config-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supabase-url")
    parser.add_argument("--publishable-key")
    arguments = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / ".env"
    configure(destination, url=arguments.supabase_url, public_key=arguments.publishable_key)
    print("Identity configuration prepared in .env. Private encryption key was not displayed.")
