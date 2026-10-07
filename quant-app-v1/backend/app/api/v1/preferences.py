from fastapi import APIRouter
from app.auth import CurrentUser
from app.models.user import UserPreferences
from app.services.database import get_preferences, upsert_preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=UserPreferences)
def read_preferences(user: CurrentUser):
    # DB-backed (SQLite locally, Supabase RPCs on Vercel) — the previous
    # in-memory dict silently lost every write on serverless deployments.
    return UserPreferences.model_validate(get_preferences(user.id))


@router.patch("", response_model=UserPreferences)
def write_preferences(prefs: UserPreferences, user: CurrentUser):
    upsert_preferences(
        user.id,
        theme=prefs.theme,
        default_timezone=prefs.default_timezone,
        watchlists=prefs.watchlists,
        saved_layouts=prefs.saved_layouts,
    )
    return UserPreferences.model_validate(get_preferences(user.id))
