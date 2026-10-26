# HomeRent AI — System Documentation & Features Guide

## 1. Project Overview
**HomeRent AI** is a full-stack, AI-powered household appliance rental management platform. It enables customers to browse high-end appliances, configure flexible rental tenures, verify delivery serviceability, and rent items seamlessly. The platform also provides an isolated **Vendor Console** for appliance vendors to list inventory, monitor bookings, track monthly rental revenues, and manage fleet logistics with strict Role-Based Access Control (RBAC).

---

## 2. Complete List of Implemented Features

### A. Customer & Guest Browsing Experience
1. **Unauthenticated / Guest Browsing**:
   - Visitors can freely browse all appliances on the catalog without needing to create an account or sign in first.
   - Transparent access to appliance photos, monthly rental rates, descriptions, star ratings, and stock badges.
2. **Appliance Details Modal Configurator**:
   - Clicking any appliance card or the "Configure" button opens an interactive modal.
   - Shows technical specifications (Energy star rating, capacity, warranty).
   - Displays mandatory **Vendor Details** (Authorized Vendor Name, Verified Business Address, and Click-to-Call Phone Number).
3. **Dynamic Tenure & Price Calculation**:
   - Support for 1-month, 3-month, 6-month, and 12-month tenures with progressive discounts.
   - Real-time monthly rate and cumulative total price recalculation.
4. **Appliance Add-Ons**:
   - Optional protection plans: HomeCare Protection, Voltage Stabilizer, and Smart Home Integration.
5. **Live Search & Autocomplete**:
   - Real-time keyword search across appliance titles, categories, and descriptions.
6. **Category Filtering**:
   - Filter appliances by categories: *All, Kitchen, Laundry, Climate Control, Living Room*.
7. **Pincode Delivery Checker**:
   - Real-time delivery serviceability verification against serviced postal codes stored in MongoDB.
8. **"Rent vs Buy" Savings Indicator**:
   - Clear financial breakdown highlighting that renting saves up to ~92% compared to full retail purchase costs.
9. **Customer Reviews & Star Ratings**:
   - Community star ratings and verified customer reviews per appliance.
   - Ability for logged-in customers to submit reviews and feedback.

---

### B. Authentication & Role-Based Access Control (RBAC)
1. **Dual-Role Authentication**:
   - Dedicated tabs for **Customer Login** and **Vendor Login**.
   - Sign In and Sign Up (Registration) modes.
2. **One-Click Demo Credentials**:
   - Fast demo buttons to populate pre-configured Customer (`customer@homerent.ai`) and Vendor (`vendor@homerent.ai`) credentials.
3. **Action-Gated Authentication**:
   - Guests can browse freely; the system only prompts for login when they attempt to rent or proceed to checkout.
4. **Strict Role Isolation**:
   - Customer accounts cannot access the Vendor Console.
   - Vendor accounts cannot place customer rental bookings.
   - Multi-Vendor isolation: Vendors can only view, edit, delete, and inspect bookings for appliances they personally uploaded.

---

### C. Rental Bag & Checkout System
1. **Slide-Out Rental Bag (Cart)**:
   - Slide-over drawer with itemized rental plans, tenure labels, quantities, and subtotal.
   - Cart data is persisted both in browser storage and in MongoDB.
2. **3-Step Checkout Wizard**:
   - **Step 1: Delivery Details** — Customer address, contact details, and pincode (auto-filled for authenticated customers).
   - **Step 2: Payment Selection** — Support for Credit/Debit Cards (with live interactive card preview), UPI / NetBanking, and Cash on Delivery.
   - **Step 3: Order Confirmation** — Generates a unique tracking ID (`HR-XXXXXX`).
3. **Automated Inventory & Revenue Sync**:
   - Decrements available stock and increments rented stock in MongoDB upon checkout.
   - Records revenue entries and triggers notifications for both customer and vendor.

---

### D. Verified Booking Receipt System
1. **Instant Post-Booking Confirmation Modal**:
   - Displays a formal, verified booking confirmation receipt immediately upon checkout.
2. **Comprehensive Receipt Details**:
   - Customer Name, Email, and Delivery Address.
   - Appliance Name, Category, and Unique Booking ID.
   - Rental Start Date, End Date, Selected Tenure, Monthly Price, and Total Rental Amount.
   - Authorized Vendor Name, Vendor Phone Number, and Vendor Business Address.
   - Booking Status and Verification Seal.
3. **Print & Download Options**:
   - **Print / Save as PDF**: Direct browser print trigger formatted for clean physical print or PDF export.
   - **Download Text Receipt**: Generates and downloads a `.txt` receipt file with complete metadata.

---

### E. Customer Self-Service Dashboard (`dashboard.html`)
1. **Rental Metrics Overview**:
   - Active rentals count, monthly spend tracker, estimated home savings, and energy efficiency score.
2. **Active Rentals Manager**:
   - Visual cards showing current active and pending rentals with renewal dates.
3. **Category Mix Visualization**:
   - Percentage breakdown of rented appliances by category (Kitchen, Laundry, Climate).
4. **Free 24h Maintenance & Repair Request**:
   - Modal to request routine hygiene filter cleaning, temperature adjustment, relocation, or emergency repairs within 24 hours.

---

### F. Multi-Vendor Management Console
1. **Vendor Dashboard Analytics**:
   - Real-time metrics tracking: **Active Rentals**, **Total Inventory Items**, and **Monthly Revenue (₹/mo)**.
2. **Vendor-Scoped Fleet Management**:
   - Vendors only manage appliances matching their verified login email.
3. **Add Appliance with Mandatory Vendor Details**:
   - Form fields: Title, Category, Monthly Rental Price, Image URL, Description, Stock Quantity.
   - Mandatory **Vendor Address** & **Vendor Phone Number** with input validation.
4. **Edit & Delete Inventory**:
   - Live updates to rental rates, descriptions, and stock counts.
   - Delete option to remove retired appliances from the fleet.
5. **Active Bookings Manager**:
   - Table displaying all live customer bookings for this vendor's appliances.
   - Status updater: *Pending, Confirmed, Out for Delivery, Active, Completed, Cancelled*.

---

### G. UI/UX & Smart Assistant
1. **AI Chat Assistant Widget**:
   - Floating interactive chatbot providing instant recommendation on room sizes, appliance capacity, and budget.
2. **Dark / Light Mode**:
   - One-click theme toggle with persistence in `localStorage`.
3. **Modern Responsive Design**:
   - Glassmorphism panels, accessible modal overlays, and mobile navigation support.
4. **Local Network / Wi-Fi Access**:
   - Configured on `0.0.0.0:5000` to allow testing across mobile devices and laptops on the same Wi-Fi network.

---

## 3. Technology Stack & Architecture

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript (ES6+) | Lightweight, high-performance UI without heavy framework bloat |
| **Backend** | Python 3.10+, Flask, Flask-CORS | RESTful API server handling business logic, authentication, and scoping |
| **Database** | MongoDB (PyMongo driver) | Document store (`homerent_db`) for flexible schema management |
| **Storage** | LocalStorage + MongoDB | Dual caching for cart items, active user sessions, and theme preferences |

---

## 4. API Endpoints Reference

### Appliances
- `GET /api/appliances` — Retrieve all active appliances in the catalog.
- `POST /api/appliances` — Add a new appliance (Requires Vendor role; records vendor email, address, and phone).
- `PUT /api/appliances/<id>` — Update appliance pricing, stock, or specifications (Vendor scoped).
- `DELETE /api/appliances/<id>` — Delete appliance from fleet (Vendor scoped).

### Bookings & Receipts
- `GET /api/bookings` — Retrieve bookings (Scoped to customer or vendor).
- `POST /api/bookings` — Create a new rental booking (Enforces customer authentication; blocks vendors; updates inventory).
- `PUT /api/bookings/<id>/status` — Update rental status (Vendor scoped).

### Authentication & Users
- `POST /api/auth/register` — Register a new Customer or Vendor account.
- `POST /api/auth/login` — Authenticate user and return role details.
- `GET /api/users` — List registered users (Demo/admin helper).

### Reviews & Cart
- `GET /api/reviews/<appliance_id>` — Fetch verified reviews for an appliance.
- `POST /api/reviews` — Submit a customer rating and review.
- `GET /api/cart/<user_email>` — Retrieve saved cart items.
- `POST /api/cart/<user_email>` — Persist cart items.
- `GET /api/pincodes/<pincode>` — Verify serviceability for a delivery postal code.
