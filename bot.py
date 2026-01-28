import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from aiogram.filters.command import CommandObject

# Python 3.9+
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Tashkent")
except Exception:
    TZ = None

logging.basicConfig(level=logging.INFO)

# -------------------- CONFIG --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден. Добавь переменную окружения BOT_TOKEN.")

# ✅ BotHost может не давать задать ADMIN_ID в ENV — поэтому делаем надёжно:
# 1) пробуем ENV ADMIN_ID
# 2) если не получилось — используем захардкоженный ID
ADMIN_ID_ENV = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID_HARDCODE = 6013591658  # ✅ твой ID админа
ADMIN_ID = int(ADMIN_ID_ENV) if ADMIN_ID_ENV.isdigit() else ADMIN_ID_HARDCODE

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://tahirovdd-lang.github.io/lora-flower-bot/?v=1")

COUNTER_FILE = Path(os.getenv("ORDER_COUNTER_FILE", "order_counter.json"))
ORDERS_FILE = Path(os.getenv("ORDERS_FILE", "orders.json"))

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


# -------------------- HELPERS --------------------
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
    """ID: FL-YYYYMMDD-0007 (дата + счетчик)."""
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
        pass

    return f"{prefix}-{today}-{data['counter']:04d}"

def normalize_delivery_type(payload: dict) -> str:
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
    if customer.get("address"):
        return "Доставка"
    return "Самовывоз"

def normalize_payment_method(payload: dict) -> str:
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
    return "Наличными"

def status_human(s: str) -> str:
    s = (s or "").strip().lower()
    mapping = {
        "accepted": "Принят",
        "created": "Принят",
        "assembling": "Собирается",
        "courier": "Курьер выехал",
        "delivered": "Доставлено",
        "canceled": "Отменён",
        "принят": "Принят",
        "собирается": "Собирается",
        "курьер_выехал": "Курьер выехал",
        "доставлено": "Доставлено",
        "отменен": "Отменён",
        "отменён": "Отменён",
    }
    return mapping.get(s, s.capitalize() if s else "Принят")

def safe_read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8") or "null") or default
    except Exception:
        pass
    return default

def safe_write_json(path: Path, data: Any) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def store_order(order: Dict[str, Any]) -> None:
    db = safe_read_json(ORDERS_FILE, default=[])
    if not isinstance(db, list):
        db = []
    db.append(order)
    safe_write_json(ORDERS_FILE, db)

def update_order_status(order_id: str, new_status: str) -> Dict[str, Any] | None:
    db = safe_read_json(ORDERS_FILE, default=[])
    if not isinstance(db, list):
        return None
    found = None
    for o in db:
        if str(o.get("orderId")) == str(order_id):
            o["status"] = new_status
            o["statusUpdatedAt"] = now_local().strftime("%Y-%m-%d %H:%M:%S")
            found = o
            break
    if found:
        safe_write_json(ORDERS_FILE, db)
    return found

def get_user_orders(tg_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    db = safe_read_json(ORDERS_FILE, default=[])
    if not isinstance(db, list):
        return []
    user_orders = [o for o in db if int(o.get("tgId", 0) or 0) == int(tg_id)]
    user_orders.sort(key=lambda x: safe_str(x.get("createdAt")), reverse=True)
    return user_orders[:limit]

def get_last_orders(limit: int = 10) -> List[Dict[str, Any]]:
    db = safe_read_json(ORDERS_FILE, default=[])
    if not isinstance(db, list):
        return []
    db.sort(key=lambda x: safe_str(x.get("createdAt")), reverse=True)
    return db[:limit]

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
    status = status_human(order.get("status") or "accepted")

    delivery_type = normalize_delivery_type(order)
    payment = normalize_payment_method(order)

    delivery_fee = int(order.get("deliveryFee", 0) or 0)
    zone = safe_str(order.get("zone", customer.get("zone")))
    slot = safe_str(order.get("deliverySlot", customer.get("deliverySlot")))
    urgent = bool(order.get("urgent") or customer.get("urgent"))

    lines = []
    lines.append("🌸 <b>Новый заказ FLORA</b>")
    lines.append(f"🧾 <b>Номер:</b> <code>{order_id}</code>")
    lines.append(f"⏱ <b>Время:</b> {created_at}")
    lines.append(f"📍 <b>Статус:</b> <b>{status}</b>")
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
        if zone != "—":
            lines.append(f"• Зона: <b>{zone}</b>")
    if slot != "—":
        lines.append(f"• Слот: <b>{slot}</b>")
    if urgent:
        lines.append("• Срочно: <b>Да (60–90 мин)</b>")

    if customer.get("date") or customer.get("time"):
        dt = f"{safe_str(customer.get('date'))} {safe_str(customer.get('time'))}".strip()
        lines.append(f"• Когда: {dt}")
    if customer.get("recipient"):
        lines.append(f"• Получатель: {safe_str(customer.get('recipient'))}")
    if customer.get("cardText"):
        lines.append(f"• Открытка: {safe_str(customer.get('cardText'))}")
    if customer.get("wrap"):
        lines.append(f"• Упаковка: {safe_str(customer.get('wrap'))}")
    if customer.get("comment"):
        lines.append(f"• Комментарий: {safe_str(customer.get('comment'))}")

    lines.append("")
    lines.append("💳 <b>Оплата:</b>")
    lines.append(f"• Способ: <b>{payment}</b>")
    lines.append("")
    lines.append("🛍 <b>Состав:</b>")

    if not items:
        lines.append("• (пусто)")
    else:
        for it in items:
            title = safe_str(it.get("title", "Товар"))
            qty = it.get("qty", 1)
            price = it.get("price", 0)
            lines.append(f"• {title} × {qty} — <b>{money_fmt(price)}</b> {currency}")

    lines.append("")
    if delivery_fee > 0:
        lines.append(f"🚚 Доставка: <b>{money_fmt(delivery_fee)}</b> {currency}")
    lines.append(f"💰 <b>Итого:</b> <b>{money_fmt(total)}</b> {currency}")

    return "\n".join(lines)

def client_confirm_text(order: dict) -> str:
    order_id = safe_str(order.get("orderId"))
    total = order.get("total", 0)
    currency = safe_str(order.get("currency", "UZS"))
    payment = normalize_payment_method(order)
    status = status_human(order.get("status") or "accepted")

    if payment == "Click":
        pay_note = "Оплата: <b>Click</b> (мы отправим ссылку/реквизиты после подтверждения)."
    elif payment == "Картой":
        pay_note = "Оплата: <b>Картой</b> (при получении или по ссылке — уточним при подтверждении)."
    else:
        pay_note = "Оплата: <b>Наличными</b> (при получении)."

    return (
        "✅ <b>Ваш заказ принят!</b>\n"
        f"🧾 Номер: <code>{order_id}</code>\n"
        f"📍 Статус: <b>{status}</b>\n"
        f"💰 Сумма: <b>{money_fmt(total)}</b> {currency}\n"
        f"{pay_note}\n\n"
        "Мы свяжемся с вами для подтверждения."
    )


# -------------------- UI --------------------
def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💐 Открыть каталог", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="🎁 Конструктор букета"), KeyboardButton(text="🔥 Акции")],
            [KeyboardButton(text="📦 Мои заказы"), KeyboardButton(text="📞 Связаться")]
        ],
        resize_keyboard=True
    )

# -------------------- HANDLERS --------------------
@dp.message(CommandStart())
async def start(message: types.Message):
    text = (
        "🌸 <b>Добро пожаловать в FLORA Samarkand</b>\n"
        "Свежие цветы • Авторские букеты • Премиум сервис\n\n"
        "Нажмите кнопку ниже, чтобы открыть каталог 👇"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(F.text == "🎁 Конструктор букета")
async def custom_bouquet(message: types.Message):
    txt = (
        "🎁 <b>Конструктор букета</b>\n\n"
        "Откройте каталог и нажмите «🎁 Конструктор букета» внутри приложения.\n"
        "Там будет мастер-подбор: повод → цвета → настроение → бюджет → упаковка → открытка → доставка."
    )
    await message.answer(txt, reply_markup=main_keyboard())

@dp.message(F.text == "🔥 Акции")
async def promo(message: types.Message):
    await message.answer(
        "🔥 Акции появятся в ближайшем обновлении.\nОткройте каталог: 💐 Открыть каталог",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "📦 Мои заказы")
async def my_orders(message: types.Message):
    orders = get_user_orders(message.from_user.id, limit=10)
    if not orders:
        await message.answer("📦 У вас пока нет заказов. Откройте каталог и оформите первый 🌸", reply_markup=main_keyboard())
        return

    lines = ["📦 <b>Ваши последние заказы:</b>"]
    for o in orders[:10]:
        oid = safe_str(o.get("orderId"))
        total = money_fmt(int(o.get("total", 0) or 0))
        cur = safe_str(o.get("currency", "UZS"))
        st = status_human(o.get("status") or "accepted")
        created = safe_str(o.get("createdAt"))
        lines.append(f"• <code>{oid}</code> — <b>{total}</b> {cur} — <b>{st}</b> ({created})")

    lines.append("\nЕсли нужно — напишите сюда, мы поможем 🙌")
    await message.answer("\n".join(lines), reply_markup=main_keyboard())

@dp.message(F.text == "📞 Связаться")
async def contact(message: types.Message):
    await message.answer(
        "📞 <b>Связаться с FLORA</b>\n\n"
        "Напишите сюда в чат — мы ответим.\n"
        "Также можете оформить заказ через каталог 👇",
        reply_markup=main_keyboard()
    )

# --- Admin: last orders
@dp.message(Command("orders"))
async def admin_orders(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    last = get_last_orders(limit=10)
    if not last:
        await message.answer("Пока нет заказов.")
        return
    lines = ["🗂 <b>Последние заказы:</b>"]
    for o in last:
        oid = safe_str(o.get("orderId"))
        total = money_fmt(int(o.get("total", 0) or 0))
        cur = safe_str(o.get("currency", "UZS"))
        st = status_human(o.get("status") or "accepted")
        lines.append(f"• <code>{oid}</code> — <b>{total}</b> {cur} — <b>{st}</b>")
    lines.append("\nКоманда смены статуса:\n<code>/setstatus FL-20260129-0007 courier</code>")
    await message.answer("\n".join(lines))

# --- Admin: set status + notify client
@dp.message(Command("setstatus"))
async def admin_setstatus(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return

    args = (command.args or "").strip()
    if not args:
        await message.answer(
            "Использование:\n<code>/setstatus FL-20260129-0007 courier</code>\n"
            "Статусы: accepted/assembling/courier/delivered/canceled"
        )
        return

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Нужно 2 аргумента:\n<code>/setstatus ORDER_ID STATUS</code>")
        return

    order_id, new_status = parts[0].strip(), parts[1].strip()
    updated = update_order_status(order_id, new_status)
    if not updated:
        await message.answer("Не нашёл такой заказ в базе (orders.json).")
        return

    human = status_human(new_status)
    await message.answer(f"✅ Статус обновлён: <code>{order_id}</code> → <b>{human}</b>")

    tg_id = int(updated.get("tgId", 0) or 0)
    if tg_id:
        try:
            await bot.send_message(tg_id, f"📦 Заказ <code>{order_id}</code>\nСтатус: <b>{human}</b>")
        except Exception as e:
            logging.exception("Не удалось уведомить клиента: %s", e)

# --- WebApp data
@dp.message(F.web_app_data)
async def on_webapp_data(message: types.Message):
    raw = message.web_app_data.data

    try:
        payload = json.loads(raw)
    except Exception:
        await message.answer("❌ Не удалось прочитать заказ. Попробуйте ещё раз.", reply_markup=main_keyboard())
        return

    if payload.get("type") != "order":
        await message.answer("✅ Данные получены.", reply_markup=main_keyboard())
        return

    # orderId если WebApp не прислал
    if not payload.get("orderId"):
        payload["orderId"] = get_next_order_id("FL")

    # createdAt если нет
    if not payload.get("createdAt"):
        payload["createdAt"] = now_local().strftime("%Y-%m-%d %H:%M:%S")

    # статус по умолчанию
    if not payload.get("status"):
        payload["status"] = "accepted"

    # привязка к Telegram
    u = message.from_user
    payload["tgId"] = u.id if u else 0
    payload["tgUsername"] = f"@{u.username}" if u and u.username else ""
    payload["tgName"] = " ".join([p for p in [getattr(u, "first_name", ""), getattr(u, "last_name", "")] if p]).strip()

    # сохранить
    store_order(payload)

    # клиенту
    await message.answer(client_confirm_text(payload), reply_markup=main_keyboard())

    # админу
    text = format_order_for_admin(message, payload)
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception as e:
        logging.exception("Не удалось отправить админу: %s", e)

async def main():
    logging.info("🚀 FLORA bot started")
    logging.info("Admin ID: %s", ADMIN_ID)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
