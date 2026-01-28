import os
import json
import logging
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

# Python 3.9+ (aiogram3 обычно на 3.10+)
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Tashkent")
except Exception:
    TZ = None

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден. Добавь переменную окружения BOT_TOKEN.")

# ✅ Твой Telegram ID администратора (куда будут приходить заказы)
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
if ADMIN_ID == 0:
    logging.warning("⚠️ ADMIN_ID не задан. Заказы не будут отправляться админу.")

# ✅ Твой рабочий GitHub Pages (можно переопределить переменной окружения WEBAPP_URL)
WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "https://tahirovdd-lang.github.io/lora-flower-bot/?v=1"
)

# Файл для счётчика заказов (дата + счетчик)
COUNTER_FILE = Path(os.getenv("ORDER_COUNTER_FILE", "order_counter.json"))

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


# ---------- Helpers ----------
def now_local() -> datetime:
    return datetime.now(TZ) if TZ else datetime.now()

def money_fmt(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        n = 0
    return f"{n:,}".replace(",", " ")

def safe_str(x) -> str:
    return "—" if x is None or str(x).strip() == "" else str(x).strip()

def get_next_order_id(prefix: str = "FL") -> str:
    """
    Генерирует ID вида: FL-20260129-0007 (дата + счетчик).
    Счётчик хранится в order_counter.json (если хостинг даёт запись на диск).
    """
    today = now_local().strftime("%Y%m%d")
    data = {"date": today, "counter": 0}

    try:
        if COUNTER_FILE.exists():
            data = json.loads(COUNTER_FILE.read_text(encoding="utf-8") or "{}") or data
    except Exception:
        data = {"date": today, "counter": 0}

    if data.get("date") != today:
        data = {"date": today, "counter": 0}

    data["counter"] = int(data.get("counter", 0)) + 1

    try:
        COUNTER_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Если нельзя писать в файл — всё равно отдадим ID (но счетчик сбросится после перезапуска)
        pass

    return f"{prefix}-{today}-{data['counter']:04d}"

def normalize_delivery_type(payload: dict) -> str:
    """
    Возвращает 'Доставка' / 'Самовывоз'
    Поддерживает разные ключи из WebApp:
    - customer.deliveryType / customer.delivery_type / customer.delivery
    - deliveryType / delivery_type
    """
    customer = payload.get("customer", {}) or {}
    val = (
        customer.get("deliveryType")
        or customer.get("delivery_type")
        or customer.get("delivery")
        or payload.get("deliveryType")
        or payload.get("delivery_type")
    )
    s = (str(val).strip().lower() if val is not None else "")
    if s in {"pickup", "самовывоз", "self", "selfpickup", "сам"}:
        return "Самовывоз"
    if s in {"delivery", "доставка", "courier", "курьер"}:
        return "Доставка"
    # если адрес указан — вероятнее доставка
    if customer.get("address"):
        return "Доставка"
    return "Самовывоз"

def normalize_payment_method(payload: dict) -> str:
    """
    Возвращает 'Наличными' / 'Click' / 'Картой' (если пришло)
    Поддерживает разные ключи:
    - customer.paymentMethod / paymentMethod / payment_method
    """
    customer = payload.get("customer", {}) or {}
    val = (
        customer.get("paymentMethod")
        or customer.get("payment_method")
        or payload.get("paymentMethod")
        or payload.get("payment_method")
        or payload.get("pay")
    )
    s = (str(val).strip().lower() if val is not None else "")

    if s in {"cash", "нал", "наличные", "налом"}:
        return "Наличными"
    if s in {"click", "клик"}:
        return "Click"
    if s in {"card", "картой", "карта", "uzcard", "humo"}:
        return "Картой"
    # если не пришло — по умолчанию
    return "Наличными"

def format_order_for_admin(message: types.Message, order: dict) -> str:
    user = message.from_user
    tg_username = f"@{user.username}" if user and user.username else "—"
    tg_id = user.id if user else "—"
    tg_name = " ".join([p for p in [getattr(user, "first_name", ""), getattr(user, "last_name", "")] if p]).strip() or "—"

    customer = order.get("customer", {}) or {}
    items = order.get("items", []) or []
    total = order.get("total", 0)
    currency = safe_str(order.get("currency", "UZS"))
    order_id = safe_str(order.get("orderId"))
    created_at = safe_str(order.get("createdAt"))

    delivery_type = normalize_delivery_type(order)
    payment = normalize_payment_method(order)

    lines = []
    lines.append("🌸 <b>Новый заказ FLORA</b>")
    lines.append(f"🧾 <b>Номер заказа:</b> <code>{order_id}</code>")
    lines.append(f"⏱ <b>Дата/время:</b> {created_at}")
    lines.append("")
    lines.append("👤 <b>Клиент (Telegram):</b>")
    lines.append(f"• Ник: <b>{tg_username}</b>")
    lines.append(f"• Имя: <b>{safe_str(tg_name)}</b>")
    lines.append(f"• TG ID: <code>{tg_id}</code>")
    lines.append("")
    lines.append("📞 <b>Контакты/детали:</b>")
    lines.append(f"• Телефон: <b>{safe_str(customer.get('phone'))}</b>")
    lines.append(f"• Формат: <b>{delivery_type}</b>")
    if delivery_type == "Доставка":
        lines.append(f"• Адрес: {safe_str(customer.get('address'))}")
    if customer.get("date") or customer.get("time"):
        dt = f"{safe_str(customer.get('date'))} {safe_str(customer.get('time'))}".strip()
        lines.append(f"• Когда: {dt}")
    if customer.get("comment"):
        lines.append(f"• Комментарий: {safe_str(customer.get('comment'))}")

    lines.append("")
    lines.append("💳 <b>Оплата:</b>")
    lines.append(f"• Способ: <b>{payment}</b>")
    lines.append("")
    lines.append("🛍 <b>Заказ:</b>")

    if not items:
        lines.append("• (пусто)")
    else:
        for it in items:
            title = safe_str(it.get("title", "Товар"))
            qty = it.get("qty", 1)
            price = it.get("price", 0)
            lines.append(f"• {title} × {qty} — <b>{money_fmt(price)}</b> {currency}")

    lines.append("")
    lines.append(f"💰 <b>Сумма:</b> <b>{money_fmt(total)}</b> {currency}")

    return "\n".join(lines)

def client_confirm_text(order: dict) -> str:
    order_id = safe_str(order.get("orderId"))
    total = order.get("total", 0)
    currency = safe_str(order.get("currency", "UZS"))
    payment = normalize_payment_method(order)

    if payment == "Click":
        pay_note = "Оплата: <b>Click</b> (мы отправим реквизиты/ссылку для оплаты после подтверждения)."
    elif payment == "Картой":
        pay_note = "Оплата: <b>Картой</b> (оплата при получении или по ссылке — уточним при подтверждении)."
    else:
        pay_note = "Оплата: <b>Наличными</b> (оплата при получении)."

    return (
        "✅ <b>Ваш заказ принят!</b>\n"
        f"🧾 Номер: <code>{order_id}</code>\n"
        f"💰 Сумма: <b>{money_fmt(total)}</b> {currency}\n"
        f"{pay_note}\n\n"
        "Мы свяжемся с вами для подтверждения."
    )


# ---------- Keyboards / Handlers ----------
def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💐 Открыть каталог", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="🎁 Собрать букет"), KeyboardButton(text="🔥 Акции")],
            [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="📞 Связаться")]
        ],
        resize_keyboard=True
    )

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
        "4) Дата/время\n"
        "5) Доставка или самовывоз\n"
        "6) Адрес (если доставка)\n\n"
        "Флорист свяжется с вами для подтверждения."
    )
    await message.answer(txt)

@dp.message(F.text == "🔥 Акции")
async def promo(message: types.Message):
    await message.answer("🔥 Акции пока не настроены. Скоро добавим!\nОткройте каталог: 💐 Открыть каталог")

@dp.message(F.text == "📦 Мои заказы")
async def my_orders(message: types.Message):
    await message.answer("📦 История заказов будет добавлена в следующей версии. Сейчас заказы оформляются через каталог.")

@dp.message(F.text == "📞 Связаться")
async def contact(message: types.Message):
    await message.answer(
        "📞 <b>Связаться с FLORA</b>\n\n"
        "Напишите сюда в чат — мы ответим.\n"
        "Контакты/адрес можно добавить сюда (позже вставим)."
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

    # Ожидаем заказы как {"type":"order", ...}
    if payload.get("type") != "order":
        await message.answer("✅ Данные получены.")
        return

    # Подставим orderId если WebApp не прислал
    if not payload.get("orderId"):
        payload["orderId"] = get_next_order_id("FL")

    # Подставим createdAt если нет
    if not payload.get("createdAt"):
        payload["createdAt"] = now_local().strftime("%Y-%m-%d %H:%M:%S")

    # Пользователю — подтверждение с правильным способом оплаты
    await message.answer(client_confirm_text(payload), reply_markup=main_keyboard())

    # Админу — полный заказ (ник, телефон, номер, дата+счетчик, доставка/самовывоз, оплата, сумма, состав)
    if ADMIN_ID != 0:
        text = format_order_for_admin(message, payload)
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
