"""
SFL Notice Bot - Sunflower Land Telegram Bot
Usa la API Key oficial del juego (Settings > Avanzado > Clave API)
"""

import os
import logging
import aiohttp
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8916752238:AAGXKRhpXTWeFI-HfxeMCUdwviPldfMGymk")  # ← Token de @BotFather

# Configuración permanente del usuario (sobrevive a reinicios/redeploys)
# Configura estos valores en Railway → Variables, NO aquí en el código
DEFAULT_FARM_ID  = os.environ.get("SFL_FARM_ID", "")
DEFAULT_API_KEY  = os.environ.get("SFL_API_KEY", "")
DEFAULT_TELEGRAM_USER_ID = os.environ.get("SFL_TELEGRAM_USER_ID", "")  # tu ID de Telegram

SFL_API          = "https://api.sunflower-land.com/community/farms"
SFL_PRICES_API   = "https://api.coingecko.com/api/v3/simple/price?ids=sunflower-land&vs_currencies=usd"
MATIC_PRICES_API = "https://api.coingecko.com/api/v3/simple/price?ids=matic-network&vs_currencies=usd"
SFL_EXCHANGE_API = "https://api.sunflower-land.com/community/trades"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Tiempos de regeneración (segundos) ───────────────────────────────────────
REGEN = {
    "trees":     2  * 3600,
    "stones":    4  * 3600,
    "iron":      8  * 3600,
    "gold":      24 * 3600,
    "crimstone": 3  * 24 * 3600,
    "sunstone":  3  * 24 * 3600,
    "obsidian":  3  * 24 * 3600,
    "oil":       16 * 3600,
    "chickens":  24 * 3600,
    "barn":      24 * 3600,
    "fruits":    14 * 3600,
    "compost":   6  * 3600,
}

ALERT_NAMES = {
    "trees":      "🌳 Árboles",
    "stones":     "⛏️ Piedras",
    "iron":       "🔩 Hierro",
    "gold":       "🥇 Oro",
    "crimstone":  "💎 Crimstone",
    "sunstone":   "🪨 Sunstone",
    "obsidian":   "🖤 Obsidiana",
    "oil":        "🛢️ Petróleo",
    "crops":      "🌾 Cultivos",
    "fruits":     "🍎 Frutas",
    "compost":    "🌿 Compost",
    "trade":      "🏪 Comercio",
    "chickens":   "🐔 Gallinero",
    "barn":       "🌾 Granero",
    "checklist":  "✅ Verificación",
    "auction":    "🏛️ Subastas",
    "giftgiver":  "🎁 Gift Giver",
    "loveisland": "🏝️ Love Island",
    "cooking":    "🍳 Cocina",
    "delivery":   "📦 Entregas NPC",
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M UTC")

def safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

def fmt_time(secs: float) -> str:
    if secs <= 0:
        return "¡Listo! ✅"
    h, m = int(secs // 3600), int((secs % 3600) // 60)
    return f"{h}h {m}m" if h > 0 else f"{m}m"

def xp_to_level(xp: float) -> int:
    # Fórmula verificada: cada nivel n requiere n*875 XP
    # XP 1,239,703 = nivel 53 ✅
    total = 0
    for lvl in range(1, 500):
        total += lvl * 875
        if total > xp:
            return lvl
    return 1

def get_user(context, user_id: str) -> dict:
    if "users" not in context.bot_data:
        context.bot_data["users"] = {}
    if user_id not in context.bot_data["users"]:
        # Si este es el usuario configurado en Railway, precargar todo automáticamente
        is_default_user = DEFAULT_TELEGRAM_USER_ID and user_id == DEFAULT_TELEGRAM_USER_ID
        if is_default_user and DEFAULT_FARM_ID and DEFAULT_API_KEY:
            context.bot_data["users"][user_id] = {
                "farm_id": DEFAULT_FARM_ID,
                "api_key": DEFAULT_API_KEY,
                **{k: True for k in ALERT_NAMES},  # todas activas por defecto
                "last_notified": {}
            }
        else:
            context.bot_data["users"][user_id] = {
                "farm_id": None,
                "api_key": None,
                **{k: False for k in ALERT_NAMES},
                "last_notified": {}
            }
    return context.bot_data["users"][user_id]

async def fetch_farm(farm_id: str, api_key: str) -> dict | None:
    """Consulta la farm usando la API Key oficial del juego."""
    try:
        headers = {"x-api-key": api_key}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(f"{SFL_API}/{farm_id}", headers=headers) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    # La API devuelve {farm: {...}, id, nft_id, ...}
                    # Normalizamos para que siempre devuelva el estado de la farm
                    if "farm" in data:
                        return data["farm"]
                    return data
                else:
                    text = await r.text()
                    logger.error(f"Error API {r.status}: {text}")
    except Exception as e:
        logger.error(f"Error fetch farm: {e}")
    return None

async def fetch_json(url: str) -> dict | None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(url) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
    except Exception as e:
        logger.error(f"Error fetch: {e}")
    return None

# ─── TECLADOS ─────────────────────────────────────────────────────────────────

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌾 Mi Land",      callback_data="do_land"),
         InlineKeyboardButton("💰 Precio SFL",   callback_data="do_precio")],
        [InlineKeyboardButton("🔔 Alertas",      callback_data="do_alertas"),
         InlineKeyboardButton("📊 Mercado P2P",  callback_data="do_mercado")],
        [InlineKeyboardButton("⏱️ Timers",       callback_data="do_timers"),
         InlineKeyboardButton("❓ Ayuda",         callback_data="do_help")],
    ])

def alerts_keyboard(user: dict) -> InlineKeyboardMarkup:
    keys    = list(ALERT_NAMES.keys())
    buttons = []
    for i in range(0, len(keys), 2):
        row = []
        for key in keys[i:i+2]:
            icon  = "🟢" if user.get(key) else "🔴"
            label = ALERT_NAMES[key]
            row.append(InlineKeyboardButton(f"{icon} {label}", callback_data=f"tog_{key}"))
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("✅ Activar TODAS",    callback_data="all_on"),
        InlineKeyboardButton("❌ Desactivar todas", callback_data="all_off"),
    ])
    buttons.append([InlineKeyboardButton("🔙 Menú", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

# ─── COMANDOS ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌻 *SFL Notice Bot* — Sunflower Land\n\n"
        "Para conectar tu farm necesitas dos cosas:\n\n"
        "1️⃣ Tu *Farm ID* (número corto del NFT)\n"
        "2️⃣ Tu *API Key* del juego\n\n"
        "Usa este comando:\n"
        "`/setup 259942 sfl.MTk1MDA1...`\n\n"
        "_(Farm ID seguido de tu API Key)_",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "📖 *Comandos:*\n\n"
        "`/setup 259942 sfl.MTk1...` — Configurar farm y API Key\n"
        "`/land` — Ver tu land\n"
        "`/timers` — Tiempos de recursos\n"
        "`/alertas` — Gestionar alertas\n"
        "`/precio` — Precio SFL y MATIC\n"
        "`/mercado` — Mercado P2P\n"
        "`/miperfil` — Ver tu configuración\n\n"
        "🔑 *¿Dónde está tu API Key?*\n"
        "Sunflower Land → ⚙️ → Avanzado → Clave API",
        parse_mode="Markdown"
    )

async def setup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configura Farm ID y API Key en un solo comando."""
    user_id = str(update.effective_user.id)

    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Uso: `/setup FARM_ID API_KEY`\n\n"
            "Ejemplo:\n`/setup 259942 sfl.MTk1MDA1...`\n\n"
            "🔑 API Key: ⚙️ → Avanzado → Clave API",
            parse_mode="Markdown"
        )
        return

    farm_id = context.args[0].strip()
    api_key = context.args[1].strip()

    if not farm_id.isdigit():
        await update.message.reply_text("❌ El Farm ID debe ser un número. Ejemplo: `259942`", parse_mode="Markdown")
        return

    msg = await update.message.reply_text("🔍 Verificando tu farm con la API Key...")

    data = await fetch_farm(farm_id, api_key)
    if not data:
        await msg.edit_text(
            "❌ No se pudo conectar con tu farm.\n\n"
            "Verifica que:\n"
            "• El Farm ID sea correcto (`259942`)\n"
            "• La API Key esté completa\n"
            "• Estés dentro del juego cuando la copiaste\n\n"
            "Intenta de nuevo con `/setup`",
            parse_mode="Markdown"
        )
        return

    # Guardar configuración
    user = get_user(context, user_id)
    user["farm_id"] = farm_id
    user["api_key"] = api_key

    state = data
    username = state.get("username", "Sin nombre")
    level    = xp_to_level(safe_float(state.get("bumpkin", {}).get("experience", 0)))
    balance  = safe_float(state.get("balance", 0))

    await msg.edit_text(
        f"✅ *¡Farm conectada exitosamente!*\n\n"
        f"🌾 Farm ID: `{farm_id}`\n"
        f"👤 {username} — Nivel {level}\n"
        f"🌻 Balance: `{balance:,.2f}` SFL\n\n"
        f"🔔 Activa tus alertas con `/alertas`\n"
        f"⏱️ Ver tiempos con `/timers`",
        parse_mode="Markdown"
    )

async def miperfil_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user    = get_user(context, user_id)
    farm_id = user.get("farm_id", "No configurado")
    api_key = user.get("api_key")
    api_status = "✅ API Key activa" if api_key else "❌ Sin API Key"
    activas = [ALERT_NAMES[k] for k in ALERT_NAMES if user.get(k)]

    await update.message.reply_text(
        f"👤 *Mi perfil SFL*\n\n"
        f"🌾 Farm ID: `{farm_id}`\n"
        f"🔑 {api_status}\n\n"
        f"🔔 Alertas activas ({len(activas)}):\n" +
        ("\n".join(f"  {a}" for a in activas) if activas else "  Ninguna — usa /alertas"),
        parse_mode="Markdown"
    )

async def land_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user    = get_user(context, user_id)
    msg     = update.message

    if not user.get("farm_id") or not user.get("api_key"):
        await msg.reply_text(
            "❌ Configura tu farm primero:\n`/setup 259942 sfl.MTk1...`",
            parse_mode="Markdown"
        )
        return

    await msg.reply_text("🔍 Consultando tu land...")
    data = await fetch_farm(user["farm_id"], user["api_key"])
    if not data:
        await msg.reply_text("❌ No se pudo obtener la land. Verifica tu API Key con `/setup`.")
        return

    state = data
    inv      = state.get("inventory", {})
    username = state.get("username", "Sin nombre")
    level    = xp_to_level(safe_float(state.get("bumpkin", {}).get("experience", 0)))
    res = {
        "🌻 SFL":       safe_float(state.get("balance", 0)),
        "🪙 Monedas":   safe_float(state.get("coins", 0)),
        "🌸 FLOWER":    safe_float(state.get("flower", 0)),
        "💎 Gemas":     safe_float(state.get("gems", 0)),
        "🪵 Madera":    safe_float(inv.get("Wood", 0)),
        "⛏️ Piedra":    safe_float(inv.get("Stone", 0)),
        "🔩 Hierro":    safe_float(inv.get("Iron", 0)),
        "🥇 Oro":       safe_float(inv.get("Gold", 0)),
        "🌽 Maíz":      safe_float(inv.get("Corn", 0)),
        "🥕 Zanahoria": safe_float(inv.get("Carrot", 0)),
    }
    lines = "\n".join(f"  {k}: `{v:,.2f}`" for k, v in res.items() if v > 0)
    await msg.reply_text(
        f"🌾 *Land #{user['farm_id']}*\n"
        f"👤 {username} — Nivel {level}\n\n"
        f"📦 *Inventario:*\n{lines or '  (vacío)'}",
        parse_mode="Markdown"
    )

async def timers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user    = get_user(context, user_id)

    if not user.get("farm_id") or not user.get("api_key"):
        await update.message.reply_text(
            "❌ Configura tu farm primero:\n`/setup 259942 sfl.MTk1...`",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text("⏱️ Calculando tiempos...")
    data = await fetch_farm(user["farm_id"], user["api_key"])
    if not data:
        await update.message.reply_text("❌ No se pudo obtener la land.")
        return

    state = data
    n     = now_ts()
    lines = [f"⏱️ *Timers — Land #{user['farm_id']}*\n"]

    def nearest(items, ts_path, regen_key):
        times = []
        for v in items.values():
            if not isinstance(v, dict): continue
            obj = v
            for p in ts_path.split("."):
                obj = obj.get(p, {}) if isinstance(obj, dict) else None
                if obj is None: break
            if obj:
                times.append(float(obj)/1000 + REGEN[regen_key] - n)
        return min(times) if times else None

    checks = [
        ("trees",        "wood.choppedAt",   "trees",     "🌳 Árboles"),
        ("stones",       "stone.minedAt",     "stones",    "⛏️ Piedras"),
        ("iron",         "stone.minedAt",     "iron",      "🔩 Hierro"),
        ("gold",         "stone.minedAt",     "gold",      "🥇 Oro"),
        ("crimstones",   "stone.minedAt",     "crimstone", "💎 Crimstone"),
        ("sunstones",    "stone.minedAt",     "sunstone",  "🪨 Sunstone"),
        ("fruitPatches", "fruit.harvestedAt", "fruits",    "🍎 Frutas"),
    ]
    for state_key, path, regen_key, label in checks:
        t = nearest(state.get(state_key, {}), path, regen_key)
        if t is not None:
            lines.append(f"{label}: {fmt_time(t)}")

    crops = state.get("crops", {})
    crop_times = []
    crop_ready = 0
    for c in crops.values():
        if not isinstance(c, dict): continue
        crop_info = c.get("crop", {})
        # Solo contar si tiene nombre (hay cultivo plantado)
        if not crop_info.get("name"):
            continue
        planted_at = crop_info.get("plantedAt")
        harvest_seconds = crop_info.get("harvestSeconds", 60)
        if planted_at:
            remaining = float(planted_at)/1000 + float(harvest_seconds) - n
            if remaining <= 0:
                crop_ready += 1
            else:
                crop_times.append(remaining)
    if crop_ready > 0:
        lines.append(f"🌾 Cultivos: ¡{crop_ready} listo(s)! ✅")
    elif crop_times:
        lines.append(f"🌾 Cultivos (próximo): {fmt_time(min(crop_times))}")

    chs = state.get("chickens", {})
    ch_times = [float(c["fedAt"])/1000 + REGEN["chickens"] - n
                for c in chs.values()
                if isinstance(c, dict) and c.get("fedAt")]
    if ch_times:
        lines.append(f"🐔 Gallinero: {fmt_time(min(ch_times))}")

    if len(lines) == 1:
        lines.append("No se encontraron recursos activos.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def precio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message or update.callback_query.message
    sfl_data   = await fetch_json(SFL_PRICES_API)
    matic_data = await fetch_json(MATIC_PRICES_API)
    if not sfl_data:
        await msg.reply_text("❌ No se pudo obtener el precio.")
        return
    sfl_price   = safe_float(sfl_data.get("sunflower-land", {}).get("usd", 0))
    matic_price = safe_float((matic_data or {}).get("matic-network", {}).get("usd", 0))
    await msg.reply_text(
        f"💰 *Precios actuales*\n\n"
        f"🌻 SFL:   `${sfl_price:.6f}` USD\n"
        f"📐 MATIC: `${matic_price:.4f}` USD\n\n"
        f"🕐 {now_utc()}\n"
        f"📊 Fuente: CoinGecko",
        parse_mode="Markdown"
    )

async def mercado_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message or update.callback_query.message
    data = await fetch_json(SFL_EXCHANGE_API)
    if not data:
        await msg.reply_text("❌ No se pudo obtener el mercado.")
        return
    items = list(data.get("p2p", {}).items())[:12]
    if not items:
        await msg.reply_text("No hay datos disponibles.")
        return
    lines = [f"  `{nm}`: {safe_float(p):.4f} SFL" for nm, p in items]
    await msg.reply_text(
        "📊 *Mercado P2P*\n\n" + "\n".join(lines) +
        f"\n\n🕐 {now_utc()}\n🔗 [sfl.world](https://sfl.world)",
        parse_mode="Markdown", disable_web_page_preview=True
    )

async def alertas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user    = get_user(context, user_id)
    farm_id = user.get("farm_id", "No configurado")
    api_status = "✅" if user.get("api_key") else "❌"
    await update.message.reply_text(
        f"🔔 *Gestionar Alertas*\n"
        f"Farm: `{farm_id}` | API Key: {api_status}\n\n"
        "Toca 🟢/🔴 para activar o desactivar:",
        parse_mode="Markdown",
        reply_markup=alerts_keyboard(user)
    )

# ─── CALLBACKS ────────────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    d       = query.data
    user_id = str(update.effective_user.id)
    user    = get_user(context, user_id)

    def alerts_header():
        farm_id    = user.get("farm_id", "No configurado")
        api_status = "✅" if user.get("api_key") else "❌"
        return f"🔔 *Gestionar Alertas*\nFarm: `{farm_id}` | API Key: {api_status}\n\nToca 🟢/🔴:"

    if d.startswith("tog_"):
        key = d[4:]
        if key in user:
            user[key] = not user[key]
        await query.edit_message_text(alerts_header(), parse_mode="Markdown",
                                      reply_markup=alerts_keyboard(user))
    elif d == "all_on":
        for k in ALERT_NAMES: user[k] = True
        await query.edit_message_text(alerts_header(), parse_mode="Markdown",
                                      reply_markup=alerts_keyboard(user))
    elif d == "all_off":
        for k in ALERT_NAMES: user[k] = False
        await query.edit_message_text(alerts_header(), parse_mode="Markdown",
                                      reply_markup=alerts_keyboard(user))
    elif d == "main_menu":
        await query.edit_message_text("🌻 *SFL Notice Bot*\n\nElige una opción:",
                                      parse_mode="Markdown", reply_markup=main_keyboard())
    elif d == "do_land":
        await query.message.reply_text("Usa `/land` para ver tu land.", parse_mode="Markdown")
    elif d == "do_precio":
        await precio_cmd(update, context)
    elif d == "do_mercado":
        await mercado_cmd(update, context)
    elif d == "do_alertas":
        await query.edit_message_text(alerts_header(), parse_mode="Markdown",
                                      reply_markup=alerts_keyboard(user))
    elif d == "do_timers":
        await query.message.reply_text("Usa `/timers` para ver los tiempos.", parse_mode="Markdown")
    elif d == "do_help":
        await help_cmd(update, context)

# ─── JOB: VERIFICAR RECURSOS CADA 10 MIN ─────────────────────────────────────

async def job_check(context: ContextTypes.DEFAULT_TYPE):
    users = context.bot_data.get("users", {})
    n     = now_ts()

    for user_id, user in users.items():
        farm_id = user.get("farm_id")
        api_key = user.get("api_key")
        if not farm_id or not api_key:
            continue
        if not any(user.get(k) for k in ALERT_NAMES):
            continue

        try:
            data = await fetch_farm(farm_id, api_key)
            if not data:
                continue

            state = data
            last  = user.setdefault("last_notified", {})
            msgs  = []

            def check_nodes(state_key, ts_path, regen_key, emoji, label, cooldown=3600):
                nodes = state.get(state_key, {})
                ready = 0
                for v in nodes.values():
                    if not isinstance(v, dict): continue
                    obj = v
                    for p in ts_path.split("."):
                        obj = obj.get(p, {}) if isinstance(obj, dict) else None
                        if obj is None: break
                    if obj and n >= float(obj)/1000 + REGEN.get(regen_key, 0):
                        ready += 1
                if ready > 0 and n - last.get(regen_key, 0) > cooldown:
                    msgs.append(f"{emoji} *¡{ready} {label} listo(s)!*")
                    last[regen_key] = n

            if user.get("trees"):      check_nodes("trees",        "wood.choppedAt",   "trees",     "🌳", "árbol(es) para talar")
            if user.get("stones"):     check_nodes("stones",       "stone.minedAt",    "stones",    "⛏️", "piedra(s) para minar")
            if user.get("iron"):       check_nodes("iron",         "stone.minedAt",    "iron",      "🔩", "nodo(s) de hierro")
            if user.get("gold"):       check_nodes("gold",         "stone.minedAt",    "gold",      "🥇", "nodo(s) de oro")
            if user.get("crimstone"):  check_nodes("crimstones",   "stone.minedAt",    "crimstone", "💎", "Crimstone")
            if user.get("sunstone"):   check_nodes("sunstones",    "stone.minedAt",    "sunstone",  "🪨", "Sunstone")
            if user.get("obsidian"):   check_nodes("obsidian",     "stone.minedAt",    "obsidian",  "🖤", "Obsidiana")
            if user.get("oil"):        check_nodes("oilReserves",  "oil.drilledAt",    "oil",       "🛢️", "reserva(s) de petróleo")
            if user.get("fruits"):     check_nodes("fruitPatches", "fruit.harvestedAt","fruits",    "🍎", "árbol(es) de fruta")

            if user.get("crops"):
                crops = state.get("crops", {})
                ready = 0
                for c in crops.values():
                    if not isinstance(c, dict): continue
                    crop_info = c.get("crop", {})
                    if not crop_info.get("name"): continue
                    planted_at = crop_info.get("plantedAt")
                    harvest_seconds = crop_info.get("harvestSeconds", 60)
                    if planted_at and n >= float(planted_at)/1000 + float(harvest_seconds):
                        ready += 1
                if ready > 0 and n - last.get("crops", 0) > 600:
                    msgs.append(f"🌾 *¡{ready} cultivo(s) listo(s) para cosechar!*")
                    last["crops"] = n

            if user.get("chickens"):
                # chickens pueden estar en henHouse o chickens
                chickens = state.get("henHouse", {}).get("chickens", state.get("chickens", {}))
                eggs = hungry = sick = 0
                for ch in chickens.values():
                    if not isinstance(ch, dict): continue
                    if ch.get("fedAt") and n >= float(ch["fedAt"])/1000 + REGEN["chickens"]: eggs += 1
                    if ch.get("state") == "hungry":  hungry += 1
                    if ch.get("state") == "sick":    sick += 1
                if eggs   > 0 and n - last.get("chickens",  0) > 3600:
                    msgs.append(f"🐔 *¡{eggs} gallina(s) con huevos listos!*");    last["chickens"] = n
                if hungry > 0 and n - last.get("ch_hungry", 0) > 3600:
                    msgs.append(f"🍗 *¡{hungry} gallina(s) con hambre!*");         last["ch_hungry"] = n
                if sick   > 0 and n - last.get("ch_sick",   0) > 3600:
                    msgs.append(f"🤒 *¡{sick} gallina(s) enferma(s)!*");           last["ch_sick"] = n

            if user.get("barn"):
                animals = state.get("barn", {}).get("animals", {})
                ready = sum(1 for a in animals.values()
                            if isinstance(a, dict) and a.get("awakeAt")
                            and n >= float(a["awakeAt"])/1000)
                if ready > 0 and n - last.get("barn", 0) > 3600:
                    msgs.append(f"🌾 *¡{ready} animal(es) del granero listo(s)!*"); last["barn"] = n

            if user.get("compost"):
                comp     = state.get("buildings", {}).get("Compost Bin", [{}])[0]
                ready_at = comp.get("producing", {}).get("readyAt", 0)
                if ready_at and n >= float(ready_at)/1000 and n - last.get("compost", 0) > 3600:
                    msgs.append("🌿 *¡Tu compost está listo!*"); last["compost"] = n

            if user.get("cooking"):
                for bname, instances in state.get("buildings", {}).items():
                    if any(x in bname for x in ["Kitchen","Fire Pit","Deli","Bakery","Smoothie Shack"]):
                        for inst in (instances if isinstance(instances, list) else []):
                            if not isinstance(inst, dict): continue
                            crafting_list = inst.get("crafting", [])
                            if isinstance(crafting_list, dict):
                                crafting_list = [crafting_list]
                            if not isinstance(crafting_list, list):
                                crafting_list = []
                            for item in crafting_list:
                                if not isinstance(item, dict): continue
                                ra = item.get("readyAt", 0)
                                item_name = item.get("name", "plato")
                                # Usamos el readyAt exacto como parte de la clave: así,
                                # mientras no recojas el plato (readyAt no cambia),
                                # solo se notifica UNA vez. Si vuelves a cocinar algo
                                # nuevo, el readyAt cambia y se notifica de nuevo.
                                cooldown_key = f"cooking_{bname}_{item_name}_{ra}"
                                if ra and n >= float(ra)/1000 and cooldown_key not in last:
                                    msgs.append(f"🍳 *¡{item_name} listo en {bname}!*")
                                    last[cooldown_key] = n

            if user.get("delivery"):
                orders = state.get("delivery", {}).get("orders", [])
                if any(o.get("completedAt") for o in orders) and n - last.get("delivery", 0) > 82800:
                    msgs.append("📦 *¡Entregas NPC disponibles!*"); last["delivery"] = n

            if user.get("giftgiver"):
                streak_at = state.get("dailyRewards", {}).get("streakAt", 0)
                if streak_at and n >= float(streak_at)/1000 + 86400 and n - last.get("giftgiver", 0) > 82800:
                    msgs.append("🎁 *¡Recompensa diaria del Gift Giver disponible!*"); last["giftgiver"] = n

            if user.get("loveisland"):
                if state.get("loveIsland", {}).get("available") and n - last.get("loveisland", 0) > 86400:
                    msgs.append("🏝️ *¡Love Island disponible!*"); last["loveisland"] = n

            if user.get("auction"):
                end_at = state.get("auctioneer", {}).get("endAt", 0)
                if end_at and n >= float(end_at)/1000 and n - last.get("auction", 0) > 3600:
                    msgs.append("🏛️ *¡Tu subasta terminó!*"); last["auction"] = n

            if user.get("checklist"):
                chores = state.get("chores", {})
                total  = len(chores)
                done   = sum(1 for c in chores.values() if isinstance(c, dict) and c.get("completedAt"))
                if total > 0 and done == total and n - last.get("checklist", 0) > 82800:
                    msgs.append(f"✅ *¡Completaste todos tus quehaceres ({done}/{total})!*"); last["checklist"] = n

            if user.get("trade"):
                listings = state.get("trades", {}).get("listings", {})
                sold = [l for l in listings.values() if isinstance(l, dict) and l.get("boughtAt")]
                if sold and n - last.get("trade", 0) > 3600:
                    msgs.append(f"🏪 *¡Vendiste {len(sold)} artículo(s)!*"); last["trade"] = n

            user["last_notified"] = last

            if msgs:
                try:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=f"🌻 *SFL Notice — Land #{farm_id}*\n\n" + "\n".join(msgs),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error notificando a {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error procesando alertas para usuario {user_id}: {e}")
            continue

# ─── TEXTO LIBRE ──────────────────────────────────────────────────────────────

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) <= 7:
        await update.message.reply_text(
            f"Para usar el Farm ID `{text}` con tu API Key:\n"
            f"`/setup {text} sfl.TuApiKeyAqui`",
            parse_mode="Markdown"
        )

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Precargar configuración permanente al iniciar (para que las alertas
    # funcionen incluso si el usuario no manda ningún mensaje tras un redeploy)
    if DEFAULT_TELEGRAM_USER_ID and DEFAULT_FARM_ID and DEFAULT_API_KEY:
        app.bot_data["users"] = {
            DEFAULT_TELEGRAM_USER_ID: {
                "farm_id": DEFAULT_FARM_ID,
                "api_key": DEFAULT_API_KEY,
                **{k: True for k in ALERT_NAMES},
                "last_notified": {}
            }
        }
        logger.info(f"✅ Configuración precargada para usuario {DEFAULT_TELEGRAM_USER_ID}")

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CommandHandler("setup",     setup_cmd))
    app.add_handler(CommandHandler("miperfil",  miperfil_cmd))
    app.add_handler(CommandHandler("land",      land_cmd))
    app.add_handler(CommandHandler("timers",    timers_cmd))
    app.add_handler(CommandHandler("precio",    precio_cmd))
    app.add_handler(CommandHandler("mercado",   mercado_cmd))
    app.add_handler(CommandHandler("alertas",   alertas_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.job_queue.run_repeating(job_check, interval=120, first=20)

    logger.info("🌻 SFL Notice Bot con API Key oficial iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
