from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import random

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bank, Borrower, CreditApplication, Deposit, GamePeriod, Loan, User

PERIOD_DAYS = 7
STARTING_CAPITAL = Decimal("1000000.00")
PERIOD = timedelta(days=PERIOD_DAYS)
MONEY_Q = Decimal("0.01")

GAME_RULES = """🏦 Суть игры
Вы управляете виртуальным банком. Ваша цель — вырасти от маленького офиса до устойчивой банковской сети.

Игровой период длится 7 дней. В конце периода банк получает проценты по нормально обслуживаемым кредитам, выплачивает проценты вкладчикам и зарплаты сотрудникам. Один период обрабатывается ровно один раз, даже после перезапуска.

📨 Кредитные заявки
Клиенты приходят с фотографией, профессией, доходом, кредитным рейтингом и историей. Вы решаете, кому доверить деньги. Высокий риск приносит больше процентов, но повышает шанс просрочки и списания.

💳 Формула
Проценты за период = остаток долга × годовая ставка × 7 / 365.
Погашение тела кредита возвращает активы в доступные деньги и не считается прибылью. Проценты — доход банка. Проценты по вкладам и зарплаты — расходы.

⚠️ Риск и ликвидность
Банк обязан держать резерв: доступные деньги не должны опускаться ниже 25% обязательств по вкладам. Три пропущенных платежа приводят к списанию долга. Репутация влияет на поток новых заявок.

🎯 Победа
Повышайте капитал, уровень и репутацию, удерживайте просрочки ниже 5% и развивайте портфель без кассовых разрывов. Это управленческая игра, а деньги внутри неё виртуальные."""

BORROWER_TEMPLATES = [
    {"name": "Илья Лолев", "age": 31, "profession": "Инженер по автоматизации", "income": "115000", "score": 742, "risk": "0.12", "amount": "180000", "rate": "19", "term": 12, "photo": "https://i.pravatar.cc/640?img=12", "note": "Два закрытых кредита без просрочек."},
    {"name": "Марина Ветрова", "age": 28, "profession": "Менеджер магазина", "income": "68000", "score": 655, "risk": "0.28", "amount": "120000", "rate": "25", "term": 10, "photo": "https://i.pravatar.cc/640?img=47", "note": "Один действующий кредит, была короткая просрочка."},
    {"name": "Роман Сафин", "age": 42, "profession": "Владелец кофейни", "income": "210000", "score": 701, "risk": "0.22", "amount": "450000", "rate": "23", "term": 18, "photo": "https://i.pravatar.cc/640?img=5", "note": "Доход зависит от сезона, есть залог оборудования."},
    {"name": "Алина Громова", "age": 24, "profession": "Дизайнер-фрилансер", "income": "92000", "score": 586, "risk": "0.46", "amount": "90000", "rate": "31", "term": 8, "photo": "https://i.pravatar.cc/640?img=32", "note": "Кредитная история короткая, доход нестабильный."},
    {"name": "Николай Орлов", "age": 55, "profession": "Врач-терапевт", "income": "145000", "score": 810, "risk": "0.08", "amount": "260000", "rate": "17", "term": 14, "photo": "https://i.pravatar.cc/640?img=68", "note": "Пять погашенных кредитов, без нарушений."},
]

STAFF_COSTS = {"credit": Decimal("80000"), "analytics": Decimal("100000"), "managers": Decimal("70000"), "security": Decimal("120000")}
STAFF_NAMES = {"credit": "кредитного специалиста", "analytics": "аналитика", "managers": "менеджера", "security": "специалиста по безопасности"}
UPGRADE_COSTS = {"office": Decimal("250000"), "online": Decimal("180000"), "scoring": Decimal("220000"), "fraud": Decimal("280000")}
UPGRADE_NAMES = {"office": "расширение офиса", "online": "онлайн-обслуживание", "scoring": "скоринг", "fraud": "антифрод"}

def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_Q, rounding=ROUND_HALF_UP)

def period_start(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc)
    epoch = datetime(2025, 1, 1, tzinfo=timezone.utc)
    periods = (now - epoch).days // PERIOD_DAYS
    return epoch + timedelta(days=periods * PERIOD_DAYS)

async def _owner_user(session: AsyncSession, owner_ref: int) -> User | None:
    """Resolve either internal user id or Telegram id.

    Handlers normally pass the internal id. Accepting Telegram id too keeps old
    callback flows safe and fixes the historical false "create a bank" error.
    """
    return await session.scalar(select(User).where(or_(User.id == owner_ref, User.telegram_id == owner_ref)))

async def bank_for_owner(session: AsyncSession, owner_ref: int, lock: bool = False) -> Bank | None:
    user = await _owner_user(session, owner_ref)
    if not user:
        return None
    query = select(Bank).where(Bank.user_id == user.id)
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)

def _history_for(template: dict) -> dict:
    return {"applications": 2, "approved": 0, "repaid": 2 if template["score"] >= 700 else 0, "defaults": 0, "active_debt": "0.00", "note": template["note"]}

async def _seed_applications(session: AsyncSession, bank: Bank, count: int = 2) -> None:
    for template in BORROWER_TEMPLATES[:count]:
        borrower = Borrower(bank_id=bank.id, name=template["name"], age=template["age"], profession=template["profession"], monthly_income=Decimal(template["income"]), photo_url=template["photo"], credit_score=template["score"], history=_history_for(template))
        session.add(borrower)
        await session.flush()
        session.add(CreditApplication(bank_id=bank.id, borrower_id=borrower.id, requested_amount=Decimal(template["amount"]), annual_rate_offer=Decimal(template["rate"]), term_periods=template["term"], risk_score=Decimal(template["risk"]), credit_score=template["score"], credit_history=borrower.history, photo_url=template["photo"], status="pending"))

async def generate_applications(session: AsyncSession, bank: Bank, target_pending: int = 3) -> list[CreditApplication]:
    pending = list((await session.scalars(select(CreditApplication).where(CreditApplication.bank_id == bank.id, CreditApplication.status == "pending"))).all())
    if len(pending) >= target_pending:
        return pending
    total = list((await session.scalars(select(CreditApplication).where(CreditApplication.bank_id == bank.id))).all())
    rng = random.Random(f"applications:{bank.id}:{len(total)}")
    while len(pending) < target_pending:
        template = BORROWER_TEMPLATES[(len(total) + rng.randrange(len(BORROWER_TEMPLATES))) % len(BORROWER_TEMPLATES)]
        borrower = Borrower(bank_id=bank.id, name=f"{template['name']} · заявка {len(total) + 1}", age=template["age"], profession=template["profession"], monthly_income=Decimal(template["income"]), photo_url=template["photo"], credit_score=template["score"], history=_history_for(template))
        session.add(borrower)
        await session.flush()
        application = CreditApplication(bank_id=bank.id, borrower_id=borrower.id, requested_amount=Decimal(template["amount"]), annual_rate_offer=Decimal(template["rate"]), term_periods=template["term"], risk_score=Decimal(template["risk"]), credit_score=template["score"], credit_history=borrower.history, photo_url=template["photo"], status="pending")
        session.add(application)
        pending.append(application); total.append(application)
    return pending

async def create_bank(session: AsyncSession, user_id: int, name: str) -> Bank:
    if not name.strip():
        raise ValueError("Название банка не может быть пустым.")
    if await bank_for_owner(session, user_id):
        raise ValueError("У вас уже есть банк.")
    bank = Bank(user_id=user_id, name=name.strip()[:100], cash=STARTING_CAPITAL, equity=STARTING_CAPITAL, upgrades={"office": 1})
    session.add(bank)
    await session.flush()
    await _seed_applications(session, bank, 2)
    await session.commit()
    return bank

async def pending_applications(session: AsyncSession, owner_ref: int) -> list[tuple[CreditApplication, Borrower]]:
    bank = await bank_for_owner(session, owner_ref)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    return list((await session.execute(select(CreditApplication, Borrower).join(Borrower, Borrower.id == CreditApplication.borrower_id).where(CreditApplication.bank_id == bank.id, CreditApplication.status == "pending").order_by(CreditApplication.created_at, CreditApplication.id))).all())

async def approve_application(session: AsyncSession, owner_ref: int, application_id: int) -> tuple[CreditApplication, Borrower, Loan]:
    bank = await bank_for_owner(session, owner_ref, lock=True)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    application = await session.scalar(select(CreditApplication).where(and_(CreditApplication.id == application_id, CreditApplication.bank_id == bank.id)).with_for_update())
    if not application or application.status != "pending":
        raise ValueError("Заявка уже обработана или не найдена.")
    borrower = await session.scalar(select(Borrower).where(Borrower.id == application.borrower_id).with_for_update())
    if bank.cash - application.requested_amount < bank.deposits * bank.liquidity_reserve:
        raise ValueError("Нельзя одобрить: после выдачи нарушится резерв ликвидности.")
    loan = Loan(bank_id=bank.id, application_id=application.id, borrower_id=borrower.id, principal=application.requested_amount, annual_rate=application.annual_rate_offer, risk=application.risk_score, remaining=application.requested_amount, term_periods=application.term_periods, payments_made=0, missed_periods=0, status="active")
    bank.cash -= application.requested_amount; bank.credit_portfolio += application.requested_amount; bank.clients += 1
    application.status = "approved"; application.decision = "Одобрено владельцем банка"; application.reviewed_at = datetime.now(timezone.utc)
    history = dict(borrower.history or {}); history["approved"] = int(history.get("approved", 0)) + 1; history["active_debt"] = str(money(Decimal(str(history.get("active_debt", 0))) + application.requested_amount)); borrower.history = history
    session.add(loan)
    await session.commit()
    return application, borrower, loan

async def reject_application(session: AsyncSession, owner_ref: int, application_id: int, reason: str = "Риск выше текущего лимита") -> CreditApplication:
    bank = await bank_for_owner(session, owner_ref, lock=True)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    application = await session.scalar(select(CreditApplication).where(and_(CreditApplication.id == application_id, CreditApplication.bank_id == bank.id)).with_for_update())
    if not application or application.status != "pending":
        raise ValueError("Заявка уже обработана или не найдена.")
    application.status = "rejected"; application.decision = reason[:255]; application.reviewed_at = datetime.now(timezone.utc)
    await session.commit()
    return application

async def issue_loan(session: AsyncSession, owner_ref: int, amount: Decimal, annual_rate: Decimal, risk: Decimal) -> Loan:
    bank = await bank_for_owner(session, owner_ref, lock=True)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    if amount <= 0 or not (Decimal("0.00") <= risk <= Decimal("1.00")):
        raise ValueError("Сумма должна быть положительной, риск — от 0 до 1.")
    if bank.cash - amount < bank.deposits * bank.liquidity_reserve:
        raise ValueError("После выдачи нарушится резерв ликвидности.")
    loan = Loan(bank_id=bank.id, principal=amount, annual_rate=annual_rate, risk=risk, remaining=amount, term_periods=12, status="active")
    bank.cash -= amount; bank.credit_portfolio += amount; bank.clients += 1
    session.add(loan)
    await session.commit()
    return loan

async def attract_deposit(session: AsyncSession, owner_ref: int, amount: Decimal, annual_rate: Decimal) -> Deposit:
    bank = await bank_for_owner(session, owner_ref, lock=True)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    if amount <= 0 or annual_rate < 0:
        raise ValueError("Сумма и ставка должны быть положительными.")
    item = Deposit(bank_id=bank.id, amount=amount, annual_rate=annual_rate)
    bank.cash += amount; bank.deposits += amount; bank.clients += 1
    session.add(item)
    await session.commit()
    return item

async def update_owner_profile(session: AsyncSession, telegram_id: int, *, age: int | None = None, photo_file_id: str | None = None, display_name: str | None = None) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
    if not user:
        raise ValueError("Пользователь не найден. Нажмите /start.")
    if age is not None:
        if not 14 <= age <= 100:
            raise ValueError("Возраст укажите от 14 до 100 лет.")
        user.age = age
    if photo_file_id:
        user.photo_file_id = photo_file_id
    if display_name:
        user.display_name = display_name[:150]
    await session.commit()
    return user

async def list_clients(session: AsyncSession, owner_ref: int) -> list[Borrower]:
    bank = await bank_for_owner(session, owner_ref)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    return list((await session.scalars(select(Borrower).where(Borrower.bank_id == bank.id).order_by(Borrower.name))).all())

async def hire_staff(session: AsyncSession, owner_ref: int, role: str) -> Bank:
    if role not in STAFF_COSTS:
        raise ValueError("Неизвестная должность.")
    bank = await bank_for_owner(session, owner_ref, lock=True)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    cost = STAFF_COSTS[role]
    if bank.cash < cost:
        raise ValueError("Недостаточно доступных средств для найма.")
    setattr(bank, f"staff_{role}", getattr(bank, f"staff_{role}") + 1)
    bank.cash -= cost; bank.equity -= cost; bank.period_expenses += cost
    await session.commit()
    return bank

async def buy_upgrade(session: AsyncSession, owner_ref: int, upgrade: str) -> Bank:
    if upgrade not in UPGRADE_COSTS:
        raise ValueError("Неизвестное улучшение.")
    bank = await bank_for_owner(session, owner_ref, lock=True)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    levels = dict(bank.upgrades or {})
    current = int(levels.get(upgrade, 0))
    cost = UPGRADE_COSTS[upgrade] * Decimal(current + 1)
    if bank.cash < cost:
        raise ValueError("Недостаточно доступных средств для улучшения.")
    levels[upgrade] = current + 1; bank.upgrades = levels; bank.cash -= cost; bank.equity -= cost; bank.period_expenses += cost
    if upgrade == "office":
        bank.level = max(bank.level, current + 2)
    await session.commit()
    return bank

async def process_period(session: AsyncSession, owner_ref: int, now: datetime | None = None) -> GamePeriod | None:
    now = now or datetime.now(timezone.utc)
    bank = await bank_for_owner(session, owner_ref, lock=True)
    if not bank:
        raise ValueError("Сначала создайте банк.")
    last_period = await session.scalar(select(GamePeriod).where(GamePeriod.bank_id == bank.id).order_by(GamePeriod.period_end.desc()))
    if last_period:
        if now <= last_period.period_end + PERIOD:
            return None
        start = last_period.period_end
    else:
        created_at = bank.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if now < created_at + PERIOD:
            return None
        # The first completed bucket ends before the current calendar bucket.
        start = period_start(now - PERIOD)
    end = start + PERIOD
    if await session.scalar(select(GamePeriod).where(and_(GamePeriod.bank_id == bank.id, GamePeriod.period_start == start))):
        return None
    loans = list((await session.scalars(select(Loan).where(Loan.bank_id == bank.id, Loan.status == "active").with_for_update())).all())
    deposits = list((await session.scalars(select(Deposit).where(Deposit.bank_id == bank.id).with_for_update())).all())
    rng = random.Random(f"{bank.id}:{start.isoformat()}")
    income = Decimal("0.00"); expenses = Decimal("0.00"); overdue_principal = Decimal("0.00")
    for loan in loans:
        interest = money(loan.remaining * loan.annual_rate / Decimal("100") * Decimal(PERIOD_DAYS) / Decimal("365"))
        borrower = await session.scalar(select(Borrower).where(Borrower.id == loan.borrower_id).with_for_update()) if loan.borrower_id else None
        risk_reduction = Decimal(bank.staff_security) * Decimal("0.01") + Decimal(bank.staff_analytics) * Decimal("0.005")
        if rng.random() < max(Decimal("0.005"), min(Decimal("0.85"), Decimal("0.015") + loan.risk * Decimal("0.18") - risk_reduction)):
            loan.missed_periods += 1; overdue_principal += loan.remaining
            if borrower:
                history = dict(borrower.history or {}); history["last_event"] = "Просрочка платежа"; borrower.history = history
            if loan.missed_periods >= 3:
                loss = money(loan.remaining); loan.remaining = Decimal("0.00"); loan.status = "written_off"; bank.credit_portfolio = money(max(Decimal("0.00"), bank.credit_portfolio - loss)); bank.equity = money(bank.equity - loss); expenses += loss
                if borrower:
                    history = dict(borrower.history or {}); history["defaults"] = int(history.get("defaults", 0)) + 1; history["active_debt"] = "0.00"; borrower.history = history
        else:
            principal_due = money(min(loan.remaining, loan.principal / Decimal(max(loan.term_periods, 1))))
            loan.remaining = money(loan.remaining - principal_due); loan.payments_made += 1; bank.cash += principal_due + interest; bank.credit_portfolio = money(max(Decimal("0.00"), bank.credit_portfolio - principal_due)); income += interest
            if borrower:
                history = dict(borrower.history or {}); history["active_debt"] = str(money(max(Decimal("0.00"), Decimal(str(history.get("active_debt", 0))) - principal_due))); borrower.history = history
            if loan.remaining <= 0:
                loan.status = "repaid"
                if borrower:
                    history = dict(borrower.history or {}); history["repaid"] = int(history.get("repaid", 0)) + 1; borrower.history = history
    for deposit in deposits:
        interest = money(deposit.amount * deposit.annual_rate / Decimal("100") * Decimal(PERIOD_DAYS) / Decimal("365")); expenses += interest; bank.cash -= interest; bank.deposits += interest
    salaries = money(Decimal("20000.00") * (bank.staff_credit + bank.staff_analytics + bank.staff_managers + bank.staff_security) * Decimal(PERIOD_DAYS) / Decimal("30")); expenses += salaries; bank.cash -= salaries
    bank.overdue_rate = Decimal("0.0000") if bank.credit_portfolio <= 0 else money(overdue_principal / bank.credit_portfolio); bank.period_income = income; bank.period_expenses = expenses; bank.equity = money(bank.equity + income - expenses); bank.reputation = max(0, min(100, bank.reputation + (2 if bank.overdue_rate < Decimal("0.05") else -3))); bank.level = int(max(1, 1 + (bank.equity // Decimal("500000"))))
    await generate_applications(session, bank, target_pending=min(8, 2 + bank.level + int((bank.upgrades or {}).get("office", 0))))
    game_period = GamePeriod(bank_id=bank.id, period_start=start, period_end=end, income=income, expenses=expenses); session.add(game_period)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback(); return None
    return game_period
