"""
Email notification service using aiosmtplib.
Sends an HTML email when a price alert is triggered.
"""

import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import settings


def _build_alert_html(
    product_name: str,
    current_price: float,
    target_price: float,
    product_url: str,
    product_image: str | None,
) -> str:
    """Return the HTML body for a price-alert email."""
    image_block = (
        f'<img src="{product_image}" alt="{product_name}" '
        f'style="max-width:300px;border-radius:12px;margin:16px 0;" />'
        if product_image
        else ""
    )
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<style>
  body {{
    font-family: 'Helvetica Neue', Arial, sans-serif;
    background: #FAFAF8;
    color: #2D3748;
    margin: 0;
    padding: 0;
  }}
  .container {{
    max-width: 560px;
    margin: 40px auto;
    background: #fff;
    border-radius: 20px;
    padding: 40px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
  }}
  .logo {{
    font-size: 22px;
    font-weight: 700;
    color: #5C7A5C;
    margin-bottom: 32px;
  }}
  .dot {{
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #5C7A5C;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
  }}
  h1 {{ font-size: 24px; margin: 0 0 8px; }}
  .price-row {{
    display: flex;
    gap: 24px;
    margin: 24px 0;
    align-items: center;
  }}
  .price-box {{
    background: #E8F0E8;
    border-radius: 12px;
    padding: 16px 24px;
    text-align: center;
  }}
  .price-box.current {{ background: #E8F0E8; }}
  .price-box.target  {{ background: #F5E6EC; }}
  .price-label {{ font-size: 12px; color: #4A5568; margin-bottom: 4px; }}
  .price-value {{ font-size: 28px; font-weight: 700; color: #5C7A5C; }}
  .price-box.target .price-value {{ color: #8B5E6B; }}
  .btn {{
    display: inline-block;
    background: #5C7A5C;
    color: #fff !important;
    text-decoration: none;
    padding: 14px 32px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 15px;
    margin-top: 16px;
  }}
  .footer {{
    margin-top: 40px;
    font-size: 12px;
    color: #4A5568;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="logo"><span class="dot"></span>PriceHound</div>
  <h1>Your target price was reached!</h1>
  <p style="color:#4A5568;">{product_name}</p>
  {image_block}
  <div class="price-row">
    <div class="price-box current">
      <div class="price-label">Current price</div>
      <div class="price-value">${current_price:.2f}</div>
    </div>
    <div style="font-size:24px;color:#4A5568;">≤</div>
    <div class="price-box target">
      <div class="price-label">Your target</div>
      <div class="price-value">${target_price:.2f}</div>
    </div>
  </div>
  <a href="{product_url}" class="btn">View Product →</a>
  <div class="footer">
    You're receiving this because you set a price alert on PriceHound.<br />
    The alert has been deactivated automatically.
  </div>
</div>
</body>
</html>
"""


async def send_alert_email(
    recipient: str,
    product_name: str,
    current_price: float,
    target_price: float,
    product_url: str,
    product_image: str | None = None,
) -> None:
    """
    Send a price-alert notification email to *recipient*.
    Raises an exception if sending fails (logged by the scheduler).
    """
    from_addr = settings.smtp_from or settings.smtp_user
    if not from_addr:
        raise ValueError("SMTP_USER or SMTP_FROM must be configured to send emails.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🐶 Price drop! {product_name[:60]} is now ${current_price:.2f}"
    msg["From"] = f"PriceHound <{from_addr}>"
    msg["To"] = recipient

    html_body = _build_alert_html(
        product_name=product_name,
        current_price=current_price,
        target_price=target_price,
        product_url=product_url,
        product_image=product_image,
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
