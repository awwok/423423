from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from app.config import settings
from app.db.session import SessionLocal
from app.keyboards.common import main_menu, finance_menu, simulator_menu
from app.models import Bank
from app.services.financial import get_or_create_user

router = Router()

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        await get_or_create_user(session, message.from_user.id, settings.default_timezone, display_name=message.from_user.full_name)
    await message.answer("Добро пожаловать! Выберите раздел:", reply_markup=main_menu())

@router.message(lambda message: message.text == "Финансы")
async def finances(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Личные финансы\nВыберите действие:", reply_markup=finance_menu())

@router.message(lambda message: message.text == "Симулятор")
async def simulator(message: Message, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, settings.default_timezone)
        bank = await session.scalar(select(Bank).where(Bank.user_id == user.id))
    await message.answer("Экономический симулятор\nВсе деньги здесь виртуальные.", reply_markup=simulator_menu(bool(bank)))

@router.callback_query(lambda c: c.data == "main")
async def main_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Главное меню", reply_markup=main_menu())
    await callback.answer()

@router.callback_query(lambda c: c.data == "cancel")
async def cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear(); await callback.message.answer("Ввод отменён.", reply_markup=main_menu()); await callback.answer()
