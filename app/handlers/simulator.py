from decimal import Decimal
from datetime import datetime, timezone
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from app.config import settings
from app.db.session import SessionLocal
from app.keyboards.common import cancel_menu, simulator_menu
from app.models import Bank
from app.services.financial import get_or_create_user, parse_money
from app.services.game import attract_deposit, create_bank, issue_loan, process_period

router = Router()

class BankForm(StatesGroup): name = State()
class LoanForm(StatesGroup): amount = State(); rate = State(); risk = State()
class DepositForm(StatesGroup): amount = State(); rate = State()

async def bank_for(session, telegram_id: int):
    user = await get_or_create_user(session, telegram_id, settings.default_timezone)
    return await session.scalar(select(Bank).where(Bank.user_id == user.id))

@router.callback_query(lambda c: c.data == "sim:create")
async def create_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(BankForm.name); await callback.message.answer("Придумайте название банка:", reply_markup=cancel_menu()); await callback.answer()

@router.message(BankForm.name)
async def create_finish(message: Message, state: FSMContext):
    async with SessionLocal() as session:
        try: bank = await create_bank(session, (await get_or_create_user(session, message.from_user.id, settings.default_timezone)).id, message.text or "")
        except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    await state.clear(); await message.answer(f"Банк «{bank.name}» создан!\nСтартовый капитал: {bank.cash:.2f} ₽.\nПериод игры — 7 дней: он учитывается один раз после наступления нового периода.", reply_markup=simulator_menu(True))

@router.callback_query(lambda c: c.data == "sim:dashboard")
async def dashboard(callback: CallbackQuery):
    async with SessionLocal() as session: bank = await bank_for(session, callback.from_user.id)
    if not bank: await callback.message.answer("Сначала создайте банк.", reply_markup=simulator_menu(False)); await callback.answer(); return
    profit = bank.period_income - bank.period_expenses
    text = (f"🏦 {bank.name} · уровень {bank.level}\nДоступные средства: {bank.cash:.2f} ₽\nКредитный портфель: {bank.credit_portfolio:.2f} ₽\nОбязательства по вкладам: {bank.deposits:.2f} ₽\nСобственный капитал: {bank.equity:.2f} ₽\nДоходы периода: {bank.period_income:.2f} ₽\nРасходы периода: {bank.period_expenses:.2f} ₽\nПрибыль периода: {profit:.2f} ₽\nПросрочки: {bank.overdue_rate * 100:.2f}%\nЛиквидность: {bank.liquidity_reserve * 100:.0f}%\nРепутация: {bank.reputation}/100\nКлиенты: {bank.clients}")
    await callback.message.answer(text, reply_markup=simulator_menu(True)); await callback.answer()

@router.callback_query(lambda c: c.data == "sim:loan")
async def loan_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(LoanForm.amount); await callback.message.answer("Сумма кредита:", reply_markup=cancel_menu()); await callback.answer()

@router.message(LoanForm.amount)
async def loan_amount(message: Message, state: FSMContext):
    try: amount = parse_money(message.text or "")
    except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    await state.update_data(amount=str(amount)); await state.set_state(LoanForm.rate); await message.answer("Годовая ставка, например 24:", reply_markup=cancel_menu())

@router.message(LoanForm.rate)
async def loan_rate(message: Message, state: FSMContext):
    try: rate = Decimal((message.text or "").replace(",", ".")); assert Decimal("0") <= rate <= Decimal("100")
    except (ValueError, AssertionError): await message.answer("Введите ставку от 0 до 100.", reply_markup=cancel_menu()); return
    await state.update_data(rate=str(rate)); await state.set_state(LoanForm.risk); await message.answer("Допустимый риск от 0 до 1 (например 0,30):", reply_markup=cancel_menu())

@router.message(LoanForm.risk)
async def loan_finish(message: Message, state: FSMContext):
    try: risk = Decimal((message.text or "").replace(",", ".")); assert Decimal("0") <= risk <= Decimal("1")
    except (ValueError, AssertionError): await message.answer("Риск укажите числом от 0 до 1.", reply_markup=cancel_menu()); return
    data = await state.get_data()
    async with SessionLocal() as session:
        try: await issue_loan(session, message.from_user.id, Decimal(data["amount"]), Decimal(data["rate"]), risk)
        except ValueError as e: await message.answer(str(e), reply_markup=simulator_menu(True)); await state.clear(); return
    await state.clear(); await message.answer("Кредит выдан. Выдача кредита уменьшает доступные средства и увеличивает активы, но не считается расходом.", reply_markup=simulator_menu(True))

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
        try: period = await process_period(session, (await get_or_create_user(session, callback.from_user.id, settings.default_timezone)).id, datetime.now(timezone.utc))
        except ValueError as e: await callback.message.answer(str(e), reply_markup=simulator_menu(False)); await callback.answer(); return
    text = "Период уже обработан." if period is None else f"Период закрыт.\nДоходы: {period.income:.2f} ₽\nРасходы: {period.expenses:.2f} ₽\nПрибыль: {(period.income - period.expenses):.2f} ₽"
    await callback.message.answer(text, reply_markup=simulator_menu(True)); await callback.answer()
