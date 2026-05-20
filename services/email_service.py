import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('.env')

SMTP_HOST     = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT     = int(os.getenv('SMTP_PORT', 587))
SMTP_USER     = os.getenv('SMTP_USER', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
FROM_EMAIL    = os.getenv('FROM_EMAIL', '') or SMTP_USER
# Fallback only — real email comes from API response user.email via bot.py
ADMIN_EMAIL   = os.getenv('ADMIN_EMAIL', '')


def send_admin_booking_alert(booking_details, customer_phone, admin_email=None):
    """
    Send booking alert to the partner/admin.

    Email priority:
      1. admin_email argument  — passed from state["partner_email"] (API user.email)
      2. ADMIN_EMAIL env var   — fallback if API email not available
    """
    to_email = (admin_email or "").strip() or ADMIN_EMAIL.strip()

    if not to_email:
        print("❌ No partner/admin email found — set ADMIN_EMAIL in .env as fallback")
        return False

    # Determine booking type
    raw_name = booking_details.get('package_name', 'N/A')
    if raw_name.startswith('Hotel:'):
        item_type = "HOTEL"
        item_name = raw_name.replace('Hotel:', '').strip()
    else:
        item_type = "PACKAGE"
        item_name = raw_name

    subject = f"NEW {item_type} BOOKING - {item_name}"
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    body = f"""NEW BOOKING REQUEST RECEIVED
Time: {current_time}

CUSTOMER DETAILS
WhatsApp Number: {customer_phone}

BOOKING DETAILS
{item_type}: {item_name}
ID: {booking_details.get('package_id', 'N/A')}
Total Price: {booking_details.get('package_price', 'N/A')}
Per Person Price: {booking_details.get('per_person_price', 'N/A')}

TRAVEL DETAILS
Travel Dates: {booking_details.get('travel_dates', 'Not specified')}
Travelers:    {booking_details.get('travellers', 'Not specified')}
Destination:  {booking_details.get('destinations', 'Not specified')}

ACTION REQUIRED
- Contact customer on WhatsApp immediately: {customer_phone}
- Confirm {item_type} availability
- Process payment
- Send final confirmation

URGENT — Customer is waiting for your call!
Customer WhatsApp: {customer_phone}
"""

    print(f"📧 Sending booking alert → {to_email}")
    return _send_email(to_email, subject, body)


def _send_email(recipient, subject, body):
    """Send plain-text email via SMTP with TLS."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("❌ SMTP credentials missing — set SMTP_USER and SMTP_PASSWORD in .env")
        return False

    try:
        msg = MIMEMultipart()
        msg['From']    = FROM_EMAIL
        msg['To']      = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"✅ Email sent to {recipient}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("❌ SMTP auth failed — check SMTP_USER / SMTP_PASSWORD in .env")
        return False
    except smtplib.SMTPException as e:
        print(f"❌ SMTP error: {e}")
        return False
    except Exception as e:
        print(f"❌ Email send failed: {e}")
        return False