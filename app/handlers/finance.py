from datetime import date, timedelta
from decimal import Decimal
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from sqlalchemy import select
from app.db.session import SessionLocal
from app.keyboards.common import cancel_menu, finance_menu
from app.models import Account, Category, FinanceOperation, User
from app.services.financial import add_operation, add_account, add_category, export_csv, get_or_create_user, list_accounts, list_categories, parse_money, summary, transfer, set_budget_limit, budget_status, create_goal, list_goals
from app.config import settings

router = Router()

class OperationForm(StatesGroup):
    amount = State(); category = State(); account = State(); comment = State()
class TransferForm(StatesGroup):
    amount = State(); source = State(); target = State()
class BudgetForm(StatesGroup):
    amount = State(); category = State()
class GoalForm(StatesGroup):
    name = State(); target = State()
class EditForm(StatesGroup):
    amount = State()
class AccountForm(StatesGroup):
    name = State(); initial = State()
class CategoryForm(StatesGroup):
    kind = State(); name = State()

async def user_id_for(session, telegram_id: int) -> int:
    user = await get_or_create_user(session, telegram_id, settings.default_timezone); return user.id

@router.callback_query(lambda c: c.data in {"fin:add:income", "fin:add:expense"})
async def add_start(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.rsplit(":", 1)[1]
    await state.clear(); await state.update_data(kind=kind); await state.set_state(OperationForm.amount)
    await callback.message.answer(f"Введите сумму {('дохода' if kind == 'income' else 'расхода')} в рублях:", reply_markup=cancel_menu()); await callback.answer()

@router.message(OperationForm.amount)
async def op_amount(message: Message, state: FSMContext):
    try: amount = parse_money(message.text or "")
    except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    await state.update_data(amount=str(amount)); await state.set_state(OperationForm.category)
    async with SessionLocal() as session:
        categories = await list_categories(session, await user_id_for(session, message.from_user.id), (await state.get_data())["kind"])
    buttons = [[__import__('aiogram').types.InlineKeyboardButton(text=x.name, callback_data=f"fin:cat:{x.id}")] for x in categories]
    from aiogram.types import InlineKeyboardMarkup
    await message.answer("Выберите категорию:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons + [[__import__('aiogram').types.InlineKeyboardButton(text="Отмена", callback_data="cancel")]]))

@router.callback_query(lambda c: c.data.startswith("fin:cat:"), OperationForm.category)
async def op_category(callback: CallbackQuery, state: FSMContext):
    await state.update_data(category_id=int(callback.data.split(":")[-1])); await state.set_state(OperationForm.account)
    async with SessionLocal() as session:
        accounts = await list_accounts(session, await user_id_for(session, callback.from_user.id))
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.answer("Выберите счёт:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{a.name} ({a.balance:.2f} ₽)", callback_data=f"fin:account:{a.id}")] for a in accounts] + [[InlineKeyboardButton(text="Отмена", callback_data="cancel")]])); await callback.answer()

@router.callback_query(lambda c: c.data.startswith("fin:account:"), OperationForm.account)
async def op_account(callback: CallbackQuery, state: FSMContext):
    await state.update_data(account_id=int(callback.data.split(":")[-1])); await state.set_state(OperationForm.comment)
    await callback.message.answer("Комментарий? Напишите его или отправьте «-»:", reply_markup=cancel_menu()); await callback.answer()

@router.message(OperationForm.comment)
async def op_comment(message: Message, state: FSMContext):
    data = await state.get_data(); comment = None if (message.text or "").strip() == "-" else (message.text or "")[:500]
    async with SessionLocal() as session:
        try:
            await add_operation(session, await user_id_for(session, message.from_user.id), data["account_id"], data["category_id"], data["kind"], Decimal(data["amount"]), date.today(), comment)
        except ValueError as e: await message.answer(str(e), reply_markup=finance_menu()); await state.clear(); return
        warning = ""
        if data["kind"] == "expense":
            for limit, spent, near in await budget_status(session, await user_id_for(session, message.from_user.id), date.today()):
                if limit.category_id == data["category_id"] and near:
                    warning = f"\n\n⚠️ Лимит почти исчерпан: {spent:.2f} / {limit.amount:.2f} ₽."
                    break
    await state.clear(); await message.answer("Операция сохранена." + warning, reply_markup=finance_menu())

@router.callback_query(lambda c: c.data == "fin:accounts")
async def accounts(callback: CallbackQuery):
    async with SessionLocal() as session:
        accounts = await list_accounts(session, await user_id_for(session, callback.from_user.id))
    text = "Счета\n" + "\n".join(f"• {a.name}: {a.balance:.2f} ₽" for a in accounts)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Новый счёт", callback_data="fin:account:new")]] + finance_menu().inline_keyboard)); await callback.answer()

@router.callback_query(lambda c: c.data == "fin:account:new")
async def account_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(AccountForm.name); await callback.message.answer("Название нового счёта:", reply_markup=cancel_menu()); await callback.answer()

@router.message(AccountForm.name)
async def account_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip()); await state.set_state(AccountForm.initial); await message.answer("Начальный остаток (можно 0):", reply_markup=cancel_menu())

@router.message(AccountForm.initial)
async def account_finish(message: Message, state: FSMContext):
    try:
        raw = (message.text or "").strip().replace(",", ".")
        initial = Decimal("0.00") if raw in {"0", "0.0", "0.00"} else parse_money(raw)
    except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    async with SessionLocal() as session:
        try: await add_account(session, await user_id_for(session, message.from_user.id), (await state.get_data())["name"], initial)
        except ValueError as e: await message.answer(str(e), reply_markup=finance_menu()); await state.clear(); return
    await state.clear(); await message.answer("Счёт создан.", reply_markup=finance_menu())

@router.callback_query(lambda c: c.data == "fin:history")
async def history(callback: CallbackQuery):
    async with SessionLocal() as session:
        uid = await user_id_for(session, callback.from_user.id)
        rows = list((await session.scalars(select(FinanceOperation).where(FinanceOperation.user_id == uid).order_by(FinanceOperation.operation_date.desc(), FinanceOperation.id.desc()).limit(15))).all())
        categories = {x.id: x.name for x in await session.scalars(select(Category).where((Category.user_id == uid) | (Category.user_id.is_(None))))}
    text = "История (последние 15)\n" + ("\n".join(f"{r.id}. {r.operation_date:%d.%m} {'+' if r.kind == 'income' else '-'}{r.amount:.2f} ₽ · {categories.get(r.category_id, '')}" for r in rows) or "Пока нет операций.")
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows_buttons = [[InlineKeyboardButton(text=f"Изменить #{r.id}", callback_data=f"fin:edit:{r.id}"), InlineKeyboardButton(text=f"Удалить #{r.id}", callback_data=f"fin:delete:{r.id}")] for r in rows[:8]]
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows_buttons + finance_menu().inline_keyboard)); await callback.answer()

@router.callback_query(lambda c: c.data.startswith("fin:delete:"))
async def delete_from_history(callback: CallbackQuery):
    from app.services.financial import delete_operation
    async with SessionLocal() as session:
        try: await delete_operation(session, await user_id_for(session, callback.from_user.id), int(callback.data.split(":")[-1]))
        except ValueError as e: await callback.message.answer(str(e), reply_markup=finance_menu()); await callback.answer(); return
    await callback.message.answer("Операция удалена, остаток пересчитан.", reply_markup=finance_menu()); await callback.answer()

@router.callback_query(lambda c: c.data.startswith("fin:edit:"))
async def edit_from_history(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.update_data(operation_id=int(callback.data.split(":")[-1])); await state.set_state(EditForm.amount)
    await callback.message.answer("Введите новую сумму операции:", reply_markup=cancel_menu()); await callback.answer()

@router.message(EditForm.amount)
async def edit_amount(message: Message, state: FSMContext):
    try: amount = parse_money(message.text or "")
    except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    from app.services.financial import edit_operation
    async with SessionLocal() as session:
        try: await edit_operation(session, await user_id_for(session, message.from_user.id), (await state.get_data())["operation_id"], amount=amount)
        except ValueError as e: await message.answer(str(e), reply_markup=finance_menu()); await state.clear(); return
    await state.clear(); await message.answer("Операция изменена, остаток пересчитан.", reply_markup=finance_menu())

@router.callback_query(lambda c: c.data == "fin:summary")
async def summaries(callback: CallbackQuery):
    today = date.today(); start = today - timedelta(days=30)
    async with SessionLocal() as session: data = await summary(session, await user_id_for(session, callback.from_user.id), start, today)
    balances = "\n".join(f"• {a.name}: {a.balance:.2f} ₽" for a in data["accounts"])
    await callback.message.answer(f"Сводка за 30 дней\nДоходы: {data['income']:.2f} ₽\nРасходы: {data['expense']:.2f} ₽\nРазница: {data['difference']:.2f} ₽\n\nОстатки:\n{balances}", reply_markup=finance_menu()); await callback.answer()

@router.callback_query(lambda c: c.data == "fin:csv")
async def csv_export(callback: CallbackQuery):
    async with SessionLocal() as session: content = await export_csv(session, await user_id_for(session, callback.from_user.id))
    await callback.message.answer_document(BufferedInputFile(content.encode("utf-8-sig"), filename="operations.csv"), caption="Выгрузка операций", reply_markup=finance_menu()); await callback.answer()

@router.callback_query(lambda c: c.data == "fin:transfer")
async def transfer_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(TransferForm.amount); await callback.message.answer("Введите сумму перевода:", reply_markup=cancel_menu()); await callback.answer()

@router.message(TransferForm.amount)
async def transfer_amount(message: Message, state: FSMContext):
    try: amount = parse_money(message.text or "")
    except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    await state.update_data(amount=str(amount)); await state.set_state(TransferForm.source)
    async with SessionLocal() as session: accounts = await list_accounts(session, await user_id_for(session, message.from_user.id))
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await message.answer("Откуда перевести?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a.name, callback_data=f"fin:from:{a.id}")] for a in accounts] + [[InlineKeyboardButton(text="Отмена", callback_data="cancel")]]))

@router.callback_query(lambda c: c.data.startswith("fin:from:"), TransferForm.source)
async def transfer_source(callback: CallbackQuery, state: FSMContext):
    await state.update_data(source=int(callback.data.split(":")[-1])); await state.set_state(TransferForm.target)
    async with SessionLocal() as session: accounts = await list_accounts(session, await user_id_for(session, callback.from_user.id))
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.answer("Куда перевести?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=a.name, callback_data=f"fin:to:{a.id}")] for a in accounts] + [[InlineKeyboardButton(text="Отмена", callback_data="cancel")]])); await callback.answer()

@router.callback_query(lambda c: c.data.startswith("fin:to:"), TransferForm.target)
async def transfer_target(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    async with SessionLocal() as session:
        try: await transfer(session, await user_id_for(session, callback.from_user.id), data["source"], int(callback.data.split(":")[-1]), Decimal(data["amount"]), date.today())
        except ValueError as e: await callback.message.answer(str(e), reply_markup=finance_menu()); await state.clear(); await callback.answer(); return
    await state.clear(); await callback.message.answer("Перевод выполнен. В доходы и расходы он не попал.", reply_markup=finance_menu()); await callback.answer()

@router.callback_query(lambda c: c.data == "fin:categories")
async def categories(callback: CallbackQuery):
    async with SessionLocal() as session: cats = await list_categories(session, await user_id_for(session, callback.from_user.id))
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.answer("Категории\n" + "\n".join(f"• {x.name} ({'доход' if x.kind == 'income' else 'расход'})" for x in cats), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Новая категория", callback_data="fin:category:new")]] + finance_menu().inline_keyboard)); await callback.answer()

@router.callback_query(lambda c: c.data == "fin:category:new")
async def category_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(CategoryForm.kind)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.answer("Тип категории:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Доход", callback_data="fin:kind:income"), InlineKeyboardButton(text="Расход", callback_data="fin:kind:expense")], [InlineKeyboardButton(text="Отмена", callback_data="cancel")]])); await callback.answer()

@router.callback_query(lambda c: c.data.startswith("fin:kind:"), CategoryForm.kind)
async def category_kind(callback: CallbackQuery, state: FSMContext):
    await state.update_data(kind=callback.data.split(":")[-1]); await state.set_state(CategoryForm.name); await callback.message.answer("Название категории:", reply_markup=cancel_menu()); await callback.answer()

@router.message(CategoryForm.name)
async def category_finish(message: Message, state: FSMContext):
    async with SessionLocal() as session:
        try: await add_category(session, await user_id_for(session, message.from_user.id), message.text or "", (await state.get_data())["kind"])
        except ValueError as e: await message.answer(str(e), reply_markup=finance_menu()); await state.clear(); return
    await state.clear(); await message.answer("Категория создана.", reply_markup=finance_menu())

@router.callback_query(lambda c: c.data == "fin:limits")
async def limits_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(BudgetForm.amount); await callback.message.answer("Введите месячный лимит расходов:", reply_markup=cancel_menu()); await callback.answer()

@router.message(BudgetForm.amount)
async def limit_amount(message: Message, state: FSMContext):
    try: amount = parse_money(message.text or "")
    except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    await state.update_data(amount=str(amount)); await state.set_state(BudgetForm.category)
    async with SessionLocal() as session: cats = await list_categories(session, await user_id_for(session, message.from_user.id), "expense")
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await message.answer("Для какой категории лимит?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c.name, callback_data=f"fin:limitcat:{c.id}")] for c in cats] + [[InlineKeyboardButton(text="Отмена", callback_data="cancel")]]))

@router.callback_query(lambda c: c.data.startswith("fin:limitcat:"), BudgetForm.category)
async def limit_category(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    async with SessionLocal() as session:
        try: await set_budget_limit(session, await user_id_for(session, callback.from_user.id), int(callback.data.split(":")[-1]), date.today(), Decimal(data["amount"])); rows = await budget_status(session, await user_id_for(session, callback.from_user.id), date.today())
        except ValueError as e: await callback.message.answer(str(e), reply_markup=finance_menu()); await state.clear(); await callback.answer(); return
    await state.clear(); await callback.message.answer("Лимит сохранён. Предупреждение появится после 80%.", reply_markup=finance_menu()); await callback.answer()

@router.callback_query(lambda c: c.data == "fin:goals")
async def goals(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session: items = await list_goals(session, await user_id_for(session, callback.from_user.id))
    text = "Цели накоплений\n" + ("\n".join(f"• {x.name}: {x.current_amount:.2f} / {x.target_amount:.2f} ₽ ({(x.current_amount / x.target_amount * 100):.0f}%)" for x in items) or "Пока нет целей.")
    await callback.message.answer(text + "\n\nЧтобы создать цель, нажмите «Создать цель».", reply_markup=__import__('aiogram').types.InlineKeyboardMarkup(inline_keyboard=[[__import__('aiogram').types.InlineKeyboardButton(text="Создать цель", callback_data="fin:goal:create")], *finance_menu().inline_keyboard])); await callback.answer()

@router.callback_query(lambda c: c.data == "fin:goal:create")
async def goal_start(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(GoalForm.name); await callback.message.answer("Название цели:", reply_markup=cancel_menu()); await callback.answer()

@router.message(GoalForm.name)
async def goal_name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip()); await state.set_state(GoalForm.target); await message.answer("Сумма цели:", reply_markup=cancel_menu())

@router.message(GoalForm.target)
async def goal_finish(message: Message, state: FSMContext):
    try: target = parse_money(message.text or "")
    except ValueError as e: await message.answer(str(e), reply_markup=cancel_menu()); return
    async with SessionLocal() as session:
        try: await create_goal(session, await user_id_for(session, message.from_user.id), (await state.get_data())["name"], target)
        except ValueError as e: await message.answer(str(e), reply_markup=finance_menu()); await state.clear(); return
    await state.clear(); await message.answer("Цель создана.", reply_markup=finance_menu())
