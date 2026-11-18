# YAAN — SMS templates

These are the exact messages the app sends (source: `backend/app/services/notifications.py`, `TEMPLATES`).
Each is shown in **DLT registration format**, where `{#var#}` is a variable (max 30 characters each on most
operators — see note below).

> **Important — read before sending to Indian numbers**
> * Indian carriers only deliver *registered* commercial SMS: you register a **Header (sender ID)**, a **Principal Entity (PE)**
>   and each **template** on a DLT portal (Jio TrueConnect, Airtel, Vodafone-Idea, BSNL). The text sent must match a
>   registered template; only the `{#var#}` parts may change.
> * The Twilio number configured today (`+1 737…`) is a **US number**. US long-code numbers are generally blocked or
>   filtered for India-bound traffic, and a Twilio **trial** account can only message *verified* numbers.
>   For production in India use Twilio's India-registered sender (DLT-registered header + template IDs) or an
>   India SMS provider — the provider sits behind `app/services/sms.py`, so swapping it is a one-file change.
> * Variables that hold addresses can be long; the app shortens addresses to 90 characters. If your operator caps
>   `{#var#}` at 30 characters, split addresses or tell me and I will shorten further.

Category suggested: **Service-Implicit / Transactional**.

| Key | When it is sent | DLT template text |
|---|---|---|
| `trip_created_driver` | Trip created → assigned driver | `YAAN: New trip {#var#} on {#var#} at {#var#}. Customer: {#var#} ({#var#}). Pickup: {#var#}. Drop: {#var#}. Vehicle: {#var#}. Please open YAAN to accept.` |
| `trip_created_employee` | Trip created → each passenger | `YAAN: Trip {#var#} booked for {#var#} at {#var#}. Pickup: {#var#}. Drop: {#var#}. Driver: {#var#} ({#var#}). Vehicle: {#var#}. Your OTP is {#var#}. Share it with the driver only when you reach your drop point.` |
| `trip_cancelled_driver` | Trip cancelled → driver (setting `sms_on_cancellation`, default **on**) | `YAAN: Trip {#var#} scheduled for {#var#} at {#var#} has been cancelled. No action needed.` |
| `trip_cancelled_employee` | Trip cancelled → each passenger | `YAAN: Your trip {#var#} scheduled for {#var#} at {#var#} has been cancelled.` |
| `trip_reassigned_driver` | Driver changed → new driver (setting `sms_on_reassignment`, default **off**) | `YAAN: Trip {#var#} on {#var#} at {#var#} is now assigned to you. Pickup: {#var#}. Drop: {#var#}. Vehicle: {#var#}. Please open YAAN to accept.` |
| `trip_unassigned_driver` | Driver changed → previous driver | `YAAN: Trip {#var#} on {#var#} at {#var#} has been reassigned to another driver. No action needed.` |
| `trip_reassigned_employee` | Driver or vehicle changed → each passenger | `YAAN: Update for trip {#var#} on {#var#} at {#var#}. Driver: {#var#} ({#var#}). Vehicle: {#var#}.` |

## OTP and channels
* `trip_created_employee` carries the employee's 4-digit drop-off OTP. The stored log text holds a placeholder (shown as `••••`); the real code is substituted only at the moment of sending. The **driver never receives an OTP**.
* The same messages go out by **Email** (subject + body) when Email is enabled in Settings. SMS and Email are switched on/off per vendor (default SMS on, Email off). Both on = both are sent; one on = only that one.
* The OTP is a variable (`{#var#}`) in the DLT template: register it as a numeric variable.

## Example of what a passenger receives

`YAAN: Trip TRP-000012 booked for 07 Jan 2030 at 14:30. Pickup: 12 MG Road, Pune. Drop: Acme HQ, Hinjewadi. Driver: Ravi Kumar (9876500001). Vehicle: MH12AB1234. Your OTP is 4821. Share it with the driver only when you reach your drop point.`

## Changing the wording
Edit `TEMPLATES` in `notifications.py` (keep the `{placeholders}`), re-register the same text on DLT, and update this file.
A configurable per-vendor template editor is not built; the spec lists exact wording as a later decision.
