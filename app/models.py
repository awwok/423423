from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, String, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin

MONEY = Numeric(18, 2)

class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Samara")
    accounts: Mapped[list["Account"]] = relationship(cascade="all, delete-orphan")
    categories: Mapped[list["Category"]] = relationship(cascade="all, delete-orphan")
    bank: Mapped["Bank | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))

class FinanceOperation(TimestampMixin, Base):
    __tablename__ = "finance_operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    operation_date: Mapped[date] = mapped_column(Date)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

class Transfer(Base):
    __tablename__ = "transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    to_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    operation_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class BudgetLimit(Base):
    __tablename__ = "budget_limits"
    __table_args__ = (UniqueConstraint("user_id", "category_id", "month"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    month: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY)

class SavingsGoal(Base):
    __tablename__ = "savings_goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    target_amount: Mapped[Decimal] = mapped_column(MONEY)
    current_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Bank(TimestampMixin, Base):
    __tablename__ = "banks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    cash: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("1000000.00"))
    credit_portfolio: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    deposits: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    equity: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("1000000.00"))
    period_income: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    period_expenses: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    overdue_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0.0000"))
    liquidity_reserve: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0.2500"))
    reputation: Mapped[int] = mapped_column(Integer, default=50)
    clients: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    staff_credit: Mapped[int] = mapped_column(Integer, default=1)
    staff_analytics: Mapped[int] = mapped_column(Integer, default=0)
    staff_managers: Mapped[int] = mapped_column(Integer, default=1)
    staff_security: Mapped[int] = mapped_column(Integer, default=0)
    upgrades: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    user: Mapped[User] = relationship(back_populates="bank")
    loans: Mapped[list["Loan"]] = relationship(cascade="all, delete-orphan")
    deposits_rows: Mapped[list["Deposit"]] = relationship(cascade="all, delete-orphan")

class Loan(Base):
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id", ondelete="CASCADE"), index=True)
    principal: Mapped[Decimal] = mapped_column(MONEY)
    annual_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    risk: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    remaining: Mapped[Decimal] = mapped_column(MONEY)
    missed_periods: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Deposit(Base):
    __tablename__ = "deposits"
    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    annual_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class GamePeriod(Base):
    __tablename__ = "game_periods"
    __table_args__ = (UniqueConstraint("bank_id", "period_start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    income: Mapped[Decimal] = mapped_column(MONEY)
    expenses: Mapped[Decimal] = mapped_column(MONEY)
