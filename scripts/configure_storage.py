"""Create/check the private document bucket using server settings from .env."""

from advanced_rag.config import Settings
from advanced_rag.web.files.object_storage import check_bucket, enabled


def main():
    settings = Settings()
    if not enabled(settings):
        raise SystemExit("Set RAG_SUPABASE_URL and RAG_SUPABASE_SECRET_KEY in .env first.")
    check_bucket(settings, create=True)
    print("Private document bucket is ready. Credentials were not displayed.")


if __name__ == "__main__":
    main()
