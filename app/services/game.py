from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import random
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Bank, Deposit, GamePeriod, Loan

PERIOD_DAYS = 7
STARTING_CAPITAL = Decimal("1000000.00")
PERIOD = timedelta(days=PERIOD_DAYS)
MONEY_Q = Decimal("0.01")

def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, rounding=ROUND_HALF_UP)

def period_start(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc)
    epoch = datetime(2025, 1, 1, tzinfo=timezone.utc)
    periods = (now - epoch).days // PERIOD_DAYS
    return epoch + timedelta(days=periods * PERIOD_DAYS)

async def create_bank(session: AsyncSession, user_id: int, name: str) -> Bank:
    if not name.strip():
        raise ValueError("Название банка не может быть пустым.")
    existing = await session.scalar(select(Bank).where(Bank.user_id == user_id))
    if existing:
        raise ValueError("У вас уже есть банк.")
    bank = Bank(user_id=user_id, name=name.strip()[:100], cash=STARTING_CAPITAL, equity=STARTING_CAPITAL, upgrades={"office": 1})
    session.add(bank)
    await session.commit()
    return bank

async def issue_loan(session: AsyncSession, user_id: int, amount: Decimal, annual_rate: Decimal, risk: Decimal) -> Loan:
    bank = await session.scalar(select(Bank).where(Bank.user_id == user_id).with_for_update())
    if not bank:
        raise ValueError("Сначала создайте банк.")
    if not (Decimal("0.00") <= risk <= Decimal("1.00")):
        raise ValueError("Риск укажите от 0 до 1.")
    if bank.cash - amount < bank.deposits * bank.liquidity_reserve:
        raise ValueError("После выдачи нарушится резерв ликвидности.")
    loan = Loan(bank_id=bank.id, principal=amount, annual_rate=annual_rate, risk=risk, remaining=amount, missed_periods=0, status="active")
    bank.cash -= amount; bank.credit_portfolio += amount; bank.clients += 1
    session.add(loan)
    await session.commit()
    return loan

async def attract_deposit(session: AsyncSession, user_id: int, amount: Decimal, annual_rate: Decimal) -> Deposit:
    bank = await session.scalar(select(Bank).where(Bank.user_id == user_id).with_for_update())
    if not bank:
        raise ValueError("Сначала создайте банк.")
    if amount <= 0 or annual_rate < 0:
        raise ValueError("Сумма и ставка должны быть положительными.")
    item = Deposit(bank_id=bank.id, amount=amount, annual_rate=annual_rate)
    bank.cash += amount; bank.deposits += amount; bank.clients += 1
    session.add(item)
    await session.commit()
    return item

async def process_period(session: AsyncSession, user_id: int, now: datetime | None = None) -> GamePeriod | None:
    now = now or datetime.now(timezone.utc)
    bank = await session.scalar(select(Bank).where(Bank.user_id == user_id).with_for_update())
    if not bank:
        raise ValueError("Сначала создайте банк.")
    start = period_start(now)
    end = start + PERIOD
    already = await session.scalar(select(GamePeriod).where(and_(GamePeriod.bank_id == bank.id, GamePeriod.period_start == start)))
    if already:
        return None
    loans = list((await session.scalars(select(Loan).where(Loan.bank_id == bank.id, Loan.status == "active").with_for_update())).all())
    deposits = list((await session.scalars(select(Deposit).where(Deposit.bank_id == bank.id).with_for_update())).all())
    rng = random.Random(f"{bank.id}:{start.isoformat()}")
    income = Decimal("0.00"); expenses = Decimal("0.00"); overdue_principal = Decimal("0.00")
    for loan in loans:
        interest = money(loan.remaining * loan.annual_rate / Decimal("100") * Decimal(PERIOD_DAYS) / Decimal("365"))
        if rng.random() < min(Decimal("0.65"), Decimal("0.01") + loan.risk * Decimal("0.12")):
            loan.missed_periods += 1; overdue_principal += loan.remaining
            if loan.missed_periods >= 3:
                loss = money(loan.remaining * Decimal("0.35"))
                loan.remaining = money(loan.remaining - loss); bank.credit_portfolio = money(bank.credit_portfolio - loss); bank.equity = money(bank.equity - loss); expenses += loss; loan.status = "written_off"
            else:
                bank.overdue_rate = Decimal("0.0000") if bank.credit_portfolio == 0 else money(overdue_principal / bank.credit_portfolio)
        else:
            income += interest; bank.cash += interest
    for deposit in deposits:
        interest = money(deposit.amount * deposit.annual_rate / Decimal("100") * Decimal(PERIOD_DAYS) / Decimal("365"))
        expenses += interest; bank.cash -= interest; bank.deposits += interest
    salaries = Decimal("20000.00") * (bank.staff_credit + bank.staff_analytics + bank.staff_managers + bank.staff_security)
    salaries = money(salaries * Decimal(PERIOD_DAYS) / Decimal("30")); expenses += salaries; bank.cash -= salaries
    bank.period_income = income; bank.period_expenses = expenses; bank.equity = money(bank.equity + income - expenses)
    bank.reputation = max(0, min(100, bank.reputation + (2 if bank.overdue_rate < Decimal("0.05") else -3)))
    bank.level = int(max(1, 1 + (bank.equity // Decimal("500000"))))
    game_period = GamePeriod(bank_id=bank.id, period_start=start, period_end=end, income=income, expenses=expenses)
    session.add(game_period)
    try:
        await session.commit()
    except IntegrityError:
        # Two workers may pass the read check simultaneously; the unique key
        # is the final idempotency guard.
        await session.rollback()
        return None
    return game_period
