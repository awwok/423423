from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Финансы"), KeyboardButton(text="Симулятор")]], resize_keyboard=True, is_persistent=True)

def finance_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Доход", callback_data="fin:add:income"), InlineKeyboardButton(text="➖ Расход", callback_data="fin:add:expense")],
        [InlineKeyboardButton(text="Счета", callback_data="fin:accounts"), InlineKeyboardButton(text="История", callback_data="fin:history")],
        [InlineKeyboardButton(text="Сводка", callback_data="fin:summary"), InlineKeyboardButton(text="CSV", callback_data="fin:csv")],
        [InlineKeyboardButton(text="Перевод", callback_data="fin:transfer"), InlineKeyboardButton(text="Категории", callback_data="fin:categories")],
        [InlineKeyboardButton(text="Лимиты", callback_data="fin:limits"), InlineKeyboardButton(text="Цели", callback_data="fin:goals")],
        [InlineKeyboardButton(text="Главное меню", callback_data="main")],
    ])

def cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="cancel")]])

def simulator_menu(has_bank: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_bank:
        rows = [[InlineKeyboardButton(text="🏦 Обзор банка", callback_data="sim:dashboard")], [InlineKeyboardButton(text="Выдать кредит", callback_data="sim:loan"), InlineKeyboardButton(text="Вклад", callback_data="sim:deposit")], [InlineKeyboardButton(text="Закрыть период", callback_data="sim:period")]]
    else:
        rows = [[InlineKeyboardButton(text="Создать банк", callback_data="sim:create")]]
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
