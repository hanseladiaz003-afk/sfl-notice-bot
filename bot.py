"""
SFL Notice Bot - Sunflower Land Telegram Bot
Replica de @sfl_notice_bot con notificaciones y consulta de lands
"""

import asyncio
import logging
import json
import aiohttp
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BOT_TOKEN = "8916752238:AAGXKRhpXTWeFI-HfxeMCUdwviPldfMGymk"   # ← Reemplaza con tu token de @BotFather

SFL_API_BASE   = "https://api.sunflower-land.com/community/farms"
SFL_WORLD_API  = "https://sfl.world/api"          # precios & land boosts
SFL_PRICES_API = "https://sfl.world/api/prices"   # precio SFL/MATIC
SFL_P2P_API    = "https://sfl.world/api/exchange"  # mercado P2P

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── HELPERS API ─────────────────────────────────────────────────────────────

async def fetch_json(url: str) -> dict | None:
    """Hace GET a una URL y retorna JSON o None si falla."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
    return None


async def get_farm_data(farm_id: str) -> dict | None:
    url = f"{SFL_API_BASE}/{farm_id}"
    return await fetch_json(url)


async def get_prices() -> dict | None:
    return await fetch_json(SFL_PRICES_API)


async def get_exchange() -> dict | None:
    return await fetch_json(SFL_P2P_API)

# ─── COMANDOS ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start — menú principal."""
    keyboard = [
        [InlineKeyboardButton("🌾 Consultar Land", callback_data="menu_land"),
         InlineKeyboardButton("💰 Precios SFL",    callback_data="menu_prices")],
        [InlineKeyboardButton("🔔 Mis Alertas",    callback_data="menu_alerts"),
         InlineKeyboardButton("📊 Mercado P2P",    callback_data="menu_exchange")],
        [InlineKeyboardButton("❓ Ayuda",           callback_data="menu_help")],
    ]
    text = (
        "🌻 *SFL Notice Bot* — Sunflower Land\n\n"
        "Tu asistente para recibir alertas y consultar información "
        "de Sunflower Land directamente en Telegram.\n\n"
        "Elige una opción:"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Comandos disponibles:*\n\n"
        "/start — Menú principal\n"
        "/land <farm\\_id> — Info de tu land\n"
        "/precio — Precio actual de SFL\n"
        "/mercado — Precios del mercado P2P\n"
        "/alertas — Ver mis alertas activas\n"
        "/alerta\\_entrega — Alerta de entrega NPC\n"
        "/alerta\\_precio <valor> — Alerta cuando SFL llegue a ese precio\n"
        "/help — Esta ayuda\n\n"
        "🌐 Datos obtenidos de [sfl.world](https://sfl.world)"
    )
    msg = update.message or update.callback_query.message
    await msg.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def land_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consulta info de una farm por ID."""
    msg = update.message
    if not context.args:
        await msg.reply_text(
            "🌾 Ingresa tu Farm ID:\n`/land 12345`", parse_mode="Markdown"
        )
        return
    farm_id = context.args[0].strip()
    await msg.reply_text(f"🔍 Buscando land #{farm_id}...")
    await _show_land(msg, farm_id)


async def _show_land(msg, farm_id: str):
    """Lógica compartida para mostrar datos de una land."""
    data = await get_farm_data(farm_id)
    if not data:
        await msg.reply_text(
            f"❌ No se encontró la land #{farm_id}.\n"
            "Verifica el ID en [sfl.world](https://sfl.world/land)",
            parse_mode="Markdown"
        )
        return

    # Extraer datos relevantes
    state = data.get("state", {})
    inventory = state.get("inventory", {})
    balance   = state.get("balance", "0")
    username  = state.get("username", "Sin nombre")
    bumpkin   = state.get("bumpkin", {})
    experience = bumpkin.get("experience", 0)

    # Calcular nivel aproximado del bumpkin
    level = _xp_to_level(experience)

    # Recursos principales
    resources = {
        "🌻 SFL":      _safe_float(balance),
        "🌽 Maíz":     _safe_float(inventory.get("Corn", 0)),
        "🥕 Zanahorias": _safe_float(inventory.get("Carrot", 0)),
        "🎃 Calabaza": _safe_float(inventory.get("Pumpkin", 0)),
        "🪵 Madera":   _safe_float(inventory.get("Wood", 0)),
        "⛏️ Piedra":   _safe_float(inventory.get("Stone", 0)),
        "🪙 Monedas":  _safe_float(inventory.get("Coin", 0)),
    }
    res_text = "\n".join(f"  {k}: `{v:,.2f}`" for k, v in resources.items() if v > 0)

    text = (
        f"🌾 *Land #{farm_id}*\n"
        f"👤 {username}  |  Nivel {level}\n"
        f"✨ XP: `{experience:,.0f}`\n\n"
        f"📦 *Inventario:*\n{res_text or '  (vacío)'}\n\n"
        f"🔗 [Ver en sfl.world](https://sfl.world/land?id={farm_id})"
    )
    await msg.reply_text(text, parse_mode="Markdown", disable_web_page_preview=False)


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _xp_to_level(xp: float) -> int:
    """Aproximación de nivel por XP de Bumpkin."""
    thresholds = [0,10,20,50,100,200,375,600,875,1200,1600,2100,
                  2700,3400,4200,5100,6100,7200,8400,9700,11100]
    level = 1
    for i, t in enumerate(thresholds):
        if xp >= t:
            level = i + 1
    return level


async def precio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Precio actual de SFL."""
    msg = update.message or update.callback_query.message
    await msg.reply_text("💰 Obteniendo precio...")
    data = await get_prices()
    if not data:
        await msg.reply_text("❌ No se pudo obtener el precio ahora. Intenta más tarde.")
        return

    sfl   = data.get("sfl",  {})
    matic = data.get("matic", {})

    text = (
        "💰 *Precios actuales*\n\n"
        f"🌻 SFL:  `${_safe_float(sfl.get('usd', 0)):.6f}` USD\n"
        f"📐 MATIC: `${_safe_float(matic.get('usd', 0)):.4f}` USD\n\n"
        f"🕐 Actualizado: {_now_utc()}"
    )
    await msg.reply_text(text, parse_mode="Markdown")


async def mercado_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Precios del mercado P2P (floor prices)."""
    msg = update.message or update.callback_query.message
    await msg.reply_text("📊 Consultando mercado P2P...")
    data = await get_exchange()
    if not data:
        await msg.reply_text("❌ No se pudo obtener el mercado ahora.")
        return

    p2p   = data.get("p2p", {})
    seq   = data.get("seq", {})
    items = list(p2p.items())[:10]   # top 10

    if not items:
        await msg.reply_text("📊 No hay datos de mercado disponibles.")
        return

    lines = [f"  `{name}`: {_safe_float(price):.4f} SFL" for name, price in items]
    text = (
        "📊 *Mercado P2P — Floor prices*\n\n"
        + "\n".join(lines) +
        f"\n\n🕐 {_now_utc()}\n"
        "🔗 [Ver mercado completo](https://sfl.world)"
    )
    await msg.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M UTC")

# ─── ALERTAS ─────────────────────────────────────────────────────────────────

async def alertas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ver alertas activas del usuario."""
    user_id = str(update.effective_user.id)
    alerts  = context.bot_data.get("alerts", {}).get(user_id, {})

    if not alerts:
        text = (
            "🔔 *Mis Alertas*\n\n"
            "No tienes alertas activas.\n\n"
            "Puedes crear:\n"
            "`/alerta_entrega` — Recordatorio de entrega NPC diaria\n"
            "`/alerta_precio 0.05` — Alerta cuando SFL llegue a ese precio"
        )
    else:
        lines = []
        if alerts.get("delivery"):
            lines.append("✅ Entrega NPC diaria (00:00 UTC)")
        if alerts.get("price"):
            lines.append(f"✅ Precio SFL ≥ `{alerts['price']}` USD")
        text = "🔔 *Mis Alertas activas:*\n\n" + "\n".join(lines)

    await update.message.reply_text(text, parse_mode="Markdown")


async def alerta_entrega_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activa alerta de entrega NPC diaria."""
    user_id = str(update.effective_user.id)
    if "alerts" not in context.bot_data:
        context.bot_data["alerts"] = {}
    if user_id not in context.bot_data["alerts"]:
        context.bot_data["alerts"][user_id] = {}

    context.bot_data["alerts"][user_id]["delivery"] = True
    await update.message.reply_text(
        "✅ *Alerta de entrega NPC activada*\n"
        "Te notificaré cada día a las 00:00 UTC cuando se reinicien las entregas.",
        parse_mode="Markdown"
    )


async def alerta_precio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activa alerta de precio SFL."""
    if not context.args:
        await update.message.reply_text(
            "Ejemplo: `/alerta_precio 0.05`\n"
            "Te aviso cuando SFL llegue a ese precio en USD.",
            parse_mode="Markdown"
        )
        return
    try:
        target = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Precio inválido. Ejemplo: `/alerta_precio 0.05`",
                                        parse_mode="Markdown")
        return

    user_id = str(update.effective_user.id)
    if "alerts" not in context.bot_data:
        context.bot_data["alerts"] = {}
    if user_id not in context.bot_data["alerts"]:
        context.bot_data["alerts"][user_id] = {}

    context.bot_data["alerts"][user_id]["price"] = target
    await update.message.reply_text(
        f"✅ *Alerta de precio activada*\n"
        f"Te notificaré cuando SFL llegue a `${target}` USD.",
        parse_mode="Markdown"
    )

# ─── JOBS (tareas periódicas) ─────────────────────────────────────────────────

async def job_npc_delivery(context: ContextTypes.DEFAULT_TYPE):
    """Notificación diaria de reset de entregas NPC (00:00 UTC)."""
    alerts = context.bot_data.get("alerts", {})
    for user_id, prefs in alerts.items():
        if prefs.get("delivery"):
            try:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=(
                        "🌻 *¡Entregas NPC reiniciadas!*\n\n"
                        "Ya puedes hacer tus entregas diarias en Sunflower Land.\n"
                        "Las entregas se reinician a las 00:00 UTC.\n\n"
                        "🔗 [Jugar ahora](https://sunflower-land.com/play)"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error notificando a {user_id}: {e}")


async def job_price_alert(context: ContextTypes.DEFAULT_TYPE):
    """Verifica precios cada 15 min y notifica si se alcanza el objetivo."""
    alerts = context.bot_data.get("alerts", {})
    if not any(v.get("price") for v in alerts.values()):
        return  # nadie tiene alerta de precio

    data = await get_prices()
    if not data:
        return
    current = _safe_float(data.get("sfl", {}).get("usd", 0))

    for user_id, prefs in alerts.items():
        target = prefs.get("price")
        if target and current >= target:
            try:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=(
                        f"🚀 *¡Alerta de precio SFL!*\n\n"
                        f"SFL ha alcanzado `${current:.6f}` USD\n"
                        f"Tu objetivo era `${target}` USD\n\n"
                        f"🔗 [Ver en sfl.world](https://sfl.world)"
                    ),
                    parse_mode="Markdown"
                )
                # Desactiva la alerta tras dispararse
                context.bot_data["alerts"][user_id]["price"] = None
            except Exception as e:
                logger.error(f"Error notificando precio a {user_id}: {e}")

# ─── CALLBACKS (botones inline) ───────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_land":
        await query.message.reply_text(
            "🌾 Envía tu Farm ID:\n`/land 12345`", parse_mode="Markdown"
        )
    elif data == "menu_prices":
        await precio_command(update, context)
    elif data == "menu_exchange":
        await mercado_command(update, context)
    elif data == "menu_alerts":
        text = (
            "🔔 *Alertas disponibles:*\n\n"
            "`/alerta_entrega` — Reset diario de entregas NPC\n"
            "`/alerta_precio 0.05` — Precio SFL objetivo\n"
            "`/alertas` — Ver mis alertas activas"
        )
        await query.message.reply_text(text, parse_mode="Markdown")
    elif data == "menu_help":
        await help_command(update, context)


# ─── MENSAJE DE TEXTO (farm ID directo) ───────────────────────────────────────

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Si el usuario envía solo un número, lo trata como Farm ID."""
    text = update.message.text.strip()
    if text.isdigit() and len(text) <= 9:
        await update.message.reply_text(f"🔍 Buscando land #{text}...")
        await _show_land(update.message, text)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start",          start))
    app.add_handler(CommandHandler("help",           help_command))
    app.add_handler(CommandHandler("land",           land_command))
    app.add_handler(CommandHandler("precio",         precio_command))
    app.add_handler(CommandHandler("mercado",        mercado_command))
    app.add_handler(CommandHandler("alertas",        alertas_command))
    app.add_handler(CommandHandler("alerta_entrega", alerta_entrega_command))
    app.add_handler(CommandHandler("alerta_precio",  alerta_precio_command))

    # Callbacks de botones
    app.add_handler(CallbackQueryHandler(button_handler))

    # Texto libre (farm ID numérico)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Jobs periódicos
    jq = app.job_queue
    # Notificación NPC: todos los días a las 00:00 UTC
    jq.run_daily(job_npc_delivery, time=datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).time())
    # Verificar precios cada 15 minutos
    jq.run_repeating(job_price_alert, interval=900, first=60)

    logger.info("🌻 SFL Notice Bot iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
