import os
import json
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден. Добавь переменную окружения BOT_TOKEN.")

# ВАЖНО: Укажи свой Telegram ID администратора (куда будут приходить заказы)
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
if ADMIN_ID == 0:
    logging.warning("⚠️ ADMIN_ID не задан. Заказы не будут отправляться админу.")

# Ссылка на GitHub Pages WebApp (добавь ?v=1 чтобы не кешировалось)
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://USERNAME.github.io/flora-webapp/?v=1")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💐 Открыть каталог", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="🎁 Собрать букет"), KeyboardButton(text="🔥 Акции")],
            [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="📞 Связаться")]
        ],
        resize_keyboard=True
    )

def format_order(order: dict) -> str:
    # order structure from WebApp:
    # {
    #  "type":"order",
    #  "orderId":"FL-....",
    #  "createdAt":"ISO",
    #  "customer": {"name":"","phone":"","address":"","date":"","time":"","comment":""},
    #  "items":[{"id":"rose_25","title":"...","qty":1,"price":350000}],
    #  "total": 350000,
    #  "currency":"UZS"
    # }
    customer = order.get("customer", {})
    items = order.get("items", [])
    total = order.get("total", 0)
    currency = order.get("currency", "UZS")
    order_id = order.get("orderId", "—")
    created_at = order.get("createdAt", "")

    lines = []
    lines.append(f"🌸 <b>Новый заказ FLORA</b>")
    lines.append(f"🧾 <b>Order ID:</b> <code>{order_id}</code>")
    if created_at:
        lines.append(f"⏱ <b>Время:</b> {created_at}")

    lines.append("")
    lines.append("👤 <b>Клиент:</b>")
    lines.append(f"• Имя: <b>{customer.get('name','—')}</b>")
    lines.append(f"• Телефон: <b>{customer.get('phone','—')}</b>")
    lines.append(f"• Адрес: {customer.get('address','—')}")
    if customer.get("date") or customer.get("time"):
        lines.append(f"• Доставка: {customer.get('date','—')} {customer.get('time','')}".strip())
    if customer.get("comment"):
        lines.append(f"• Комментарий: {customer.get('comment')}")

    lines.append("")
    lines.append("💐 <b>Состав:</b>")
    if not items:
        lines.append("• (пусто)")
    else:
        for it in items:
            title = it.get("title", "Товар")
            qty = it.get("qty", 1)
            price = it.get("price", 0)
            lines.append(f"• {title} × {qty} — <b>{price:,}</b> {currency}".replace(",", " "))

    lines.append("")
    lines.append(f"💰 <b>Итого:</b> <b>{total:,}</b> {currency}".replace(",", " "))
    return "\n".join(lines)

@dp.message(CommandStart())
async def start(message: types.Message):
    text = (
        "🌸 <b>Добро пожаловать в FLORA Samarkand</b>\n"
        "Свежие цветы • Авторские букеты • Быстрая доставка\n\n"
        "Нажмите кнопку ниже, чтобы открыть каталог 👇"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "🎁 Собрать букет")
async def custom_bouquet(message: types.Message):
    txt = (
        "🎁 <b>Собрать букет</b>\n\n"
        "Напишите одним сообщением:\n"
        "1) Повод (день рождения/любимому/свадьба/корпоратив)\n"
        "2) Любимые цветы/цвета\n"
        "3) Бюджет\n"
        "4) Дата/время доставки\n"
        "5) Адрес доставки\n\n"
        "Флорист свяжется с вами для подтверждения."
    )
    await message.answer(txt)

@dp.message(F.text == "🔥 Акции")
async def акции(message: types.Message):
    await message.answer("🔥 Акции пока не настроены. Скоро добавим!\nОткройте каталог: 💐 Открыть каталог")

@dp.message(F.text == "📦 Мои заказы")
async def my_orders(message: types.Message):
    await message.answer("📦 История заказов будет добавлена в следующей версии. Сейчас заказы оформляются через каталог.")

@dp.message(F.text == "📞 Связаться")
async def contact(message: types.Message):
    await message.answer(
        "📞 <b>Связаться с FLORA</b>\n\n"
        "Напишите сюда в чат — мы ответим.\n"
        "Также можно указать контакты/адрес в этом сообщении (позже вставим)."
    )

# Приём данных из WebApp: message.web_app_data.data
@dp.message(F.web_app_data)
async def on_webapp_data(message: types.Message):
    raw = message.web_app_data.data
    try:
        payload = json.loads(raw)
    except Exception:
        await message.answer("❌ Не удалось прочитать заказ. Попробуйте ещё раз.")
        return

    if payload.get("type") != "order":
        await message.answer("✅ Данные получены.")
        return

    # Подтверждение пользователю
    order_id = payload.get("orderId", "—")
    await message.answer(
        f"✅ <b>Заказ принят!</b>\n"
        f"🧾 Номер: <code>{order_id}</code>\n"
        f"Мы свяжемся с вами для подтверждения."
    )

    # Отправка админу
    if ADMIN_ID != 0:
        text = format_order(payload)
        try:
            await bot.send_message(ADMIN_ID, text)
        except Exception as e:
            logging.exception("Не удалось отправить админу: %s", e)

async def main():
    logging.info("🚀 FLORA bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
