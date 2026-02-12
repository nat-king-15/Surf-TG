"""
Payment plugin: Telegram Stars payment integration for premium subscriptions.
Commands: /plans (or /pay) — show premium plans, handle invoice + payment callbacks.
Matches source bot's pay.py format exactly.
"""
import logging
from datetime import timedelta
from pyrogram import filters, Client
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    PreCheckoutQuery,
)
from pyrogram.enums.parse_mode import ParseMode

from bot.telegram import StreamBot
from bot.config import Telegram
from bot.helper.database import Database
from bot.utils.func import format_expiry

LOGGER = logging.getLogger(__name__)
db = Database()
P0 = Telegram.PREMIUM_PLANS  # shorthand matching source


# ═══════════════════════════════════════════════════════════════════
# /plans (or /pay) — Display premium plans
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.command(["plans", "pay"]) & filters.private)
async def plans_handler(bot: Client, message: Message):
    """Show available premium subscription plans."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"⭐ {P0['d']['l']} - {P0['d']['s']} Star",
            callback_data="p_d",
        )],
        [InlineKeyboardButton(
            f"⭐ {P0['w']['l']} - {P0['w']['s']} Stars",
            callback_data="p_w",
        )],
        [InlineKeyboardButton(
            f"⭐ {P0['m']['l']} - {P0['m']['s']} Stars",
            callback_data="p_m",
        )],
    ])

    text = (
        "💎 **Choose your premium plan:**\n\n"
        f"📅 **{P0['d']['l']}** — {P0['d']['s']} Star\n"
        f"🗓️ **{P0['w']['l']}** — {P0['w']['s']} Stars\n"
        f"📆 **{P0['m']['l']}** — {P0['m']['s']} Stars\n\n"
        "Select a plan below to continue ⤵️"
    )
    await message.reply_text(text, reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════
# Callback → Send invoice
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_callback_query(filters.regex(r"^p_"))
async def send_invoice(bot: Client, query: CallbackQuery):
    """Send a Telegram Stars invoice for the chosen plan."""
    plan_key = query.data.split("_")[1]  # d, w, or m
    plan = P0.get(plan_key)
    if not plan:
        await query.answer("❌ Invalid plan.", show_alert=True)
        return

    try:
        await bot.send_invoice(
            chat_id=query.from_user.id,
            title=f"Premium {plan['l']}",
            description=f"{plan['du']} {plan['u']} subscription",
            payload=f"{plan_key}_{query.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"Premium {plan['l']}", amount=plan["s"])],
        )
        await query.answer("Invoice sent 💫")
    except Exception as e:
        LOGGER.error(f"Invoice error: {e}")
        await query.answer(f"Err: {e}", show_alert=True)


# ═══════════════════════════════════════════════════════════════════
# Pre-checkout — always approve
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_pre_checkout_query()
async def pre_checkout(bot: Client, query: PreCheckoutQuery):
    """Approve all pre-checkout queries."""
    await query.answer(ok=True)


# ═══════════════════════════════════════════════════════════════════
# Successful payment → Grant premium
# ═══════════════════════════════════════════════════════════════════

@StreamBot.on_message(filters.successful_payment)
async def successful_payment(bot: Client, message: Message):
    """Process successful payment and grant premium."""
    payment = message.successful_payment
    user_id = message.from_user.id
    plan_key = payment.invoice_payload.split("_")[0]
    plan = P0.get(plan_key)

    if not plan:
        await message.reply_text("⚠️ Payment received but plan not found.")
        return

    success, result = await db.add_premium(user_id, plan["du"], plan["u"])

    if success:
        expiry_str = format_expiry(result)
        await message.reply_text(
            f"✅ **Paid!**\n\n"
            f"💎 Premium {plan['l']} active!\n"
            f"⭐ {payment.total_amount}\n"
            f"⏰ Till: {expiry_str} IST\n"
            f"🔖 Txn: `{payment.telegram_payment_charge_id}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        # Notify owner
        try:
            await bot.send_message(
                Telegram.OWNER_ID,
                f"💰 User {user_id} just purchased Premium {plan['l']}, "
                f"txn id is {payment.telegram_payment_charge_id}.",
            )
        except Exception:
            pass
    else:
        await message.reply_text(
            f"⚠️ Paid but premium activation failed.\n"
            f"Txn `{payment.telegram_payment_charge_id}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        # Notify owner about issue
        try:
            await bot.send_message(
                Telegram.OWNER_ID,
                f"⚠️ Issue!\nUser {user_id}\nPlan {plan['l']}\n"
                f"Txn {payment.telegram_payment_charge_id}\nErr {result}",
            )
        except Exception:
            pass
