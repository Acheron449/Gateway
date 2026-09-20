from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from app.services.database import (
    get_connection,
    create_portfolio,
    get_portfolio,
)


class PortfolioRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    VIEWER = "viewer"
    TRADER = "trader"


class Permission(str, Enum):
    VIEW_PORTFOLIO = "view_portfolio"
    VIEW_POSITIONS = "view_positions"
    VIEW_ORDERS = "view_orders"
    VIEW_FILLS = "view_fills"
    PLACE_ORDERS = "place_orders"
    CANCEL_ORDERS = "cancel_orders"
    MANAGE_PORTFOLIO = "manage_portfolio"
    MANAGE_USERS = "manage_users"
    VIEW_RISK = "view_risk"
    MANAGE_RISK = "manage_risk"
    WITHDRAW = "withdraw"
    DEPOSIT = "deposit"


ROLE_PERMISSIONS: dict[PortfolioRole, set[Permission]] = {
    PortfolioRole.OWNER: set(Permission),
    PortfolioRole.ADMIN: {
        Permission.VIEW_PORTFOLIO,
        Permission.VIEW_POSITIONS,
        Permission.VIEW_ORDERS,
        Permission.VIEW_FILLS,
        Permission.PLACE_ORDERS,
        Permission.CANCEL_ORDERS,
        Permission.MANAGE_PORTFOLIO,
        Permission.MANAGE_USERS,
        Permission.VIEW_RISK,
        Permission.MANAGE_RISK,
        Permission.WITHDRAW,
        Permission.DEPOSIT,
    },
    PortfolioRole.TRADER: {
        Permission.VIEW_PORTFOLIO,
        Permission.VIEW_POSITIONS,
        Permission.VIEW_ORDERS,
        Permission.VIEW_FILLS,
        Permission.PLACE_ORDERS,
        Permission.CANCEL_ORDERS,
        Permission.VIEW_RISK,
    },
    PortfolioRole.VIEWER: {
        Permission.VIEW_PORTFOLIO,
        Permission.VIEW_POSITIONS,
        Permission.VIEW_ORDERS,
        Permission.VIEW_FILLS,
        Permission.VIEW_RISK,
    },
}


@dataclass(frozen=True, slots=True)
class PortfolioMember:
    user_id: str
    portfolio_id: str
    role: PortfolioRole
    permissions: set[Permission]
    added_at: datetime
    added_by: str


@dataclass(frozen=True, slots=True)
class PortfolioGroup:
    id: str
    name: str
    description: str
    owner_id: str
    portfolio_ids: list[str]
    created_at: datetime


class MultiPortfolioService:
    """Manage multiple portfolios, users, and permissions."""

    def __init__(self):
        self._init_tables()

    def _init_tables(self):
        """Initialize multi-portfolio tables."""
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_members (
                    id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    permissions TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    added_by TEXT NOT NULL,
                    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id),
                    UNIQUE(portfolio_id, user_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    owner_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_group_members (
                    group_id TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL,
                    PRIMARY KEY (group_id, portfolio_id),
                    FOREIGN KEY(group_id) REFERENCES portfolio_groups(id),
                    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_portfolio_members_user_id ON portfolio_members(user_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_portfolio_members_portfolio_id ON portfolio_members(portfolio_id)
                """
            )
            conn.commit()

    def create_portfolio(
        self,
        user_id: str,
        name: str,
        initial_cash: float = 100000.0,
    ) -> dict:
        """Create a new portfolio with the user as owner."""
        portfolio_id = str(uuid4())
        create_portfolio(portfolio_id, user_id, initial_cash)

        self.add_member(
            portfolio_id=portfolio_id,
            user_id=user_id,
            role=PortfolioRole.OWNER,
            added_by=user_id,
        )

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE portfolios SET name = ? WHERE id = ?",
                (name, portfolio_id),
            )
            conn.commit()

        return get_portfolio(portfolio_id)

    def add_member(
        self,
        portfolio_id: str,
        user_id: str,
        role: PortfolioRole,
        added_by: str,
        custom_permissions: Optional[set[Permission]] = None,
    ) -> PortfolioMember:
        """Add a user to a portfolio with a role."""
        permissions = custom_permissions or ROLE_PERMISSIONS[role]

        member = PortfolioMember(
            user_id=user_id,
            portfolio_id=portfolio_id,
            role=role,
            permissions=permissions,
            added_at=datetime.now(timezone.utc),
            added_by=added_by,
        )

        import json
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO portfolio_members 
                   (id, portfolio_id, user_id, role, permissions, added_at, added_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    portfolio_id,
                    user_id,
                    role.value,
                    json.dumps([p.value for p in permissions]),
                    member.added_at.isoformat(),
                    added_by,
                ),
            )
            conn.commit()

        return member

    def remove_member(self, portfolio_id: str, user_id: str) -> bool:
        """Remove a user from a portfolio."""
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM portfolio_members WHERE portfolio_id = ? AND user_id = ?",
                (portfolio_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def update_member_role(
        self,
        portfolio_id: str,
        user_id: str,
        role: PortfolioRole,
    ) -> Optional[PortfolioMember]:
        """Update a member's role."""
        permissions = ROLE_PERMISSIONS[role]

        import json
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """UPDATE portfolio_members 
                   SET role = ?, permissions = ?
                   WHERE portfolio_id = ? AND user_id = ?""",
                (role.value, json.dumps([p.value for p in permissions]), portfolio_id, user_id),
            )
            conn.commit()

            if cur.rowcount == 0:
                return None

        return self.get_member(portfolio_id, user_id)

    def get_member(self, portfolio_id: str, user_id: str) -> Optional[PortfolioMember]:
        """Get a portfolio member."""
        import json
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            row = conn.execute(
                "SELECT * FROM portfolio_members WHERE portfolio_id = ? AND user_id = ?",
                (portfolio_id, user_id),
            ).fetchone()

        if not row:
            return None

        return PortfolioMember(
            user_id=row["user_id"],
            portfolio_id=row["portfolio_id"],
            role=PortfolioRole(row["role"]),
            permissions=set(Permission(p) for p in json.loads(row["permissions"])),
            added_at=datetime.fromisoformat(row["added_at"]),
            added_by=row["added_by"],
        )

    def get_portfolio_members(self, portfolio_id: str) -> list[PortfolioMember]:
        """Get all members of a portfolio."""
        import json
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            rows = conn.execute(
                "SELECT * FROM portfolio_members WHERE portfolio_id = ?",
                (portfolio_id,),
            ).fetchall()

        return [
            PortfolioMember(
                user_id=row["user_id"],
                portfolio_id=row["portfolio_id"],
                role=PortfolioRole(row["role"]),
                permissions=set(Permission(p) for p in json.loads(row["permissions"])),
                added_at=datetime.fromisoformat(row["added_at"]),
                added_by=row["added_by"],
            )
            for row in rows
        ]

    def get_user_portfolios(self, user_id: str) -> list[dict]:
        """Get all portfolios a user has access to."""
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            rows = conn.execute(
                """SELECT p.*, pm.role, pm.permissions
                   FROM portfolios p
                   JOIN portfolio_members pm ON p.id = pm.portfolio_id
                   WHERE pm.user_id = ?""",
                (user_id,),
            ).fetchall()

        return rows

    def check_permission(
        self,
        portfolio_id: str,
        user_id: str,
        permission: Permission,
    ) -> bool:
        """Check if a user has a specific permission on a portfolio."""
        member = self.get_member(portfolio_id, user_id)
        if not member:
            return False
        return permission in member.permissions

    def create_group(
        self,
        name: str,
        owner_id: str,
        description: str = "",
    ) -> PortfolioGroup:
        """Create a portfolio group."""
        group = PortfolioGroup(
            id=str(uuid4()),
            name=name,
            description=description,
            owner_id=owner_id,
            portfolio_ids=[],
            created_at=datetime.now(timezone.utc),
        )

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO portfolio_groups (id, name, description, owner_id, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (group.id, group.name, group.description, group.owner_id, group.created_at.isoformat()),
            )
            conn.commit()

        return group

    def add_portfolio_to_group(self, group_id: str, portfolio_id: str) -> bool:
        """Add a portfolio to a group."""
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO portfolio_group_members (group_id, portfolio_id) VALUES (?, ?)",
                (group_id, portfolio_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def remove_portfolio_from_group(self, group_id: str, portfolio_id: str) -> bool:
        """Remove a portfolio from a group."""
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM portfolio_group_members WHERE group_id = ? AND portfolio_id = ?",
                (group_id, portfolio_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_group(self, group_id: str) -> Optional[PortfolioGroup]:
        """Get a portfolio group with its portfolios."""
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            group_row = conn.execute(
                "SELECT * FROM portfolio_groups WHERE id = ?",
                (group_id,),
            ).fetchone()

            if not group_row:
                return None

            portfolio_rows = conn.execute(
                """SELECT p.* FROM portfolios p
                   JOIN portfolio_group_members pgm ON p.id = pgm.portfolio_id
                   WHERE pgm.group_id = ?""",
                (group_id,),
            ).fetchall()

        return PortfolioGroup(
            id=group_row["id"],
            name=group_row["name"],
            description=group_row["description"],
            owner_id=group_row["owner_id"],
            portfolio_ids=[p["id"] for p in portfolio_rows],
            created_at=datetime.fromisoformat(group_row["created_at"]),
        )

    def get_user_groups(self, user_id: str) -> list[PortfolioGroup]:
        """Get all groups owned by a user."""
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            rows = conn.execute(
                "SELECT * FROM portfolio_groups WHERE owner_id = ?",
                (user_id,),
            ).fetchall()

        groups = []
        for row in rows:
            group = self.get_group(row["id"])
            if group:
                groups.append(group)

        return groups


def get_default_permissions(role: PortfolioRole) -> set[Permission]:
    return ROLE_PERMISSIONS[role]