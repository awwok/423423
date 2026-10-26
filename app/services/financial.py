from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import StringIO
import csv
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Account, Category, FinanceOperation, Transfer, User, BudgetLimit, SavingsGoal

MONEY_Q = Decimal("0.01")
DEFAULT_CATEGORIES = [("Продукты", "expense"), ("Транспорт", "expense"), ("Жильё", "expense"), ("Развлечения", "expense"), ("Здоровье", "expense"), ("Зарплата", "income"), ("Другое", "expense")]

def parse_money(value: str) -> Decimal:
    cleaned = value.strip().replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(cleaned).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("Введите сумму числом, например 1500,50.")
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля.")
    return amount

async def get_or_create_user(session: AsyncSession, telegram_id: int, timezone: str, display_name: str | None = None) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            await session.commit()
        return user
    user = User(telegram_id=telegram_id, timezone=timezone, display_name=display_name)
    session.add(user)
    await session.flush()
    for name in ("Наличные", "Карта", "Накопления"):
        session.add(Account(user_id=user.id, name=name, balance=Decimal("0.00")))
    for name, kind in DEFAULT_CATEGORIES:
        session.add(Category(user_id=user.id, name=name, kind=kind))
    await session.commit()
    return user

async def list_accounts(session: AsyncSession, user_id: int) -> list[Account]:
    return list((await session.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.id))).all())

async def list_categories(session: AsyncSession, user_id: int, kind: str | None = None) -> list[Category]:
    query = select(Category).where((Category.user_id == user_id) | (Category.user_id.is_(None)))
    if kind:
        query = query.where(Category.kind == kind)
    return list((await session.scalars(query.order_by(Category.id))).all())

async def add_account(session: AsyncSession, user_id: int, name: str, initial_balance: Decimal = Decimal("0.00")) -> Account:
    if not name.strip():
        raise ValueError("Название счёта не может быть пустым.")
    account = Account(user_id=user_id, name=name.strip()[:100], balance=initial_balance)
    session.add(account)
    await session.commit()
    return account

async def add_category(session: AsyncSession, user_id: int, name: str, kind: str) -> Category:
    if kind not in {"income", "expense"}:
        raise ValueError("Неизвестный тип категории.")
    category = Category(user_id=user_id, name=name.strip()[:100], kind=kind)
    session.add(category)
    await session.commit()
    return category

async def add_operation(session: AsyncSession, user_id: int, account_id: int, category_id: int, kind: str, amount: Decimal, operation_date: date, comment: str | None = None) -> FinanceOperation:
    if kind not in {"income", "expense"}:
        raise ValueError("Неизвестный тип операции.")
    account = await session.scalar(select(Account).where(and_(Account.id == account_id, Account.user_id == user_id)).with_for_update())
    category = await session.scalar(select(Category).where(and_(Category.id == category_id, (Category.user_id == user_id) | (Category.user_id.is_(None)), Category.kind == kind)))
    if not account or not category:
        raise ValueError("Счёт или категория не принадлежат пользователю.")
    if kind == "expense" and account.balance < amount:
        raise ValueError("На счёте недостаточно средств.")
    account.balance += amount if kind == "income" else -amount
    operation = FinanceOperation(user_id=user_id, account_id=account_id, category_id=category_id, kind=kind, amount=amount, operation_date=operation_date, comment=comment)
    session.add(operation)
    await session.commit()
    return operation

async def edit_operation(session: AsyncSession, user_id: int, operation_id: int, *, amount: Decimal | None = None, comment: str | None = None) -> FinanceOperation:
    operation = await session.scalar(select(FinanceOperation).where(and_(FinanceOperation.id == operation_id, FinanceOperation.user_id == user_id)).with_for_update())
    if not operation:
        raise ValueError("Операция не найдена.")
    if amount is not None:
        account = await session.scalar(select(Account).where(and_(Account.id == operation.account_id, Account.user_id == user_id)).with_for_update())
        if not account:
            raise ValueError("Счёт не найден.")
        old_effect = operation.amount if operation.kind == "income" else -operation.amount
        new_effect = amount if operation.kind == "income" else -amount
        if account.balance - old_effect + new_effect < 0:
            raise ValueError("После изменения на счёте будет отрицательный остаток.")
        account.balance += new_effect - old_effect
        operation.amount = amount
    if comment is not None:
        operation.comment = comment
    await session.commit()
    return operation

async def delete_operation(session: AsyncSession, user_id: int, operation_id: int) -> None:
    operation = await session.scalar(select(FinanceOperation).where(and_(FinanceOperation.id == operation_id, FinanceOperation.user_id == user_id)).with_for_update())
    if not operation:
        raise ValueError("Операция не найдена.")
    account = await session.scalar(select(Account).where(and_(Account.id == operation.account_id, Account.user_id == user_id)).with_for_update())
    effect = operation.amount if operation.kind == "income" else -operation.amount
    if account:
        account.balance -= effect
    await session.delete(operation)
    await session.commit()

async def transfer(session: AsyncSession, user_id: int, from_id: int, to_id: int, amount: Decimal, operation_date: date) -> Transfer:
    if from_id == to_id:
        raise ValueError("Выберите разные счета.")
    ids = sorted([from_id, to_id])
    rows = list((await session.scalars(select(Account).where(Account.id.in_(ids), Account.user_id == user_id).with_for_update())).all())
    by_id = {row.id: row for row in rows}
    if len(by_id) != 2:
        raise ValueError("Один из счетов не найден.")
    if by_id[from_id].balance < amount:
        raise ValueError("На счёте недостаточно средств.")
    by_id[from_id].balance -= amount
    by_id[to_id].balance += amount
    item = Transfer(user_id=user_id, from_account_id=from_id, to_account_id=to_id, amount=amount, operation_date=operation_date)
    session.add(item)
    await session.commit()
    return item

async def summary(session: AsyncSession, user_id: int, start: date, end: date) -> dict[str, Decimal | list[Account]]:
    rows = list((await session.scalars(select(FinanceOperation).where(FinanceOperation.user_id == user_id, FinanceOperation.operation_date.between(start, end)))).all())
    income = sum((x.amount for x in rows if x.kind == "income"), Decimal("0.00"))
    expense = sum((x.amount for x in rows if x.kind == "expense"), Decimal("0.00"))
    return {"income": income, "expense": expense, "difference": income - expense, "accounts": await list_accounts(session, user_id)}

async def export_csv(session: AsyncSession, user_id: int, start: date | None = None, end: date | None = None) -> str:
    query = select(FinanceOperation).where(FinanceOperation.user_id == user_id).order_by(FinanceOperation.operation_date, FinanceOperation.id)
    if start and end:
        query = query.where(FinanceOperation.operation_date.between(start, end))
    rows = list((await session.scalars(query)).all())
    out = StringIO(); writer = csv.writer(out); writer.writerow(["id", "тип", "сумма", "дата", "счёт", "категория", "комментарий"])
    accounts = {x.id: x.name for x in await session.scalars(select(Account).where(Account.user_id == user_id))}
    categories = {x.id: x.name for x in await session.scalars(select(Category).where((Category.user_id == user_id) | (Category.user_id.is_(None))))}
    for row in rows:
        writer.writerow([row.id, row.kind, row.amount, row.operation_date.isoformat(), accounts.get(row.account_id, ""), categories.get(row.category_id, ""), row.comment or ""])
    return out.getvalue()

async def set_budget_limit(session: AsyncSession, user_id: int, category_id: int, month: date, amount: Decimal) -> BudgetLimit:
    category = await session.scalar(select(Category).where(and_(Category.id == category_id, Category.user_id == user_id, Category.kind == "expense")))
    if not category:
        raise ValueError("Категория расходов не найдена.")
    month_start = month.replace(day=1)
    item = await session.scalar(select(BudgetLimit).where(BudgetLimit.user_id == user_id, BudgetLimit.category_id == category_id, BudgetLimit.month == month_start).with_for_update())
    if item:
        item.amount = amount
    else:
        item = BudgetLimit(user_id=user_id, category_id=category_id, month=month_start, amount=amount); session.add(item)
    await session.commit(); return item

async def budget_status(session: AsyncSession, user_id: int, month: date) -> list[tuple[BudgetLimit, Decimal, bool]]:
    month_start = month.replace(day=1); last_day = monthrange(month_start.year, month_start.month)[1]; month_end = month_start.replace(day=last_day)
    limits = list((await session.scalars(select(BudgetLimit).where(BudgetLimit.user_id == user_id, BudgetLimit.month == month_start))).all())
    result = []
    for limit in limits:
        spent = await session.scalar(select(func.coalesce(func.sum(FinanceOperation.amount), 0)).where(FinanceOperation.user_id == user_id, FinanceOperation.category_id == limit.category_id, FinanceOperation.kind == "expense", FinanceOperation.operation_date.between(month_start, month_end)))
        spent = Decimal(str(spent or 0)).quantize(MONEY_Q)
        result.append((limit, spent, spent >= limit.amount * Decimal("0.8")))
    return result

async def create_goal(session: AsyncSession, user_id: int, name: str, target_amount: Decimal) -> SavingsGoal:
    if not name.strip() or target_amount <= 0:
        raise ValueError("Укажите название и цель больше нуля.")
    goal = SavingsGoal(user_id=user_id, name=name.strip()[:100], target_amount=target_amount, current_amount=Decimal("0.00")); session.add(goal); await session.commit(); return goal

async def list_goals(session: AsyncSession, user_id: int) -> list[SavingsGoal]:
    return list((await session.scalars(select(SavingsGoal).where(SavingsGoal.user_id == user_id).order_by(SavingsGoal.id))).all())
