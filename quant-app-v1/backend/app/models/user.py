from pydantic import BaseModel
from typing import List, Dict, Optional

class Watchlist(BaseModel):
    id: str
    name: str
    symbols: List[str]

class Layout(BaseModel):
    symbol: str
    tab: str
    timeframe: str
    indicators: List[str]
    inspector_width: int

class UserPreferences(BaseModel):
    theme: str = "dark"
    default_timezone: str = "UTC"
    watchlists: List[Watchlist] = []
    saved_layouts: Dict[str, Layout] = {}

class User(BaseModel):
    id: str
    email: str
    hashed_password: str
    preferences: UserPreferences = UserPreferences()
