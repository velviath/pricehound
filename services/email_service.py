"""
Email notification service using aiosmtplib.
Sends an HTML email when a price alert is triggered.
"""
from __future__ import annotations

import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import settings


_CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$", "AUD": "A$",
    "CHF": "Fr ", "JPY": "¥", "CNY": "¥", "HKD": "HK$", "SGD": "S$",
    "KRW": "₩", "INR": "₹", "SEK": "kr ", "NOK": "kr ", "DKK": "kr ",
    "PLN": "zł ", "CZK": "Kč ", "HUF": "Ft ", "RON": "lei ", "BGN": "лв ",
    "UAH": "₴", "TRY": "₺", "AED": "د.إ ", "SAR": "﷼ ", "ILS": "₪",
    "BRL": "R$", "MXN": "MX$", "ZAR": "R ", "NZD": "NZ$", "THB": "฿",
    "MYR": "RM ", "IDR": "Rp ", "PHP": "₱",
}


def _fmt(amount: float, currency: str) -> str:
    sym = _CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{sym}{amount:.2f}"


def _build_alert_html(
    product_name: str,
    old_price: float,
    current_price: float,
    target_price: float,
    product_page_url: str,
    product_image: str | None,
    currency: str = "USD",
) -> str:
    dropped = current_price < old_price
    badge_bg    = "#E6F0E6" if dropped else "#F5EEF0"
    badge_color = "#4A7A4A" if dropped else "#8B5E6B"
    badge_text  = "&#x2193; Price dropped" if dropped else "&#x2191; Price rose"
    headline    = "Your target price was reached!"
    now_color   = "#5C7A5C" if dropped else "#8B5E6B"

    image_block = ""
    if product_image:
        image_block = f"""
        <tr>
          <td align="center" style="padding:24px 0 8px;">
            <img src="{product_image}" width="220" alt=""
                 style="display:block;width:220px;height:auto;border-radius:14px;border:1px solid #EFEFED;" />
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>PriceHound Alert</title>
<style>
  @media only screen and (max-width: 480px) {{
    .price-val {{ font-size: 24px !important; }}
    .price-td  {{ padding: 16px 12px !important; }}
    .card-wrap {{ padding: 24px 20px 20px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:#FAFAF8;font-family:'Helvetica Neue',Arial,sans-serif;color:#2D3748;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#FAFAF8;padding:40px 16px;">
  <tr>
    <td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:540px;">

        <!-- Logo -->
        <tr>
          <td style="padding:0 0 28px;">
            <span style="font-size:22px;font-weight:800;color:#5C7A5C;letter-spacing:-0.5px;">
              &#9679;&nbsp;PriceHound
            </span>
          </td>
        </tr>

        <!-- Card -->
        <tr>
          <td class="card-wrap" style="background:#ffffff;border-radius:20px;border:1.5px solid #EFEFED;padding:36px 36px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0">

              <!-- Badge -->
              <tr>
                <td style="padding-bottom:20px;">
                  <span style="display:inline-block;background:{badge_bg};color:{badge_color};font-size:12px;font-weight:700;padding:5px 14px;border-radius:100px;">
                    {badge_text}
                  </span>
                </td>
              </tr>

              <!-- Headline -->
              <tr>
                <td style="padding-bottom:8px;">
                  <h1 style="margin:0;font-size:24px;font-weight:800;color:#1A202C;line-height:1.3;">{headline}</h1>
                </td>
              </tr>

              <!-- Product name -->
              <tr>
                <td style="padding-bottom:4px;">
                  <p style="margin:0;font-size:17px;font-weight:600;color:#2D3748;line-height:1.5;">{product_name}</p>
                </td>
              </tr>

              {image_block}

              <!-- Divider -->
              <tr><td style="padding:20px 0 0;"><div style="height:1px;background:#F0F0EC;"></div></td></tr>

              <!-- Prices -->
              <tr>
                <td style="padding:28px 0;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td class="price-td" width="46%" style="background:#F7F7F5;border-radius:14px;padding:20px 16px;text-align:center;vertical-align:middle;">
                        <div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">Was</div>
                        <div class="price-val" style="font-size:32px;font-weight:800;color:#718096;line-height:1;text-decoration:line-through;">{_fmt(old_price, currency)}</div>
                      </td>
                      <td width="8%" style="text-align:center;vertical-align:middle;">
                        <span style="font-size:28px;font-weight:700;color:#2D3748;line-height:1;">&#8594;</span>
                      </td>
                      <td class="price-td" width="46%" style="background:#F7F7F5;border-radius:14px;padding:20px 16px;text-align:center;vertical-align:middle;">
                        <div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">Now</div>
                        <div class="price-val" style="font-size:32px;font-weight:800;color:{now_color};line-height:1;">{_fmt(current_price, currency)}</div>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- Target -->
              <tr>
                <td style="padding-bottom:24px;text-align:center;">
                  <span style="font-size:13px;color:#A0AEC0;">Your target: <strong style="color:#718096;">{_fmt(target_price, currency)}</strong></span>
                </td>
              </tr>

              <!-- CTA -->
              <tr>
                <td style="padding-bottom:8px;text-align:center;">
                  <a href="{product_page_url}"
                     style="display:inline-block;background:#5C7A5C;color:#ffffff;text-decoration:none;padding:15px 30px;border-radius:12px;font-size:15px;font-weight:700;">
                    View on PriceHound &#8594;
                  </a>
                </td>
              </tr>

            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:24px 4px 0;">
            <p style="margin:0;font-size:12px;color:#A0AEC0;line-height:1.7;">
              You're receiving this because you set a price alert on PriceHound.<br />
              The alert has been deactivated automatically.
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>

</body>
</html>"""


async def send_alert_email(
    recipient: str,
    product_name: str,
    old_price: float,
    current_price: float,
    target_price: float,
    product_id: int,
    product_image: str | None = None,
    currency: str = "USD",
) -> None:
    """
    Send a price-alert notification email to *recipient*.
    Raises an exception if sending fails (logged by the scheduler).
    """
    from_addr = settings.smtp_from or settings.smtp_user
    if not from_addr:
        raise ValueError("SMTP_USER or SMTP_FROM must be configured to send emails.")

    base = (settings.app_host or "").rstrip("/")
    product_page_url = f"{base}/product?id={product_id}"

    dropped = current_price <= target_price
    subject_price = _fmt(current_price, currency)
    subject = (
        f"🐶 Price drop! {product_name[:55]} is now {subject_price}"
        if dropped
        else f"🔔 Price alert: {product_name[:55]} hit {subject_price}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"PriceHound <{from_addr}>"
    msg["To"]      = recipient

    html_body = _build_alert_html(
        product_name=product_name,
        old_price=old_price,
        current_price=current_price,
        target_price=target_price,
        product_page_url=product_page_url,
        product_image=product_image,
        currency=currency,
    )
    msg.attach(MIMEText(html_body, "html"))

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
    )


async def _send(msg: MIMEMultipart) -> None:
    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
    )


def _base_email(from_addr: str, recipient: str, subject: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"PriceHound <{from_addr}>"
    msg["To"]      = recipient
    return msg


def _email_wrap(content: str, footer: str = "") -> str:
    footer_html = f'<p style="margin:0;font-size:12px;color:#A0AEC0;line-height:1.7;">{footer}</p>' if footer else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>PriceHound</title></head>
<body style="margin:0;padding:0;background:#FAFAF8;font-family:'Helvetica Neue',Arial,sans-serif;color:#2D3748;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#FAFAF8;padding:40px 16px;">
  <tr><td align="center">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width:540px;">
      <tr><td style="padding:0 0 28px;">
        <span style="font-size:22px;font-weight:800;color:#5C7A5C;letter-spacing:-0.5px;">&#9679;&nbsp;PriceHound</span>
      </td></tr>
      <tr><td style="background:#ffffff;border-radius:20px;border:1.5px solid #EFEFED;padding:36px 36px 32px;">
        {content}
      </td></tr>
      {'<tr><td style="padding:24px 4px 0;">' + footer_html + '</td></tr>' if footer_html else ''}
    </table>
  </td></tr>
</table>
</body></html>"""


async def send_inactive_email(recipient: str) -> None:
    from_addr = settings.smtp_from or settings.smtp_user
    if not from_addr:
        return

    base = (settings.app_host or "").rstrip("/")
    content = f"""
    <h1 style="margin:0 0 12px;font-size:22px;font-weight:800;color:#1A202C;">Auto-tracking paused</h1>
    <p style="margin:0 0 20px;font-size:15px;color:#4A5568;line-height:1.6;">
      We haven't seen you in a while, so we've paused automatic price tracking for your products to save resources.
    </p>
    <p style="margin:0 0 28px;font-size:15px;color:#4A5568;line-height:1.6;">
      Just visit your dashboard and refresh any product price — tracking will resume instantly.
    </p>
    <table width="100%" cellpadding="0" cellspacing="0"><tr><td style="text-align:center;">
      <a href="{base}/dashboard"
         style="display:inline-block;background:#5C7A5C;color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:12px;font-size:15px;font-weight:700;">
        Go to Dashboard &#8594;
      </a>
    </td></tr></table>"""

    msg = _base_email(from_addr, recipient, "⏸ Price tracking has been paused")
    msg.attach(MIMEText(_email_wrap(content, "You're receiving this because you have an account on PriceHound."), "html"))
    await _send(msg)


async def send_unavailable_email(
    recipient: str,
    product_name: str,
    product_id: int,
    product_image: str | None = None,
) -> None:
    from_addr = settings.smtp_from or settings.smtp_user
    if not from_addr:
        return

    base = (settings.app_host or "").rstrip("/")
    product_url = f"{base}/product?id={product_id}"

    image_block = ""
    if product_image:
        image_block = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;">
          <tr><td style="text-align:center;">
            <img src="{product_image}" width="160" alt=""
                 style="display:block;margin:0 auto;width:160px;height:auto;border-radius:12px;border:1px solid #EFEFED;" />
          </td></tr>
        </table>"""

    content = f"""
    <span style="display:inline-block;background:#F5EEF0;color:#8B5E6B;font-size:12px;font-weight:700;padding:5px 14px;border-radius:100px;margin-bottom:20px;">
      &#x26A0; No longer available
    </span>
    <h1 style="margin:0 0 12px;font-size:22px;font-weight:800;color:#1A202C;">A product you track is unavailable</h1>
    <p style="margin:0 0 4px;font-size:16px;font-weight:600;color:#2D3748;">{product_name}</p>
    {image_block}
    <p style="margin:16px 0 28px;font-size:14px;color:#718096;line-height:1.6;">
      This listing appears to be sold out or removed. Automatic tracking has been paused — you can refresh the price manually to check if it's back.
    </p>
    <table width="100%" cellpadding="0" cellspacing="0"><tr><td style="text-align:center;">
      <a href="{product_url}"
         style="display:inline-block;background:#5C7A5C;color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:12px;font-size:15px;font-weight:700;">
        View on PriceHound &#8594;
      </a>
    </td></tr></table>"""

    msg = _base_email(from_addr, recipient, f"⚠️ {product_name[:60]} is no longer available")
    msg.attach(MIMEText(_email_wrap(content, "You're receiving this because you're tracking this product on PriceHound."), "html"))
    await _send(msg)


async def send_password_reset_email(recipient: str, code: str) -> None:
    from_addr = settings.smtp_from or settings.smtp_user
    if not from_addr:
        return

    content = f"""
    <h1 style="margin:0 0 12px;font-size:22px;font-weight:800;color:#1A202C;">Reset your password</h1>
    <p style="margin:0 0 24px;font-size:15px;color:#4A5568;line-height:1.6;">
      Use the code below to reset your PriceHound password. It expires in <strong>15 minutes</strong>.
    </p>
    <div style="background:#F7F7F5;border-radius:14px;padding:24px;text-align:center;margin-bottom:28px;">
      <div style="font-size:36px;font-weight:800;letter-spacing:10px;color:#1A202C;">{code}</div>
    </div>
    <p style="margin:0;font-size:13px;color:#A0AEC0;line-height:1.6;">
      If you didn't request this, you can safely ignore this email.
    </p>"""

    msg = _base_email(from_addr, recipient, "🔑 Your PriceHound password reset code")
    msg.attach(MIMEText(_email_wrap(content), "html"))
    await _send(msg)
