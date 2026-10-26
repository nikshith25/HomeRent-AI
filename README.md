markdown
# Razorpay Payment Integration

This repository documents the Razorpay payment gateway integration added to the HomeRent AI appliance rental platform.

Runs in **Razorpay Test Mode** — no real money moves.

---

## What Was Added

- Razorpay Checkout (Card, UPI, Netbanking, Wallet)
- Server-side HMAC-SHA256 signature verification
- Cash on Delivery (COD) skips the gateway
- Booking only created after payment verification
- Webhook endpoint for production reliability
- `.env` git-ignored — API keys never committed

---

## Files Changed

| File | Change |
|---|---|
| `server.py` | Razorpay SDK init + 3 new payment endpoints |
| `app.js` | Replaced fake-payment logic with real Razorpay checkout |
| `appliances.html` | Added Razorpay Checkout script tag |
| `.env.example` | Added placeholder Razorpay keys |
| `.gitignore` | Added to prevent `.env` from being committed |

---

## Backend Changes — `server.py`

### New Imports

```python
import razorpay
import hmac
import hashlib
Razorpay Client Init
python
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if RAZORPAY_KEY_ID else None
New Endpoints
Endpoint	Method	Purpose
/api/payments/create-order	POST	Creates Razorpay order, returns order_id + key_id
/api/payments/verify	POST	Verifies HMAC-SHA256 signature, marks payment as paid
/api/payments/webhook	POST	Handles Razorpay webhook events
Frontend Changes — app.js
Removed
Fake payment logic that instantly marked bookings as paid:

javascript
// Simulate successful rental booking creation
state.checkoutStep = 3;
const bookingId = "HR-" + Math.floor(100000 + Math.random() * 900000);
Added
Calculate cart total

Call /api/payments/create-order → get order_id

Open Razorpay Checkout modal

On success → call /api/payments/verify with signature

Only if verified → finalizeBookingAndShowReceipt()

New Function
finalizeBookingAndShowReceipt(payMethod, paymentId, providedBookingId)

COD Behavior
If user selects Pay on Delivery, Razorpay is skipped and the booking is created with payment_status: pending.

Frontend Changes — appliances.html
Added in <head>:

html
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
Environment Variables — .env.example
env
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXX
RAZORPAY_KEY_SECRET=XXXXXXXXXXXXXXXXXXXXXXXX
RAZORPAY_WEBHOOK_SECRET=
Get test keys: https://dashboard.razorpay.com/app/keys

Dependency
bash
pip install razorpay
Payment Flow
text
Customer clicks "Confirm Rental Bookings"
        │
        ▼
POST /api/payments/create-order    →  Flask creates Razorpay order
        │  returns { order_id, amount, key_id }
        ▼
Razorpay Checkout modal opens
        │  Customer pays with test card
        ▼
Razorpay returns payment_id + signature
        │
        ▼
POST /api/payments/verify          →  Flask verifies HMAC signature
        │  returns { success: true, payment_id }
        ▼
finalizeBookingAndShowReceipt()    →  Booking saved to MongoDB
        │
        ▼
Booking confirmed + receipt shown
How to Test
Test Card (India Domestic)
Field	Value
Card Number	4100 2800 0000 1007
Expiry	12/30
CVV	123
OTP	Any 4-10 digit number
Steps
Sign in as customer

Add appliance to cart

Checkout → fill address → Continue to Payment

Select Credit / Debit Card

Click Confirm Rental Bookings

Enter test card in Razorpay modal

On demo bank page, click Success

Booking confirmed + receipt shown

Verify Payment in MongoDB
homerent_db → payments collection:

json
{
  "razorpay_order_id": "order_XXXXXXXX",
  "razorpay_payment_id": "pay_XXXXXXXX",
  "payment_status": "paid",
  "amount": 1499.0,
  "payment_method": "razorpay"
}
Security
.env git-ignored — real keys never pushed

HMAC-SHA256 signature verified on every payment

Booking only created after signature verification

Real cards automatically rejected in Test Mode
