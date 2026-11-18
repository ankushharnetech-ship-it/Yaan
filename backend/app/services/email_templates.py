"""Branded HTML + plain-text email layouts. Every email greets the recipient by name and shows its facts in a table.

`render()` is the one layout; the `*_email()` helpers fill it for each kind of message and return (text, html).
All dynamic values are HTML-escaped. Driver emails never mention an OTP (spec: the driver never receives it).
"""
from html import escape

BRAND = "#0f766e"
BRAND_DARK = "#115e59"
BRAND_LIGHT = "#f0fdfa"
TEXT = "#0f1f24"
MUTED = "#5b6b72"
BORDER = "#e2e8eb"


def render(*, heading: str, name: str, intro: str, details: list[tuple[str, str]] | None = None, otp: str | None = None,
           otp_note: str = "", button: tuple[str, str] | None = None, notes: list[str] | None = None,
           preheader: str = "") -> tuple[str, str]:
    """Returns (plain_text, html)."""
    details, notes = details or [], notes or []
    e = escape

    # ---- plain text
    t = [f"Hello {name},", "", intro, ""]
    if details:
        width = max(len(k) for k, _ in details)
        t += [f"{k.ljust(width)} : {v}" for k, v in details] + [""]
    if otp:
        t += [f"Your OTP is {otp}. {otp_note}".strip(), ""]
    if button:
        t += [f"{button[0]}:", button[1], ""]
    for n in notes:
        t += [n, ""]
    t += ["— Team YAAN", "Employee Transport Management"]
    text = "\n".join(t)

    # ---- html
    rows = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px solid {BORDER};color:{MUTED};font-size:14px;width:38%;vertical-align:top">{e(k)}</td>'
        f'<td style="padding:10px 0 10px 12px;border-bottom:1px solid {BORDER};color:{TEXT};font-size:14px;font-weight:600;vertical-align:top">{e(v)}</td></tr>'
        for k, v in details)
    details_html = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0 4px;'
                    f'border-top:1px solid {BORDER}">{rows}</table>') if details else ""
    otp_html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:22px 0 4px"><tr>'
        f'<td align="center" style="background:{BRAND_LIGHT};border:1px dashed {BRAND};border-radius:12px;padding:18px">'
        f'<div style="font-size:13px;color:{MUTED};margin-bottom:6px">Your drop-off OTP</div>'
        f'<div style="font-size:34px;font-weight:800;letter-spacing:10px;color:{BRAND_DARK};font-family:Consolas,Menlo,monospace">{e(otp)}</div>'
        f'<div style="font-size:13px;color:{MUTED};margin-top:8px">{e(otp_note)}</div>'
        f'</td></tr></table>') if otp else ""
    button_html = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:26px 0 6px"><tr>'
        f'<td style="background:{BRAND};border-radius:10px"><a href="{e(button[1], quote=True)}" '
        f'style="display:inline-block;padding:13px 26px;color:#ffffff;font-size:15px;font-weight:700;text-decoration:none">{e(button[0])}</a></td></tr></table>'
        f'<p style="margin:10px 0 0;font-size:12px;color:{MUTED};word-break:break-all">Button not working? Copy this link into your browser:<br>'
        f'<a href="{e(button[1], quote=True)}" style="color:{BRAND}">{e(button[1])}</a></p>') if button else ""
    notes_html = "".join(f'<p style="margin:16px 0 0;font-size:13px;line-height:1.55;color:{MUTED}">{e(n)}</p>' for n in notes)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(heading)}</title></head>
<body style="margin:0;padding:0;background:#f6f8f9;font-family:Arial,Helvetica,sans-serif;color:{TEXT}">
<span style="display:none;max-height:0;overflow:hidden;opacity:0">{e(preheader or intro)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f8f9;padding:24px 12px"><tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border:1px solid {BORDER};border-radius:14px;overflow:hidden">
    <tr><td style="background:{BRAND};padding:20px 28px;color:#ffffff;font-size:22px;font-weight:800;letter-spacing:.5px">YAAN
      <span style="font-size:12px;font-weight:400;opacity:.85;margin-left:8px">Employee Transport</span></td></tr>
    <tr><td style="padding:28px">
      <h1 style="margin:0 0 14px;font-size:22px;line-height:1.3;color:{TEXT}">{e(heading)}</h1>
      <p style="margin:0 0 6px;font-size:15px;line-height:1.6">Hello <strong>{e(name)}</strong>,</p>
      <p style="margin:0;font-size:15px;line-height:1.6;color:{TEXT}">{e(intro)}</p>
      {details_html}{otp_html}{button_html}{notes_html}
    </td></tr>
    <tr><td style="padding:16px 28px;background:#f6f8f9;border-top:1px solid {BORDER};font-size:12px;color:{MUTED}">
      Sent by YAAN · Employee Transport Management<br>This is an automated message, please do not reply.</td></tr>
  </table>
</td></tr></table></body></html>"""
    return text, html


# --------------------------------------------------------------------------- account emails
def onboarding(name: str, username: str, role: str, expires: str, days: int, link: str) -> tuple[str, str]:
    return render(
        heading="Welcome to YAAN", name=name, preheader="Set your password to start using YAAN",
        intro="An account has been created for you on YAAN. Use the button below to set your own password and sign in.",
        details=[("Name", name), ("Username", username), ("Role", role), ("Link valid until", f"{expires} ({days} days)")],
        button=("Set your password", link),
        notes=["Your administrator may also have given you a temporary password. If you sign in with it, you will be asked to choose a new password straight away.",
               "If the link has expired, open the sign-in page and choose 'Forgot password'."])


def password_reset(name: str, minutes: int, link: str) -> tuple[str, str]:
    return render(
        heading="Reset your password", name=name, preheader="Use this link to choose a new password",
        intro="We received a request to reset the password of your YAAN account. Use the button below to choose a new one.",
        details=[("Link valid for", f"{minutes} minutes"), ("Can be used", "Once")],
        button=("Reset password", link),
        notes=["If you did not ask for this, you can safely ignore this email — your password will not change."])


# --------------------------------------------------------------------------- trip emails
_HEADINGS = {
    "trip_created_driver": ("New trip assigned to you", "A new trip has been assigned to you. Please review the details and accept it in YAAN."),
    "trip_created_employee": ("Your trip is booked", "Your trip has been booked. Here are the details."),
    "trip_cancelled_driver": ("Trip cancelled", "The trip below has been cancelled. No action is needed from you."),
    "trip_cancelled_employee": ("Your trip was cancelled", "The trip below has been cancelled."),
    "trip_reassigned_driver": ("Trip assigned to you", "The trip below is now assigned to you. Please review the details and accept it in YAAN."),
    "trip_unassigned_driver": ("Trip reassigned", "The trip below has been reassigned to another driver. No action is needed from you."),
    "trip_reassigned_employee": ("Update for your trip", "There is an update to your trip. Your driver or vehicle has changed."),
}


def trip(template: str, name: str, c: dict, otp: str | None, app_url: str) -> tuple[str, str]:
    """`c` carries: code, date, time, customer, site, trip_type, pickup, drop, vehicle, driver_name, driver_phone (full addresses)."""
    heading, intro = _HEADINGS[template]
    who_driver = template.endswith("_driver")
    cancelled = "cancelled" in template or template == "trip_unassigned_driver"
    d: list[tuple[str, str]] = [("Trip", c["code"]), ("Date", c["date"]), ("Pickup time", c["time"])]
    if not cancelled:
        if who_driver:
            d += [("Customer", f'{c["customer"]} ({c["site"]})')]
        if c.get("trip_type"):
            d += [("Trip type", c["trip_type"])]
        d += [("Pickup", c["pickup"]), ("Drop", c["drop"])]
        if not who_driver:
            d += [("Driver", f'{c["driver_name"]} ({c["driver_phone"]})')]
        d += [("Vehicle", c["vehicle"])]
    notes = []
    button = None
    if who_driver and not cancelled:
        button = ("Open YAAN to accept", app_url)
    if template == "trip_created_employee":
        notes = ["Be ready at your pickup point on time. Keep your OTP private until you reach your drop point."]
    return render(heading=heading, name=name, intro=intro, details=d, button=button, notes=notes,
                  otp=otp if template == "trip_created_employee" else None,
                  otp_note="Share it with the driver only when you reach your drop point.",
                  preheader=f"{heading} — trip {c['code']} on {c['date']} at {c['time']}")
