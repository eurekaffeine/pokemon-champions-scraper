# src/notify.py
"""Telegram notification module for scraper status updates."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


def send_telegram_notification(
    message: str,
    chat_id: str,
    bot_token: str,
    parse_mode: Optional[str] = "HTML",
    disable_notification: bool = False,
    timeout: float = 10.0,
) -> bool:
    """
    Send a notification message via Telegram Bot API.
    
    Args:
        message: The message text to send
        chat_id: Telegram chat ID (user, group, or channel)
        bot_token: Telegram bot token from @BotFather
        parse_mode: Message parse mode ('HTML', 'Markdown', 'MarkdownV2', or None)
        disable_notification: If True, sends silently
        timeout: Request timeout in seconds
        
    Returns:
        True if message was sent successfully, False otherwise
        
    Example:
        >>> send_telegram_notification(
        ...     message="✅ Scrape complete! 100 Pokémon updated.",
        ...     chat_id="123456789",
        ...     bot_token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
        ... )
        True
    """
    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not provided, skipping notification")
        return False
    
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_notification": disable_notification,
    }
    
    if parse_mode:
        payload["parse_mode"] = parse_mode
    
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            if result.get("ok"):
                logger.info(f"Telegram notification sent to chat {chat_id}")
                return True
            else:
                logger.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
                return False
                
    except httpx.TimeoutException:
        logger.error("Telegram notification timed out")
        return False
    except httpx.HTTPStatusError as e:
        logger.error(f"Telegram API HTTP error: {e.response.status_code} - {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False


def format_scrape_result(
    success: bool,
    pokemon_count: int = 0,
    duration_seconds: Optional[float] = None,
    error_message: Optional[str] = None,
) -> str:
    """
    Format a scrape result into a notification message.
    
    Args:
        success: Whether the scrape succeeded
        pokemon_count: Number of Pokémon scraped
        duration_seconds: How long the scrape took
        error_message: Error message if failed
        
    Returns:
        Formatted message string
    """
    if success:
        msg = f"✅ <b>Pokémon Champions Scrape Complete!</b>\n\n"
        msg += f"📊 <b>{pokemon_count}</b> Pokémon updated\n"
        if duration_seconds:
            msg += f"⏱️ Duration: {duration_seconds:.1f}s\n"
        msg += f"\n🔗 Data available at your configured endpoint"
    else:
        msg = f"❌ <b>Pokémon Champions Scrape Failed!</b>\n\n"
        if error_message:
            msg += f"⚠️ Error: <code>{error_message}</code>\n"
        msg += f"\n📋 Check workflow logs for details"
    
    return msg
