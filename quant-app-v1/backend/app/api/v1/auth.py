import os
from fastapi import APIRouter, HTTPException
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta
from app.models.user import User, UserPreferences

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET = os.getenv("JWT_SECRET_KEY")
if not SECRET:
    raise RuntimeError("JWT_SECRET_KEY must be set — failure-closed")
ALGORITHM = "HS256"
ACCESS_EXPIRE = timedelta(minutes=30)

_users_db = {}

def _token(data: dict, expires: timedelta = ACCESS_EXPIRE):
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + expires
    return jwt.encode(to_encode, SECRET, algorithm=ALGORITHM)

@router.post("/register")
def register(email: str, password: str):
    if email in _users_db:
        raise HTTPException(status_code=400, detail="User exists")
    u = User(id=str(len(_users_db)+1), email=email, hashed_password=pwd_context.hash(password))
    _users_db[email] = u
    return {"id": u.id, "email": u.email}

@router.post("/login")
def login(email: str, password: str):
    u = _users_db.get(email)
    if not u or not pwd_context.verify(password, u.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": _token({"sub": u.email}), "token_type": "bearer"}

@router.get("/me")
def me(token: str):
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        email = payload.get("sub")
        return _users_db.get(email, None)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/logout")
def logout():
    return {"message": "Logged out; client should discard token"}

@router.post("/refresh")
def refresh(token: str):
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM], options={"verify_exp": False})
        email = payload.get("sub")
        return {"access_token": _token({"sub": email})}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
