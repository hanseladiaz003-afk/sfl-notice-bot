"""
SFL Notice Bot - Sunflower Land Telegram Bot
Con soporte para farms privadas via JWT token
"""

import logging
import aiohttp
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = "8916752238:AAGXKRhpXTWeFI-HfxeMCUdwviPldfMGymk"  # ← Reemplaza con tu token de @BotFather

SFL_API          = "https://api.sunflower-land.com"
SFL_COMMUNITY    = "https://api.sunflower-land.com/community/farms"
SFL_PRICES_API   = "https://sfl.world/api/prices"
SFL_EXCHANGE_API = "https://sfl.world/api/exchange"

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
    thresholds = [0,10,20,50,100,200,375,600,875,1200,1600,2100,
                  2700,3400,4200,5100,6100,7200,8400,9700,11100]
    lvl = 1
    for i, t in enumerate(thresholds):
        if xp >= t:
            lvl = i + 1
    return lvl

def get_user(context, user_id: str) -> dict:
    """Obtiene o crea el perfil del usuario."""
    if "users" not in context.bot_data:
        context.bot_data["users"] = {}
    if user_id not in context.bot_data["users"]:
        context.bot_data["users"][user_id] = {
            "farm_id": None,
            "jwt": None,
            **{k: False for k in ALERT_NAMES},
            "last_notified": {}
        }
    return context.bot_data["users"][user_id]

async def fetch_public(farm_id: str) -> dict | None:
    """Consulta farm pública (ID corto)."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(f"{SFL_COMMUNITY}/{farm_id}") as r:
                if r.status == 200:
                    return await r.json(content_type=None)
    except Exception as e:
        logger.error(f"Error fetch público: {e}")
    return None

async def fetch_private(jwt: str) -> dict | None:
    """Consulta farm privada usando JWT token."""
    try:
        headers = {
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            # Intentar endpoint de sesión autenticada
            async with s.get(
                f"{SFL_API}/auth/session",
                headers=headers
            ) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
                # Si no funciona, intentar endpoint de farm
                async with s.get(
                    f"{SFL_API}/visit",
                    headers=headers
                ) as r2:
                    if r2.status == 200:
                        return await r2.json(content_type=None)
    except Exception as e:
        logger.error(f"Error fetch privado: {e}")
    return None

async def fetch_farm(user: dict) -> dict | None:
    """Elige automáticamente público o privado según lo que tenga el usuario."""
    jwt     = user.get("jwt")
    farm_id = user.get("farm_id")
    if jwt:
        data = await fetch_private(jwt)
        if data:
            return data
    if farm_id:
        return await fetch_public(farm_id)
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
        "Bienvenido. Para conectar tu farm tienes dos opciones:\n\n"
        "1️⃣ *Farm con ID corto (público):*\n`/setfarm 12345`\n\n"
        "2️⃣ *Farm privada con token JWT:*\n`/settoken eyJhbGci...`\n\n"
        "Usa el comando según tu caso y luego activa tus alertas con `/alertas`",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "📖 *Comandos:*\n\n"
        "`/setfarm 12345` — Farm pública por ID\n"
        "`/settoken eyJ...` — Farm privada con JWT\n"
        "`/land` — Ver tu land\n"
        "`/timers` — Tiempos de recursos\n"
        "`/alertas` — Gestionar alertas\n"
        "`/precio` — Precio SFL y MATIC\n"
        "`/mercado` — Mercado P2P\n"
        "`/miperfil` — Ver tu configuración actual\n\n"
        "🔗 [sfl.world](https://sfl.world)",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

async def setfarm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Ejemplo: `/setfarm 12345`", parse_mode="Markdown")
        return
    farm_id = context.args[0].strip()
    await update.message.reply_text(f"🔍 Verificando land #{farm_id}...")
    data = await fetch_public(farm_id)
    if not data:
        await update.message.reply_text(
            f"❌ Land #{farm_id} no encontrada con la API pública.\n"
            "Si tu farm tiene ID largo, usa `/settoken` en su lugar.",
            parse_mode="Markdown"
        )
        return
    state    = data.get("state", {})
    username = state.get("username", "Sin nombre")
    level    = xp_to_level(safe_float(state.get("bumpkin", {}).get("experience", 0)))
    user     = get_user(context, user_id)
    user["farm_id"] = farm_id
    await update.message.reply_text(
        f"✅ *Land #{farm_id} registrada*\n"
        f"👤 {username} — Nivel {level}\n\n"
        "Activa tus alertas con `/alertas`",
        parse_mode="Markdown"
    )

async def settoken_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra el JWT token para farms privadas."""
    user_id = str(update.effective_user.id)

    # Borrar el mensaje del usuario por seguridad (contiene el token)
    try:
        await update.message.delete()
    except Exception:
        pass

    if not context.args:
        await update.message.reply_text(
            "⚠️ Uso: `/settoken TU_JWT_TOKEN`\n\n"
            "El token es el texto largo que obtuviste de la consola del navegador.\n\n"
            "🔒 Por seguridad, tu mensaje con el token será eliminado automáticamente.",
            parse_mode="Markdown"
        )
        return

    jwt = context.args[0].strip()
    if not jwt.startswith("ey"):
        await update.message.reply_text(
            "❌ Ese no parece un token JWT válido.\n"
            "Debe empezar con `eyJ...`",
            parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text("🔍 Verificando token con Sunflower Land...")

    data = await fetch_private(jwt)
    if not data:
        await msg.edit_text(
            "❌ No se pudo verificar el token.\n\n"
            "Posibles causas:\n"
            "• El token expiró (vuelve a entrar al juego y cópialo de nuevo)\n"
            "• El token está incompleto\n\n"
            "Intenta de nuevo con `/settoken`",
            parse_mode="Markdown"
        )
        return

    # Guardar el token
    user = get_user(context, user_id)
    user["jwt"] = jwt

    # Extraer info de la farm
    state    = data.get("state", data)  # algunas respuestas traen el state directo
    username = state.get("username", "Sin nombre")
    bumpkin  = state.get("bumpkin", {})
    level    = xp_to_level(safe_float(bumpkin.get("experience", 0)))
    balance  = safe_float(state.get("balance", 0))

    await msg.edit_text(
        f"✅ *¡Token registrado exitosamente!*\n\n"
        f"👤 {username} — Nivel {level}\n"
        f"🌻 Balance: `{balance:,.2f}` SFL\n\n"
        f"🔒 Tu token está guardado de forma segura.\n"
        f"Activa tus alertas con `/alertas`",
        parse_mode="Markdown"
    )

async def miperfil_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user    = get_user(context, user_id)
    farm_id = user.get("farm_id", "No configurado")
    jwt     = user.get("jwt")
    jwt_status = "✅ Token JWT activo" if jwt else "❌ Sin token JWT"
    activas = [ALERT_NAMES[k] for k in ALERT_NAMES if user.get(k)]

    await update.message.reply_text(
        f"👤 *Mi perfil SFL*\n\n"
        f"🌾 Farm ID: `{farm_id}`\n"
        f"🔑 {jwt_status}\n\n"
        f"🔔 Alertas activas ({len(activas)}):\n" +
        ("\n".join(f"  {a}" for a in activas) if activas else "  Ninguna"),
        parse_mode="Markdown"
    )

async def land_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user    = get_user(context, user_id)
    msg     = update.message

    if not user.get("jwt") and not user.get("farm_id"):
        await msg.reply_text(
            "❌ No tienes farm configurada.\n"
            "Usa `/setfarm 12345` o `/settoken eyJ...`",
            parse_mode="Markdown"
        )
        return

    await msg.reply_text("🔍 Consultando tu land...")
    data = await fetch_farm(user)
    if not data:
        await msg.reply_text(
            "❌ No se pudo obtener la land.\n"
            "Si usas token JWT, puede haber expirado. Usa `/settoken` para actualizarlo."
        )
        return

    state    = data.get("state", data)
    inv      = state.get("inventory", {})
    username = state.get("username", "Sin nombre")
    level    = xp_to_level(safe_float(state.get("bumpkin", {}).get("experience", 0)))
    res = {
        "🌻 SFL":    safe_float(state.get("balance", 0)),
        "🪵 Madera": safe_float(inv.get("Wood", 0)),
        "⛏️ Piedra": safe_float(inv.get("Stone", 0)),
        "🔩 Hierro": safe_float(inv.get("Iron", 0)),
        "🥇 Oro":    safe_float(inv.get("Gold", 0)),
        "🌽 Maíz":   safe_float(inv.get("Corn", 0)),
        "🥕 Zanahoria": safe_float(inv.get("Carrot", 0)),
        "🪙 Monedas":safe_float(inv.get("Coin", 0)),
    }
    lines = "\n".join(f"  {k}: `{v:,.2f}`" for k, v in res.items() if v > 0)
    farm_id = user.get("farm_id", "privada")
    await msg.reply_text(
        f"🌾 *Land #{farm_id}*\n👤 {username} — Nivel {level}\n\n"
        f"📦 *Inventario:*\n{lines or '  (vacío)'}",
        parse_mode="Markdown"
    )

async def timers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user    = get_user(context, user_id)

    if not user.get("jwt") and not user.get("farm_id"):
        await update.message.reply_text(
            "❌ Usa `/setfarm` o `/settoken` primero.", parse_mode="Markdown"
        )
        return

    await update.message.reply_text("⏱️ Calculando tiempos...")
    data = await fetch_farm(user)
    if not data:
        await update.message.reply_text("❌ No se pudo obtener la land.")
        return

    state = data.get("state", data)
    n     = now_ts()
    lines = ["⏱️ *Timers de tu farm*\n"]

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
    crop_times = [float(c["crop"]["plantedAt"])/1000 + 60 - n
                  for c in crops.values()
                  if isinstance(c, dict) and c.get("crop", {}).get("plantedAt")]
    if crop_times:
        lines.append(f"🌾 Cultivos: {fmt_time(min(crop_times))}")

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
    data = await fetch_json(SFL_PRICES_API)
    if not data:
        await msg.reply_text("❌ No se pudo obtener el precio.")
        return
    sfl   = data.get("sfl", {})
    matic = data.get("matic", {})
    await msg.reply_text(
        f"💰 *Precios actuales*\n\n"
        f"🌻 SFL:   `${safe_float(sfl.get('usd',0)):.6f}` USD\n"
        f"📐 MATIC: `${safe_float(matic.get('usd',0)):.4f}` USD\n\n"
        f"🕐 {now_utc()}",
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
    jwt_status = "✅ JWT" if user.get("jwt") else "❌ Sin JWT"
    farm_id    = user.get("farm_id", "No configurado")
    await update.message.reply_text(
        f"🔔 *Gestionar Alertas*\n"
        f"Farm: `{farm_id}` | {jwt_status}\n\n"
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

    if d.startswith("tog_"):
        key = d[4:]
        if key in user:
            user[key] = not user[key]
        jwt_status = "✅ JWT" if user.get("jwt") else "❌ Sin JWT"
        farm_id    = user.get("farm_id", "No configurado")
        await query.edit_message_text(
            f"🔔 *Gestionar Alertas*\nFarm: `{farm_id}` | {jwt_status}\n\nToca 🟢/🔴:",
            parse_mode="Markdown",
            reply_markup=alerts_keyboard(user)
        )
    elif d == "all_on":
        for k in ALERT_NAMES:
            user[k] = True
        jwt_status = "✅ JWT" if user.get("jwt") else "❌ Sin JWT"
        farm_id    = user.get("farm_id", "No configurado")
        await query.edit_message_text(
            f"🔔 *Gestionar Alertas*\nFarm: `{farm_id}` | {jwt_status}\n\n✅ Todas activadas:",
            parse_mode="Markdown",
            reply_markup=alerts_keyboard(user)
        )
    elif d == "all_off":
        for k in ALERT_NAMES:
            user[k] = False
        jwt_status = "✅ JWT" if user.get("jwt") else "❌ Sin JWT"
        farm_id    = user.get("farm_id", "No configurado")
        await query.edit_message_text(
            f"🔔 *Gestionar Alertas*\nFarm: `{farm_id}` | {jwt_status}\n\n❌ Todas desactivadas:",
            parse_mode="Markdown",
            reply_markup=alerts_keyboard(user)
        )
    elif d == "main_menu":
        await query.edit_message_text(
            "🌻 *SFL Notice Bot*\n\nElige una opción:",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    elif d == "do_land":
        await query.message.reply_text("Usa `/land` para ver tu land.", parse_mode="Markdown")
    elif d == "do_precio":
        await precio_cmd(update, context)
    elif d == "do_mercado":
        await mercado_cmd(update, context)
    elif d == "do_alertas":
        jwt_status = "✅ JWT" if user.get("jwt") else "❌ Sin JWT"
        farm_id    = user.get("farm_id", "No configurado")
        await query.edit_message_text(
            f"🔔 *Gestionar Alertas*\nFarm: `{farm_id}` | {jwt_status}\n\nToca 🟢/🔴:",
            parse_mode="Markdown",
            reply_markup=alerts_keyboard(user)
        )
    elif d == "do_timers":
        await query.message.reply_text("Usa `/timers` para ver los tiempos.", parse_mode="Markdown")
    elif d == "do_help":
        await help_cmd(update, context)

# ─── JOB: VERIFICAR RECURSOS CADA 10 MIN ─────────────────────────────────────

async def job_check(context: ContextTypes.DEFAULT_TYPE):
    users = context.bot_data.get("users", {})
    n     = now_ts()

    for user_id, user in users.items():
        if not user.get("jwt") and not user.get("farm_id"):
            continue
        if not any(user.get(k) for k in ALERT_NAMES):
            continue

        data = await fetch_farm(user)
        if not data:
            continue

        state = data.get("state", data)
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

        if user.get("trees"):      check_nodes("trees",       "wood.choppedAt",   "trees",     "🌳", "árbol(es) para talar")
        if user.get("stones"):     check_nodes("stones",      "stone.minedAt",    "stones",    "⛏️", "piedra(s) para minar")
        if user.get("iron"):       check_nodes("iron",        "stone.minedAt",    "iron",      "🔩", "nodo(s) de hierro")
        if user.get("gold"):       check_nodes("gold",        "stone.minedAt",    "gold",      "🥇", "nodo(s) de oro")
        if user.get("crimstone"):  check_nodes("crimstones",  "stone.minedAt",    "crimstone", "💎", "Crimstone")
        if user.get("sunstone"):   check_nodes("sunstones",   "stone.minedAt",    "sunstone",  "🪨", "Sunstone")
        if user.get("obsidian"):   check_nodes("obsidian",    "stone.minedAt",    "obsidian",  "🖤", "Obsidiana")
        if user.get("oil"):        check_nodes("oilReserves", "oil.drilledAt",    "oil",       "🛢️", "reserva(s) de petróleo")
        if user.get("fruits"):     check_nodes("fruitPatches","fruit.harvestedAt","fruits",    "🍎", "árbol(es) de fruta")

        if user.get("crops"):
            crops = state.get("crops", {})
            ready = sum(1 for c in crops.values()
                        if isinstance(c, dict) and c.get("crop", {}).get("plantedAt")
                        and n >= float(c["crop"]["plantedAt"])/1000 + 60)
            if ready > 0 and n - last.get("crops", 0) > 600:
                msgs.append(f"🌾 *¡{ready} cultivo(s) listo(s) para cosechar!*")
                last["crops"] = n

        if user.get("chickens"):
            chickens = state.get("chickens", {})
            eggs, hungry, sick = 0, 0, 0
            for ch in chickens.values():
                if not isinstance(ch, dict): continue
                if ch.get("fedAt") and n >= float(ch["fedAt"])/1000 + REGEN["chickens"]:
                    eggs += 1
                if ch.get("state") == "hungry":  hungry += 1
                if ch.get("state") == "sick":    sick += 1
            if eggs   > 0 and n - last.get("chickens",       0) > 3600:
                msgs.append(f"🐔 *¡{eggs} gallina(s) con huevos listos!*");    last["chickens"] = n
            if hungry > 0 and n - last.get("ch_hungry",      0) > 3600:
                msgs.append(f"🍗 *¡{hungry} gallina(s) con hambre!*");         last["ch_hungry"] = n
            if sick   > 0 and n - last.get("ch_sick",        0) > 3600:
                msgs.append(f"🤒 *¡{sick} gallina(s) enferma(s)!*");           last["ch_sick"] = n

        if user.get("barn"):
            animals = state.get("barn", {}).get("animals", {})
            ready = sum(1 for a in animals.values()
                        if isinstance(a, dict) and a.get("awakeAt")
                        and n >= float(a["awakeAt"])/1000)
            if ready > 0 and n - last.get("barn", 0) > 3600:
                msgs.append(f"🌾 *¡{ready} animal(es) del granero listo(s)!*"); last["barn"] = n

        if user.get("compost"):
            comp     = state.get("buildings", {}).get("Composter", [{}])[0]
            ready_at = comp.get("producing", {}).get("readyAt", 0)
            if ready_at and n >= float(ready_at)/1000 and n - last.get("compost", 0) > 3600:
                msgs.append("🌿 *¡Tu compost está listo!*"); last["compost"] = n

        if user.get("cooking"):
            buildings = state.get("buildings", {})
            for bname, instances in buildings.items():
                if any(x in bname for x in ["Kitchen","Fire","Deli","Bakery"]):
                    for inst in (instances if isinstance(instances, list) else []):
                        ra = inst.get("crafting", {}).get("readyAt", 0)
                        if ra and n >= float(ra)/1000 and n - last.get("cooking", 0) > 600:
                            msgs.append(f"🍳 *¡Plato listo en {bname}!*"); last["cooking"] = n; break

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
                msgs.append("🏛️ *¡Tu subasta terminó! Revisa los resultados.*"); last["auction"] = n

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
                msgs.append(f"🏪 *¡Vendiste {len(sold)} artículo(s) en el mercado!*"); last["trade"] = n

        user["last_notified"] = last

        if msgs:
            farm_id = user.get("farm_id", "tu farm")
            try:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text=f"🌻 *SFL Notice — Land #{farm_id}*\n\n" + "\n".join(msgs),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error notificando a {user_id}: {e}")

# ─── TEXTO LIBRE ──────────────────────────────────────────────────────────────

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) <= 9:
        data = await fetch_public(text)
        if not data:
            await update.message.reply_text("❌ Land no encontrada con la API pública.")
            return
        state    = data.get("state", {})
        username = state.get("username", "Sin nombre")
        level    = xp_to_level(safe_float(state.get("bumpkin", {}).get("experience", 0)))
        await update.message.reply_text(
            f"🌾 *Land #{text}*\n👤 {username} — Nivel {level}\n\n"
            f"Usa `/setfarm {text}` para activar alertas.",
            parse_mode="Markdown"
        )

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CommandHandler("setfarm",   setfarm_cmd))
    app.add_handler(CommandHandler("settoken",  settoken_cmd))
    app.add_handler(CommandHandler("miperfil",  miperfil_cmd))
    app.add_handler(CommandHandler("land",      land_cmd))
    app.add_handler(CommandHandler("timers",    timers_cmd))
    app.add_handler(CommandHandler("precio",    precio_cmd))
    app.add_handler(CommandHandler("mercado",   mercado_cmd))
    app.add_handler(CommandHandler("alertas",   alertas_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.job_queue.run_repeating(job_check, interval=600, first=30)

    logger.info("🌻 SFL Notice Bot con JWT iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
