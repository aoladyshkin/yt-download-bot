from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

from balance import add_balance, get_balance

async def handle_crypto_topup(update: Update, context: CallbackContext, cryptopay) -> None:
    """Обрабатывает сумму для пополнения через CryptoBot."""
    try:
        amount_credits = int(update.message.text)
        if amount_credits <= 0:
            await update.message.reply_text("Сумма должна быть положительной.")
            return

        amount_usd = amount_credits * 0.01
        invoice = await cryptopay.create_invoice(asset='USDT', amount=amount_usd)
        
        context.user_data['crypto_invoice_id'] = invoice.invoice_id
        context.user_data['crypto_amount_credits'] = amount_credits

        keyboard = [[InlineKeyboardButton("Проверить пополнение", callback_data=f"check_crypto_payment:{invoice.invoice_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Для пополнения баланса на {amount_credits} кредитов, "
            f"оплатите счет по следующей ссылке:\n{invoice.bot_invoice_url}",
            reply_markup=reply_markup
        )

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
    except Exception as e:
        # logger.error(f"Error in handle_crypto_topup: {e}", exc_info=True)
        await update.message.reply_text("Произошла ошибка при создании счета.")
    finally:
        if 'crypto_topup' in context.user_data:
            del context.user_data['crypto_topup']


async def check_crypto_payment_handler(update: Update, context: CallbackContext, cryptopay) -> None:
    """Проверяет статус платежа CryptoBot."""
    query = update.callback_query
    await query.answer()

    _, invoice_id = query.data.split(":")
    invoice_id = int(invoice_id)

    try:
        invoices = await cryptopay.get_invoices(invoice_ids=invoice_id)
        invoice = invoices

        if invoice.status == 'paid':
            user_id = query.from_user.id
            amount_credits = context.user_data.get('crypto_amount_credits')
            if amount_credits:
                add_balance(user_id, amount_credits)
                new_balance = get_balance(user_id)
                await query.edit_message_text(
                    f"✅ Платёж прошёл успешно! Ваш баланс пополнен на {amount_credits} кредитов.\n"
                    f"Новый баланс: {new_balance} кредитов."
                )
                del context.user_data['crypto_invoice_id']
                del context.user_data['crypto_amount_credits']
            else:
                await query.edit_message_text("Произошла ошибка при пополнении. Обратитесь в поддержку.")
        else:
            await query.message.reply_text("Платёж еще не подтвержден.")

    except Exception as e:
        # logger.error(f"Error in check_crypto_payment_handler: {e}", exc_info=True)
        await query.edit_message_text("Произошла ошибка при проверке платежа.")
