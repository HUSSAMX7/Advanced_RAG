"""Supabase Auth adapter with an explicit HTTP client dependency."""

import httpx
from fastapi import HTTPException


async def verify_supabase_token(settings, client, token):
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(503, "تسجيل الدخول غير متاح حاليًا. يمكنك المتابعة كضيف.")
    try:
        response = await client.get(
            settings.supabase_url.rstrip("/") + "/auth/v1/user",
            headers={
                "apikey": settings.supabase_publishable_key,
                "Authorization": f"Bearer {token}",
            },
        )
    except httpx.HTTPError:
        raise HTTPException(503, "تعذر التحقق من الدخول. حاول مرة أخرى.") from None
    if response.status_code in {401, 403}:
        raise HTTPException(401, "انتهى تسجيل الدخول. سجّل الدخول مرة أخرى.")
    if response.status_code != 200:
        raise HTTPException(503, "تعذر التحقق من الدخول. حاول مرة أخرى.")
    try:
        return response.json()
    except ValueError:
        raise HTTPException(503, "تعذر التحقق من الدخول. حاول مرة أخرى.") from None
