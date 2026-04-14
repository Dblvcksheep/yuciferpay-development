import time

from gevent import monkey

monkey.patch_all()
import uuid
from flask import Flask, abort, render_template, redirect, url_for, flash, request, session
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user,login_required
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Text, DateTime, Float, Boolean, or_
from functools import wraps
from http import HTTPStatus
import os
import pandas
from flask_mail import Mail, Message
from datetime import datetime, timedelta
import requests
from werkzeug.security import generate_password_hash, check_password_hash
from Crypto.Cipher import AES
from celery_app import make_celery
from flask_migrate import Migrate
import base64
import random
import hmac
import hashlib
import json
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import TooManyRequests
import threading


load_dotenv()

encryption_key = os.environ['ENCRYPTION_KEY'].encode()
pkey = os.environ['PAYSTACK_PUBLIC_KEY']
skey = os.environ['PAYSTACK_SECRET']
app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
celery = make_celery(app)


recv_window=str(5000)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=os.environ['CELERY_BROKER_URL'],
)

app.config['MAIL_SERVER']   = os.environ['MAIL_SERVER']
app.config['MAIL_PORT']     = 587
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USERNAME'] = os.environ['MAIL_USERNAME']
app.config['MAIL_PASSWORD'] = os.environ['MAIL_PASSWORD']
app.config['MAIL_DEFAULT_SENDER'] = ('YuciferPay', os.environ['MAIL_USERNAME'])

mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
app.jinja_env.globals['now'] = datetime.now

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

# CREATE DATABASE
class Base(DeclarativeBase):
    pass
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}
db = SQLAlchemy(model_class=Base)
db.init_app(app)
migrate = Migrate(app, db)

def login_key():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    if email:
        return f"email:{email}"
    return f"ip:{get_remote_address()}"

def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # If id is not 1 then return abort with 403 error
        if not current_user.is_authenticated and current_user.id != 1:
            return abort(403)
        # Otherwise continue with the route function
        return f(*args, **kwargs)
    return decorated_function

def encrypt(private_key):
    cipher = AES.new(encryption_key, AES.MODE_EAX)
    nonce = cipher.nonce
    ciphertext, tag = cipher.encrypt_and_digest(private_key.encode())
    return base64.b64encode(nonce + tag + ciphertext).decode()

def decrypt(enc_private_key):
    data = base64.b64decode(enc_private_key)
    nonce, tag, ciphertext = data[:16], data[16:32], data[32:]
    cipher = AES.new(encryption_key, AES.MODE_EAX, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode()

class User(db.Model, UserMixin):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(225), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    trades = db.Column(db.Integer(), nullable=False, default=0)
    password = db.Column(db.Text, nullable=False)
    api_key = db.Column(db.Text, nullable=True)
    api_secret = db.Column(db.Text, nullable=True)
    service = db.Column(db.String(100), nullable=False, default = 'bybit')
    bank = db.Column(db.String(100), nullable=False, default='paystack')
    paystack_secret = db.Column(db.Text, nullable=True)
    paystack_public = db.Column(db.Text, nullable=True)
    nombank_accountid = db.Column(db.Text, nullable=True)
    nombank_clientid = db.Column(db.Text, nullable=True)
    nombank_clientsecret = db.Column(db.Text, nullable=True)
    balance = db.Column(db.Float, nullable=False, default=0.0)
    top_up_balance = db.Column(db.Float, nullable=False, default=0.0)
    automate = db.Column(db.Boolean, nullable=False, default=True)
    deposits = db.relationship(
        'Deposit',
        backref='user',
        cascade='all, delete-orphan'
    )
    withdraws = db.relationship(
        'Withdraw',
        backref='user',
        cascade='all, delete-orphan'
    )
    order = db.relationship('Order', backref='user' ,lazy='dynamic', cascade="all, delete-orphan")
    notify = db.relationship('Notify', backref='user',lazy='dynamic', cascade="all, delete-orphan")
    schedule = db.relationship('Schedule', backref='user', lazy='dynamic', cascade="all, delete-orphan")

class Notify(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text)
    level = db.Column(db.String(20))
    seen = db.Column(db.Boolean, default=False)
    expire_at = db.Column(db.DateTime)


class Deposit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.now())

class Withdraw(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    acct_name =db.Column(db.String(100), nullable=False)
    acct_number = db.Column(db.String(100), nullable=False)
    bank_code = db.Column(db.String(100), nullable=False)
    verify_code = db.Column(db.Integer(), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.now())


class Schedule(db.Model):
    id = db.Column(db.String, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    acct_name = db.Column(db.String, nullable=False)
    bank_name = db.Column(db.String, nullable=False)
    acct_num = db.Column(db.String, nullable=False)
    amount = db.Column(db.String, nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    date= db.Column(db.DateTime)

class Order(db.Model):
    __tablename__ = 'orders'

    order_id = db.Column(db.String, primary_key=True)  # Bybit order ID
    account_number = db.Column(db.String, nullable=True)
    account_name = db.Column(db.String, nullable=True)
    bank_name = db.Column(db.String, nullable=True)
    Bank_code = db.Column(db.String, nullable=True)
    nombank_code = db.Column(db.String, nullable=True)
    amount = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False, default='processing')
    payment_type =db.Column(db.String, nullable=True)
    payment_id = db.Column(db.String, nullable=True)
    processed_with = db.Column(db.String, nullable=True)
    reference_id = db.Column(db.String, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_queued = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now())
    updated_at = db.Column(db.DateTime, default=datetime.now(), onupdate=datetime.now())
    expire_at = db.Column(db.DateTime)

with app.app_context():
    db.create_all()

BANK_ALIASES = {
    "uba": ["united bank for africa"],
    "gtb": ["guaranty trust bank", "gtbank"],
    "fcmb": ["first city monument bank"],
    "fidelity": ["fidelity bank"],
    "firstbank"or 'first bank': ["first bank of nigeria"],
    "stanbic": ["stanbic ibtc bank"],
    "ecobank": ["eco bank", "ecobank nigeria"],
}

NOMBANK_ALIASES = {
    "uba": ["united bank for africa"],
    "gtb": ["guaranty trust bank", "gtbank"],
    "fcmb": ["first city monument bank"],
    "fidelity": ["fidelity bank"],
    "firstbank"or 'first bank': ["first bank of nigeria"],
    "stanbic": ["stanbic ibtc bank"],
    "ecobank": ["eco bank", "ecobank nigeria"],
    "opay":["paycom"]
}

reason =['Goods', 'Services', 'Bills', 'Gift', 'Loan']


with open('bank.json', 'r') as f:
    banks=json.load(f)

with open('nombanks.json', 'r') as f:
    nombanks=json.load(f)

def normalize(name):
    import re
    name = name.lower()
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'[^a-z0-9 ]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def match_bank(user_input):
    user_input = normalize(user_input)


    for bank in banks:
        bank_name = normalize(bank['name'])


        # 1. Alias match (UBA, GTB, etc.)
        if user_input in BANK_ALIASES:
            if bank_name in BANK_ALIASES[user_input]:
                return bank['code']

        # 2. Containment match
        if user_input in bank_name or bank_name in user_input:
            return bank['code']


    return None

def match_nombank(user_input):
    user_input = normalize(user_input)


    for bank in nombanks:
        bank_name = normalize(bank['name'])


        # 1. Alias match (UBA, GTB, etc.)
        if user_input in NOMBANK_ALIASES:
            if bank_name in NOMBANK_ALIASES[user_input]:
                return bank['code']

        # 2. Containment match
        if user_input in bank_name or bank_name in user_input:
            return bank['code']


    return None

def name_tokens(name):
    return set(normalize(name).split())

def names_match(input_name, resolved_name, threshold=0.6):
    input_tokens = name_tokens(input_name)
    resolved_tokens = name_tokens(resolved_name)

    if not input_tokens or not resolved_tokens:
        return False

    intersection = input_tokens & resolved_tokens
    score = len(intersection) / max(len(input_tokens), len(resolved_tokens))

    return score >= threshold
def resolve(acct_num,bank_code, name ):
    name=normalize(name)

    url = "https://api.paystack.co/bank/resolve"
    params = {
        "account_number": acct_num,
        "bank_code": bank_code
    }
    headers = {
        "Authorization": f"Bearer {decrypt(current_user.paystack_secret)}"
    }

    res = requests.get(url, params=params, headers=headers)
    data = res.json()
    if not data['status']:
        return False
    acct_name = data['data']['account_name']
    acct_name = normalize(acct_name)
    return names_match(name, acct_name)


def initiate_transfer(code, acct_num, name):
    url = "https://api.paystack.co/transferrecipient"
    headers = {
        "Authorization": f"Bearer {decrypt(current_user.paystack_secret)}",
        "Content-Type": "application/json"
    }

    payload = {
        "type": "nuban",
        "name": name,
        "account_number": acct_num,
        "bank_code": code,
        "currency": "NGN"
    }

    res = requests.post(url, json=payload, headers=headers)
    recipient = res.json()

    recipient_code = recipient["data"]["recipient_code"]
    return recipient_code

def transfer(recipient_code, amount, reference):
    url = "https://api.paystack.co/transfer"
    headers = {
        "Authorization": f"Bearer {decrypt(current_user.paystack_secret)}",
        "Content-Type": "application/json"
    }

    payload = {
        "source": "balance",
        "amount": amount*100,  # kobo → ₦5,000
        "recipient": recipient_code,
        "reason": random.choice(reason),
        "reference": reference  # <-- your custom reference
    }

    res = requests.post(url, json=payload, headers=headers)
    transfer = res.json()
    return transfer

def confirm_transaction(reference):
    url = f"https://api.paystack.co/transfer/verify/{reference}"
    headers = {
        "Authorization": f"Bearer {decrypt(current_user.paystack_secret)}"
    }

    res = requests.get(url, headers=headers)
    data = res.json()
    return data
def get_paystack_balance():
    url = "https://api.paystack.co/balance"
    headers = {
        "Authorization": f"Bearer {decrypt(current_user.paystack_secret)}"
    }
    response = requests.get(url, headers=headers)
    data = response.json()

    return data
def nombank_access_token(clientid, client_secret, acctid):
    url = "https://api.nomba.com/v1/auth/token/issue"

    payload = {
        "grant_type": "client_credentials",
        "client_id": clientid,
        "client_secret": client_secret
    }
    headers = {
        "accountId": acctid,
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers,timeout=10)
    token = response.json()
    return token

def revoke_access(access, clientid):
    url = "https://api.nomba.com/v1/auth/token/revoke"

    payload = {
        "clientId": clientid,
        "access_token": access
    }
    headers = {"Content-Type": "application/json"}

    response = requests.post(url, json=payload, headers=headers,timeout=10)

    return response.json()

def nombank_balance(acctid, access_token):
    url = "https://api.nomba.com/v1/accounts/balance"

    headers = {
        "accountId": acctid,
        "Authorization": f"Bearer {access_token}"
    }

    response = requests.get(url, headers=headers,timeout=10)

    return response.json()

def resolve_nombank(acct_num,bank_code, name, access_token,acct_id ):
    name=normalize(name)

    url = "https://api.nomba.com/v1/transfers/bank/lookup"

    payload = {
        "accountNumber": acct_num,
        "bankCode": bank_code
    }
    headers = {
        "accountId": acct_id,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers,timeout=10)

    data= response.json()
    if data['description'] != "SUCCESS":
        return False
    acct_name = data['data']['accountName']
    acct_name = normalize(acct_name)
    return names_match(name, acct_name)

def nombank_transfer(amount, acct_number, acct_name, bankcode, reference, sender, acct_id, access_token):
    url = "https://api.nomba.com/v2/transfers/bank"

    payload = {
        "amount": amount,
        "accountNumber": str(acct_number),
        "accountName": acct_name,
        "bankCode": str(bankcode),
        "merchantTxRef": str(reference),
        "senderName": str(sender),
        "narration": random.choice(reason)
    }
    headers = {
        "accountId": acct_id,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers,timeout=10)

    return response.json()

def nombank_confirm(reference, acct_id, access_token):
    url = "https://api.nomba.com/v1/transactions/accounts/single"

    payload = {
        "merchantTxRef": str(reference),
    }
    headers = {
        "accountId": acct_id,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.get(url,params=payload, headers=headers)

    return response.json()



def send_welcome_email(name, user_email, user_password):
    # Plain text fallback
    plain_body = f"""
Hello {name},

Your account has been created. Please find your login details below:

Email: {user_email}
Password: {user_password}

Thank you for registering!
"""

    # HTML body
    html_body = f"""
<html>
  <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
    <div style="max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 12px; background-color: #f9f9f9;">
      <h2 style="color: #0d6efd; text-align: center;">Welcome to Yuciferpay</h2>
      <p>Hello <strong>{name}</strong>,</p>
      <p>Your Account have been created successfully, You can start enjoying Yuciferpay:</p>


      <p style="margin-top: 20px;">Your login details:</p>
      <table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
        <tr>
          <td style="padding: 8px; font-weight: bold;">Email:</td>
          <td style="padding: 8px;">{user_email}</td>
        </tr>
        <tr style="background-color: #f1f1f1;">
          <td style="padding: 8px; font-weight: bold;">Password:</td>
          <td style="padding: 8px;">{user_password}</td>
        </tr>
      </table>

      <p style="text-align: center; margin-top: 30px;">
        <a href='yuciferpay.xyz/login_now_' style="display: inline-block; padding: 12px 24px; background-color: #0d6efd; color: #fff; text-decoration: none; border-radius: 8px; font-weight: 600;">Login Now</a>
      </p>

      <hr style="margin-top: 30px;">
      <p style="font-size: 12px; color: #888; text-align: center;">
        Thank you for Registering.
      </p>
    </div>
  </body>
</html>
"""

    # Create the message
    msg = Message(
        subject="Your Yuciferpay Account Details",
        recipients=[user_email],
        body=plain_body,
        html=html_body
    )

    # Send it
    with app.app_context():
        mail.send(msg)
        flash(f"Email sent to {user_email} ✅")

def withdrawal_verification(name, user_email, code, amount, reference_id):
    # Plain text fallback
    plain_body = f"""
Hello {name},

You are about to make a withdrawal, confirm with this code:

amount: {amount}
Verification code: {code}
reference: {reference_id}

Ignore if this isnt you!
"""

    # HTML body
    html_body = f"""
<html>
  <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
    <div style="max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 12px; background-color: #f9f9f9;">
      <h2 style="color: #0d6efd; text-align: center;">Verification Code</h2>
      <p>Hello <strong>{name}</strong>,</p>
      <p>You are about to make a withdrawal, This is your confirmation code:</p>


      <p style="margin-top: 20px;">Withdrawal details:</p>
      <table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
        <tr>
          <td style="padding: 8px; font-weight: bold;">Amount:</td>
          <td style="padding: 8px;">{amount}</td>
        </tr>
        <tr style="background-color: #f1f1f1;">
          <td style="padding: 8px; font-weight: bold;">Verification Code:</td>
          <td style="padding: 8px;">{code}</td>
        </tr>
        <tr>
          <td style="padding: 8px; font-weight: bold;">Reference:</td>
          <td style="padding: 8px;">{reference_id}</td>
        </tr>
      </table>

      <hr style="margin-top: 30px;">
      <p style="font-size: 12px; color: #888; text-align: center;">
        Please ignore if this wasn't you!
      </p>
    </div>
  </body>
</html>
"""

    # Create the message
    msg = Message(
        subject="Withdrawal Verification",
        recipients=[user_email],
        body=plain_body,
        html=html_body
    )

    # Send it
    with app.app_context():
        mail.send(msg)
        flash(f"code sent to email✅")

def check_expiry():
    now = datetime.now()

    orders = Order.query.filter(
        Order.user_id == current_user.id,
        Order.expire_at <= now
    ).all()

    for order in orders:
        db.session.delete(order)

    db.session.commit()

def notify_expiry():
    now = datetime.now()

    Notifys = Notify.query.filter(
        Notify.user_id == current_user.id,
        Notify.expire_at <= now
    ).all()

    for order in Notifys:
        db.session.delete(order)

    db.session.commit()

def genSignature(payload, time_stamp,api_key,api_secret):
    param_str= str(time_stamp) + api_key + recv_window + payload
    hash = hmac.new(bytes(api_secret, "utf-8"), param_str.encode("utf-8"),hashlib.sha256)
    signature = hash.hexdigest()
    return signature

def get_server_time():
    url = "https://api.bytick.com/v5/market/time"
    r = requests.get(url, timeout=10)
    return int(r.json()["time"])

def get_orders(apikey,apisecret):
    time_stamp = str(get_server_time())
    # time_stamp = str(int(time.time() * 10 ** 3))
    body = {
        "status": 10,
        "side": 0,
        "beginTime": None,
        "endTime": time_stamp,
        "page": 1,
        "size": 20
    }

    body_str = json.dumps(body, separators=(",", ":"))

    signature=genSignature(body_str, time_stamp,apikey,apisecret)
    headers = {
        'X-BAPI-API-KEY': apikey,
        'X-BAPI-SIGN': signature,
        'X-BAPI-SIGN-TYPE': '2',
        'X-BAPI-TIMESTAMP': time_stamp,
        'X-BAPI-RECV-WINDOW': recv_window,
        'Content-Type': 'application/json'
    }
    get_order_endpoint= 'https://api.bytick.com/v5/p2p/order/pending/simplifyList'

    response = requests.post(url=get_order_endpoint, headers=headers, data=body_str)

    return response.json()

def order_details(order_id,apikey,apisecret):
    time_stamp = str(get_server_time())
    body={
        'orderId':order_id
    }
    body_str = json.dumps(body, separators=(",", ":"))

    signature=genSignature(body_str, time_stamp,apikey,apisecret)
    headers = {
        'X-BAPI-API-KEY': apikey,
        'X-BAPI-SIGN': signature,
        'X-BAPI-SIGN-TYPE': '2',
        'X-BAPI-TIMESTAMP': time_stamp,
        'X-BAPI-RECV-WINDOW': recv_window,
        'Content-Type': 'application/json'
    }
    get_order_endpoint = 'https://api.bytick.com/v5/p2p/order/info'

    response = requests.post(url=get_order_endpoint, headers=headers, data=body_str)

    return response.json()
def bybit_mark_paid(order_id, payment_type, payment_id,apikey,apisecret):
    time_stamp = str(get_server_time())
    body={
        'orderId':order_id,
        'paymentType':payment_type,
        'paymentId': payment_id
    }
    body_str = json.dumps(body, separators=(",", ":"))

    signature=genSignature(body_str, time_stamp,apikey,apisecret)
    headers = {
        'X-BAPI-API-KEY': apikey,
        'X-BAPI-SIGN': signature,
        'X-BAPI-SIGN-TYPE': '2',
        'X-BAPI-TIMESTAMP': time_stamp,
        'X-BAPI-RECV-WINDOW': recv_window,
        'Content-Type': 'application/json'
    }
    get_order_endpoint = 'https://api.bytick.com/v5/p2p/order/pay'
    response = requests.post(url=get_order_endpoint, headers=headers, data=body_str)

    return response.json()
# def upload_img():
#     time_stamp = str(get_server_time())
#     body={
#         "upload_file": open("receipt.jpg", "rb")
#     }
#     body_str = json.dumps(body, separators=(",", ":"))
#
#     signature=genSignature(body_str, time_stamp)
#     headers = {
#         'X-BAPI-API-KEY': decrypt(current_user.api_key),
#         'X-BAPI-SIGN': signature,
#         'X-BAPI-SIGN-TYPE': '2',
#         'X-BAPI-TIMESTAMP': time_stamp,
#         'X-BAPI-RECV-WINDOW': recv_window,
#         'Content-Type': 'application/json'
#     }
#     get_order_endpoint = 'https://api.bytick.com/v5/p2p/oss/upload_file'
#     response = requests.post(url=get_order_endpoint, headers=headers, data=body_str)
#
#     relative_url = response.json()["result"]["url"]
#     file_url = "https://api.bytick.com" + relative_url
#     return file_url

def reciept_img(order_id, apikey,apisecret):
    time_stamp = str(get_server_time())
    body={
        "orderId": order_id,
        "contentType": "str",
        "message": 'Paid Boss, please confirm and release coins Asap!\n\nHelp leave a positive review!',
        "msgUuid": uuid.uuid4().hex
    }
    body_str = json.dumps(body, separators=(",", ":"))

    signature=genSignature(body_str, time_stamp,apikey,apisecret)
    headers = {
        'X-BAPI-API-KEY': apikey,
        'X-BAPI-SIGN': signature,
        'X-BAPI-SIGN-TYPE': '2',
        'X-BAPI-TIMESTAMP': time_stamp,
        'X-BAPI-RECV-WINDOW': recv_window,
        'Content-Type': 'application/json'
    }
    get_order_endpoint = 'https://api.bytick.com/v5/p2p/order/message/send'
    response = requests.post(url=get_order_endpoint, headers=headers, data=body_str)

    return response.json()


def check(user):
    if user.service == 'bybit':
        orders = get_orders(decrypt(user.api_key),decrypt(user.api_secret))

        if orders.get('ret_msg') != 'SUCCESS':
            db.session.add(Notify(
                user_id=user.id,
                message='There was an error connecting to the API',
                level='error',
                seen=False,
                expire_at=datetime.now() + timedelta(hours=1)
            ))
            db.session.commit()
            return None

        items = orders.get('result', {}).get('items', [])

        if not items:
            return None

        for order in items:
            order_id = order.get('id')
            amount = order.get('amount')

            # 🔒 Skip if order already exists
            existing = Order.query.filter_by(order_id=order_id).first()
            if existing:
                continue

            detail = order_details(order_id,decrypt(user.api_key),decrypt(user.api_secret))
            if detail.get('ret_msg') != 'SUCCESS':
                continue

            payment_list = detail.get('result', {}).get('paymentTermList', [])
            if not payment_list:
                continue  # no payment info

            payment = payment_list[0]  # get the first payment term

            bank_name = payment.get('bankName')
            account_number = payment.get('accountNo')
            account_name = payment.get('realName')
            payment_type = payment.get('paymentType')
            payment_id = payment.get('id')

            # 🚫 Validate required fields
            if not bank_name or not account_number:
                status = 'failed'
            else:
                status = 'processing'

            new_order = Order(
                order_id=order_id,
                amount=amount,
                bank_name=bank_name,
                account_name=account_name,
                account_number=account_number,
                payment_type=payment_type,
                payment_id=payment_id,
                Bank_code=match_bank(bank_name),
                nombank_code =match_nombank(bank_name),
                reference_id=f"YPF-PROD{user.id}-{order_id}",
                user_id=user.id,
                status=status,
                expire_at=datetime.now() + timedelta(days=2),
            )

            db.session.add(new_order)

            db.session.commit()
    elif user.service in ['payroll', 'payout']:
        now = datetime.now()

        schedules = Schedule.query.filter(
            Schedule.user_id == user.id,
            Schedule.date <= now,
            Schedule.is_active == False
        ).all()

        for m in schedules:
            new_order = Order(
                order_id=m.id,
                amount=m.amount,
                bank_name=m.bank_name,
                account_name=m.acct_name,
                account_number=m.acct_num,
                Bank_code=match_bank(m.bank_name),
                nombank_code=match_nombank(m.bank_name),
                reference_id=f"YPF-PROD{user.id}-{uuid.uuid4().hex[:12]}",
                user_id=user.id,
                status='processing',
                expire_at=datetime.now() + timedelta(days=2),
            )

            m.is_active = True

            db.session.add(new_order)

            db.session.commit()
    return None


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login_now_', methods=["GET", "POST"])
@limiter.limit("10 per hour", key_func=login_key, methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        email = request.form.get('email').lower()
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user:
            if check_password_hash(user.password, password):
                login_user(user)
                return redirect(url_for('dashboard'))
            else:
                flash('wrong password')

        else:
            flash('user not in the database')
    return render_template('login.html')



@app.route('/register__', methods=["GET", "POST"])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email').lower()
        service = request.form.get('service').lower()
        bank = request.form.get('bank').lower()
        api_key = request.form.get('api_key')
        api_secret = request.form.get('api_secret')
        paystack_public = request.form.get('paystack_pkey')
        paystack_secret = request.form.get('paystack_secret')
        nombank_accountid = request.form.get('nombank_accountid')
        nombank_clientid = request.form.get('nombank_clientid')
        nombank_clientsecret = request.form.get('nombank_clientsecret')
        password = request.form.get('password')
        confirm_pass = request.form.get('confirm_password')
        if password == confirm_pass:
            reg = User(name=name,
                       api_key=encrypt(api_key) if api_key else None,
                       api_secret=encrypt(api_secret) if api_secret else None,
                       email=email,
                       password=generate_password_hash(password, salt_length=5),
                       service=service,
                       bank=bank,
                       paystack_secret=encrypt(paystack_secret) if paystack_secret else None,
                       paystack_public=encrypt(paystack_public) if paystack_public else None,
                       nombank_accountid=encrypt(nombank_accountid) if nombank_accountid else None,
                       nombank_clientid=encrypt(nombank_clientid) if nombank_clientid else None,
                       nombank_clientsecret=encrypt(nombank_clientsecret) if nombank_clientsecret else None
                       )
            db.session.add(reg)
            db.session.commit()
            send_welcome_email(name, email, password)
            return redirect(url_for('dashboard'))
        else:
            flash('passwords do not match')
    return render_template('register.html')



@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    est_min = 0
    est_sec = 0
    dbalance=0
    if current_user.id != 1:

        check_expiry()
        notify_expiry()
        try:
            if current_user.bank == 'paystack':
                balance = get_paystack_balance()
                if not balance['status']:
                    flash(f'{balance["message"]}', 'error')
                else:
                    for item in balance['data']:
                        current_user.balance = item['balance']/100
                        db.session.commit()
            elif current_user.bank == 'nombank':
                access = nombank_access_token(decrypt(current_user.nombank_clientid), decrypt(current_user.nombank_clientsecret), decrypt(current_user.nombank_accountid))
                if access['description'] == 'Successful':
                    access_token = access['data']['access_token']
                else:
                    print(access['description'])

                balance =nombank_balance(decrypt(current_user.nombank_accountid), access_token)

                if not balance['data']:
                    flash(f'{balance["message"]}')
                else:
                    current_user.balance = float(balance['data']['amount'])
                    db.session.commit()
                    try:
                        revoke_access(access_token,decrypt(current_user.nombank_accountid))
                    except Exception as e:
                        flash(f'{str(e)}', 'error')
            order_count = current_user.order.filter_by(status='processing').count()
            total_seconds = order_count * 30
            est_min = total_seconds // 60
            est_sec = total_seconds % 60
            if est_min < 10:
                est_min = '0'+str(est_min)
            if est_sec < 10:
                est_sec = '0'+str(est_sec)

            dbalance = round(float(current_user.balance), 2)
        except Exception as e:
            flash(f'{str(e)}', 'error')
    # Get the current page number from query params, default is 1
    page = request.args.get('page', 1, type=int)
    per_page = 20  # number of users per page

    # Query users excluding id=1 and paginate
    users = User.query.filter(User.id != 1).paginate(page=page, per_page=per_page)
    orders = Order.query.filter(Order.user_id == current_user.id, Order.status !='paid').order_by(Order.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    return render_template('dashboard.html', users=users, orders=orders, min=est_min, sec=est_sec, dbalance=dbalance)


@app.route('/notify')
@login_required
def notify():
    page = request.args.get('page', 1, type=int)
    per_page = 20  # number of users per page

    # Query users excluding id=1 and paginate
    Notifys = Notify.query.filter(Notify.user_id == current_user.id, Notify.seen == False).paginate(page=page, per_page=per_page)

    return render_template('notify.html', notifys=Notifys)


@app.route('/seen/<int:notify_id>')
@login_required
def mark_seen(notify_id):
    notify = Notify.query.filter_by(id=notify_id, user_id=current_user.id).first()
    if not notify:
        flash('This notification does not exist', 'error')
        return redirect(url_for('notify'))
    if notify.user_id != current_user.id:
        abort(404)
    notify.seen = True
    db.session.commit()
    return redirect(url_for('notify'))



@app.route('/view_account/<int:user_id>', methods=["GET", "POST"])
@admin_only
@login_required
def view_account(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email').lower()
        service = request.form.get('service').lower()
        bank = request.form.get('bank').lower()
        password = request.form.get('password')
        balance = request.form.get('balance')
        top_up_balance = request.form.get('up_balance')
        trades = request.form.get('trades')
        apikey = request.form.get('api_key')
        apisecret = request.form.get('api_secret')
        paystack_public = request.form.get('paystack_pkey')
        paystack_secret = request.form.get('paystack_secret')
        nombank_accountid = request.form.get('nombank_accountid')
        nombank_clientid = request.form.get('nombank_clientid')
        nombank_clientsecret = request.form.get('nombank_clientsecret')
        user.name = name
        user.email = email
        user.balance = float(balance)
        user.top_up_balance = float(top_up_balance)
        user.trades = trades
        user.service = service
        user.bank = bank
        if password:
            user.password = generate_password_hash(password, salt_length=5)
        if apikey:
            user.api_key = encrypt(apikey)
        if apisecret:
            user.api_secret = encrypt(apisecret)
        if paystack_public:
            user.paystack_public = encrypt(paystack_public)
        if paystack_secret:
            user.paystack_secret=encrypt(paystack_secret)
        if nombank_accountid:
            user.nombank_accountid = encrypt(nombank_accountid)
        if nombank_clientid:
            user.nombank_clientid = encrypt(nombank_clientid)
        if nombank_clientsecret:
            user.nombank_clientsecret = encrypt(nombank_clientsecret)
        db.session.commit()
        # send_welcome_email(name, email, password, code)
        return redirect(url_for('dashboard'))
    return render_template('edit.html', user=user)


@app.route('/fund')
@login_required
def fund():
    return render_template('fund.html', PAYSTACK_PUBLIC_KEY=pkey)

@app.route("/nombank/webhook", methods=["POST"])
def nombank_webhook():
    payload = request.get_json()

    event_type = payload.get("event_type")
    transaction = payload.get("data", {}).get("transaction", {})
    reference = transaction.get('merchantTxRef')

    if not reference:
        return "", 200

    order = Order.query.filter_by(reference_id=reference).first()

    if not order:
        return "", 200

    user = order.user

    if event_type == "payout_success":

        if order.status == 'paid':
            return "", 200
        if user.service == 'bybit':
            mark = bybit_mark_paid(order.order_id, order.payment_type, order.payment_id,decrypt(user.api_key),decrypt(user.api_secret))
            # img_url = upload_img()
            # if img_url:
            reciept_img(order.order_id,decrypt(user.api_key),decrypt(user.api_secret))
            if mark.get('ret_msg') != 'SUCCESS':
                order.status = 'paid_pending'
                db.session.add(Notify(
                    user_id=user.id,
                    message=f'{order.account_name} {str(mark.get("ret_msg"))}',
                    level='error',
                    seen=False,
                    expire_at=datetime.now() + timedelta(hours=1)
                ))
                db.session.commit()
            else:
                amount = float(order.amount)
                user.trades += 1
                order.status = 'paid'
                if 4500 <= amount <= 50000:
                    user.top_up_balance -= 5
                elif 50000 < amount <= 500000:
                    user.top_up_balance -= 10
                else:
                    user.top_up_balance -= 20
                db.session.commit()
        elif user.service == 'payroll':
            pay = Schedule.query.get_or_404(order.order_id)
            amount = float(order.amount)
            pay.date = datetime.now() + timedelta(days=30)
            pay.is_active = False
            user.trades += 1
            order.status = 'paid'
            if amount <= 20000:
                user.top_up_balance -= 100
            elif 20000 < amount <= 50000:
                user.top_up_balance -= 200
            elif 50000 < amount <= 100000:
                user.top_up_balance -= 300
            elif 100000 < amount <= 500000:
                user.top_up_balance -= 500
            else:
                user.top_up_balance -= 1000
            db.session.commit()
        elif user.service == 'payout':
            pay = Schedule.query.get_or_404(order.order_id)
            amount = float(order.amount)
            user.trades += 1
            order.status = 'paid'
            if amount <= 20000:
                user.top_up_balance -= 100
            elif 20000 < amount <= 50000:
                user.top_up_balance -= 200
            elif 50000 < amount <= 100000:
                user.top_up_balance -= 300
            elif 100000 < amount <= 500000:
                user.top_up_balance -= 500
            else:
                user.top_up_balance -= 1000
            db.session.delete(pay)
            db.session.commit()

    else:
        order.status = event_type

    db.session.commit()
    return "", 200

@app.route("/paystack/transfer/webhook", methods=["POST"])
def paystack_transfer_webhook():
    events = request.get_json()

    event = events.get("event")
    data = events.get("data") or {}
    reference = data.get('reference')

    # If no reference or no matching transaction, ignore
    if not reference:
        return "", 200

    order = Order.query.filter_by(reference_id=reference).first()

    if not order:
        return "", 200

    user = order.user

    # Handle events
    if event == "charge.success" or event == "transfer.success":

        if order.status == 'paid':
            return "", 200

        if user.service == 'bybit':
            mark = bybit_mark_paid(order.order_id, order.payment_type, order.payment_id,decrypt(user.api_key),decrypt(user.api_secret))
            # img_url = upload_img()
            # if img_url:
            reciept_img(order.order_id,decrypt(user.api_key),decrypt(user.api_secret))
            if mark.get('ret_msg') != 'SUCCESS':
                order.status = 'paid_pending'
                db.session.add(Notify(
                    user_id=user.id,
                    message=f'{order.account_name} {str(mark.get("ret_msg"))}',
                    level='error',
                    seen=False,
                    expire_at=datetime.now() + timedelta(hours=1)
                ))
                db.session.commit()
            else:
                amount = float(order.amount)
                user.trades += 1
                order.status = 'paid'
                if 4500 <= amount <= 50000:
                    user.top_up_balance -= 5
                elif 50000 < amount <= 500000:
                    user.top_up_balance -= 10
                else:
                    user.top_up_balance -= 20
                db.session.commit()
        elif user.service == 'payroll':
            pay = Schedule.query.get_or_404(order.order_id)
            amount = float(order.amount)
            pay.date = datetime.now() + timedelta(days=30)
            pay.is_active = False
            user.trades += 1
            order.status = 'paid'
            if amount <= 20000:
                user.top_up_balance -= 100
            elif 20000 < amount <= 50000:
                user.top_up_balance -= 200
            elif 50000 < amount <= 100000:
                user.top_up_balance -= 300
            elif 100000 < amount <= 500000:
                user.top_up_balance -= 500
            else:
                user.top_up_balance -= 1000
            db.session.commit()
        elif user.service == 'payout':
            pay = Schedule.query.get_or_404(order.order_id)
            amount = float(order.amount)
            user.trades += 1
            order.status = 'paid'
            if amount <= 20000:
                user.top_up_balance -= 100
            elif 20000 < amount <= 50000:
                user.top_up_balance -= 200
            elif 50000 < amount <= 100000:
                user.top_up_balance -= 300
            elif 100000 < amount <= 500000:
                user.top_up_balance -= 500
            else:
                user.top_up_balance -= 1000
            db.session.delete(pay)
            db.session.commit()
    else:
        order.status = event
    # You can handle more event types as needed

    db.session.commit()
    return "", 200

@app.route("/paystack/webhook", methods=["POST"])
def paystack_webhook():
    signature = request.headers.get("X-Paystack-Signature")
    payload = request.data
    event = request.get_json()

    if event["event"] != "charge.success":
        return "Ignored", 200

    data = event["data"]
    user_id = data["metadata"]["user_id"]


    if not user_id:
        return "User not found in metadata", 400

    user = User.query.get(user_id)
    if not user:
        return "Invalid user", 404


    secret = skey

    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha512
    ).hexdigest()

    if signature != expected:
        return "Invalid signature", 400


    reference = data["reference"]
    amount = data["amount"] / 100  # kobo → naira


    # Prevent double credit
    if Deposit.query.filter_by(reference=reference).first():
        return "Already processed", 200



    # Record deposit
    deposit = Deposit(
        user_id=user.id,
        reference=reference,
        amount=amount,
        status="success"
    )

    user.top_up_balance += amount

    db.session.add(deposit)
    db.session.commit()

    return "OK", 200



@app.route('/delete_/<int:user_id>',methods=['GET', 'POST'])
@admin_only
@login_required
def delete(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.id == 1:
        abort(403)
    if current_user.id != 1:
        flash('You are not authorised to access that route', 'error')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(current_user.id)
    if request.method == 'POST':
        code = request.form.get('code')
        if check_password_hash(user.password, code):

            flash(f"{user_to_delete.name} has been deleted.", "success")
            db.session.delete(user_to_delete)
            db.session.commit()

            return redirect(url_for('dashboard'))
        else:
            flash('Invalid code', 'error')
            return redirect(url_for('delete', user_id=user_id))
    return render_template('delete.html')


@app.route('/check_orders')
@login_required
def check_orders():
    if current_user.service == 'bybit':
        orders = get_orders(decrypt(current_user.api_key),decrypt(current_user.api_secret))

        if orders.get('ret_msg') != 'SUCCESS':
            flash('There was an error connecting to the API', 'error')
            return redirect(url_for('dashboard'))

        items = orders.get('result', {}).get('items', [])

        if not items:
            flash('No available orders', 'success')
            return redirect(url_for('dashboard'))

        for order in items:
            order_id = order.get('id')
            amount = order.get('amount')

            # 🔒 Skip if order already exists
            existing = Order.query.filter_by(order_id=order_id).first()
            if existing:
                continue

            detail = order_details(order_id,decrypt(current_user.api_key),decrypt(current_user.api_secret))
            if detail.get('ret_msg') != 'SUCCESS':
                continue

            payment_list = detail.get('result', {}).get('paymentTermList', [])
            if not payment_list:
                continue  # no payment info

            payment = payment_list[0]  # get the first payment term

            bank_name = payment.get('bankName')
            account_number = payment.get('accountNo')
            account_name = payment.get('realName')
            payment_type = payment.get('paymentType')
            payment_id = payment.get('id')

            # 🚫 Validate required fields
            if not bank_name or not account_number:
                status = 'failed'
            else:
                status = 'processing'

            new_order = Order(
                order_id=order_id,
                amount=amount,
                bank_name=bank_name,
                account_name=account_name,
                account_number=account_number,
                payment_type=payment_type,
                payment_id=payment_id,
                Bank_code=match_bank(bank_name),
                nombank_code =match_nombank(bank_name),
                reference_id=f"YPF-PROD{current_user.id}-{order_id}",
                user_id=current_user.id,
                status=status,
                expire_at=datetime.now() + timedelta(days=2),
            )

            db.session.add(new_order)

            db.session.commit()
    elif current_user.service in ['payroll', 'payout']:
        now = datetime.now()

        schedules = Schedule.query.filter(
            Schedule.user_id == current_user.id,
            Schedule.date <= now,
            Schedule.is_active == False
        ).all()

        for m in schedules:
            new_order = Order(
                order_id=m.id,
                amount=m.amount,
                bank_name=m.bank_name,
                account_name=m.acct_name,
                account_number=m.acct_num,
                Bank_code=match_bank(m.bank_name),
                nombank_code=match_nombank(m.bank_name),
                reference_id=f"YPF-PROD{current_user.id}-{uuid.uuid4().hex[:12]}",
                user_id=current_user.id,
                status='processing',
                expire_at=datetime.now() + timedelta(days=2),
            )

            m.is_active = True

            db.session.add(new_order)

            db.session.commit()

    flash('Orders synced successfully', 'success')
    return redirect(url_for('dashboard'))


@app.route('/pay_all')
@login_required
def pay_all():
    from tasks import process_pay_all
    orders = Order.query.filter(
        Order.user_id == current_user.id,
        Order.status == 'processing',
        Order.is_queued == False
    ).all()
    if not orders:
        flash('No active orders to pay', 'error')
        return redirect(url_for('dashboard'))

    if current_user.top_up_balance <=100:
        flash('Your Top up balance must not go below 100', 'error')
        return redirect(url_for('dashboard'))

    for order in orders:
        process_pay_all.delay(current_user.id, order.order_id)
        order.is_queued = True

    db.session.commit()
    flash("Bulk payment started. Refresh dashboard for updates.", "info")
    return redirect(url_for("dashboard"))



@app.route('/paid/<orderid>')
@login_required
def mark_paid(orderid):
    order = Order.query.filter_by(order_id=orderid, user_id=current_user.id).first()
    if not order:
        flash('This order does not exist', 'error')
        return redirect(url_for('dashboard'))

    if current_user.top_up_balance <=100:
        flash('Your Top up balance must not go below 100', 'error')
        return redirect(url_for('dashboard'))

    if order.status == 'paid':
        flash('This order is already paid', 'error')
        return redirect(url_for('dashboard'))
    else:
        if current_user.service == 'bybit':
            amount = float(order.amount)
            current_user.trades+=1
            order.status = 'paid'
            if amount <= 50000:
                current_user.top_up_balance -= 5
            elif 50000 < amount <= 500000:
                current_user.top_up_balance -= 10
            else:
                current_user.top_up_balance -= 20
            db.session.commit()
            mark = bybit_mark_paid(order.order_id, order.payment_type, order.payment_id,decrypt(current_user.api_key),decrypt(current_user.api_secret))
            # img_url = upload_img()
            # if img_url:
            reciept_img(order.order_id,decrypt(current_user.api_key),decrypt(current_user.api_secret))
            if mark.get('ret_msg') != 'SUCCESS':
                flash(f'{order.account_name} {str(mark.get("ret_msg"))}', 'error')
        elif current_user.service == 'payroll':
            pay = Schedule.query.get_or_404(orderid)
            amount = float(order.amount)
            pay.date = datetime.now() + timedelta(days=30)
            pay.is_active = False
            current_user.trades += 1
            order.status = 'paid'
            if amount <= 20000:
                current_user.top_up_balance -= 100
            elif 20000 < amount <=50000:
                current_user.top_up_balance -= 200
            elif 50000 < amount <= 100000:
                current_user.top_up_balance -= 300
            elif 100000 < amount <= 500000:
                current_user.top_up_balance -= 500
            else:
                current_user.top_up_balance -= 1000
            db.session.commit()
        elif current_user.service == 'payout':
            pay = Schedule.query.get_or_404(orderid)
            amount = float(order.amount)
            current_user.trades += 1
            order.status = 'paid'
            if amount <= 20000:
                current_user.top_up_balance -= 100
            elif 20000 < amount <=50000:
                current_user.top_up_balance -= 200
            elif 50000 < amount <= 100000:
                current_user.top_up_balance -= 300
            elif 100000 < amount <= 500000:
                current_user.top_up_balance -= 500
            else:
                current_user.top_up_balance -= 1000
            db.session.delete(pay)
            db.session.commit()

    flash('Successfully marked', 'success')
    return redirect(url_for('dashboard'))


@app.route('/withdrawal', methods=['GET', 'POST'])
@login_required
def withdraw():
    if current_user.bank != 'paystack':
        flash('Only paystack users can use this withdrawal route', 'error')
        return redirect(url_for('dashboard'))
    if not current_user.paystack_secret:
        flash('This user haven\'t logged a paystack account')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name')
        acct_number = request.form.get('acct_number')
        amount = float(request.form.get('amount'))
        bank = request.form.get('bank')
        bank_code = match_bank(bank)
        resolved = resolve(acct_number,bank_code,name)
        reference_id = f'WTH-{current_user.id}-{uuid.uuid4().hex[:12]}'

        tx = Withdraw.query.filter_by(user_id=current_user.id).first()
        if tx:
            reference = tx.reference
            status = confirm_transaction(reference)

            if not status['status']:
                db.session.delete(tx)
                db.session.commit()

            elif status['status'] and status['data']['status'] == 'success':

                fee = float(status['data']['fee_charged'] / 100)
                current_user.balance -= (tx.amount + fee)
                current_user.trades += 1

                db.session.delete(tx)
                db.session.commit()

            elif status['status'] and status['data']['status'] == 'pending':
                flash('A Transaction is processing, hold and try again letter')
                return redirect(url_for('withdraw'))
            elif status['status'] and status['data']['status'] == 'processing':
                flash('A Transaction is processing, hold and try again letter')
                return redirect(url_for('withdraw'))
            elif status['status'] and status['data']['status'] == 'failed':
                db.session.delete(tx)
                db.session.commit()
            elif status['status']:
                db.session.delete(tx)
                db.session.commit()



        if amount + 100 > current_user.balance:
            flash('Insufficient balance.', 'error')
            return redirect(url_for('withdraw'))
        if resolved:
            code=random.randint(100000, 999999)
            tx = Withdraw(user_id=current_user.id,reference=reference_id,amount=amount,acct_name=name,
                          acct_number=str(acct_number),bank_code=str(bank_code), verify_code=code)
            db.session.add(tx)
            db.session.commit()

            withdrawal_verification(current_user.name,current_user.email, code,amount,reference_id)
            return redirect(url_for('withdraw_verify'))
        else:
            flash('The account name doesnt match')
            return redirect(url_for('withdraw'))
    return render_template('withdraw.html')


@app.route('/withdraw_verify', methods=['GET', 'POST'])
@login_required
def withdraw_verify():
    sessions =Withdraw.query.filter_by(user_id=current_user.id).first()
    if not sessions:
        flash('Session expired', 'error')
        return redirect(url_for('withdraw'))

    if request.method == 'POST':
        verify_code = sessions.verify_code
        bank_code = sessions.bank_code
        reference = sessions.reference
        amount = sessions.amount
        acct_number = sessions.acct_number
        acct_name = sessions.acct_name
        code = int(request.form.get('code'))
        if code == verify_code:
            try:
                if amount+100 > current_user.balance:
                    flash('Insufficient balance.', 'error')
                    return redirect(url_for('withdraw'))
                recipient = initiate_transfer(bank_code,acct_number,acct_name)
                transfered = transfer(recipient,amount, reference)

                if not transfered['status']:
                    flash(f'{transfered["message"]}', 'error')
                    return redirect(url_for('withdraw'))

                status = confirm_transaction(reference)
                if not status['status']:
                    flash(f'{status["message"]}', 'error')
                    db.session.delete(sessions)
                    db.session.commit()
                    return redirect(url_for('withdraw'))
                elif status['status'] and status['data']['status'] == 'success':
                    fee = float(status['data']['fee_charged'] / 100)
                    current_user.balance -= (amount + fee)
                    current_user.trades += 1

                    db.session.delete(sessions)
                    db.session.commit()
                    flash(f'{amount} transfered successfully')
                    return redirect(url_for('dashboard'))
                elif status['status'] and status['data']['status'] == 'pending':
                    flash('A Transaction is processing, hold and try again letter')
                    return redirect(url_for('withdraw'))
                elif status['status'] and status['data']['status'] == 'processing':
                    flash('A Transaction is processing, hold and try again letter')
                    return redirect(url_for('withdraw'))
                elif status['status'] and status['data']['status'] == 'failed':
                    db.session.delete(sessions)
                    db.session.commit()
                    flash('Transaction failed', 'error')
                    return redirect(url_for('withdraw'))
                else:
                    db.session.delete(sessions)
                    db.session.commit()

                    flash(f"{status['data']['status']}",'error')
                    return redirect(url_for('withdraw'))

            except Exception as e:
                flash(f'Transfer error {e}', 'error')
                return redirect(url_for('withdraw'))
        else:
            flash('Invalid verification code', 'error')
            return redirect(url_for('withdraw_verify'))
    return render_template('verify_withdraw.html')

@app.route("/update-bank", methods=['GET', 'POST'])
@login_required
def update_bank():
    bank = request.form.get("bank")

    if bank not in ["paystack", "nombank"]:
        flash("Invalid bank option", "error")
        return redirect(url_for('dashboard'))

    current_user.bank = bank
    db.session.commit()

    flash("Bank updated successfully", "success")
    return redirect(url_for('dashboard'))

@app.route('/schedule',methods=['GET', 'POST'])
@login_required
def schedule():
    if current_user.service not in ['payroll','payout']:
        flash('This route is only available for payroll and payout services', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        acct_name = request.form.get('acct_name', '')
        bank_name = request.form.get('bank_name', '')
        acct_num = request.form.get('acct_num', '')
        amount = request.form.get('amount', '')
        date = request.form.get('date', '')
        file = request.files.get('file')

        if file and file.filename != '':
            if not file.filename.endswith('.csv'):
                flash('File must be a CSV file', 'error')
                return redirect(url_for('schedule'))
            df = pandas.read_csv(file)
            for rows in df.itertuples(index=False):
                try:
                    schedules = Schedule(
                        id=f'SCHEDULE-{current_user.id}-{uuid.uuid4().hex[:12]}',
                        user_id=current_user.id,
                        acct_name=rows.acct_name,
                        bank_name=rows.bank_name,
                        acct_num=str(rows.acct_num),
                        amount=str(rows.amount),
                        date=datetime.strptime(rows.date, '%d/%m/%Y')
                    )
                    db.session.add(schedules)
                except Exception as e:
                    flash(f'{str(e)}', 'error')
                    return redirect(url_for('schedule'))
            db.session.commit()

        if acct_name:
            if not bank_name and not acct_num and not amount and not date:
                flash('Make sure you fill every box when scheduling manually', 'error')
                return redirect(url_for('schedule'))
            dateformat = datetime.strptime(date, '%Y-%m-%d')
            print(dateformat)
            schedules = Schedule(
                id = f'SCHEDULE-{current_user.id}-{uuid.uuid4().hex[:12]}',
                user_id = current_user.id,
                acct_name=acct_name,
                bank_name =bank_name,
                acct_num = str(acct_num),
                amount = str(amount),
                date = dateformat
            )
            db.session.add(schedules)
            db.session.commit()
        flash('Scheduling successful', 'success')
        return redirect(url_for('dashboard'))
    return render_template('schedule.html')

@app.route('/all_schedule')
@login_required
def all_schedule():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')

    query = Schedule.query

    if search:
        query = query.filter(
            or_(
                Schedule.acct_name.ilike(f"%{search}%"),
                Schedule.acct_num.ilike(f"%{search}%"),
                Schedule.bank_name.ilike(f"%{search}%")
            )
        )

    schedules = query.paginate(page=page, per_page=20)

    return render_template("all_pays.html", schedule=schedules)
@app.route('/edit_schedule/<schedule_id>', methods=["GET", "POST"])
@login_required
def edit_schedule(schedule_id):
    schedules = Schedule.query.filter_by(id=schedule_id, user_id=current_user.id).first()

    if not schedules:
        flash('No such schedule', 'error')
        return redirect(url_for('schedule'))
    ddate = schedules.date.strftime('%Y-%m-%d')

    if request.method == 'POST':
        acct_name = request.form.get('acct_name', '')
        bank_name = request.form.get('bank_name', '')
        acct_num = request.form.get('acct_num', '')
        amount = request.form.get('amount', '')
        date = request.form.get('date', '')

        if not acct_name and not bank_name and not acct_num and not amount and not date:
            flash('Make sure you fill every box', 'error')
            return redirect(url_for('schedule'))
        schedules.acct_name = acct_name
        schedules.bank_name = bank_name
        schedules.acct_num = acct_num
        schedules.amount = amount
        dateformat = datetime.strptime(date, '%Y-%m-%d')
        schedules.date = dateformat
        db.session.commit()
        flash('Edit was successful', 'success')
        return redirect(url_for('all_schedule'))
    return render_template('edit_schedule.html', schedule=schedules, date=ddate)

@app.route('/delete_schedule/<schedule_id>',methods=['GET', 'POST'])
@login_required
def delete_schedule(schedule_id):
    schedule_to_delete = Schedule.query.get_or_404(schedule_id)
    user = User.query.get_or_404(schedule_to_delete.user_id)
    if current_user.id != user.id:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        code = request.form.get('code')
        if check_password_hash(user.password, code):

            flash(f"{schedule_to_delete.acct_name} has been deleted.", "success")
            db.session.delete(schedule_to_delete)
            db.session.commit()

            return redirect(url_for('dashboard'))
        else:
            flash('Invalid code', 'error')
            return redirect(url_for('delete_schedule', schedule_id=schedule_id))
    return render_template('delete_schedule.html')

@app.route("/automate")
@login_required
def automated():
    if current_user.automate:
        current_user.automate = False
    else:
        current_user.automate = True
    db.session.commit()

    flash("Automation enabled" if current_user.automate else "Automation disabled")
    return redirect(url_for('dashboard'))


@app.route("/reg_info")
def reg_info():
    return render_template('reg_info.html')

@app.errorhandler(TooManyRequests)
def rate_limit_handler(e):
    flash("Too many login attempt.", "warning")
    # stay on the same page
    return redirect(request.referrer or url_for("index"))

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


@login_manager.unauthorized_handler
def unauthorized():
    if request.blueprint == 'api':
        abort(HTTPStatus.UNAUTHORIZED)
    return redirect(url_for('login'))

def work(user):
    print(f"working on user:{user.id}")
    with app.app_context():
        try:
            check(user)
        except Exception as e:
            db.session.add(Notify(
                user_id=user.id,
                message=f'{str(e)}',
                level='error',
                seen=False,
                expire_at=datetime.now() + timedelta(hours=1)
            ))
            db.session.commit()
        from tasks import process_pay_all
        orders = Order.query.filter(
            Order.user_id == user.id,
            Order.status == 'processing',
            Order.is_queued == False
        ).all()

        if user.top_up_balance <= 100:
            db.session.add(Notify(
                user_id=user.id,
                message=f'Your Top up balance must not go below 100',
                level='error',
                seen=False,
                expire_at=datetime.now() + timedelta(hours=1)
            ))
            db.session.commit()
        else:
            for order in orders:
                process_pay_all.delay(user.id, order.order_id)
                order.is_queued = True

            db.session.commit()

def automating():
    print("Thread started")
    while True:
        with app.app_context():
            users = User.query.filter(User.automate == True).all()
        threads = []
        for user in users:
            t = threading.Thread(target=work,args=(user,))
            t.start()
            threads.append(t)

            if len(threads)==5:
                for t in threads:
                    t.join()
                threads.clear()
        time.sleep(5)

if __name__ == "__main__":
    t = threading.Thread(target=automating, daemon=True)
    t.start()
    app.run(debug=False, port=5000)