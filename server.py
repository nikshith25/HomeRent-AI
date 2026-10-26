import math
import os
import json
import socket
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from pymongo import MongoClient
from bson import ObjectId
import time
import re

import razorpay
import hmac
import hashlib

from lstm_forecaster import generate_demand_forecast, get_vendor_appliances_and_counts

# Automatically load variables from .env file if it exists
def load_env_file():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val

load_env_file()
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if RAZORPAY_KEY_ID else None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR)
PORT = int(os.getenv('PORT', 5000))
HOST = os.getenv('HOST', '0.0.0.0')
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017')
DB_NAME = os.getenv('DB_NAME', 'homerent_db')

db = None

# ─────────────────────────────────────────────
# HYDERABAD LOCALITIES & HAVERSINE DISTANCE
# ─────────────────────────────────────────────

HYDERABAD_LOCALITIES = {
    "Gachibowli":    {"area": "Gachibowli", "latitude": 17.4401, "longitude": 78.3489},
    "Madhapur":      {"area": "Madhapur", "latitude": 17.4483, "longitude": 78.3915},
    "Kondapur":      {"area": "Kondapur", "latitude": 17.4699, "longitude": 78.3578},
    "Hitech City":   {"area": "Hitech City", "latitude": 17.4435, "longitude": 78.3772},
    "Kukatpally":    {"area": "Kukatpally", "latitude": 17.4948, "longitude": 78.3996},
    "Miyapur":       {"area": "Miyapur", "latitude": 17.4968, "longitude": 78.3614},
    "Jubilee Hills": {"area": "Jubilee Hills", "latitude": 17.4319, "longitude": 78.4073},
    "Banjara Hills": {"area": "Banjara Hills", "latitude": 17.4156, "longitude": 78.4350},
    "Ameerpet":      {"area": "Ameerpet", "latitude": 17.4375, "longitude": 78.4482},
    "Begumpet":      {"area": "Begumpet", "latitude": 17.4448, "longitude": 78.4664},
    "Secunderabad":  {"area": "Secunderabad", "latitude": 17.4399, "longitude": 78.4983},
    "Uppal":         {"area": "Uppal", "latitude": 17.4018, "longitude": 78.5602},
    "LB Nagar":      {"area": "LB Nagar", "latitude": 17.3457, "longitude": 78.5522},
    "Mehdipatnam":   {"area": "Mehdipatnam", "latitude": 17.3916, "longitude": 78.4398},
    "Manikonda":     {"area": "Manikonda", "latitude": 17.4042, "longitude": 78.3788},
    "Narsingi":      {"area": "Narsingi", "latitude": 17.3828, "longitude": 78.3582},
    "Attapur":       {"area": "Attapur", "latitude": 17.3688, "longitude": 78.4299},
    "Dilsukhnagar":  {"area": "Dilsukhnagar", "latitude": 17.3685, "longitude": 78.5247},
    "Tarnaka":       {"area": "Tarnaka", "latitude": 17.4285, "longitude": 78.5303},
    "Nacharam":      {"area": "Nacharam", "latitude": 17.4262, "longitude": 78.5684}
}

LOCALITY_LIST = list(HYDERABAD_LOCALITIES.keys())

def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance in kilometers between two points using the Haversine formula."""
    try:
        R = 6371.0  # Earth's radius in kilometers
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = (math.sin(dlat / 2.0) ** 2 +
             math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) *
             math.sin(dlon / 2.0) ** 2)
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(R * c, 1)
    except Exception as e:
        return None

# ─────────────────────────────────────────────
# SEED DATA
# ─────────────────────────────────────────────

SEED_CATEGORIES = [
    {"category_name": "kitchen",  "description": "Kitchen appliances like refrigerators, microwaves and dishwashers"},
    {"category_name": "laundry",  "description": "Laundry appliances like washing machines and garment steamers"},
    {"category_name": "climate",  "description": "Climate control appliances like ACs and air purifiers"},
    {"category_name": "living",   "description": "Smart living appliances like water purifiers and beverage chillers"},
]

SEED_APPLIANCES = [
    {"id":1,"title":"Smart Double-Door Refrigerator","category":"kitchen","brand":"HomeRent","price":1499.00,"rating":4.9,"reviews":124,"image":"assets/images/smart_refrigerator.jpg","desc":"350L double-door refrigerator with AI energy saving, convertible zones, and real-time freshness tracking via smart display.","badge":"Bestseller","availability":True,"vendorAddress":"Indiranagar, Bengaluru, Karnataka","vendorPhone":"9876543210","sizeUpcharges":{"standard":0,"deluxe":-100,"premium":-200}},
    {"id":2,"title":"Front Load Inverter Washing Machine","category":"laundry","brand":"HomeRent","price":1199.00,"rating":4.8,"reviews":95,"image":"assets/images/washing_machine.jpg","desc":"8kg premium front load washing machine with AI wash cycle optimization, 5-star energy rating, and built-in water heater.","badge":"Eco-Friendly","availability":True,"vendorAddress":"Koramangala, Bengaluru, Karnataka","vendorPhone":"9876543211","sizeUpcharges":{"standard":0,"deluxe":-100,"premium":-200}},
    {"id":3,"title":"Convection Microwave Oven","category":"kitchen","brand":"HomeRent","price":599.00,"rating":4.7,"reviews":82,"image":"assets/images/microwave_oven.jpg","desc":"28L convection microwave with 360-degree uniform heating, auto-cook menus, and elegant touch controls.","badge":"Popular","availability":True,"vendorAddress":"HSR Layout, Bengaluru, Karnataka","vendorPhone":"9876543212","sizeUpcharges":{"standard":0,"deluxe":-50,"premium":-100}},
    {"id":4,"title":"Smart Inverter Split AC","category":"climate","brand":"HomeRent","price":1799.00,"rating":4.9,"reviews":154,"image":"assets/images/air_conditioner.jpg","desc":"1.5 Ton 5-Star split air conditioner with smart Wi-Fi controls, PM2.5 filter, and ultra-quiet cooling mode.","badge":"Seasonal","availability":True,"vendorAddress":"Whitefield, Bengaluru, Karnataka","vendorPhone":"9876543213","sizeUpcharges":{"standard":0,"deluxe":-150,"premium":-300}},
    {"id":5,"title":"Built-In Automatic Dishwasher","category":"kitchen","brand":"HomeRent","price":1299.00,"rating":4.6,"reviews":41,"image":"assets/images/dishwasher.jpg","desc":"14 place settings dishwasher with intensive wash for Indian utensils, auto-dry technology, and low water consumption.","badge":"Luxury","availability":True,"vendorAddress":"Indiranagar, Bengaluru, Karnataka","vendorPhone":"9876543210","sizeUpcharges":{"standard":0,"deluxe":-100,"premium":-200}},
    {"id":6,"title":"Minimalist HEPA Air Purifier","category":"climate","brand":"HomeRent","price":799.00,"rating":4.5,"reviews":73,"image":"assets/images/air_purifier.jpg","desc":"True HEPA H13 air purifier with real-time AQI display, smart filter life alerts, and CADR of 350 m3/h.","badge":"Smart Living","availability":True,"vendorAddress":"Jayanagar, Bengaluru, Karnataka","vendorPhone":"9876543214","sizeUpcharges":{"standard":0,"deluxe":-50,"premium":-100}},
    {"id":7,"title":"Smart Air Fryer Pro","category":"kitchen","brand":"HomeRent","price":699.00,"rating":4.7,"reviews":68,"image":"assets/images/microwave_oven.jpg","desc":"5.5L connected air fryer with guided recipes, rapid crisp technology, and dishwasher-safe parts for effortless everyday cooking.","badge":"New","availability":True,"vendorAddress":"Koramangala, Bengaluru, Karnataka","vendorPhone":"9876543211","sizeUpcharges":{"standard":0,"deluxe":-50,"premium":-100}},
    {"id":8,"title":"Top Load Turbo Washer","category":"laundry","brand":"HomeRent","price":899.00,"rating":4.6,"reviews":57,"image":"assets/images/washing_machine.jpg","desc":"7kg top-load washer with turbo drum cleaning, quick wash programs, and smart load balancing for compact homes.","badge":"Value Pick","availability":True,"vendorAddress":"HSR Layout, Bengaluru, Karnataka","vendorPhone":"9876543212","sizeUpcharges":{"standard":0,"deluxe":-75,"premium":-150}},
    {"id":9,"title":"Tower Air Cooler","category":"climate","brand":"HomeRent","price":649.00,"rating":4.4,"reviews":39,"image":"assets/images/air_conditioner.jpg","desc":"Energy-saving tower cooler with three fan modes, a wide-angle swing, and remote control for comfortable summer evenings.","badge":"Summer Ready","availability":True,"vendorAddress":"Whitefield, Bengaluru, Karnataka","vendorPhone":"9876543213","sizeUpcharges":{"standard":0,"deluxe":-50,"premium":-100}},
    {"id":10,"title":"Countertop Water Purifier","category":"living","brand":"HomeRent","price":749.00,"rating":4.6,"reviews":46,"image":"assets/images/air_purifier.jpg","desc":"Compact multi-stage water purifier with filter-life alerts, child lock, and instant access to fresh drinking water.","badge":"Healthy Home","availability":True,"vendorAddress":"Indiranagar, Bengaluru, Karnataka","vendorPhone":"9876543210","sizeUpcharges":{"standard":0,"deluxe":-50,"premium":-100}},
    {"id":11,"title":"Compact Beverage Chiller","category":"living","brand":"HomeRent","price":599.00,"rating":4.3,"reviews":31,"image":"assets/images/smart_refrigerator.jpg","desc":"Quiet 45L beverage chiller with adjustable temperature zones and a space-saving glass door for entertaining at home.","badge":"Compact","availability":True,"vendorAddress":"Jayanagar, Bengaluru, Karnataka","vendorPhone":"9876543214","sizeUpcharges":{"standard":0,"deluxe":-40,"premium":-80}},
    {"id":12,"title":"SteamCare Garment Steamer","category":"laundry","brand":"HomeRent","price":499.00,"rating":4.5,"reviews":28,"image":"assets/images/washing_machine.jpg","desc":"Fast-heating garment steamer with crease-release modes and a removable water tank for polished clothes in minutes.","badge":"Easy Care","availability":True,"vendorAddress":"HSR Layout, Bengaluru, Karnataka","vendorPhone":"9876543212","sizeUpcharges":{"standard":0,"deluxe":-40,"premium":-80}},
]

SEED_USERS = [
    {"name":"Aarav Sharma","email":"customer@homerent.ai","password":"customer123","phone":"","role":"customer"},
    {"name":"SmartRent Vendor","email":"vendor@homerent.ai","password":"vendor123","phone":"9876543210","role":"vendor"},
]

SEED_BOOKINGS = [
    {"id":"LR-829471","user_id":"customer@homerent.ai","appliance_id":1,"customerName":"Aarav Sharma","email":"customer@homerent.ai","address":"402, Green Glen Heights, HSR Layout, Bengaluru - 560102","applianceName":"Smart Double-Door Refrigerator","tenure":"12 Months","start_date":"12/07/2026","end_date":"12/07/2027","total_amount":1299.00,"totalRent":1299.00,"status":"active","date":"12/07/2026"},
    {"id":"LR-304859","user_id":"customer@homerent.ai","appliance_id":2,"customerName":"Priya Patel","email":"priya.patel@example.com","address":"A-504, Windsor Court, Indiranagar, Bengaluru - 560038","applianceName":"Front Load Inverter Washing Machine","tenure":"6 Months","start_date":"24/07/2026","end_date":"24/01/2027","total_amount":1099.00,"totalRent":1099.00,"status":"pending","date":"24/07/2026"},
]

SEED_REVIEWS = [
    {
        "applianceId": 1,
        "customerId": "customer@homerent.ai",
        "customerName": "Aarav Sharma",
        "rating": 5,
        "comment": "Exceptional smart refrigerator! Maintains ideal freshness, silent inverter cooling, and the rental process was seamless.",
        "createdAt": "15-08-2026"
    },
    {
        "applianceId": 1,
        "customerId": "priya.patel@example.com",
        "customerName": "Priya Patel",
        "rating": 5,
        "comment": "Very good appliance and the rental process was smooth. Highly recommend!",
        "createdAt": "02-10-2026"
    },
    {
        "applianceId": 2,
        "customerId": "priya.patel@example.com",
        "customerName": "Priya Patel",
        "rating": 5,
        "comment": "Super clean wash cycles and low vibration. Installation was done effortlessly by the vendor technician.",
        "createdAt": "10-09-2026"
    },
    {
        "applianceId": 3,
        "customerId": "customer@homerent.ai",
        "customerName": "Aarav Sharma",
        "rating": 4,
        "comment": "Convection microwave heats evenly and makes baking very convenient. Sturdy build.",
        "createdAt": "18-09-2026"
    },
    {
        "applianceId": 4,
        "customerId": "rohit.verma@example.com",
        "customerName": "Rohit Verma",
        "rating": 5,
        "comment": "Chills our large living room very quickly. The 5-star inverter keeps electricity bills low.",
        "createdAt": "25-09-2026"
    }
]

# ─────────────────────────────────────────────
# DB CONNECTION + SEEDING
# ─────────────────────────────────────────────

def connect_to_mongo():
    global db
    try:
        # 5000ms timeout provides stability for remote / cloud MongoDB connections
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[DB_NAME]
        print(f'Connected to MongoDB database: {DB_NAME}')
        # Enforce Compound Index on Users for role-specific email uniqueness:
        # One email can have 1 customer account and 1 vendor account; duplicates for the same role are blocked.
        try:
            db.users.create_index([('email', 1), ('role', 1)], unique=True)
            db.categories.create_index('category_name', unique=True)
            db.return_requests.create_index('request_id', unique=True)
            db.return_requests.create_index('customer_email')
            db.return_requests.create_index('vendor_email')
            db.return_requests.create_index('booking_id')
        except Exception as idx_err:
            print("Index creation notice:", idx_err)
        seed_database()
    except Exception as e:
        print('Failed to connect to MongoDB:', e)
        print(f'Attempted URI: {MONGO_URI}')
        if '127.0.0.1' in MONGO_URI or 'localhost' in MONGO_URI:
            print('Ensure your local MongoDB service is running, or set MONGO_URI in a .env file to your MongoDB Atlas cluster URI.')
        else:
            print('Please check your network connection, credentials, and ensure your IP is whitelisted on MongoDB Atlas (0.0.0.0/0).')

def seed_database():
    # Categories
    if db.categories.count_documents({}) == 0:
        db.categories.insert_many(SEED_CATEGORIES)
        print('Seeded categories')

    # Users
    if db.users.count_documents({}) == 0:
        db.users.insert_many(SEED_USERS)
        print('Seeded users')

    # Appliances + Inventory
    if db.appliances.count_documents({}) == 0 or db.inventory.count_documents({}) == 0:
        db.appliances.delete_many({})
        db.inventory.delete_many({})
        cat_map = {c['category_name']: str(c['_id']) for c in db.categories.find()}
        apps_to_insert = []
        for a in SEED_APPLIANCES:
            app_doc = dict(a)
            app_doc['vendor_email'] = 'vendor@homerent.ai'
            app_doc['vendorAddress'] = a.get('vendorAddress', 'Indiranagar, Bengaluru, Karnataka')
            app_doc['vendorPhone'] = a.get('vendorPhone', '9876543210')
            app_doc['category_id'] = cat_map.get(a['category'], '')
            app_doc['price_per_day'] = round(a['price'] / 30, 2)
            app_doc['name'] = a['title']
            app_doc['description'] = a['desc']
            apps_to_insert.append(app_doc)
        result = db.appliances.insert_many(apps_to_insert)
        # Inventory for each
        inv_docs = []
        for oid, a in zip(result.inserted_ids, SEED_APPLIANCES):
            inv_docs.append({
                'appliance_id': str(oid),
                'appliance_int_id': a['id'],
                'appliance_name': a['title'],
                'vendor_email': 'vendor@homerent.ai',
                'vendorAddress': a.get('vendorAddress', 'Indiranagar, Bengaluru, Karnataka'),
                'vendorPhone': a.get('vendorPhone', '9876543210'),
                'total_quantity': 10,
                'available_quantity': 10,
                'rented_quantity': 0,
                'status': 'available'
            })
        db.inventory.insert_many(inv_docs)
        print('Seeded all 12 appliances + inventory')

    # Bookings + Revenue
    if db.bookings.count_documents({}) == 0:
        db.bookings.insert_many([dict(b, vendor_email='vendor@homerent.ai') for b in SEED_BOOKINGS])
        # Revenue entries
        rev_docs = []
        for b in SEED_BOOKINGS:
            rev_docs.append({
                'booking_id': b['id'],
                'amount': b['total_amount'],
                'date': b['date'],
                'payment_status': 'paid' if b['status'] == 'active' else 'pending'
            })
        db.revenue.insert_many(rev_docs)
        print('Seeded bookings + revenue')

    # Reviews Seeding
    if db.reviews.count_documents({}) == 0:
        db.reviews.insert_many([dict(r) for r in SEED_REVIEWS])
        print('Seeded customer reviews')

    # Safe migration: ensure any existing items have vendor_email, vendorAddress, vendorPhone
    db.appliances.update_many({'vendor_email': {'$exists': False}}, {'$set': {'vendor_email': 'vendor@homerent.ai'}})
    db.inventory.update_many({'vendor_email': {'$exists': False}}, {'$set': {'vendor_email': 'vendor@homerent.ai'}})
    db.bookings.update_many({'vendor_email': {'$exists': False}}, {'$set': {'vendor_email': 'vendor@homerent.ai'}})

    # Safe migration: ensure all appliances have vendorLocation with realistic Hyderabad coordinates
    all_apps = list(db.appliances.find())
    for idx, app in enumerate(all_apps):
        vloc = app.get('vendorLocation')
        if not vloc or not isinstance(vloc, dict) or not vloc.get('latitude') or not vloc.get('longitude') or not vloc.get('area'):
            locality_key = LOCALITY_LIST[idx % len(LOCALITY_LIST)]
            loc_data = HYDERABAD_LOCALITIES[locality_key]
            v_addr = f"{locality_key}, Hyderabad, Telangana"
            db.appliances.update_one(
                {'_id': app['_id']},
                {'$set': {
                    'vendorLocation': {
                        'area': loc_data['area'],
                        'latitude': loc_data['latitude'],
                        'longitude': loc_data['longitude']
                    },
                    'vendorAddress': v_addr,
                    'vendorPhone': app.get('vendorPhone') or '9876543210'
                }}
            )
            db.inventory.update_one(
                {'appliance_int_id': app.get('id')},
                {'$set': {
                    'vendorLocation': {
                        'area': loc_data['area'],
                        'latitude': loc_data['latitude'],
                        'longitude': loc_data['longitude']
                    },
                    'vendorAddress': v_addr,
                    'vendorPhone': app.get('vendorPhone') or '9876543210'
                }}
            )

connect_to_mongo()

@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        response = app.make_default_options_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-User-Email, X-User-Role, Authorization'
        return response

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-User-Email, X-User-Role, Authorization'
    return response

# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────

def clean(doc):
    """Remove MongoDB _id field for JSON serialization."""
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop('_id', None)
    return doc

def clean_list(docs):
    return [clean(d) for d in docs]

# ─────────────────────────────────────────────
# USERS API
# ─────────────────────────────────────────────

@app.route('/api/users', methods=['GET'])
def get_users():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    users = clean_list(db.users.find({}, {'password': 0}))
    return jsonify(users)

@app.route('/api/users', methods=['POST'])
def handle_user():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    data = request.json or {}
    action = data.get('action', 'register')

    if action == 'login':
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        role = data.get('role', 'customer').strip().lower()
        user = db.users.find_one({'email': email, 'password': password, 'role': role})
        if not user:
            return jsonify({"error": f"Invalid email, password, or role for {role.capitalize()}."}), 401
        return jsonify(clean(user))

    elif action == 'register':
        email = data.get('email', '').strip().lower()
        role = data.get('role', 'customer').strip().lower()
        if not email:
            return jsonify({"error": "Email address is required."}), 400
        if role not in ['customer', 'vendor']:
            return jsonify({"error": "Invalid role specified. Must be customer or vendor."}), 400
        
        # Enforce single email restriction per role:
        # A single email can register once as Customer and once as Vendor.
        # Disallow duplicate registration for the SAME role.
        existing = db.users.find_one({'email': email, 'role': role})
        if existing:
            return jsonify({"error": f"An account with this email already exists as a {role.capitalize()}."}), 409

        new_user = {
            'name': data.get('name', '').strip(),
            'email': email,
            'password': data.get('password', ''),
            'phone': data.get('phone', '').strip(),
            'role': role
        }
        db.users.insert_one(new_user)
        # Notification for new registration
        db.notifications.insert_one({
            'user_id': email,
            'message': f'Welcome to HomeRent AI! Your {role.capitalize()} account has been created successfully.',
            'type': 'welcome',
            'is_read': False,
            'created_at': datetime.now().isoformat()
        })
        return jsonify(clean(new_user)), 201

# ─────────────────────────────────────────────
# CATEGORIES API (DYNAMIC CATEGORY MANAGEMENT)
# ─────────────────────────────────────────────

@app.route('/api/categories', methods=['GET'])
def get_categories():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    active_only = request.args.get('active_only', '').lower() in ('true', '1')
    query = {'is_active': True} if active_only else {}
    cats = list(db.categories.find(query))
    result = []
    for c in cats:
        c_clean = clean(c)
        cat_slug = c.get('category_name', '')
        # Count appliances associated with this category in MongoDB
        c_clean['appliance_count'] = db.appliances.count_documents({'category': cat_slug})
        result.append(c_clean)
    return jsonify(result)

@app.route('/api/categories', methods=['POST'])
def add_category():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = (request.headers.get('X-User-Role') or '').strip().lower()
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to add categories"}), 403

    data = request.json or {}
    raw_name = data.get('category_name', '').strip()
    display_name = data.get('display_name', '').strip() or raw_name.title()
    if not raw_name:
        return jsonify({"error": "Category name / identifier is required"}), 400

    slug = raw_name.lower().replace(' ', '-').replace('_', '-')
    existing = db.categories.find_one({'category_name': slug})
    if existing:
        return jsonify({"error": f"A category with identifier '{slug}' already exists."}), 409

    now_iso = datetime.now().isoformat()
    new_cat = {
        'category_name': slug,
        'display_name': display_name,
        'description': data.get('description', '').strip(),
        'icon': data.get('icon', '📦').strip() or '📦',
        'is_active': bool(data.get('is_active', True)),
        'created_at': now_iso,
        'updated_at': now_iso
    }
    db.categories.insert_one(new_cat)
    res_clean = clean(new_cat)
    res_clean['appliance_count'] = 0
    return jsonify(res_clean), 201

@app.route('/api/categories/<cat_name>', methods=['PUT'])
def update_category(cat_name):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = (request.headers.get('X-User-Role') or '').strip().lower()
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to update categories"}), 403

    cat_slug = cat_name.strip().lower()
    existing = db.categories.find_one({'category_name': cat_slug})
    if not existing:
        return jsonify({"error": f"Category '{cat_slug}' not found"}), 404

    data = request.json or {}
    update_fields = {'updated_at': datetime.now().isoformat()}
    if 'display_name' in data:
        update_fields['display_name'] = data['display_name'].strip()
    if 'description' in data:
        update_fields['description'] = data['description'].strip()
    if 'icon' in data:
        update_fields['icon'] = data['icon'].strip()
    if 'is_active' in data:
        update_fields['is_active'] = bool(data['is_active'])

    db.categories.update_one({'category_name': cat_slug}, {'$set': update_fields})
    updated = db.categories.find_one({'category_name': cat_slug})
    up_clean = clean(updated)
    up_clean['appliance_count'] = db.appliances.count_documents({'category': cat_slug})
    return jsonify(up_clean)

@app.route('/api/categories/<cat_name>', methods=['DELETE'])
def delete_category(cat_name):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = (request.headers.get('X-User-Role') or '').strip().lower()
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to delete categories"}), 403

    cat_slug = cat_name.strip().lower()
    existing = db.categories.find_one({'category_name': cat_slug})
    if not existing:
        return jsonify({"error": f"Category '{cat_slug}' not found"}), 404

    app_count = db.appliances.count_documents({'category': cat_slug})
    if app_count > 0:
        return jsonify({
            "error": f"Cannot delete category '{existing.get('display_name', cat_slug)}' because {app_count} appliance(s) are currently associated with it. You can deactivate it instead to hide it from customer listings."
        }), 400

    db.categories.delete_one({'category_name': cat_slug})
    return jsonify({"success": True, "message": f"Category '{cat_slug}' deleted successfully."})

# ─────────────────────────────────────────────
# APPLIANCES API
# ─────────────────────────────────────────────

@app.route('/api/upload', methods=['POST'])
def upload_image():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = request.headers.get('X-User-Role', '')
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to upload images"}), 403

    if 'file' in request.files:
        file = request.files['file']
        if file.filename:
            filename = f"upload_{int(time.time()*1000)}_{os.path.basename(file.filename)}"
            save_path = os.path.join('assets', 'images', filename)
            file.save(save_path)
            return jsonify({"success": True, "url": f"assets/images/{filename}"})

    if request.is_json and 'image_data' in request.json:
        data = request.json['image_data']
        if ',' in data:
            data = data.split(',', 1)[1]
        import base64
        img_bytes = base64.b64decode(data)
        filename = f"upload_{int(time.time()*1000)}.jpg"
        save_path = os.path.join('assets', 'images', filename)
        with open(save_path, 'wb') as f:
            f.write(img_bytes)
        return jsonify({"success": True, "url": f"assets/images/{filename}"})

    return jsonify({"error": "No image provided"}), 400

@app.route('/api/localities', methods=['GET'])
def get_localities():
    return jsonify(HYDERABAD_LOCALITIES)

@app.route('/api/users/location', methods=['POST'])
def update_user_location():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    data = request.json or {}
    email = (data.get('email') or request.headers.get('X-User-Email') or '').strip().lower()
    lat = data.get('latitude')
    lng = data.get('longitude')
    if not email or lat is None or lng is None:
        return jsonify({"error": "email, latitude, and longitude are required"}), 400
    try:
        lat = float(lat)
        lng = float(lng)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid coordinates"}), 400

    db.users.update_one(
        {'email': email},
        {'$set': {'location': {'latitude': lat, 'longitude': lng}}}
    )
    return jsonify({"success": True, "location": {"latitude": lat, "longitude": lng}})

@app.route('/api/appliances', methods=['GET'])
def get_appliances():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    apps = clean_list(db.appliances.find())

    # Distance calculation parameters
    lat_param = request.args.get('lat')
    lng_param = request.args.get('lng')
    max_distance = request.args.get('max_distance', type=float)
    sort_param = request.args.get('sort', '').lower()

    cust_lat = None
    cust_lng = None
    if lat_param is not None and lng_param is not None:
        try:
            cust_lat = float(lat_param)
            cust_lng = float(lng_param)
        except (ValueError, TypeError):
            pass

    for a in apps:
        # Ensure vendorLocation structure
        vloc = a.get('vendorLocation')
        if not vloc or not isinstance(vloc, dict) or not vloc.get('latitude') or not vloc.get('longitude'):
            # Fallback based on vendorAddress or default
            area_match = 'Gachibowli'
            v_addr = a.get('vendorAddress', '')
            for area in LOCALITY_LIST:
                if area.lower() in v_addr.lower():
                    area_match = area
                    break
            loc_data = HYDERABAD_LOCALITIES[area_match]
            vloc = {'area': loc_data['area'], 'latitude': loc_data['latitude'], 'longitude': loc_data['longitude']}
            a['vendorLocation'] = vloc

        if cust_lat is not None and cust_lng is not None and vloc.get('latitude') and vloc.get('longitude'):
            dist = haversine_km(cust_lat, cust_lng, vloc['latitude'], vloc['longitude'])
            a['distance_km'] = dist
            a['distance_text'] = f"{dist} km away" if dist is not None else None
        else:
            a['distance_km'] = None
            a['distance_text'] = None

    # Filter by max_distance if requested
    if max_distance is not None:
        apps = [a for a in apps if a.get('distance_km') is not None and a['distance_km'] <= max_distance]

    # Sort by nearest / farthest if requested
    if sort_param == 'nearest':
        apps.sort(key=lambda a: (a.get('distance_km') is None, a.get('distance_km') or 999999))
    elif sort_param == 'farthest':
        apps.sort(key=lambda a: (a.get('distance_km') is None, -(a.get('distance_km') or 0)))

    try:
        all_reviews = list(db.reviews.find())
        review_map = {}
        for r in all_reviews:
            app_id = r.get('applianceId') if r.get('applianceId') is not None else r.get('appliance_id')
            if app_id is not None:
                try:
                    key = int(app_id)
                except (ValueError, TypeError):
                    key = str(app_id)
                review_map.setdefault(key, []).append(r)
        for a in apps:
            key = a.get('id')
            revs = review_map.get(key) or review_map.get(str(key))
            if revs:
                a['rating'] = round(sum(float(r.get('rating', 5)) for r in revs) / len(revs), 1)
                a['reviews'] = len(revs)
    except Exception as e:
        print("Error enriching appliances with ratings:", e)
    return jsonify(apps)

@app.route('/api/appliances/<int:app_id>', methods=['GET'])
def get_single_appliance(app_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    app_doc = db.appliances.find_one({'id': app_id})
    if not app_doc:
        return jsonify({"error": "Appliance not found"}), 404
    a = clean(app_doc)

    # Attach distance if customer coordinates provided
    lat_param = request.args.get('lat')
    lng_param = request.args.get('lng')
    if lat_param is not None and lng_param is not None:
        try:
            cust_lat = float(lat_param)
            cust_lng = float(lng_param)
            vloc = a.get('vendorLocation') or {}
            if vloc.get('latitude') and vloc.get('longitude'):
                dist = haversine_km(cust_lat, cust_lng, vloc['latitude'], vloc['longitude'])
                a['distance_km'] = dist
                a['distance_text'] = f"{dist} km away" if dist is not None else None
        except (ValueError, TypeError):
            pass

    try:
        revs = list(db.reviews.find({
            '$or': [
                {'applianceId': app_id},
                {'applianceId': str(app_id)},
                {'appliance_id': app_id},
                {'appliance_id': str(app_id)}
            ]
        }))
        if revs:
            a['rating'] = round(sum(float(r.get('rating', 5)) for r in revs) / len(revs), 1)
            a['reviews'] = len(revs)
    except Exception as e:
        print("Error fetching reviews for single appliance:", e)
    return jsonify(a)

@app.route('/api/appliances', methods=['POST'])
def add_appliance():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = request.headers.get('X-User-Role', '')
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to add appliances"}), 403

    data = request.json or {}
    vendor_email = (request.headers.get('X-User-Email') or data.get('vendor_email') or 'vendor@homerent.ai').strip().lower()
    data['vendor_email'] = vendor_email

    # Validate mandatory Vendor Address
    vendor_address = (data.get('vendorAddress') or data.get('address') or '').strip()
    if not vendor_address:
        return jsonify({"error": "Vendor address is mandatory. Please provide the address from where the appliance is provided."}), 400

    # Validate mandatory Vendor Phone Number (at least 10 digits)
    vendor_phone = (data.get('vendorPhone') or data.get('phone') or '').strip()
    phone_digits = re.sub(r'\D', '', vendor_phone)
    if len(phone_digits) < 10:
        return jsonify({"error": "Please enter a valid vendor phone number (at least 10 digits)."}), 400

    data['vendorAddress'] = vendor_address
    data['vendorPhone'] = vendor_phone

    # Vendor location handling (Hyderabad locality & coordinates)
    vendor_loc = data.get('vendorLocation') or {}
    area = (vendor_loc.get('area') or data.get('locality') or data.get('area') or '').strip()
    if not area:
        for loc_name in LOCALITY_LIST:
            if loc_name.lower() in vendor_address.lower():
                area = loc_name
                break
    if not area:
        area = 'Gachibowli'

    loc_coords = HYDERABAD_LOCALITIES.get(area, HYDERABAD_LOCALITIES['Gachibowli'])
    try:
        lat = float(vendor_loc.get('latitude') if vendor_loc.get('latitude') is not None else data.get('latitude', loc_coords['latitude']))
        lng = float(vendor_loc.get('longitude') if vendor_loc.get('longitude') is not None else data.get('longitude', loc_coords['longitude']))
    except (ValueError, TypeError):
        lat = loc_coords['latitude']
        lng = loc_coords['longitude']

    data['vendorLocation'] = {
        'area': area,
        'latitude': lat,
        'longitude': lng
    }

    # Assign numeric id
    max_id_doc = db.appliances.find_one(sort=[('id', -1)])
    new_id = (max_id_doc['id'] + 1) if max_id_doc and 'id' in max_id_doc else 1
    data['id'] = new_id
    data['name'] = data.get('title', data.get('name', ''))
    data['title'] = data['name']
    data['description'] = data.get('desc', data.get('description', ''))
    data['desc'] = data['description']
    data['price'] = float(data.get('price', 0))
    data['price_per_day'] = round(float(data.get('price', 0)) / 30, 2)
    data['availability'] = True
    data['availability_status'] = 'Available'
    data['quantity'] = int(data.get('stock', 10))
    data['available_quantity'] = int(data.get('stock', 10))
    # Resolve category_id
    cat = db.categories.find_one({'category_name': data.get('category', '')})
    data['category_id'] = str(cat['_id']) if cat else ''

    result = db.appliances.insert_one(dict(data))
    # Create inventory entry with vendor ownership & location
    stock = int(data.get('stock', 10))
    db.inventory.insert_one({
        'appliance_id': str(result.inserted_id),
        'appliance_int_id': new_id,
        'appliance_name': data['name'],
        'vendor_email': vendor_email,
        'vendorAddress': vendor_address,
        'vendorPhone': vendor_phone,
        'vendorLocation': data['vendorLocation'],
        'total_quantity': stock,
        'available_quantity': stock,
        'rented_quantity': 0,
        'status': 'available'
    })
    return jsonify(clean(data)), 201

@app.route('/api/appliances/<int:app_id>', methods=['PUT'])
def update_appliance(app_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = request.headers.get('X-User-Role', '')
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to update appliances"}), 403

    app_doc = db.appliances.find_one({'id': app_id})
    if not app_doc:
        return jsonify({"error": "Appliance not found"}), 404

    req_vendor = (request.headers.get('X-User-Email') or (request.json and request.json.get('vendor_email')) or '').strip().lower()
    owner_vendor = (app_doc.get('vendor_email') or 'vendor@homerent.ai').strip().lower()

    if req_vendor and req_vendor != owner_vendor:
        return jsonify({"error": "Forbidden: You can only edit appliances in your own inventory"}), 403

    data = request.json or {}
    data['name'] = data.get('title', data.get('name', ''))
    data['description'] = data.get('desc', data.get('description', ''))
    data['vendor_email'] = owner_vendor  # Preserve owner

    if 'vendorAddress' in data or 'address' in data:
        data['vendorAddress'] = (data.get('vendorAddress') or data.get('address') or '').strip()
    if 'vendorPhone' in data or 'phone' in data:
        data['vendorPhone'] = (data.get('vendorPhone') or data.get('phone') or '').strip()

    # Vendor location handling on update
    inv_update = {}
    if 'vendorLocation' in data and isinstance(data['vendorLocation'], dict):
        vloc = data['vendorLocation']
        area = vloc.get('area') or 'Gachibowli'
        loc_coords = HYDERABAD_LOCALITIES.get(area, HYDERABAD_LOCALITIES['Gachibowli'])
        try:
            lat = float(vloc.get('latitude', loc_coords['latitude']))
            lng = float(vloc.get('longitude', loc_coords['longitude']))
        except (ValueError, TypeError):
            lat = loc_coords['latitude']
            lng = loc_coords['longitude']
        data['vendorLocation'] = {'area': area, 'latitude': lat, 'longitude': lng}
        inv_update['vendorLocation'] = data['vendorLocation']
    elif 'area' in data or 'locality' in data:
        area = (data.get('area') or data.get('locality') or 'Gachibowli').strip()
        loc_coords = HYDERABAD_LOCALITIES.get(area, HYDERABAD_LOCALITIES['Gachibowli'])
        try:
            lat = float(data.get('latitude', loc_coords['latitude']))
            lng = float(data.get('longitude', loc_coords['longitude']))
        except (ValueError, TypeError):
            lat = loc_coords['latitude']
            lng = loc_coords['longitude']
        data['vendorLocation'] = {'area': area, 'latitude': lat, 'longitude': lng}
        inv_update['vendorLocation'] = data['vendorLocation']

    db.appliances.update_one({'id': app_id}, {'$set': data})
    if 'stock' in data or 'quantity' in data:
        new_stock = int(data.get('stock', data.get('quantity', 10)))
        inv_update['total_quantity'] = new_stock
        inv_update['available_quantity'] = new_stock
    if 'vendorAddress' in data:
        inv_update['vendorAddress'] = data['vendorAddress']
    if 'vendorPhone' in data:
        inv_update['vendorPhone'] = data['vendorPhone']
    if inv_update:
        db.inventory.update_one({'appliance_int_id': app_id}, {'$set': inv_update})
    return jsonify({"success": True})

@app.route('/api/appliances/<int:app_id>', methods=['DELETE'])
def delete_appliance(app_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = request.headers.get('X-User-Role', '')
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to delete appliances"}), 403

    app_doc = db.appliances.find_one({'id': app_id})
    if not app_doc:
        return jsonify({"error": "Appliance not found"}), 404

    req_vendor = (request.headers.get('X-User-Email') or request.args.get('vendor_email') or '').strip().lower()
    owner_vendor = (app_doc.get('vendor_email') or 'vendor@homerent.ai').strip().lower()

    if req_vendor and req_vendor != owner_vendor:
        return jsonify({"error": "Forbidden: You can only delete appliances from your own inventory"}), 403

    db.inventory.delete_one({'appliance_int_id': app_id})
    db.appliances.delete_one({'id': app_id})
    return jsonify({"success": True})

@app.route('/api/appliances/bulk', methods=['POST'])
def bulk_appliances():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    appliances = request.json
    if not appliances:
        return jsonify({"success": True})
    for a in appliances:
        if 'id' in a:
            update_data = {k: v for k, v in a.items()}
            db.appliances.update_one({'id': a['id']}, {'$set': update_data}, upsert=True)
    return jsonify({"success": True})


# ─────────────────────────────────────────────
# PAYMENT GATEWAY (RAZORPAY)
# ─────────────────────────────────────────────

@app.route('/api/payments/create-order', methods=['POST'])
def create_payment_order():
    if db is None:
        return jsonify({"error": "DB not connected"}), 500
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        return jsonify({"error": "Payment gateway not configured. Add RAZORPAY keys to .env"}), 500

    data = request.json or {}
    amount = data.get('amount')
    receipt_id = data.get('receipt_id') or f"rcpt_{int(time.time())}"

    try:
        amount_paise = int(float(amount) * 100)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount"}), 400

    if amount_paise < 100:
        return jsonify({"error": "Amount must be at least ₹1"}), 400

    try:
        order = razorpay_client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt_id,
            "payment_capture": 1
        })
    except Exception as e:
        print("Razorpay order creation failed:", e)
        return jsonify({"error": f"Razorpay error: {str(e)}"}), 500

    # Save pending payment record
    db.payments.insert_one({
        'razorpay_order_id': order['id'],
        'amount': float(amount),
        'currency': 'INR',
        'receipt_id': receipt_id,
        'payment_status': 'created',
        'payment_method': 'razorpay',
        'user_email': (request.headers.get('X-User-Email') or '').lower(),
        'created_at': datetime.now().isoformat()
    })

    return jsonify({
        "order_id": order['id'],
        "amount": order['amount'],
        "currency": order['currency'],
        "key_id": RAZORPAY_KEY_ID
    })


@app.route('/api/payments/verify', methods=['POST'])
def verify_payment():
    if db is None:
        return jsonify({"error": "DB not connected"}), 500

    data = request.json or {}
    razorpay_order_id   = data.get('razorpay_order_id')
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_signature  = data.get('razorpay_signature')

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        return jsonify({"error": "Missing payment verification fields"}), 400

    msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
    expected = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        msg,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, razorpay_signature):
        db.payments.update_one(
            {'razorpay_order_id': razorpay_order_id},
            {'$set': {'payment_status': 'signature_failed'}}
        )
        return jsonify({"error": "Payment signature verification failed"}), 400

    db.payments.update_one(
        {'razorpay_order_id': razorpay_order_id},
        {'$set': {
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature,
            'payment_status': 'paid',
            'paid_at': datetime.now().isoformat()
        }}
    )

    return jsonify({"success": True, "payment_id": razorpay_payment_id})


@app.route('/api/payments/webhook', methods=['POST'])
def razorpay_webhook():
    """Optional: catches payments even if user closes browser."""
    webhook_secret = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')
    body = request.get_data()
    signature = request.headers.get('X-Razorpay-Signature', '')

    if webhook_secret and signature:
        expected = hmac.new(
            webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return jsonify({"error": "Invalid webhook signature"}), 400

    event = request.json or {}
    if event.get('event') == 'payment.captured':
        payment = event['payload']['payment']['entity']
        db.payments.update_one(
            {'razorpay_order_id': payment['order_id']},
            {'$set': {
                'payment_status': 'captured',
                'razorpay_payment_id': payment['id'],
                'webhook_received_at': datetime.now().isoformat()
            }},
            upsert=True
        )
    return jsonify({"status": "ok"})
# ─────────────────────────────────────────────
# BOOKINGS API
# ─────────────────────────────────────────────

@app.route('/api/bookings', methods=['GET'])
def get_bookings():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    return jsonify(clean_list(db.bookings.find()))

@app.route('/api/bookings/<booking_id>', methods=['GET'])
def get_single_booking(booking_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    b = db.bookings.find_one({'id': booking_id})
    if not b:
        return jsonify({"error": "Booking not found"}), 404
    return jsonify(clean(b))

@app.route('/api/bookings', methods=['POST'])
def add_booking():
    if db is None: return jsonify({"error": "DB not connected"}), 500

    booking = request.json or {}

    user_email = (request.headers.get('X-User-Email') or '').strip().lower()
    role = (request.headers.get('X-User-Role') or '').strip().lower()
    cust_email = (booking.get('email') or booking.get('user_id') or '').strip().lower()

    effective_email = user_email or cust_email

    # Backend Authentication Check: Must be logged in to book an appliance
    if not effective_email:
        return jsonify({"error": "Authentication required. Please sign in to book an appliance."}), 401

    # Verify user exists in database or demo users
    user_doc = db.users.find_one({'email': effective_email})
    if not user_doc and effective_email not in ['customer@homerent.ai']:
        return jsonify({"error": "Authentication required. Please sign in to book an appliance."}), 401

    # RBAC: Vendor accounts cannot book appliances
    if role == 'vendor' or (user_doc and user_doc.get('role') == 'vendor'):
        return jsonify({"error": "Forbidden: Vendor accounts cannot place customer rental bookings"}), 403

    # Check if booking with this id already exists
    if db.bookings.find_one({'id': booking.get('id')}):
        return jsonify({"success": True, "message": "already exists"})

    # Determine vendor owning the booked appliance
    appliance_int_id = booking.get('appliance_id')
    app_doc = None
    if appliance_int_id:
        try:
            app_doc = db.appliances.find_one({'id': int(appliance_int_id)})
        except Exception:
            pass
    vendor_email = (booking.get('vendor_email') or (app_doc.get('vendor_email') if app_doc else None) or 'vendor@homerent.ai').strip().lower()
    booking['vendor_email'] = vendor_email

    # Ensure complete vendor and category info for receipt
    booking['vendor_name'] = booking.get('vendor_name') or (app_doc.get('brand') if app_doc else None) or 'HomeRent Certified Vendor'
    booking['vendor_phone'] = booking.get('vendor_phone') or booking.get('vendorPhone') or (app_doc.get('vendorPhone') if app_doc else None) or '9876543210'
    booking['vendor_address'] = booking.get('vendor_address') or booking.get('vendorAddress') or (app_doc.get('vendorAddress') if app_doc else None) or 'Indiranagar, Bengaluru, Karnataka'
    booking['vendorPhone'] = booking['vendor_phone']
    booking['vendorAddress'] = booking['vendor_address']
    if 'category' not in booking and app_doc:
        booking['category'] = app_doc.get('category', 'kitchen')

    # Payment Method & Status Configuration
    pay_method = (booking.get('paymentMethod') or booking.get('payment_method') or 'cod').lower()
    is_online = pay_method in ['razorpay', 'online', 'upi']

    if is_online:
        booking['paymentMethod'] = 'razorpay'
        booking['payment_method'] = 'razorpay'
        booking['payment_status'] = 'paid'
        booking['status'] = booking.get('status', 'active')
        if not booking.get('receipt_number'):
            booking['receipt_number'] = f"REC-ONL-{int(time.time()*1000)%10000000:07d}"
    else:
        booking['paymentMethod'] = 'cod'
        booking['payment_method'] = 'cod'
        booking['payment_status'] = 'pending'
        booking['status'] = booking.get('status', 'confirmed')
        if not booking.get('receipt_number'):
            booking['receipt_number'] = f"REC-COD-{int(time.time()*1000)%10000000:07d}"

    db.bookings.insert_one(dict(booking))

    # Payment record
    payment_record = {
        'receipt_number': booking['receipt_number'],
        'booking_id': booking.get('id'),
        'user_id': booking.get('email', booking.get('user_id', '')),
        'amount': booking.get('totalRent', booking.get('total_amount', 0)),
        'payment_method': 'razorpay' if is_online else 'cod',
        'payment_status': 'paid' if is_online else 'pending',
        'payment_date': datetime.now().isoformat()
    }
    if is_online:
        payment_record['razorpay_payment_id'] = booking.get('razorpay_payment_id')
        payment_record['razorpay_order_id'] = booking.get('razorpay_order_id')
    db.payments.insert_one(payment_record)

    # Revenue record
    db.revenue.insert_one({
        'booking_id': booking.get('id'),
        'vendor_email': vendor_email,
        'amount': booking.get('totalRent', booking.get('total_amount', 0)),
        'date': booking.get('date', datetime.now().strftime('%d/%m/%Y')),
        'payment_status': 'paid' if is_online else 'pending'
    })

    # Update inventory — decrement available, increment rented
    if appliance_int_id:
        db.inventory.update_one(
            {'appliance_int_id': int(appliance_int_id)},
            {'$inc': {'available_quantity': -1, 'rented_quantity': 1}}
        )

    # Notification for the appliance's specific vendor
    db.notifications.insert_one({
        'user_id': vendor_email,
        'message': f"New booking #{booking.get('id')} received for {booking.get('applianceName', 'an appliance')} from {booking.get('customerName', 'a customer')}.",
        'type': 'new_booking',
        'is_read': False,
        'created_at': datetime.now().isoformat()
    })

    # Notification for customer
    user_email = booking.get('email', '')
    if user_email:
        db.notifications.insert_one({
            'user_id': user_email,
            'message': f"Your booking #{booking.get('id')} for {booking.get('applianceName', 'an appliance')} is confirmed!",
            'type': 'booking_confirmed',
            'is_read': False,
            'created_at': datetime.now().isoformat()
        })

    return jsonify({"success": True})

@app.route('/api/bookings/<booking_id>/status', methods=['PUT'])
def update_booking_status(booking_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = request.headers.get('X-User-Role', '')
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to update booking status"}), 403

    data = request.json
    new_status = data.get('status')

    booking = db.bookings.find_one({'id': booking_id})
    if not booking:
        return jsonify({"error": "Booking not found"}), 404

    req_vendor = (request.headers.get('X-User-Email') or (request.json and request.json.get('vendor_email')) or '').strip().lower()
    owner_vendor = (booking.get('vendor_email') or 'vendor@homerent.ai').strip().lower()
    if req_vendor and req_vendor != owner_vendor:
        return jsonify({"error": "Forbidden: You can only update bookings for your own appliances"}), 403

    db.bookings.update_one({'id': booking_id}, {'$set': {'status': new_status}})

    # If completed/returned → create returns record + restore inventory
    if new_status == 'completed':
        appliance_int_id = booking.get('appliance_id')
        if appliance_int_id:
            db.inventory.update_one(
                {'appliance_int_id': int(appliance_int_id)},
                {'$inc': {'available_quantity': 1, 'rented_quantity': -1}}
            )
        db.returns.insert_one({
            'booking_id': booking_id,
            'appliance_id': booking.get('appliance_id'),
            'return_date': datetime.now().strftime('%d/%m/%Y'),
            'condition': 'good',
            'late_fee': 0
        })
        # Notify customer
        user_id = booking.get('email', booking.get('user_id', ''))
        if user_id:
            db.notifications.insert_one({
                'user_id': user_id,
                'message': f"Your rental #{booking_id} has been marked as returned. Thank you for choosing HomeRent AI!",
                'type': 'booking_returned',
                'is_read': False,
                'created_at': datetime.now().isoformat()
            })

    return jsonify({"success": True})

@app.route('/api/bookings/bulk', methods=['POST'])
def bulk_bookings():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    bookings = request.json
    if not bookings:
        return jsonify({"success": True})
    for b in bookings:
        if 'id' in b:
            db.bookings.update_one({'id': b['id']}, {'$set': b}, upsert=True)
    return jsonify({"success": True})

@app.route('/api/bookings/<booking_id>/cod-confirm', methods=['PUT'])
def confirm_cod_payment(booking_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = (request.headers.get('X-User-Role') or '').strip().lower()
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to confirm cash collection"}), 403

    booking = db.bookings.find_one({'id': booking_id})
    if not booking:
        return jsonify({"error": "Booking not found"}), 404

    req_vendor = (request.headers.get('X-User-Email') or (request.json and request.json.get('vendor_email')) or '').strip().lower()
    owner_vendor = (booking.get('vendor_email') or 'vendor@homerent.ai').strip().lower()
    if req_vendor and req_vendor != owner_vendor:
        return jsonify({"error": "Forbidden: You can only confirm COD payments for your own appliances"}), 403

    db.bookings.update_one({'id': booking_id}, {'$set': {'payment_status': 'paid'}})
    db.payments.update_one({'booking_id': booking_id}, {'$set': {'payment_status': 'paid', 'confirmed_at': datetime.now().isoformat()}})
    db.revenue.update_one({'booking_id': booking_id}, {'$set': {'payment_status': 'paid'}})

    amount = booking.get('totalRent', booking.get('total_amount', 0))
    cust_email = (booking.get('email') or booking.get('user_id') or '').strip().lower()
    if cust_email:
        db.notifications.insert_one({
            'user_id': cust_email,
            'message': f"Payment Received: Cash payment of ₹{amount:,.0f} for rental #{booking_id} has been verified and marked as Paid by the vendor.",
            'type': 'payment_confirmed',
            'is_read': False,
            'created_at': datetime.now().isoformat()
        })

    return jsonify({"success": True, "message": f"Cash on delivery payment of ₹{amount:,.0f} marked as Paid."})

# ─────────────────────────────────────────────
# APPLIANCE RETURN REQUESTS API
# ─────────────────────────────────────────────

@app.route('/api/return-requests', methods=['GET'])
def get_return_requests():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    user_email = (request.args.get('email') or request.headers.get('X-User-Email') or '').strip().lower()
    role = (request.args.get('role') or request.headers.get('X-User-Role') or '').strip().lower()

    query = {}
    if role == 'customer' and user_email:
        query['customer_email'] = user_email
    elif role == 'vendor' and user_email:
        query['vendor_email'] = user_email

    requests_list = list(db.return_requests.find(query).sort('created_at', -1))
    return jsonify(clean_list(requests_list))

@app.route('/api/return-requests', methods=['POST'])
def create_return_request():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    data = request.json or {}
    cust_email = (data.get('customer_email') or request.headers.get('X-User-Email') or '').strip().lower()
    booking_id = data.get('booking_id')
    requested_pickup_date = data.get('requested_pickup_date', '').strip()
    reason = data.get('reason', '').strip()

    if not cust_email:
        return jsonify({"error": "Customer email is required"}), 401
    if not booking_id:
        return jsonify({"error": "Booking ID is required"}), 400
    if not reason:
        return jsonify({"error": "Reason for return is required"}), 400

    booking = db.bookings.find_one({'id': booking_id})
    if not booking:
        return jsonify({"error": f"Booking '{booking_id}' not found"}), 404

    # RBAC: Verify customer owns booking
    owner_cust = (booking.get('email') or booking.get('user_id') or '').strip().lower()
    if cust_email != owner_cust:
        return jsonify({"error": "Forbidden: You can only submit return requests for your own rental bookings"}), 403

    # Check booking status: must be active/confirmed
    b_status = (booking.get('status') or '').lower()
    if b_status in ['completed', 'cancelled', 'returned']:
        return jsonify({"error": f"Cannot return an appliance for a booking that is already {b_status}."}), 400

    # Prevent duplicate active return requests
    existing_req = db.return_requests.find_one({
        'booking_id': booking_id,
        'status': {'$in': ['pending', 'accepted', 'pickup_scheduled']}
    })
    if existing_req:
        return jsonify({
            "error": f"An active return request is already in progress for this booking (Request ID: {existing_req.get('request_id')})."
        }), 409

    # Calculate remaining days and return policy eligibility
    # Advance-notice period is 3 days
    end_date_str = booking.get('end_date', '')
    days_remaining = None
    if end_date_str:
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
            try:
                dt_end = datetime.strptime(end_date_str.strip(), fmt).date()
                today_date = date.today()
                days_remaining = (dt_end - today_date).days
                break
            except Exception:
                pass

    if days_remaining is not None:
        if days_remaining < 3 and days_remaining >= 0:
            return jsonify({
                "error": f"Return policy violation: Return requests must be submitted with at least 3 days advance notice before the rental tenure ends ({end_date_str}). Remaining days: {days_remaining}."
            }), 400
        elif days_remaining < 0:
            return jsonify({
                "error": f"Rental tenure ended on {end_date_str}. Please contact support or vendor for overdue return assistance."
            }), 400

    req_id = f"RET-{int(time.time()*1000)%10000000:07d}"
    now_iso = datetime.now().isoformat()
    return_doc = {
        'request_id': req_id,
        'booking_id': booking_id,
        'appliance_id': booking.get('appliance_id'),
        'appliance_name': booking.get('applianceName') or booking.get('appliance_name', 'Appliance'),
        'category': booking.get('category', 'kitchen'),
        'customer_email': cust_email,
        'customer_name': booking.get('customerName') or booking.get('customer_name') or 'Customer',
        'customer_phone': booking.get('customerPhone') or booking.get('phone', ''),
        'vendor_email': (booking.get('vendor_email') or 'vendor@homerent.ai').strip().lower(),
        'rental_start_date': booking.get('start_date', ''),
        'rental_end_date': end_date_str,
        'remaining_days_at_request': days_remaining if days_remaining is not None else 30,
        'requested_pickup_date': requested_pickup_date or datetime.now().strftime('%d/%m/%Y'),
        'reason': reason,
        'status': 'pending',
        'vendor_response': '',
        'scheduled_pickup_date': '',
        'created_at': now_iso,
        'updated_at': now_iso
    }
    db.return_requests.insert_one(return_doc)

    # Notify vendor
    db.notifications.insert_one({
        'user_id': return_doc['vendor_email'],
        'message': f"New Return Request #{req_id}: Customer {return_doc['customer_name']} requested pickup for {return_doc['appliance_name']}.",
        'type': 'return_request',
        'is_read': False,
        'created_at': now_iso
    })

    return jsonify(clean(return_doc)), 201

@app.route('/api/return-requests/<request_id>', methods=['PUT'])
def update_return_request(request_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    role = (request.headers.get('X-User-Role') or '').strip().lower()
    if role and role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required to manage return requests"}), 403

    req_doc = db.return_requests.find_one({'request_id': request_id})
    if not req_doc:
        return jsonify({"error": f"Return request '{request_id}' not found"}), 404

    vendor_email = (request.headers.get('X-User-Email') or '').strip().lower()
    owner_vendor = (req_doc.get('vendor_email') or 'vendor@homerent.ai').strip().lower()
    if vendor_email and vendor_email != owner_vendor:
        return jsonify({"error": "Forbidden: You can only manage return requests for your own appliances"}), 403

    data = request.json or {}
    new_status = data.get('status')
    vendor_response = data.get('vendor_response', '').strip()
    scheduled_date = data.get('scheduled_pickup_date', '').strip()

    valid_statuses = ['pending', 'accepted', 'rejected', 'pickup_scheduled', 'returned', 'closed']
    if new_status and new_status not in valid_statuses:
        return jsonify({"error": f"Invalid status '{new_status}'. Valid values: {valid_statuses}"}), 400

    now_iso = datetime.now().isoformat()
    update_data = {'updated_at': now_iso}
    if new_status:
        update_data['status'] = new_status
    if vendor_response:
        update_data['vendor_response'] = vendor_response
    if scheduled_date:
        update_data['scheduled_pickup_date'] = scheduled_date

    db.return_requests.update_one({'request_id': request_id}, {'$set': update_data})

    # If status is 'returned' or 'closed' -> complete booking, restore inventory, record in db.returns
    if new_status in ('returned', 'closed'):
        booking_id = req_doc.get('booking_id')
        db.bookings.update_one({'id': booking_id}, {'$set': {'status': 'completed'}})

        appliance_int_id = req_doc.get('appliance_id')
        if appliance_int_id:
            try:
                db.inventory.update_one(
                    {'appliance_int_id': int(appliance_int_id)},
                    {'$inc': {'available_quantity': 1, 'rented_quantity': -1}}
                )
            except Exception:
                pass

        db.returns.insert_one({
            'return_request_id': request_id,
            'booking_id': booking_id,
            'appliance_id': appliance_int_id,
            'return_date': datetime.now().strftime('%d/%m/%Y'),
            'condition': 'good',
            'late_fee': 0,
            'vendor_confirmed': True,
            'created_at': now_iso
        })

        # Notify customer
        db.notifications.insert_one({
            'user_id': req_doc['customer_email'],
            'message': f"Return Completed: Your rental #{booking_id} ({req_doc['appliance_name']}) has been successfully returned and inspected.",
            'type': 'return_completed',
            'is_read': False,
            'created_at': now_iso
        })
    elif new_status == 'accepted':
        db.notifications.insert_one({
            'user_id': req_doc['customer_email'],
            'message': f"Return Request Accepted: Vendor accepted your return request for {req_doc['appliance_name']}. Note: {vendor_response or 'Pickup will be scheduled.'}",
            'type': 'return_accepted',
            'is_read': False,
            'created_at': now_iso
        })
    elif new_status == 'rejected':
        db.notifications.insert_one({
            'user_id': req_doc['customer_email'],
            'message': f"Return Request Update: Your return request for {req_doc['appliance_name']} was rejected. Reason: {vendor_response or 'Policy requirements not met.'}",
            'type': 'return_rejected',
            'is_read': False,
            'created_at': now_iso
        })

    updated_doc = db.return_requests.find_one({'request_id': request_id})
    return jsonify(clean(updated_doc))

# ─────────────────────────────────────────────
# INVENTORY API
# ─────────────────────────────────────────────

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    return jsonify(clean_list(db.inventory.find()))

# ─────────────────────────────────────────────
# REVENUE API
# ─────────────────────────────────────────────

@app.route('/api/revenue', methods=['GET'])
def get_revenue():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    return jsonify(clean_list(db.revenue.find()))

# ─────────────────────────────────────────────
# NOTIFICATIONS API
# ─────────────────────────────────────────────

@app.route('/api/notifications/<user_id>', methods=['GET'])
def get_notifications(user_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    notes = clean_list(db.notifications.find({'user_id': user_id}).sort('created_at', -1).limit(20))
    return jsonify(notes)

@app.route('/api/notifications', methods=['POST'])
def create_notification():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    data = request.json
    data['created_at'] = datetime.now().isoformat()
    data['is_read'] = False
    db.notifications.insert_one(data)
    return jsonify({"success": True})

@app.route('/api/notifications/<nid>/read', methods=['PUT'])
def mark_notification_read(nid):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    try:
        db.notifications.update_one({'_id': ObjectId(nid)}, {'$set': {'is_read': True}})
    except Exception:
        pass
    return jsonify({"success": True})

# ─────────────────────────────────────────────
# CART API (user-scoped)
# ─────────────────────────────────────────────

@app.route('/api/cart', methods=['GET'])
def get_global_cart():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    cart_doc = db.cart.find_one({"user_id": "global_cart"})
    return jsonify(cart_doc["items"] if cart_doc else [])

@app.route('/api/cart', methods=['POST'])
def update_global_cart():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    cart_items = request.json
    db.cart.update_one(
        {"user_id": "global_cart"},
        {"$set": {"user_id": "global_cart", "items": cart_items}},
        upsert=True
    )
    return jsonify({"success": True})

@app.route('/api/cart/<user_id>', methods=['GET'])
def get_user_cart(user_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    cart_doc = db.cart.find_one({"user_id": user_id})
    return jsonify(cart_doc["items"] if cart_doc else [])

@app.route('/api/cart/<user_id>', methods=['POST'])
def update_user_cart(user_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    cart_items = request.json
    db.cart.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "items": cart_items}},
        upsert=True
    )
    return jsonify({"success": True})

# ─────────────────────────────────────────────
# REVIEWS API
# ─────────────────────────────────────────────

def handle_create_review(app_id, data, user_email, user_role):
    if not user_email:
        return jsonify({"error": "Authentication required. Please sign in as a customer to post a review."}), 401
    
    if user_role == 'vendor':
        return jsonify({"error": "Vendor accounts cannot submit customer reviews."}), 403

    # Validate rating
    try:
        rating = float(data.get('rating', 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid rating score. Please provide a rating between 1 and 5."}), 400
    
    if rating < 1 or rating > 5:
        return jsonify({"error": "Rating must be between 1 and 5 stars."}), 400

    # Validate comment
    comment = (data.get('comment') or '').strip()
    if not comment:
        return jsonify({"error": "Review comment cannot be empty."}), 400

    # Rental verification rule: customer must have rented or booked this appliance
    booking = db.bookings.find_one({
        '$and': [
            {'$or': [
                {'email': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}},
                {'user_id': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}}
            ]},
            {'$or': [
                {'appliance_id': app_id},
                {'appliance_id': str(app_id)},
                {'applianceId': app_id},
                {'applianceId': str(app_id)}
            ]}
        ]
    })

    if not booking:
        return jsonify({
            "error": "Rental verification required: Only customers who have rented or booked this appliance can write a review."
        }), 403

    # Duplicate prevention: customer can review an appliance only once
    existing_rev = db.reviews.find_one({
        '$and': [
            {'$or': [
                {'customerId': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}},
                {'customerEmail': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}},
                {'user_id': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}}
            ]},
            {'$or': [
                {'applianceId': app_id},
                {'applianceId': str(app_id)},
                {'appliance_id': app_id},
                {'appliance_id': str(app_id)}
            ]}
        ]
    })

    if existing_rev:
        return jsonify({
            "error": "You have already submitted a review for this appliance. Duplicate reviews are not permitted."
        }), 400

    # Fetch customer display name
    customer_name = (data.get('customerName') or '').strip()
    if not customer_name:
        u = db.users.find_one({'email': user_email})
        if u and u.get('name'):
            customer_name = u['name']
        elif booking and booking.get('customerName'):
            customer_name = booking['customerName']
        else:
            customer_name = user_email.split('@')[0].capitalize()

    new_review = {
        'applianceId': int(app_id) if str(app_id).isdigit() else app_id,
        'appliance_id': int(app_id) if str(app_id).isdigit() else app_id,
        'customerId': user_email,
        'customerEmail': user_email,
        'customerName': customer_name,
        'rating': round(rating, 1),
        'comment': comment,
        'createdAt': datetime.now().strftime("%d-%m-%Y"),
        'created_at': datetime.now().isoformat()
    }
    db.reviews.insert_one(new_review)

    # Recalculate average rating & reviews count in db.appliances
    all_revs = list(db.reviews.find({
        '$or': [
            {'applianceId': app_id},
            {'applianceId': str(app_id)},
            {'appliance_id': app_id},
            {'appliance_id': str(app_id)},
            {'applianceId': int(app_id) if str(app_id).isdigit() else app_id}
        ]
    }))
    total_count = len(all_revs)
    avg_rating = round(sum(float(r.get('rating', 5)) for r in all_revs) / total_count, 1) if total_count > 0 else 5.0

    db.appliances.update_one(
        {'$or': [{'id': app_id}, {'id': int(app_id) if str(app_id).isdigit() else app_id}]},
        {'$set': {'rating': avg_rating, 'reviews': total_count}}
    )

    return jsonify({
        "success": True,
        "message": "Review submitted successfully!",
        "review": clean(new_review),
        "average_rating": avg_rating,
        "total_reviews": total_count
    }), 201

@app.route('/api/appliances/<int:app_id>/reviews', methods=['GET'])
def get_appliance_reviews(app_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    revs = list(db.reviews.find({
        '$or': [
            {'applianceId': app_id},
            {'applianceId': str(app_id)},
            {'appliance_id': app_id},
            {'appliance_id': str(app_id)}
        ]
    }))
    clean_revs = clean_list(revs)
    total = len(clean_revs)
    avg = round(sum(float(r.get('rating', 5)) for r in clean_revs) / total, 1) if total > 0 else 0
    return jsonify({
        'appliance_id': app_id,
        'total_reviews': total,
        'average_rating': avg,
        'reviews': clean_revs
    })

@app.route('/api/appliances/<int:app_id>/reviews', methods=['POST'])
def post_appliance_review(app_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    data = request.json or {}
    user_email = (request.headers.get('X-User-Email') or data.get('customerId') or data.get('email') or '').strip().lower()
    user_role = (request.headers.get('X-User-Role') or data.get('role') or 'customer').strip().lower()
    return handle_create_review(app_id, data, user_email, user_role)

@app.route('/api/appliances/<int:app_id>/review-eligibility', methods=['GET'])
def check_review_eligibility(app_id):
    if db is None: return jsonify({"error": "DB not connected"}), 500
    user_email = (request.headers.get('X-User-Email') or request.args.get('email') or '').strip().lower()
    user_role = (request.headers.get('X-User-Role') or request.args.get('role') or 'customer').strip().lower()

    if not user_email:
        return jsonify({"can_review": False, "reason": "not_logged_in", "message": "Sign in as a customer to post a review."})
    
    if user_role == 'vendor':
        return jsonify({"can_review": False, "reason": "vendor_account", "message": "Vendor accounts cannot post customer reviews."})

    has_booked = db.bookings.find_one({
        '$and': [
            {'$or': [
                {'email': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}},
                {'user_id': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}}
            ]},
            {'$or': [
                {'appliance_id': app_id},
                {'appliance_id': str(app_id)},
                {'applianceId': app_id},
                {'applianceId': str(app_id)}
            ]}
        ]
    }) is not None

    if not has_booked:
        return jsonify({"can_review": False, "reason": "not_rented", "message": "Only customers who have rented or booked this appliance can write a review."})

    already_reviewed = db.reviews.find_one({
        '$and': [
            {'$or': [
                {'customerId': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}},
                {'customerEmail': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}},
                {'user_id': {'$regex': f'^{re.escape(user_email)}$', '$options': 'i'}}
            ]},
            {'$or': [
                {'applianceId': app_id},
                {'applianceId': str(app_id)},
                {'appliance_id': app_id},
                {'appliance_id': str(app_id)}
            ]}
        ]
    }) is not None

    if already_reviewed:
        return jsonify({"can_review": False, "reason": "already_reviewed", "message": "You have already submitted a review for this appliance."})

    return jsonify({"can_review": True, "message": "Eligible to review this appliance."})

@app.route('/api/reviews', methods=['GET'])
def get_reviews():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    app_id = request.args.get('appliance_id') or request.args.get('applianceId')
    if app_id:
        try:
            aid = int(app_id)
        except ValueError:
            aid = app_id
        return jsonify(clean_list(db.reviews.find({
            '$or': [
                {'applianceId': aid},
                {'applianceId': str(aid)},
                {'appliance_id': aid},
                {'appliance_id': str(aid)}
            ]
        })))
    return jsonify(clean_list(db.reviews.find()))

@app.route('/api/reviews', methods=['POST'])
def add_review():
    if db is None: return jsonify({"error": "DB not connected"}), 500
    data = request.json or {}
    app_id = data.get('applianceId') or data.get('appliance_id') or data.get('id')
    if not app_id:
        return jsonify({"error": "appliance_id is required"}), 400
    user_email = (request.headers.get('X-User-Email') or data.get('customerId') or data.get('email') or '').strip().lower()
    user_role = (request.headers.get('X-User-Role') or data.get('role') or 'customer').strip().lower()
    return handle_create_review(app_id, data, user_email, user_role)

# ─────────────────────────────────────────────
# VENDOR LSTM DEMAND FORECASTING API
# ─────────────────────────────────────────────

@app.route('/api/vendor/forecast-appliances', methods=['GET', 'OPTIONS'])
def get_vendor_forecast_appliances():
    if db is None:
        return jsonify({"error": "DB not connected"}), 500
    user_email = (request.headers.get('X-User-Email') or request.args.get('email') or 'vendor@homerent.ai').strip().lower()
    user_role = (request.headers.get('X-User-Role') or request.args.get('role') or 'vendor').strip().lower()
    if user_role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required for forecasting console"}), 403
    
    data = get_vendor_appliances_and_counts(db, user_email)
    return jsonify({"success": True, **data})

@app.route('/api/vendor/demand-forecast', methods=['GET', 'POST', 'OPTIONS'])
def get_demand_forecast():
    if db is None:
        return jsonify({"error": "DB not connected"}), 500
    
    if request.method == 'GET':
        req_data = request.args.to_dict()
    else:
        req_data = request.get_json(silent=True) or {}

    user_email = (request.headers.get('X-User-Email') or req_data.get('vendor_email') or req_data.get('email') or 'vendor@homerent.ai').strip().lower()
    user_role = (request.headers.get('X-User-Role') or req_data.get('role') or 'vendor').strip().lower()
    if user_role != 'vendor':
        return jsonify({"error": "Forbidden: Vendor access required for forecasting console"}), 403

    appliance_id = req_data.get('appliance_id')
    category = req_data.get('category')
    try:
        horizon = int(req_data.get('horizon', 14))
    except (ValueError, TypeError):
        horizon = 14
    interval = req_data.get('interval', 'daily')
    force_retrain = str(req_data.get('force_retrain', False)).lower() in ('true', '1')

    if horizon not in [7, 14, 30, 90]:
        horizon = 14

    result = generate_demand_forecast(
        db,
        vendor_email=user_email,
        appliance_id=appliance_id,
        category=category,
        horizon=horizon,
        interval=interval,
        force_retrain=force_retrain
    )

    return jsonify(result)

# ─────────────────────────────────────────────
# STATIC FILE SERVING
# ─────────────────────────────────────────────

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path.startswith('api/'):
        return jsonify({"error": f"API endpoint not found: /{path}"}), 404
    if path == '':
        path = 'home.html'
    full_path = os.path.join(app.static_folder, path)
    if os.path.exists(full_path) and os.path.isfile(full_path):
        resp = send_from_directory(app.static_folder, path)
    else:
        resp = send_from_directory(app.static_folder, 'home.html')

    if path.endswith('.html') or path == '' or path == 'home.html':
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    return resp

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

if __name__ == '__main__':
    local_ip = get_local_ip()
    print("=" * 65)
    print("  HomeRent AI Server is running!")
    print(f"  - Local URL:         http://localhost:{PORT}")
    print(f"  - Network (Wi-Fi):   http://{local_ip}:{PORT}")
    print(f"  - Database:          {MONGO_URI}")
    print("=" * 65)
    print("  To access from other devices on the same Wi-Fi / network, open:")
    print(f"  http://{local_ip}:{PORT}/appliances.html")
    print("=" * 65)
    app.run(host=HOST, port=PORT, debug=False)
