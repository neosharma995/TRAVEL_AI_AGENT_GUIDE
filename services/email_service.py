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


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _fmt(val) -> str:
    """Format a number as Rs. with commas, or return as string if not numeric."""
    try:
        num = float(str(val).replace(",", "").replace("Rs.", "").strip())
        return f"Rs.{num:,.0f}"
    except (ValueError, TypeError):
        return str(val) if val is not None else "—"


def _row(label: str, value: str, bold: bool = False, color: str = "#1E293B") -> str:
    weight = "700" if bold else "500"
    return f"""
      <tr>
        <td style="padding:7px 0;color:#64748B;font-size:13px;width:45%;vertical-align:top;">{label}</td>
        <td style="padding:7px 0;color:{color};font-size:13px;font-weight:{weight};vertical-align:top;">{value}</td>
      </tr>"""


def _section(title: str, icon: str, rows_html: str) -> str:
    return f"""
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#F8FAFC;border-radius:12px;overflow:hidden;margin-bottom:18px;">
        <tr>
          <td style="background:#1E293B;padding:11px 20px;">
            <p style="margin:0;color:#ffffff;font-size:12px;font-weight:700;letter-spacing:1px;">
              {icon}&nbsp; {title}
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 20px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              {rows_html}
            </table>
          </td>
        </tr>
      </table>"""


def _divider() -> str:
    return '<tr><td colspan="2" style="border-top:1px dashed #E2E8F0;padding:4px 0;"></td></tr>'


# ─────────────────────────────────────────────────────────────
# HOTEL EMAIL TEMPLATE
# ─────────────────────────────────────────────────────────────

def _build_hotel_html(item_name: str, d: dict, customer_phone: str, current_time: str) -> str:
    clean_phone = str(customer_phone).lstrip('+').replace(' ', '')
    wa_link     = f"https://wa.me/{clean_phone}"
    ref_id      = d.get('package_id', 'N/A')

    nights        = d.get('nights', 'N/A')
    rooms_needed  = d.get('rooms_needed', 1)
    ppn           = d.get('price_per_night', 0)
    season        = d.get('season_used', 'Regular Rate')
    room_total    = d.get('room_total', 0)
    extra_people  = d.get('extra_people', 0)
    extra_total   = d.get('extra_total', 0)
    meal_plan     = d.get('meal_plan', 'N/A')
    meal_total    = d.get('meal_total', 0)
    subtotal      = d.get('subtotal', 0)
    tax_rate      = d.get('tax_rate', 0)
    tax_amount    = d.get('tax_amount', 0)
    grand_total   = d.get('grand_total', 0)
    travellers    = d.get('travellers', 'N/A')
    destination   = d.get('destinations', 'N/A')
    check_in      = d.get('travel_dates', 'N/A')
    hotel_cat     = d.get('hotel_category', 'N/A')
    room_cat      = d.get('room_category', 'N/A')
    room_type     = d.get('room_type', 'N/A')

    # ── Customer rows
    customer_rows = (
        _row("WhatsApp Number", f"+{clean_phone}")
      + _row("Quick Link", f'<a href="{wa_link}" style="color:#6C63FF;font-weight:600;text-decoration:none;">💬 Open WhatsApp →</a>')
    )

    # ── Hotel details rows
    hotel_rows = (
        _row("Hotel Name", f"<strong>{item_name}</strong>")
      + _row("Category", hotel_cat)
      + _row("Destination", f"📍 {destination}")
      + _row("Travel Dates", f"📅 {check_in}")
      + _row("Travellers", f"👥 {travellers} Person(s)")
      + _row("Booking Reference", f'<span style="background:#EDE9FE;color:#5B21B6;padding:3px 10px;border-radius:6px;font-size:12px;font-weight:700;">{ref_id}</span>')
    )

    # ── Room rows
    room_rows = (
        _row("Room Category", room_cat)
      + _row("Room Type", room_type)
      + _row("No. of Rooms", str(rooms_needed))
      + _row("No. of Nights", str(nights))
      + _row("Rate / Room / Night", _fmt(ppn))
      + _row("Season", season)
    )

    # ── Price breakdown rows
    price_rows = _row("Room Charges", _fmt(room_total))
    if extra_people > 0:
        price_rows += _row(f"Extra Person ({extra_people} pax)", _fmt(extra_total))
    if meal_total > 0:
        price_rows += _row(f"Meal Plan ({meal_plan})", _fmt(meal_total))
    price_rows += _divider()
    price_rows += _row("Subtotal", _fmt(subtotal))
    if tax_rate > 0:
        price_rows += _row(f"GST ({int(tax_rate)}%)", _fmt(tax_amount))
    price_rows += _divider()
    price_rows += _row("💵 Total Payable", f'<span style="color:#059669;font-size:16px;font-weight:700;">{_fmt(grand_total)}</span>', bold=True, color="#059669")
    return _wrap_email(
        icon="🏨", type_label="Hotel Booking", item_name=item_name,
        accent="#F97316", current_time=current_time,
        customer_rows=customer_rows, detail_rows=hotel_rows,
        room_rows=room_rows, price_rows=price_rows,
        wa_link=wa_link, clean_phone=clean_phone, item_type="hotel"
    )


# ─────────────────────────────────────────────────────────────
# PACKAGE EMAIL TEMPLATE
# ─────────────────────────────────────────────────────────────

def _build_package_html(item_name: str, d: dict, customer_phone: str, current_time: str) -> str:
    clean_phone = str(customer_phone).lstrip('+').replace(' ', '')
    wa_link     = f"https://wa.me/{clean_phone}"
    ref_id      = d.get('package_id', 'N/A')

    nights              = d.get('nights', 'N/A')
    travellers          = d.get('travellers', 'N/A')
    destination         = d.get('destinations', 'N/A')
    travel_dates        = d.get('travel_dates', 'N/A')
    total_hotel_price   = d.get('total_hotel_price', 0)
    meal_total          = d.get('meal_total', 0)
    vehicle_name        = d.get('vehicle_name', None)
    vehicle_price       = d.get('vehicle_price', 0)
    embedded_price      = d.get('total_embedded_price', 0)
    package_margin      = d.get('package_margin', 0)
    subtotal            = d.get('subtotal', 0)
    tax_rate            = d.get('tax_rate', 0)
    tax_amount          = d.get('tax_amount', 0)
    grand_total         = d.get('grand_total', 0)
    hotel_costs         = d.get('hotel_costs', [])

    # ── Customer rows
    customer_rows = (
        _row("WhatsApp Number", f"+{clean_phone}")
      + _row("Quick Link", f'<a href="{wa_link}" style="color:#6C63FF;font-weight:600;text-decoration:none;">💬 Open WhatsApp →</a>')
    )

    # ── Package details rows
    pkg_rows = (
        _row("Package Name", f"<strong>{item_name}</strong>")
      + _row("Destination", f"📍 {destination}")
      + _row("Start Date", f"📅 {travel_dates}")
      + _row("No. of Nights", str(nights))
      + _row("Travellers", f"👥 {travellers} Person(s)")
      + _row("Booking Reference", f'<span style="background:#EDE9FE;color:#5B21B6;padding:3px 10px;border-radius:6px;font-size:12px;font-weight:700;">{ref_id}</span>')
    )

    # ── Hotel costs per location
    hotel_rows = ""
    if hotel_costs:
        for hc in hotel_costs:
            loc   = hc.get("location", "Hotel")
            hnts  = hc.get("nights", "")
            hprc  = hc.get("total", hc.get("price", 0))
            label = f"{loc}" + (f" ({hnts}N)" if hnts else "")
            hotel_rows += _row(label, _fmt(hprc))
    else:
        if total_hotel_price > 0:
            hotel_rows += _row("Hotel Charges", _fmt(total_hotel_price))

    # ── Price breakdown rows
    price_rows = ""
    if total_hotel_price > 0:
        price_rows += _row("Hotel Charges", _fmt(total_hotel_price))
    if meal_total > 0:
        price_rows += _row("Meal Charges", _fmt(meal_total))
    if vehicle_name and vehicle_price > 0:
        price_rows += _row(f"Vehicle ({vehicle_name})", _fmt(vehicle_price))
    if embedded_price > 0:
        price_rows += _row("Transport (Itinerary)", _fmt(embedded_price))
    if package_margin > 0:
        price_rows += _row("Package Fee", _fmt(package_margin))
    price_rows += _divider()
    price_rows += _row("Subtotal", _fmt(subtotal))
    if tax_rate > 0:
        price_rows += _row(f"GST ({int(tax_rate)}%)", _fmt(tax_amount))
    price_rows += _divider()
    price_rows += _row("💵 Total Payable", f'<span style="color:#059669;font-size:16px;font-weight:700;">{_fmt(grand_total)}</span>', bold=True, color="#059669")

    return _wrap_email(
        icon="📦", type_label="Package Booking", item_name=item_name,
        accent="#6C63FF", current_time=current_time,
        customer_rows=customer_rows, detail_rows=pkg_rows,
        room_rows=hotel_rows, price_rows=price_rows,
        wa_link=wa_link, clean_phone=clean_phone, item_type="package"
    )


# ─────────────────────────────────────────────────────────────
# SHARED HTML WRAPPER
# ─────────────────────────────────────────────────────────────

def _wrap_email(icon, type_label, item_name, accent, current_time,
                customer_rows, detail_rows, room_rows, price_rows,
                wa_link, clean_phone, item_type) -> str:

    room_section_title = "ROOM DETAILS" if item_type == "hotel" else "HOTEL / STAY DETAILS"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>New {type_label} Alert</title>
</head>
<body style="margin:0;padding:0;background:#EEF2FF;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#EEF2FF;padding:28px 0;">
  <tr><td align="center">

    <!-- CARD -->
    <table width="620" cellpadding="0" cellspacing="0"
           style="background:#ffffff;border-radius:16px;overflow:hidden;
                  box-shadow:0 6px 30px rgba(0,0,0,0.10);max-width:620px;width:100%;">

      <!-- HEADER -->
      <tr>
        <td style="background:linear-gradient(135deg,{accent} 0%,#3B82F6 100%);
                    padding:36px 40px 28px;text-align:center;">
          <div style="font-size:36px;margin-bottom:10px;">{icon}</div>
          <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:800;letter-spacing:0.3px;">
            New {type_label} Received!
          </h1>
          <p style="margin:8px 0 0;color:rgba(255,255,255,0.82);font-size:13px;">
            🕐 {current_time}
          </p>
        </td>
      </tr>

      <!-- URGENT BANNER -->
      <tr>
        <td style="background:#FEF2F2;border-left:4px solid #EF4444;padding:13px 32px;">
          <p style="margin:0;color:#B91C1C;font-size:13px;font-weight:600;">
            🚨 URGENT — A customer just confirmed a booking. Contact immediately!
          </p>
        </td>
      </tr>

      <!-- BODY -->
      <tr><td style="padding:28px 32px 10px;">

        <!-- CUSTOMER DETAILS -->
        {_section("CUSTOMER DETAILS", "👤", customer_rows)}

        <!-- BOOKING / PACKAGE DETAILS -->
        {_section("BOOKING DETAILS", "📋", detail_rows)}

        <!-- ROOM / STAY DETAILS -->
        {_section(room_section_title, "🛏️" if item_type == "hotel" else "🏨", room_rows)}

        <!-- PRICE BREAKDOWN -->
        {_section("PRICE BREAKDOWN", "💰", price_rows)}

        <!-- ACTION REQUIRED -->
        <table width="100%" cellpadding="0" cellspacing="0"
               style="background:#FFF7ED;border:1px solid #FED7AA;
                       border-radius:12px;margin-bottom:24px;">
          <tr>
            <td style="padding:18px 22px;">
              <p style="margin:0 0 10px;color:#C2410C;font-size:13px;font-weight:700;letter-spacing:0.5px;">
                ⚡ ACTION REQUIRED
              </p>
              <ul style="margin:0;padding-left:18px;color:#78350F;font-size:13px;line-height:2.0;">
                <li>Call / WhatsApp customer on <strong>+{clean_phone}</strong> immediately</li>
                <li>Confirm availability for the selected dates &amp; options</li>
                <li>Send payment link or invoice to the customer</li>
                <li>Send final booking confirmation on WhatsApp</li>
              </ul>
            </td>
          </tr>
        </table>

        <!-- WHATSAPP BUTTON -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
          <tr>
            <td align="center">
              <a href="{wa_link}"
                 style="display:inline-block;background:linear-gradient(135deg,#25D366,#128C7E);
                         color:#ffffff;text-decoration:none;padding:14px 44px;
                         border-radius:50px;font-size:15px;font-weight:700;letter-spacing:0.4px;">
                💬 &nbsp;Open Customer WhatsApp
              </a>
            </td>
          </tr>
        </table>

      </td></tr>

      <!-- FOOTER -->
      <tr>
        <td style="background:#F8FAFC;border-top:1px solid #E2E8F0;
                    padding:18px 32px;text-align:center;">
          <p style="margin:0;color:#94A3B8;font-size:12px;line-height:1.7;">
            This is an automated notification from your Travel Booking System.<br/>
            Please do not reply to this email.
          </p>
        </td>
      </tr>

    </table>
    <!-- /CARD -->

  </td></tr>
</table>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# MAIN SEND FUNCTION
# ─────────────────────────────────────────────────────────────

def send_admin_booking_alert(booking_details: dict, customer_phone: str, admin_email: str = None):
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

    current_time = datetime.now().strftime('%d %b %Y, %I:%M %p')
    subject      = f"🔔 New {item_type} Booking — {item_name}"

    if item_type == "HOTEL":
        html_body = _build_hotel_html(item_name, booking_details, customer_phone, current_time)
    else:
        html_body = _build_package_html(item_name, booking_details, customer_phone, current_time)

    print(f"📧 Sending booking alert → {to_email}")
    return _send_email(to_email, subject, html_body)


# ─────────────────────────────────────────────────────────────
# SMTP SENDER
# ─────────────────────────────────────────────────────────────

def _send_email(recipient: str, subject: str, html_body: str) -> bool:
    """Send HTML email via SMTP with TLS. From header uses FROM_EMAIL env var."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("❌ SMTP credentials missing — set SMTP_USER and SMTP_PASSWORD in .env")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['From']    = f"no-reply <{FROM_EMAIL}>"
        msg['To']      = recipient
        msg['Subject'] = subject

        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

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