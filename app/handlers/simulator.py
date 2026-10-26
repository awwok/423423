from datetime import datetime, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from app.config import settings
from app.db.session import SessionLocal
from app.keyboards.common import cancel_menu, simulator_menu
from app.models import Bank, CreditApplication, Loan, User
from app.services.financial import get_or_create_user, parse_money
from app.services.game import GAME_RULES, STAFF_COSTS, STAFF_NAMES, UPGRADE_COSTS, UPGRADE_NAMES, approve_application, attract_deposit, bank_for_owner, buy_upgrade, create_bank, hire_staff, list_clients, pending_applications, process_period, reject_application, update_owner_profile

router = Router()

class BankForm(StatesGroup):
    name = State()

class DepositForm(StatesGroup):
    amount = State()
    rate = State()

class OwnerForm(StatesGroup):
    age = State()
    photo = State()

async def owner_id(session, telegram_id: int, display_name: str | None = None) -> int:
    user = await get_or_create_user(session, telegram_id, settings.default_timezone, display_name=display_name)
    return user.id

def owner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить возраст", callback_data="sim:owner:age"), InlineKeyboardButton(text="Установить фото", callback_data="sim:owner:photo")],
        [InlineKeyboardButton(text="Назад в банк", callback_data="sim:dashboard")],
    ])

def application_keyboard(application_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"sim:app:approve:{application_id}"), InlineKeyboardButton(text="❌ Отказать", callback_data=f"sim:app:reject:{application_id}")],
        [InlineKeyboardButton(text="К заявкам", callback_data="sim:applications")],
    ])

def applicant_caption(application, borrower) -> str:
    history = borrower.history or {}
    active_debt = history.get("active_debt", "0.00")
    return (f"📨 Кредитная заявка №{application.id}\n\n👤 {borrower.name}, {borrower.age} лет\n💼 {borrower.profession}\n💰 Доход: {borrower.monthly_income:.2f} ₽/мес.\n⭐ Кредитный рейтинг: {borrower.credit_score}/850\n🧾 История: {history.get('note', 'данных пока мало')}\n✅ Погашено: {history.get('repaid', 0)}\n⚠️ Невозвратов: {history.get('defaults', 0)}\n💳 Текущий долг: {active_debt} ₽\n\nЗапрос: {application.requested_amount:.2f} ₽\nСтавка: {application.annual_rate_offer:.2f}% годовых\nСрок: {application.term_periods} периодов\nРиск модели: {application.risk_score * 100:.0f}%\n\nРешение влияет на доступные деньги, резерв и будущую прибыль банка.")

@router.callback_query(lambda c: c.data == "sim:create")
async def create_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(BankForm.name)
    await callback.message.answer("Придумайте название банка:\n\nПосле создания сразу появятся первые кредитные заявки.", reply_markup=cancel_menu()); await callback.answer()

@router.message(BankForm.name)
async def create_finish(message: Message, state: FSMContext):
    async with SessionLocal() as session:
        try:
            user_id = await owner_id(session, message.from_user.id, message.from_user.full_name)
            bank = await create_bank(session, user_id, message.text or "")
        except ValueError as e:
            await message.answer(str(e), reply_markup=cancel_menu()); return
    await state.clear(); await message.answer(f"🏦 Банк «{bank.name}» создан!\nСтартовый капитал: {bank.cash:.2f} ₽.\nПервые клиенты уже ждут решения по кредиту.\n\nПериод игры — 7 дней.", reply_markup=simulator_menu(True))

@router.callback_query(lambda c: c.data == "sim:dashboard")
async def dashboard(callback: CallbackQuery):
    async with SessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
        bank = await bank_for_owner(session, user.id)
    if not bank:
        await callback.message.answer("Сначала создайте банк.", reply_markup=simulator_menu(False)); await callback.answer(); return
    profit = bank.period_income - bank.period_expenses
    text = (f"🏦 {bank.name} · уровень {bank.level}\n👤 Владелец: {user.display_name or callback.from_user.full_name}{f', {user.age} лет' if user.age else ''}\n\n💰 Доступные средства: {bank.cash:.2f} ₽\n📊 Кредитный портфель: {bank.credit_portfolio:.2f} ₽\n🏛 Обязательства по вкладам: {bank.deposits:.2f} ₽\n💎 Собственный капитал: {bank.equity:.2f} ₽\n\nДоход периода: {bank.period_income:.2f} ₽\nРасходы периода: {bank.period_expenses:.2f} ₽\nПрибыль периода: {profit:.2f} ₽\nПросрочки: {bank.overdue_rate * 100:.2f}%\nРезерв ликвидности: {bank.liquidity_reserve * 100:.0f}%\nРепутация: {bank.reputation}/100\nКлиенты: {bank.clients}")
    await callback.message.answer(text, reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:rules")
async def rules(callback: CallbackQuery):
    await callback.message.answer(GAME_RULES, reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:staff")
async def staff(callback: CallbackQuery):
    async with SessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
        bank = await bank_for_owner(session, user.id)
    if not bank:
        await callback.message.answer("Сначала создайте банк.", reply_markup=simulator_menu(False)); await callback.answer(); return
    text = (f"👨‍💼 Персонал\n\nКредитные специалисты: {bank.staff_credit}\nАналитики: {bank.staff_analytics}\nМенеджеры: {bank.staff_managers}\nБезопасность: {bank.staff_security}\n\nНайм оплачивается сразу. Зарплаты списываются в конце периода.")
    buttons = [[InlineKeyboardButton(text=f"Нанять {STAFF_NAMES[role]} · {cost:.0f} ₽", callback_data=f"sim:hire:{role}")] for role, cost in STAFF_COSTS.items()]
    buttons.append([InlineKeyboardButton(text="В банк", callback_data="sim:dashboard")])
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith("sim:hire:"))
async def hire(callback: CallbackQuery):
    role = callback.data.rsplit(":", 1)[-1]
    async with SessionLocal() as session:
        try:
            await hire_staff(session, callback.from_user.id, role)
        except ValueError as e:
            await callback.message.answer(str(e), reply_markup=simulator_menu(True)); await callback.answer(); return
    await callback.message.answer(f"Нанят {STAFF_NAMES[role]}. Он начнёт влиять на банк со следующего периода.", reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:upgrades")
async def upgrades(callback: CallbackQuery):
    async with SessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
        bank = await bank_for_owner(session, user.id)
    if not bank:
        await callback.message.answer("Сначала создайте банк.", reply_markup=simulator_menu(False)); await callback.answer(); return
    levels = dict(bank.upgrades or {})
    text = "🧩 Развитие банка\n\n" + "\n".join(f"{UPGRADE_NAMES[key].capitalize()}: уровень {int(levels.get(key, 0))}" for key in UPGRADE_COSTS) + "\n\nСтоимость следующего уровня растёт после каждой покупки."
    buttons = [[InlineKeyboardButton(text=f"Улучшить: {UPGRADE_NAMES[key]} · {UPGRADE_COSTS[key] * Decimal(int(levels.get(key, 0)) + 1):.0f} ₽", callback_data=f"sim:upgrade:{key}")] for key in UPGRADE_COSTS]
    buttons.append([InlineKeyboardButton(text="В банк", callback_data="sim:dashboard")])
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith("sim:upgrade:"))
async def upgrade(callback: CallbackQuery):
    key = callback.data.rsplit(":", 1)[-1]
    async with SessionLocal() as session:
        try: await buy_upgrade(session, callback.from_user.id, key)
        except ValueError as e: await callback.message.answer(str(e), reply_markup=simulator_menu(True)); await callback.answer(); return
    await callback.message.answer(f"Улучшение «{UPGRADE_NAMES[key]}» куплено.", reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:analytics")
async def analytics(callback: CallbackQuery):
    async with SessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
        bank = await bank_for_owner(session, user.id)
        if bank:
            loans = list((await session.scalars(select(Loan).where(Loan.bank_id == bank.id))).all())
            applications = list((await session.scalars(select(CreditApplication).where(CreditApplication.bank_id == bank.id))).all())
    if not bank:
        await callback.message.answer("Сначала создайте банк.", reply_markup=simulator_menu(False)); await callback.answer(); return
    active = sum(1 for loan in loans if loan.status == "active")
    repaid = sum(1 for loan in loans if loan.status == "repaid")
    written_off = sum(1 for loan in loans if loan.status == "written_off")
    approved = sum(1 for item in applications if item.status == "approved")
    text = (f"📈 Аналитика банка\n\nЗаявок всего: {len(applications)}\nОдобрено: {approved}\nАктивных договоров: {active}\nПогашено: {repaid}\nСписано: {written_off}\n\nПортфель: {bank.credit_portfolio:.2f} ₽\nПросрочки: {bank.overdue_rate * 100:.2f}%\nРепутация: {bank.reputation}/100\nПрибыль последнего периода: {(bank.period_income - bank.period_expenses):.2f} ₽")
    await callback.message.answer(text, reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:achievements")
async def achievements(callback: CallbackQuery):
    async with SessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
        bank = await bank_for_owner(session, user.id)
        loans = list((await session.scalars(select(Loan).where(Loan.bank_id == bank.id))).all()) if bank else []
    if not bank:
        await callback.message.answer("Сначала создайте банк.", reply_markup=simulator_menu(False)); await callback.answer(); return
    unlocked = []
    if loans: unlocked.append("🏁 Первый договор — выдали первый кредит")
    if any(loan.status == "repaid" for loan in loans): unlocked.append("✅ Надёжный партнёр — клиент полностью погасил кредит")
    if bank.reputation >= 75: unlocked.append("⭐ Доверие рынка — репутация 75+")
    if bank.level >= 3: unlocked.append("🏢 Сеть растёт — уровень банка 3+")
    if bank.clients >= 10: unlocked.append("👥 Своя аудитория — 10 клиентов")
    await callback.message.answer("🏆 Достижения\n\n" + ("\n".join(unlocked) if unlocked else "Пока нет достижений. Первое решение по заявке уже откроет стартовое достижение."), reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:owner")
async def owner_profile(callback: CallbackQuery):
    async with SessionLocal() as session:
        user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
        bank = await bank_for_owner(session, user.id)
    text = f"👤 Профиль владельца\n\nИмя: {user.display_name or callback.from_user.full_name}\nВозраст: {user.age or 'не указан'}\nБанк: {bank.name if bank else 'не создан'}\nФото: {'установлено' if user.photo_file_id else 'не установлено'}"
    if user.photo_file_id:
        try:
            await callback.message.answer_photo(user.photo_file_id, caption=text, reply_markup=owner_keyboard())
        except TelegramBadRequest:
            await callback.message.answer(text, reply_markup=owner_keyboard())
    else:
        await callback.message.answer(text, reply_markup=owner_keyboard())
    await callback.answer()

@router.callback_query(lambda c: c.data == "sim:owner:age")
async def owner_age_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(OwnerForm.age); await callback.message.answer("Сколько вам лет?", reply_markup=cancel_menu()); await callback.answer()

@router.message(OwnerForm.age)
async def owner_age_finish(message: Message, state: FSMContext):
    try: age = int((message.text or "").strip())
    except ValueError: await message.answer("Введите возраст целым числом от 14 до 100.", reply_markup=cancel_menu()); return
    async with SessionLocal() as session:
        try: await update_owner_profile(session, message.from_user.id, age=age, display_name=message.from_user.full_name)
        except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    await state.clear(); await message.answer("Возраст сохранён.", reply_markup=simulator_menu(True))

@router.callback_query(lambda c: c.data == "sim:owner:photo")
async def owner_photo_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(OwnerForm.photo); await callback.message.answer("Пришлите фотографию одним сообщением. Она будет показываться в профиле владельца.", reply_markup=cancel_menu()); await callback.answer()

@router.message(OwnerForm.photo, F.photo)
async def owner_photo_finish(message: Message, state: FSMContext):
    async with SessionLocal() as session: await update_owner_profile(session, message.from_user.id, photo_file_id=message.photo[-1].file_id, display_name=message.from_user.full_name)
    await state.clear(); await message.answer("Фото владельца сохранено.", reply_markup=simulator_menu(True))

@router.message(OwnerForm.photo)
async def owner_photo_wrong(message: Message):
    await message.answer("Нужно прислать именно фотографию.", reply_markup=cancel_menu())

@router.callback_query(lambda c: c.data in {"sim:applications", "sim:loan"})
async def applications(callback: CallbackQuery):
    async with SessionLocal() as session:
        try:
            user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
            items = await pending_applications(session, user.id)
        except ValueError as e:
            await callback.message.answer(str(e), reply_markup=simulator_menu(False)); await callback.answer(); return
    if not items:
        await callback.message.answer("📨 Новых заявок пока нет. Они появятся в следующем игровом периоде.", reply_markup=simulator_menu(True)); await callback.answer(); return
    await callback.message.answer(f"📨 Кредитные заявки: {len(items)}\nИзучите профиль и историю каждого клиента перед решением.")
    for application, borrower in items[:5]:
        markup = application_keyboard(application.id)
        try:
            await callback.message.answer_photo(borrower.photo_url, caption=applicant_caption(application, borrower), reply_markup=markup)
        except (TelegramBadRequest, TypeError):
            await callback.message.answer(applicant_caption(application, borrower), reply_markup=markup)
    await callback.answer()

@router.callback_query(lambda c: c.data.startswith("sim:app:approve:"))
async def approve(callback: CallbackQuery):
    application_id = int(callback.data.rsplit(":", 1)[-1])
    async with SessionLocal() as session:
        try:
            user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
            application, borrower, loan = await approve_application(session, user.id, application_id)
        except ValueError as e:
            await callback.message.answer(str(e), reply_markup=simulator_menu(True)); await callback.answer(); return
    await callback.message.answer(f"✅ Заявка одобрена.\nКлиент: {borrower.name}\nВыдано: {loan.principal:.2f} ₽\nСтавка: {loan.annual_rate:.2f}%\nТеперь клиент будет платить или допускать просрочки в игровых периодах.", reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith("sim:app:reject:"))
async def reject(callback: CallbackQuery):
    application_id = int(callback.data.rsplit(":", 1)[-1])
    async with SessionLocal() as session:
        try:
            user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
            await reject_application(session, user.id, application_id)
        except ValueError as e:
            await callback.message.answer(str(e), reply_markup=simulator_menu(True)); await callback.answer(); return
    await callback.message.answer("❌ Заявка отклонена. Деньги банка сохранены, но репутация может расти медленнее из-за осторожной политики.", reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:clients")
async def clients(callback: CallbackQuery):
    async with SessionLocal() as session:
        try:
            user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
            borrowers = await list_clients(session, user.id)
        except ValueError as e:
            await callback.message.answer(str(e), reply_markup=simulator_menu(False)); await callback.answer(); return
    if not borrowers:
        await callback.message.answer("👥 Клиентов пока нет.", reply_markup=simulator_menu(True)); await callback.answer(); return
    await callback.message.answer(f"👥 Клиенты банка: {len(borrowers)}")
    for borrower in borrowers[:10]:
        history = borrower.history or {}
        caption = f"👤 {borrower.name}, {borrower.age} лет\n💼 {borrower.profession}\n💰 Доход: {borrower.monthly_income:.2f} ₽/мес.\n⭐ Рейтинг: {borrower.credit_score}/850\n✅ Погашено: {history.get('repaid', 0)}\n⚠️ Невозвратов: {history.get('defaults', 0)}\n💳 Текущий долг: {history.get('active_debt', '0.00')} ₽"
        try: await callback.message.answer_photo(borrower.photo_url, caption=caption)
        except (TelegramBadRequest, TypeError): await callback.message.answer(caption)
    await callback.message.answer("Карточки клиентов показывают текущую кредитную историю и состояние договоров.", reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:deposit")
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(DepositForm.amount); await callback.message.answer("Сумма вклада клиента:", reply_markup=cancel_menu()); await callback.answer()

@router.message(DepositForm.amount)
async def deposit_amount(message: Message, state: FSMContext):
    try: amount = parse_money(message.text or "")
    except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    await state.update_data(amount=str(amount)); await state.set_state(DepositForm.rate); await message.answer("Годовая ставка по вкладу:", reply_markup=cancel_menu())

@router.message(DepositForm.rate)
async def deposit_finish(message: Message, state: FSMContext):
    try: rate = Decimal((message.text or "").replace(",", ".")); assert Decimal("0") <= rate <= Decimal("100")
    except (ValueError, AssertionError): await message.answer("Введите ставку от 0 до 100.", reply_markup=cancel_menu()); return
    data = await state.get_data()
    async with SessionLocal() as session:
        try: await attract_deposit(session, message.from_user.id, Decimal(data["amount"]), rate)
        except ValueError as e: await message.answer(str(e), reply_markup=simulator_menu(True)); await state.clear(); return
    await state.clear(); await message.answer("Вклад привлечён. Деньги вкладчика — обязательство банка, не прибыль.", reply_markup=simulator_menu(True))

@router.callback_query(lambda c: c.data == "sim:period")
async def close_period(callback: CallbackQuery):
    async with SessionLocal() as session:
        try:
            user = await get_or_create_user(session, callback.from_user.id, settings.default_timezone, display_name=callback.from_user.full_name)
            period = await process_period(session, user.id, datetime.now(timezone.utc))
        except ValueError as e:
            await callback.message.answer(str(e), reply_markup=simulator_menu(False)); await callback.answer(); return
    text = "Период ещё не завершён или уже обработан. Следующий расчёт станет доступен через 7 дней." if period is None else f"Период закрыт.\nДоходы: {period.income:.2f} ₽\nРасходы: {period.expenses:.2f} ₽\nПрибыль: {(period.income - period.expenses):.2f} ₽\nНовые заявки и платежи клиентов рассчитаны."
    await callback.message.answer(text, reply_markup=simulator_menu(True)); await callback.answer()
