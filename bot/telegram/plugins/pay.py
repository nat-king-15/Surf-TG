from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, PreCheckoutQuery
from bot.telegram import StreamBot
from bot.helper.database import Database
from bot.config import Telegram
from datetime import datetime, timedelta

db = Database()

# --- Admin Commands ---

@StreamBot.on_message(filters.command('addpremium') & filters.user(Telegram.OWNER_ID))
async def add_premium_cmd(client, message: Message):
    if len(message.command) < 4:
        await message.reply("Usage: /addpremium <user_id> <time_value> <time_unit>\nUnits: min, hours, days, weeks, month, year")
        return
        
    try:
        user_id = int(message.command[1])
        time_value = int(message.command[2])
        time_unit = message.command[3].lower()
        
        success, result = await db.add_premium_user(user_id, time_value, time_unit)
        
        if success:
            expiry = result + timedelta(hours=5, minutes=30)
            formatted_expiry = expiry.strftime('%d-%b-%Y %I:%M:%S %p')
            await message.reply(f"Premium added for user {user_id} until {formatted_expiry} IST")
            try:
                await client.send_message(user_id, f"You have been added as premium member.\nValidity until: {formatted_expiry} IST")
            except:
                pass
        else:
            await message.reply(f"Failed to add premium: {result}")
            
    except ValueError:
        await message.reply("Invalid User ID or Time Value")
    except Exception as e:
        await message.reply(f"Error: {e}")

@StreamBot.on_message(filters.command('removepremium') & filters.user(Telegram.OWNER_ID))
async def remove_premium_cmd(client, message: Message):
    if len(message.command) < 2:
        await message.reply("Usage: /removepremium <user_id>")
        return
        
    try:
        user_id = int(message.command[1])
        await db.db.premium_users.update_one(
            {"user_id": user_id},
            {"$set": {"subscription_end": datetime.now()}}
        )
        await message.reply(f"Premium removed for user {user_id}")
            
    except ValueError:
        await message.reply("Invalid User ID")
    except Exception as e:
        await message.reply(f"Error: {e}")

@StreamBot.on_message(filters.command('myplan'))
async def myplan_cmd(client, message: Message):
    user_id = message.from_user.id
    user = await db.get_premium_details(user_id)
    
    if user and await db.is_premium_user(user_id):
        expiry = user.get("subscription_end")
        if expiry:
             expiry = expiry + timedelta(hours=5, minutes=30)
             formatted_expiry = expiry.strftime('%d-%b-%Y %I:%M:%S %p')
             await message.reply(f"You are a Premium User.\nExpires on: {formatted_expiry} IST")
        else:
             await message.reply("Premium Active (No expiry)")
    else:
        await message.reply("You are a Free User.")

# --- Payment Commands (Stars) ---

@StreamBot.on_message(filters.command("pay") & filters.private)
async def pay_cmd(client, message: Message):
    P0 = Telegram.P0
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ {P0['d']['l']} - {P0['d']['s']} Star", callback_data="p_d")],
        [InlineKeyboardButton(f"⭐ {P0['w']['l']} - {P0['w']['s']} Stars", callback_data="p_w")],
        [InlineKeyboardButton(f"⭐ {P0['m']['l']} - {P0['m']['s']} Stars", callback_data="p_m")]
    ])
    
    txt = (
        "💎 **Choose your premium plan:**\n\n"
        f"📅 **{P0['d']['l']}** — {P0['d']['s']} Star\n"
        f"🗓️ **{P0['w']['l']}** — {P0['w']['s']} Stars\n"
        f"📆 **{P0['m']['l']}** — {P0['m']['s']} Stars\n\n"
        "Select a plan below to continue ⤵️"
    )
    await message.reply_text(txt, reply_markup=kb)

@StreamBot.on_callback_query(filters.regex("^p_"))
async def pay_callback(client, query):
    P0 = Telegram.P0
    pl = query.data.split("_")[1]
    pi = P0[pl]
    try:
        await client.send_invoice(
            chat_id=query.from_user.id,
            title=f"Premium {pi['l']}",
            description=f"{pi['du']} {pi['u']} subscription",
            payload=f"{pl}_{query.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"Premium {pi['l']}", amount=pi['s'])]
        )
        await query.answer("Invoice sent 💫")
    except Exception as e:
        await query.answer(f"Error: {e}", show_alert=True)

@StreamBot.on_pre_checkout_query()
async def pre_checkout_query(client, query: PreCheckoutQuery):
    await query.answer(ok=True)

@StreamBot.on_message(filters.successful_payment)
async def successful_payment(client, message: Message):
    P0 = Telegram.P0
    payment = message.successful_payment
    user_id = message.from_user.id
    
    payload_parts = payment.invoice_payload.split("_")
    pl = payload_parts[0]
    
    if pl not in P0:
         return # Error
         
    pi = P0[pl]
    
    # Add premium
    success, expiry = await db.add_premium_user(user_id, pi['du'], pi['u'])
    
    if success:
        expiry = expiry + timedelta(hours=5, minutes=30)
        formatted_expiry = expiry.strftime('%d-%b-%Y %I:%M:%S %p')
        
        await message.reply_text(
            f"✅ **Paid!**\n\n"
            f"💎 Premium {pi['l']} active!\n"
            f"⭐ {payment.total_amount}\n"
            f"⏰ Till: {formatted_expiry} IST\n"
            f"🔖 Txn: `{payment.telegram_payment_charge_id}`"
        )
        
        # Notify Owners
        if Telegram.OWNER_ID:
            for owner in Telegram.OWNER_ID:
                 try:
                    await client.send_message(owner, f"User {user_id} purchased premium. Txn: {payment.telegram_payment_charge_id}")
                 except:
                    pass
    else:
        await message.reply_text("Paid but failed to add premium. Contact admin.")
