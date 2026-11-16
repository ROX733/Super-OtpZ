from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

UPDATES_CHANNEL = "@Super_Otpz"
UPDATES_CHANNEL_LINK = "https://t.me/Super_Otpz"

WELCOME_TEXT = (
    "❌ 𝖸𝗈𝗎 𝗆𝗎𝗌𝗍 𝗌𝗎𝖻𝗌𝖼𝗋𝗂𝖻𝖾 𝗍𝗈 𝗍𝗁𝖾 𝗈𝖿𝖿𝗂𝖼𝗂𝖺𝗅 𝖻𝗈𝗍 𝖼𝗁𝖺𝗇𝗇𝖾𝗅 𝗍𝗈 𝗎𝗌𝖾 𝗍𝗁𝖾 𝖻𝗈𝗍...\n\n"
    "<blockquote>- <b>𝖢𝗁𝖺𝗇𝗇𝖾𝗅</b> - @Super_Otpz</blockquote>\n\n"
    "<b>• Press Verify Button below to check</b>"
)


async def check_join(client, message: types.Message):
    """Require membership in the official Updates channel."""
    try:
        member = await client.get_chat_member(UPDATES_CHANNEL, message.from_user.id)
        if member.status in ("left", "kicked"):
            await send_join_message(message)
            return False
        return True
    except Exception:
        await send_join_message(message)
        return False


async def send_join_message(message: types.Message):
    """Show only the Updates channel and Verify Join buttons."""
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📢 𝖴𝗉𝖽𝖺𝗍𝖾𝗌", url=UPDATES_CHANNEL_LINK))
    kb.row(types.InlineKeyboardButton(text="Verify Join ☑️", callback_data="back_main"))
    await message.answer(
        WELCOME_TEXT,
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
