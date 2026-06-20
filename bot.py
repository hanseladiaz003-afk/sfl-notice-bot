import os
import logging
import aiohttp
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ─── CONFIGURACIÓN ──────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8916752238:AAGXKRhpXTWeFI-HfxeMCUdwviPldfMGymk")

# Valores de Railway Variables por defecto para precarga automática
DEFAULT_FARM_ID = os.environ.get("SFL_FARM_ID", "")
DEFAULT_API_KEY = os.environ.get("SFL_API_KEY", "")
DEFAULT_TELEGRAM_USER_ID = os.environ.get("SFL_TELEGRAM_USER_ID", "")

SFL_API = "https://api.sunflower-land.com/community/farms"
SFL_PRICES_API = "https://api.coingecko.com/api/v3/simple/price?ids=sunflower-land&vs_currencies=usd"
MATIC_PRICES_API = "https://api.coingecko.com/api/v3/simple/price?ids=matic-network&vs_currencies=usd"
SFL_EXCHANGE_API = "https://api.sunflower-land.com/community/trades"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Tiempos de regeneración de recursos (segundos)
REGEN = {
    "trees": 2 * 3600,
    "stones": 4 * 3600,
    "iron": 8 * 3600,
    "gold": 24 * 3600,
    "crimstone": 3 * 24 * 3600,
    "sunstone": 3 * 24 * 3600,
    "obsidian": 3 * 24 * 3600,
    "oil": 16 * 3600,
    "chickens": 24 * 3600,
    "barn": 24 * 3600,
    "fruits": 14 * 3600,
    "compost": 6 * 3600,
}

# Tiempos base de crecimiento de cultivos (segundos)
CROP_TIMES = {
    "Sunflower": 60,            # 1 min
    "Potato": 5 * 60,           # 5 min
    "Pumpkin": 30 * 60,         # 30 min
    "Carrot": 60 * 60,          # 1 hora
    "Cabbage": 2 * 3600,        # 2 horas
    "Beetroot": 4 * 3600,       # 4 horas
    "Cauliflower": 8 * 3600,    # 8 horas
    "Parsnip": 12 * 3600,       # 12 horas
    "Eggplant": 16 * 3600,      # 16 horas
    "Corn": 20 * 3600,          # 20 horas
    "Radish": 24 * 3600,        # 24 horas
    "Wheat": 24 * 3600,         # 24 horas
    "Barley": 24 * 3600,        # 24 horas
    "Kale": 8 * 3600,           # 8 horas
    "Rice": 48 * 3600,          # 48 horas
    "Olive": 48 * 3600,         # 48 horas
}

ALERT_NAMES = {
    "trees": "🌲 Árboles",
    "stones": "🪨 Piedras",
    "iron": "⛏️ Hierro",
    "gold": "🪙 Oro",
    "crimstone": "🔻 Crimstone",
    "sunstone": "☀️ Sunstone",
    "obsidian": "⚫ Obsidiana",
    "oil": "🛢️ Petróleo",
    "crops": "🌱 Cultivos",
    "fruits": "🍎 Frutas",
    "compost": "🪱 Compost",
    "trade": "⚖️ Comercio",
    "chickens": "🐓 Gallinero",
    "barn": "🐄 Granero",
    "checklist": "✔ Verificación",
    "auction": "🔨 Subastas",
    "giftgiver": "🎁 Gift Giver",
    "loveisland": "🏝️ Love Island",
    "cooking": "🍳 Cocina",
    "delivery": "📦 Entregas NPC",
}

# ─── HELPERS ────────────────────────────────────────────────────────────────
def now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M UTC")

def safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0

def get_secs(val) -> float:
    """Detecta automáticamente si el timestamp está en milisegundos o segundos y lo normaliza."""
    try:
        v = float(val)
        if v > 50000000000:  # Si es mayor a este umbral, definitivamente son milisegundos
            return v / 1000
        return v
    except (TypeError, ValueError):
        return 0.0

def fmt_time(secs: float) -> str:
    if secs <= 0:
        return "¡Listo!"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    return f"{h}h {m}m" if h > 0 else f"{m}m"

def xp_to_level(xp: float) -> int:
    total = 0
    for lvl in range(1, 500):
        total += lvl * 875
        if total > xp:
            return lvl
    return 500

def get_user(context, user_id: str) -> dict:
    if "users" not in context.bot_data:
        context.bot_data["users"] = {}
    if user_id not in context.bot_data["users"]:
        is_default_user = DEFAULT_TELEGRAM_USER_ID and user_id == DEFAULT_TELEGRAM_USER_ID
        if is_default_user and DEFAULT_FARM_ID and DEFAULT_API_KEY:
            context.bot_data["users"][user_id] = {
                "farm_id": DEFAULT_FARM_ID,
                "api_key": DEFAULT_API_KEY,
                **{k: True for k in ALERT_NAMES},
                "last_notified": {}
            }
            logger.info(f"Configuración precargada automáticamente para el usuario default: {user_id}")
        else:
            context.bot_data["users"][user_id] = {
                "farm_id": None,
                "api_key": None,
                **{k: False for k in ALERT_NAMES},
                "last_notified": {}
            }
    return context.bot_data["users"][user_id]

async def fetch_farm(farm_id: str, api_key: str) -> dict | None:
    try:
        headers = {"x-api-key": api_key}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(f"{SFL_API}/{farm_id}", headers=headers) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    if "farm" in data:
                        return data["farm"]
                    return data
                else:
                    text = await r.text()
                    logger.error(f"Error API ({r.status}): {text}")
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
        logger.error(f"Error fetch json: {e}")
    return None

# ─── TECLADOS ───────────────────────────────────────────────────────────────
def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌾 Mi Land", callback_data="do_land"),
         InlineKeyboardButton("💰 Precio SFL", callback_data="do_precio")],
        [InlineKeyboardButton("🔔 Alertas", callback_data="do_alertas"),
         InlineKeyboardButton("🛒 Mercado P2P", callback_data="do_market")],
        [InlineKeyboardButton("⏱️ Timers", callback_data="do_timers"),
         InlineKeyboardButton("❓ Ayuda", callback_data="do_help")]
    ])

def alerts_keyboard(user: dict) -> InlineKeyboardMarkup:
    keys = list(ALERT_NAMES.keys())
    buttons = []
    for i in range(0, len(keys), 2):
        row = []
        for key in keys[i:i+2]:
            icon = "✅ " if user.get(key) else "❌ "
            label = ALERT_NAMES[key]
            row.append(InlineKeyboardButton(f"{icon}{label}", callback_data=f"tog_{key}"))
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("✓ Activar TODAS", callback_data="all_on"),
        InlineKeyboardButton("❌ Desactivar todas", callback_data="all_off")
    ])
    buttons.append([InlineKeyboardButton("🔙 BACK Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

# ─── COMANDOS ───────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*SFL Notice Bot* — Sunflower Land\n\n"
        "Para conectar tu farm necesitas dos cosas:\n\n"
        "1. Tu *Farm ID* (número corto del NFT)\n"
        "2. Tu *API Key* oficial del juego\n\n"
        "Usa este comando:\n"
        "`/setup 259942 sfl.MTk1MDA1...` \n\n"
        "_(Farm ID seguido de tu API Key)_",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "*Comandos disponibles:*\n\n"
        "/setup `ID` `KEY` - Configurar farm y API Key\n"
        "/land - Ver recursos e inventario\n"
        "/timers - Ver estado de los tiempos\n"
        "/alertas - Gestionar alertas push\n"
        "/precio - Precio SFL y MATIC\n"
        "/mercado - Mercado P2P\n"
        "/miperfil - Ver tu configuración actual\n\n"
        "¿Dónde está tu API Key?\n"
        "En el juego: *Settings > Avanzado > Clave API*",
        parse_mode="Markdown"
    )

async def setup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Uso: /setup FARM_ID API_KEY\n\n"
            "Ejemplo:\n`/setup 259942 sfl.MTk1MDA1...`",
            parse_mode="Markdown"
        )
        return
    farm_id = context.args[0].strip()
    api_key = context.args[1].strip()
    
    if not farm_id.isdigit():
        await update.message.reply_text("❌ El Farm ID debe ser un número válido.")
        return
        
    msg = await update.message.reply_text("🔄 Verificando tu farm con la API Key...")
    data = await fetch_farm(farm_id, api_key)
    
    if not data:
        await msg.edit_text(
            "❌ No se pudo conectar con tu farm.\n\n"
            "Verifica que:\n"
            "• El Farm ID sea correcto\n"
            "• La API Key esté completa\n"
            "• Copiaste la clave estando dentro de la sesión de juego",
            parse_mode="Markdown"
        )
        return
        
    user = get_user(context, user_id)
    user["farm_id"] = farm_id
    user["api_key"] = api_key
    
    username = data.get("username", "Sin nombre")
    level = xp_to_level(safe_float(data.get("bumpkin", {}).get("experience", 0)))
    balance = safe_float(data.get("balance", 0))
    
    await msg.edit_text(
        f"🎉 *¡Farm conectada exitosamente!*\n\n"
        f"🆔 *Farm ID:* {farm_id}\n"
        f"🧑‍🌾 *Nombre:* {username} (Nivel {level})\n"
        f"💰 *Balance:* {balance:,.2f} SFL\n\n"
        f"Activa tus alertas con /alertas o revisa los tiempos con /timers",
        parse_mode="Markdown"
    )

async def miperfil_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(context, user_id)
    farm_id = user.get("farm_id", "No configurado")
    api_key = user.get("api_key")
    api_status = "🟢 API Key activa" if api_key else "🔴 Sin API Key"
    activas = [ALERT_NAMES[k] for k in ALERT_NAMES if user.get(k)]
    
    await update.message.reply_text(
        f"👤 *Mi perfil SFL*\n\n"
        f"🆔 *Farm ID:* {farm_id}\n"
        f"🔑 *Estado:* {api_status}\n\n"
        f"🔔 *Alertas activas ({len(activas)}):*\n" +
        ("\n".join(f"• {a}" for a in activas) if activas else "Ninguna. Usa /alertas para activar."),
        parse_mode="Markdown"
    )

async def land_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(context, user_id)
    msg = update.message
    
    if not user.get("farm_id") or not user.get("api_key"):
        await msg.reply_text("❌ Configura tu farm primero usando /setup.", parse_mode="Markdown")
        return
        
    status_msg = await msg.reply_text("🔄 Consultando tu land...")
    data = await fetch_farm(user["farm_id"], user["api_key"])
    
    if not data:
        await status_msg.edit_text("❌ No se pudo obtener la land. Verifica tu configuración.")
        return
        
    inv = data.get("inventory", {})
    username = data.get("username", "Sin nombre")
    level = xp_to_level(safe_float(data.get("bumpkin", {}).get("experience", 0)))
    
    res = {
        "SFL": safe_float(data.get("balance", 0)),
        "Monedas": safe_float(data.get("coins", 0)),
        "Madera": safe_float(inv.get("Wood", 0)),
        "Piedra": safe_float(inv.get("Stone", 0)),
        "Hierro": safe_float(inv.get("Iron", 0)),
        "Oro": safe_float(inv.get("Gold", 0)),
        "Maíz": safe_float(inv.get("Corn", 0)),
        "Zanahoria": safe_float(inv.get("Carrot", 0)),
    }
    lines = "\n".join(f"• {k}: {v:,.2f}" for k, v in res.items() if v > 0)
    
    await status_msg.edit_text(
        f"🏰 *Land #{user['farm_id']}*\n"
        f"🧑‍🌾 {username} | Nivel {level}\n\n"
        f"📦 *Inventario activo:*\n{lines or '(vacío)'}",
        parse_mode="Markdown"
    )

async def timers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(context, user_id)
    msg = update.message or update.callback_query.message
    
    if not user.get("farm_id") or not user.get("api_key"):
        await msg.reply_text("❌ Configura tu farm primero usando /setup.", parse_mode="Markdown")
        return
        
    status_msg = await msg.reply_text("⏱️ Calculando tiempos...")
    data = await fetch_farm(user["farm_id"], user["api_key"])
    
    if not data:
        await status_msg.edit_text("❌ No se pudo obtener la información de la land.")
        return
        
    n = now_ts()
    lines = [f"⏱️ *Timers Land #{user['farm_id']}*\n"]
    
    def nearest(items, sub_key, ts_field):
        times = []
        if not isinstance(items, dict): return None
        for v in items.values():
            if not isinstance(v, dict): continue
            sub_obj = v.get(sub_key, {})
            if not isinstance(sub_obj, dict): continue
            ts_value = sub_obj.get(ts_field)
            boosted_time = sub_obj.get("boostedTime", 0)
            if ts_value:
                remaining = (get_secs(ts_value) + get_secs(boosted_time)) - n
                times.append(remaining)
        return min(times) if times else None

    checks = [
        ("trees", "wood", "choppedAt", "🌲 Árboles"),
        ("stones", "stone", "minedAt", "🪨 Piedras"),
        ("iron", "stone", "minedAt", "⛏️ Hierro"),
        ("gold", "stone", "minedAt", "🪙 Oro"),
        ("crimstones", "stone", "minedAt", "🔻 Crimstone"),
        ("sunstones", "stone", "minedAt", "☀️ Sunstone"),
        ("obsidian", "stone", "minedAt", "⚫ Obsidiana"),
        ("fruitPatches", "fruit", "harvestedAt", "🍎 Frutas")
    ]
    
    for state_key, sub_key, ts_field, label in checks:
        t = nearest(data.get(state_key, {}), sub_key, ts_field)
        if t is not None:
            lines.append(f"{label}: {fmt_time(t)}")
            
    # LÓGICA DE CULTIVOS PROTEGIDA (Soporta esquemas planos/anidados e ignora parcelas vacías)
    crops = data.get("crops", {})
    crop_times = []
    crop_ready = 0
    if isinstance(crops, dict):
        for c in crops.values():
            if not isinstance(c, dict): continue
            
            crop_info = c.get("crop")
            if isinstance(crop_info, dict):
                crop_name = crop_info.get("name")
                planted_at = crop_info.get("plantedAt")
            else:
                crop_name = c.get("name")
                planted_at = c.get("plantedAt")
                
            if not crop_name or not planted_at:
                continue  # Se salta las parcelas vacías o ya recolectadas para evitar falsos positivos
                
            base_grow_time = CROP_TIMES.get(crop_name, 7200)
            remaining = (get_secs(planted_at) + base_grow_time) - n
            if remaining <= 0:
                crop_ready += 1
            else:
                crop_times.append(remaining)
                    
    if crop_ready > 0:
        lines.append(f"🌱 Cultivos: ¡{crop_ready} listo(s)!")
    elif crop_times:
        lines.append(f"🌱 Cultivos (próximo): {fmt_time(min(crop_times))}")
    else:
        lines.append("🌱 Cultivos: Ninguno sembrado")
        
    chs = data.get("chickens", {})
    if isinstance(chs, dict):
        ch_times = []
        for c in chs.values():
            if isinstance(c, dict) and c.get("fedAt"):
                rem = (get_secs(c["fedAt"]) + REGEN["chickens"]) - n
                ch_times.append(rem)
        if ch_times:
            lines.append(f"🐓 Gallinero: {fmt_time(min(ch_times))}")
            
    if len(lines) == 1:
        lines.append("No se encontraron recursos activos en regeneración.")
        
    await status_msg.edit_text("\n".join(lines), parse_mode="Markdown")

async def precio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    sfl_data = await fetch_json(SFL_PRICES_API)
    matic_data = await fetch_json(MATIC_PRICES_API)
    
    if not sfl_data:
        await msg.reply_text("❌ No se pudo obtener la cotización de mercado.")
        return
        
    sfl_price = safe_float(sfl_data.get("sunflower-land", {}).get("usd", 0))
    matic_price = safe_float((matic_data or {}).get("matic-network", {}).get("usd", 0))
    
    await msg.reply_text(
        f"📈 *Precios de Mercado*\n\n"
        f"🌻 SFL: `${sfl_price:.6f} USD`\n"
        f"🪙 MATIC: `${matic_price:.4f} USD`\n\n"
        f"🕒 _Actualizado: {now_utc()}_\n"
        f"Fuente: CoinGecko",
        parse_mode="Markdown"
    )

async def mercado_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    data = await fetch_json(SFL_EXCHANGE_API)
    
    if not data:
        await msg.reply_text("❌ Sin respuesta del mercado P2P.")
        return
        
    items = list(data.get("p2p", {}).items())[:12]
    if not items:
        await msg.reply_text("No hay datos de operaciones en el libro P2P.")
        return
        
    lines = [f"• {nm}: `{safe_float(p):.4f} SFL`" for nm, p in items]
    await msg.reply_text(
        f"🛒 *Mercado P2P (Muestreo En Línea)*\n\n" + "\n".join(lines) +
        f"\n\n🕒 {now_utc()} | 🌐 [sfl.world](https://sfl.world)",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

async def alertas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(context, user_id)
    farm_id = user.get("farm_id", "No configurado")
    api_status = "🟢 Lista" if user.get("api_key") else "🔴 Desconectada"
    
    await update.message.reply_text(
        f"🔔 *Gestionar Alertas*\n"
        f"Farm: `{farm_id}` | API Key: {api_status}\n\n"
        "Toca los botones para alternar el envío automático:",
        parse_mode="Markdown",
        reply_markup=alerts_keyboard(user)
    )

# ─── CALLBACKS DE BOTONES ───────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    d = query.data
    user_id = str(update.effective_user.id)
    user = get_user(context, user_id)
    
    def alerts_header():
        farm_id = user.get("farm_id", "No configurado")
        api_status = "🟢 Activa" if user.get("api_key") else "🔴 Inactiva"
        return f"🔔 *Gestionar Alertas*\nFarm: `{farm_id}` | API Key: {api_status}\n\nToca para alternar:"

    if d.startswith("tog_"):
        key = d[4:]
        if key in user:
            user[key] = not user[key]
        await query.edit_message_text(alerts_header(), parse_mode="Markdown", reply_markup=alerts_keyboard(user))
    elif d == "all_on":
        for k in ALERT_NAMES: user[k] = True
        await query.edit_message_text(alerts_header(), parse_mode="Markdown", reply_markup=alerts_keyboard(user))
    elif d == "all_off":
        for k in ALERT_NAMES: user[k] = False
        await query.edit_message_text(alerts_header(), parse_mode="Markdown", reply_markup=alerts_keyboard(user))
    elif d == "main_menu":
        await query.edit_message_text("🤖 *SFL Notice Bot*\n\nElige una opción del menú:", parse_mode="Markdown", reply_markup=main_keyboard())
    elif d == "do_land":
        await query.message.reply_text("Usa el comando `/land` para ver tu inventario completo.", parse_mode="Markdown")
    elif d == "do_precio":
        await precio_cmd(update, context)
    elif d == "do_market":
        await mercado_cmd(update, context)
    elif d == "do_alertas":
        await query.edit_message_text(alerts_header(), parse_mode="Markdown", reply_markup=alerts_keyboard(user))
    elif d == "do_timers":
        await timers_cmd(update, context)
    elif d == "do_help":
        await help_cmd(update, context)

# ─── CRON JOB: VERIFICACIÓN AUTOMÁTICA EN SEGUNDO PLANO ──────────────────────
async def job_check(context: ContextTypes.DEFAULT_TYPE):
    users = context.bot_data.get("users", {})
    n = now_ts()
    
    for user_id, user in list(users.items()):
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
            last = user.setdefault("last_notified", {})
            msgs = []
            
            def check_nodes(state_key, sub_key, ts_field, emoji, label):
                nodes = state.get(state_key, {})
                if not isinstance(nodes, dict): return
                ready_new = 0
                for node_id, v in nodes.items():
                    if not isinstance(v, dict): continue
                    sub_obj = v.get(sub_key, {})
                    if not isinstance(sub_obj, dict): continue
                    ts_value = sub_obj.get(ts_field)
                    boosted_time = sub_obj.get("boostedTime", 0)
                    if ts_value:
                        ready_at = get_secs(ts_value) + get_secs(boosted_time)
                        if n >= ready_at:
                            notify_key = f"{state_key}_{node_id}_{ts_value}"
                            if notify_key not in last:
                                ready_new += 1
                                last[notify_key] = n
                if ready_new > 0:
                    msgs.append(f"{emoji} *¡{ready_new} {label} listo(s)!*")

            if user.get("trees"): check_nodes("trees", "wood", "choppedAt", "🌲", "árbol(es) para talar")
            if user.get("stones"): check_nodes("stones", "stone", "minedAt", "🪨", "piedra(s) para minar")
            if user.get("iron"): check_nodes("iron", "stone", "minedAt", "⛏️", "nodo(s) de hierro")
            if user.get("gold"): check_nodes("gold", "stone", "minedAt", "🪙", "nodo(s) de oro")
            if user.get("crimstone"): check_nodes("crimstones", "stone", "minedAt", "🔻", "Crimstone")
            if user.get("sunstone"): check_nodes("sunstones", "stone", "minedAt", "☀️", "Sunstone")
            if user.get("obsidian"): check_nodes("obsidian", "stone", "minedAt", "⚫", "Obsidiana")
            if user.get("oil"): check_nodes("oilReserves", "oil", "drilledAt", "🛢️", "reserva(s) de petróleo")
            if user.get("fruits"): check_nodes("fruitPatches", "fruit", "harvestedAt", "🍎", "árbol(es) de fruta")
            
            # CRON JOB DE CULTIVOS PROTEGIDO
            if user.get("crops"):
                crops = state.get("crops", {})
                ready_crops = []
                if isinstance(crops, dict):
                    for crop_id, c in crops.items():
                        if not isinstance(c, dict): continue
                        
                        crop_info = c.get("crop")
                        if isinstance(crop_info, dict):
                            crop_name = crop_info.get("name")
                            planted_at = crop_info.get("plantedAt")
                        else:
                            crop_name = c.get("name")
                            planted_at = c.get("plantedAt")
                            
                        if not crop_name or not planted_at:
                            continue
                            
                        base_grow_time = CROP_TIMES.get(crop_name, 7200)
                        if n >= (get_secs(planted_at) + base_grow_time):
                            notify_key = f"crop_{crop_id}_{planted_at}"
                            if notify_key not in last:
                                ready_crops.append(crop_name)
                                last[notify_key] = n
                if ready_crops:
                    msgs.append(f"🌱 *¡{len(ready_crops)} cultivo(s) listo(s) para cosechar!*")
                    
            if user.get("chickens"):
                chickens = state.get("henHouse", {}).get("chickens", state.get("chickens", {}))
                eggs_new = hungry_new = sick_new = 0
                if isinstance(chickens, dict):
                    for ch_id, ch in chickens.items():
                        if not isinstance(ch, dict): continue
                        fed_at = ch.get("fedAt")
                        if fed_at and n >= get_secs(fed_at) + REGEN["chickens"]:
                            k = f"egg_{ch_id}_{fed_at}"
                            if k not in last:
                                eggs_new += 1
                                last[k] = n
                        if ch.get("state") == "hungry":
                            k = f"hungry_{ch_id}_{fed_at or 0}"
                            if k not in last:
                                hungry_new += 1
                                last[k] = n
                        if ch.get("state") == "sick":
                            k = f"sick_{ch_id}_{fed_at or 0}"
                            if k not in last:
                                sick_new += 1
                                last[k] = n
                if eggs_new > 0: msgs.append(f"🐓 *¡{eggs_new} gallina(s) con huevos listos!*")
                if hungry_new > 0: msgs.append(f"🍲 *¡{hungry_new} gallina(s) con hambre!*")
                if sick_new > 0: msgs.append(f"💔 *¡{sick_new} gallina(s) enferma(s)!*")
                
            if user.get("barn"):
                animals = state.get("barn", {}).get("animals", {})
                ready_new = 0
                if isinstance(animals, dict):
                    for a_id, a in animals.items():
                        if not isinstance(a, dict): continue
                        awake_at = a.get("awakeAt")
                        if awake_at and n >= get_secs(awake_at):
                            k = f"barn_{a_id}_{awake_at}"
                            if k not in last:
                                ready_new += 1
                                last[k] = n
                if ready_new > 0: msgs.append(f"🐄 *¡{ready_new} animal(es) del granero listo(s)!*")
                
            if user.get("compost"):
                comp_list = state.get("buildings", {}).get("Compost Bin", [{}])
                if comp_list and isinstance(comp_list, list):
                    comp = comp_list[0]
                    ready_at = comp.get("producing", {}).get("readyAt", 0)
                    if ready_at and n >= get_secs(ready_at):
                        k = f"compost_{ready_at}"
                        if k not in last:
                            msgs.append("🪱 *¡Tu compost está listo!*")
                            last[k] = n
                            
            if user.get("cooking"):
                for bname, instances in state.get("buildings", {}).items():
                    if any(x in bname for x in ["Kitchen","Fire Pit","Deli","Bakery","Smoothie Shack"]):
                        for inst in (instances if isinstance(instances, list) else []):
                            if not isinstance(inst, dict): continue
                            crafting_list = inst.get("crafting", [])
                            if isinstance(crafting_list, dict): crafting_list = [crafting_list]
                            if not isinstance(crafting_list, list): crafting_list = []
                            for item in crafting_list:
                                if not isinstance(item, dict): continue
                                ra = item.get("readyAt", 0)
                                item_name = item.get("name", "plato")
                                cooldown_key = f"cooking_{bname}_{item_name}_{ra}"
                                if ra and n >= get_secs(ra) and cooldown_key not in last:
                                    msgs.append(f"🍳 *¡{item_name} listo en {bname}!*")
                                    last[cooldown_key] = n
                                    
            if user.get("delivery"):
                orders = state.get("delivery", {}).get("orders", [])
                if any(o.get("completedAt") for o in orders) and n - last.get("delivery", 0) > 82800:
                    msgs.append("📦 *¡Entregas NPC disponibles!*")
                    last["delivery"] = n
                    
            if user.get("giftgiver"):
                streak_at = state.get("dailyRewards", {}).get("streakAt", 0)
                if streak_at and n >= get_secs(streak_at) + 86400 and n - last.get("giftgiver", 0) > 82800:
                    msgs.append("🎁 *¡Recompensa diaria del Gift Giver disponible!*")
                    last["giftgiver"] = n
                    
            if user.get("loveisland"):
                if state.get("loveIsland", {}).get("available") and n - last.get("loveisland", 0) > 86400:
                    msgs.append("🏝️ *¡Love Island disponible!*")
                    last["loveisland"] = n
                    
            if user.get("auction"):
                end_at = state.get("auctioneer", {}).get("endAt", 0)
                if end_at and n >= get_secs(end_at):
                    k = f"auction_{end_at}"
                    if k not in last:
                        msgs.append("🔨 *¡Tu subasta terminó!*")
                        last[k] = n
                        
            if user.get("checklist"):
                chores = state.get("chores", {})
                if isinstance(chores, dict):
                    total = len(chores)
                    done = sum(1 for c in chores.values() if isinstance(c, dict) and c.get("completedAt"))
                    if total > 0 and done == total and n - last.get("checklist", 0) > 82800:
                        msgs.append(f"✔ *¡Completaste todos tus quehaceres ({done}/{total})!*")
                        last["checklist"] = n
                        
            if user.get("trade"):
                listings = state.get("trades", {}).get("listings", {})
                if isinstance(listings, dict):
                    sold = [l for l in listings.values() if isinstance(l, dict) and l.get("boughtAt")]
                    if sold and n - last.get("trade", 0) > 3600:
                        msgs.append(f"⚖️ *¡Vendiste {len(sold)} artículo(s)!*")
                        last["trade"] = n
                        
            user["last_notified"] = last
            if msgs:
                try:
                    await context.bot.send_message(
                        chat_id=int(user_id),
                        text=f"🔔 *SFL Notice — Land #{farm_id}*\n\n" + "\n".join(msgs),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error notificando a {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error procesando alertas para usuario {user_id}: {e}")
            continue

# ─── HANDLER DE TEXTO PLANO ──────────────────────────────────────────────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.isdigit() and len(text) <= 7:
        await update.message.reply_text(
            f"ℹ️ Para enlazar este Farm ID, usa el formato completo de comando:\n"
            f"`/setup {text} TuApiKeyAqui`",
            parse_mode="Markdown"
        )

# ─── FUNCIÓN PRINCIPAL ──────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN or BOT_TOKEN == "TU TOKEN AQUI":
        logger.error("BOT_TOKEN no configurado en las variables de entorno.")
        return
        
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Precargar configuración permanente al iniciar desde Variables de Entorno (Railway)
    if DEFAULT_TELEGRAM_USER_ID and DEFAULT_FARM_ID and DEFAULT_API_KEY:
        app.bot_data["users"] = {
            DEFAULT_TELEGRAM_USER_ID: {
                "farm_id": DEFAULT_FARM_ID,
                "api_key": DEFAULT_API_KEY,
                **{k: True for k in ALERT_NAMES},
                "last_notified": {}
            }
        }
        logger.info(f"Configuración de Railway precargada exitosamente para el usuario {DEFAULT_TELEGRAM_USER_ID}")
        
    # Registro de Handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("setup", setup_cmd))
    app.add_handler(CommandHandler("miperfil", miperfil_cmd))
    app.add_handler(CommandHandler("land", land_cmd))
    app.add_handler(CommandHandler("timers", timers_cmd))
    app.add_handler(CommandHandler("precio", precio_cmd))
    app.add_handler(CommandHandler("mercado", mercado_cmd))
    app.add_handler(CommandHandler("alertas", alertas_cmd))
    
    # Registro de Handlers de callbacks e interfaz interactiva
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    # Cola de trabajos concurrentes para alertas programadas en bucle (cada 10 Minutos)
    app.job_queue.run_repeating(job_check, interval=600, first=20)
    
    logger.info("SFL Notice Bot con API Key oficial iniciado exitosamente...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
