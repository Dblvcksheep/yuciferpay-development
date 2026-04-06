import hashlib
import hmac
import json
import uuid
from time import sleep

import requests
import random
from main import celery
from datetime import datetime, timedelta

recv_window=str(5000)
reason =['Goods', 'Services', 'Bills', 'Gift', 'Loan']
def normalize(name):
    import re
    name = name.lower()
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'[^a-z0-9 ]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name
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
def resolve(acct_num,bank_code, name, paystacksecret ):
    name=normalize(name)

    url = "https://api.paystack.co/bank/resolve"
    params = {
        "account_number": acct_num,
        "bank_code": bank_code
    }
    headers = {
        "Authorization": f"Bearer {paystacksecret}"
    }

    res = requests.get(url, params=params, headers=headers)
    data = res.json()
    if not data['status']:
        return False
    acct_name = data['data']['account_name']
    acct_name = normalize(acct_name)
    return names_match(name, acct_name)


def initiate_transfer(code, acct_num, name,paystacksecret):
    url = "https://api.paystack.co/transferrecipient"
    headers = {
        "Authorization": f"Bearer {paystacksecret}",
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

def transfer(recipient_code, amount, reference,paystacksecret):
    url = "https://api.paystack.co/transfer"
    headers = {
        "Authorization": f"Bearer {paystacksecret}",
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

def confirm_transaction(reference,paystacksecret):
    url = f"https://api.paystack.co/transfer/verify/{reference}"
    headers = {
        "Authorization": f"Bearer {paystacksecret}"
    }

    res = requests.get(url, headers=headers)
    data = res.json()
    return data

def genSignature(payload, time_stamp,api_key,api_secret):
    param_str= str(time_stamp) + api_key + recv_window + payload
    hash = hmac.new(bytes(api_secret, "utf-8"), param_str.encode("utf-8"),hashlib.sha256)
    signature = hash.hexdigest()
    return signature

def get_server_time():
    url = "https://api.bytick.com/v5/market/time"
    r = requests.get(url, timeout=10)
    return int(r.json()["time"])

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

@celery.task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 4, 'countdown': 10})
def process_pay_all(self, user_id, orderid):
    from main import User, Order,db,decrypt,Notify,nombank_access_token, resolve_nombank, nombank_transfer, nombank_confirm,revoke_access

    user = User.query.get(user_id)
    if not user:
        return "User not found"

    order = Order.query.filter_by(order_id=orderid, user_id=user_id).first()

    if user.bank == 'nombank':
        access = nombank_access_token(decrypt(user.nombank_clientid), decrypt(user.nombank_clientsecret), decrypt(user.nombank_accountid))
        if access['description'] == 'Successful':
            access_token = access['data']['access_token']
        else:
            db.session.add(Notify(
                user_id=user_id,
                message=str(access['description']),
                level='error',
                seen=False,
                expire_at=datetime.now() + timedelta(hours=1)
            ))
            db.session.commit()


    try:
        if float(order.amount) + 100 > user.balance:
            db.session.add(Notify(
                user_id =user_id,
                message='Your balance is too low',
                level ='error',
                seen=False,
                expire_at= datetime.now() + timedelta(hours=1)
            ))

            db.session.commit()
            return 'failed'

        if user.top_up_balance <= 100:
            db.session.add(Notify(
                user_id =user_id,
                message='Your top up balance can not be less than ₦100',
                level ='error',
                seen=False,
                expire_at= datetime.now() + timedelta(hours=1)
            ))
            db.session.commit()
            return 'failed'

        if order.processed_with and order.processed_with != user.bank:
            db.session.add(Notify(
                user_id =user_id,
                message=f'You started making payment with {order.processed_with} for {order.account_name}, please continue with that bank to avoid double payment!!',
                level ='error',
                seen=False,
                expire_at= datetime.now() + timedelta(hours=1)
            ))
            db.session.commit()
            return 'failed'



        if user.bank=='paystack':
            confirm = confirm_transaction(order.reference_id,decrypt(user.paystack_secret))

            # CASE 1: No Paystack record yet
            if not confirm['status']:


                # Check bank info
                if not order.Bank_code:
                    order.status = 'failed'
                    db.session.add(Notify(
                        user_id=user_id,
                        message=f"This order: {order.account_name}, doesnt have a valid bank, so the system could not get bankcode",
                        level="error",
                        seen=False,
                        expire_at=datetime.now() + timedelta(hours=1)
                    ))
                    db.session.commit()
                    return 'failed'

                # Resolve account name
                if not resolve(order.account_number, order.Bank_code, order.account_name,decrypt(user.paystack_secret)):
                    order.status = 'failed'
                    db.session.add(Notify(
                        user_id=user_id,
                        message=f"This order: {order.account_name}, Account name and resolved name doesnt match.",
                        level="error",
                        seen=False,
                        expire_at=datetime.now() + timedelta(hours=1)
                    ))
                    db.session.commit()
                    return 'failed'

                # Initiate transfer
                recipient_code = initiate_transfer(order.Bank_code, order.account_number, order.account_name,decrypt(user.paystack_secret))

                order.processed_with = user.bank
                db.session.commit()
                transfered = transfer(recipient_code, float(order.amount), order.reference_id,decrypt(user.paystack_secret))

                if not transfered['status']:
                    db.session.add(Notify(
                        user_id=user_id,
                        message=transfered.get("message", "Paystack transfer failed"),
                        level="error",
                        seen=False,
                        expire_at=datetime.now() + timedelta(hours=1)
                    ))
                    db.session.commit()
                    return 'failed'
                order.status = 'pending'
                db.session.commit()
            # CASE 2: Paystack record exists

            elif confirm['status'] and confirm['data']['status'] == 'success':
                order.status = 'paid'
                amount = float(order.amount)
                if 4500 <= amount <= 50000:
                    user.top_up_balance -= 5
                elif 50000 < amount <= 500000:
                    user.top_up_balance -= 10
                else:
                    user.top_up_balance -= 20
                user.trades += 1
                db.session.commit()
                try:
                    mark = bybit_mark_paid(order.order_id, order.payment_type, order.payment_id,decrypt(user.api_key),decrypt(user.api_secret))
                    # img_url = upload_img()
                    # if img_url:
                    reciept_img(order.order_id,decrypt(user.api_key),decrypt(user.api_secret))
                    if mark.get('ret_msg') != 'SUCCESS':
                        order.status = 'paid_pending'
                        db.session.add(Notify(
                            user_id=user_id,
                            message=f'{order.account_name} {str(mark.get("ret_msg"))}',
                            level='error',
                            seen=False,
                            expire_at=datetime.now() + timedelta(hours=1)
                        ))
                        db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    order.status = 'paid_pending'
                    db.session.add(Notify(
                        user_id=user_id,
                        message=f'{order.account_name} {str(e)}',
                        level='error',
                        seen=False,
                        expire_at=datetime.now() + timedelta(hours=1)
                    ))
                    db.session.commit()

            elif confirm['status'] and confirm['data']['status'] == 'pending':
                order.status = 'processing'
            elif confirm['status'] and confirm['data']['status'] == 'failed':
                order.status = "failed"
            elif confirm['status']:
                order.status = confirm['data']['status']
            db.session.commit()
        elif user.bank=='nombank':
            confirm = nombank_confirm(order.reference_id, decrypt(user.nombank_accountid),access_token)

            # CASE 1: No Paystack record yet
            if confirm['description'] != 'SUCCESS':

                # Check bank info
                if not order.nombank_code:
                    order.status = 'failed'
                    db.session.add(Notify(
                        user_id=user_id,
                        message=f"This order: {order.account_name}, doesnt have a valid bank, so the system could not get bankcode",
                        level="error",
                        seen=False,
                        expire_at=datetime.now() + timedelta(hours=1)
                    ))
                    db.session.commit()
                    return 'failed'


                # Resolve account name
                if not resolve_nombank(order.account_number, order.nombank_code, order.account_name,access_token,
                               decrypt(user.nombank_accountid)):
                    order.status = 'failed'
                    db.session.add(Notify(
                        user_id=user_id,
                        message=f"This order: {order.account_name}, Account name and resolved name doesnt match.",
                        level="error",
                        seen=False,
                        expire_at=datetime.now() + timedelta(hours=1)
                    ))
                    db.session.commit()
                    return 'failed'

                order.processed_with = user.bank
                db.session.commit()
                # Initiate transfer
                transfered = nombank_transfer(float(order.amount),order.account_number,order.account_name,order.nombank_code, order.reference_id,user.name,
                                      decrypt(user.nombank_accountid),access_token)

                if transfered['description'] == 'FAILED':
                    db.session.add(Notify(
                        user_id=user_id,
                        message=transfered.get("message", "Paystack transfer failed"),
                        level="error",
                        seen=False,
                        expire_at=datetime.now() + timedelta(hours=1)
                    ))
                    db.session.commit()
                    return 'failed'

                order.status = 'pending'
                db.session.commit()


            # CASE 2: Paystack record exists

            elif confirm['description'] == 'SUCCESS' and confirm['data']['status'] in ['SUCCESS', 'PAYMENT_SUCCESSFUL']:
                order.status = 'paid'
                amount = float(order.amount)
                if 4500 <= amount <= 50000:
                    user.top_up_balance -= 5
                elif 50000 < amount <= 500000:
                    user.top_up_balance -= 10
                else:
                    user.top_up_balance -= 20
                user.trades += 1
                db.session.commit()
                try:
                    mark = bybit_mark_paid(order.order_id, order.payment_type, order.payment_id,
                                           decrypt(user.api_key), decrypt(user.api_secret))
                    # img_url = upload_img()
                    # if img_url:
                    reciept_img(order.order_id, decrypt(user.api_key), decrypt(user.api_secret))
                    if mark.get('ret_msg') != 'SUCCESS':
                        order.status = 'paid_pending'
                        db.session.add(Notify(
                            user_id=user_id,
                            message=f'{order.account_name} {str(mark.get("ret_msg"))}',
                            level='error',
                            seen=False,
                            expire_at=datetime.now() + timedelta(hours=1)
                        ))
                        db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    order.status = 'paid_pending'
                    db.session.add(Notify(
                        user_id=user_id,
                        message=f'{order.account_name} {str(e)}',
                        level='error',
                        seen=False,
                        expire_at=datetime.now() + timedelta(hours=1)
                    ))
                    db.session.commit()

            elif confirm['description'] == 'SUCCESS' and confirm['data']['status'] in ['PENDING_PAYMENT','PENDING_BILLING','PENDING']:
                order.status = 'processing'
            elif confirm['description'] == 'SUCCESS' and confirm['data']['status'] in ['PAYMENT_FAILED','FAILED']:
                order.status = "failed"
            elif confirm['status']:
                order.status = confirm['data']['status'].lower()
            db.session.commit()

    except Exception as e:
        db.session.rollback()
        order.status = 'error'
        db.session.add(Notify(
            user_id=user_id,
            message=f'{order.account_name} {str(e)}',
            level='error',
            seen=False,
            expire_at=datetime.now() + timedelta(hours=1)
        ))
        db.session.commit()

    if user.bank == 'nombank':
        try:
            revoke_access(access_token, decrypt(user.nombank_clientid))
        except Exception as e:
            db.session.add(Notify(
                user_id=user_id,
                message=f'{str(e)}',
                level='error',
                seen=False,
                expire_at=datetime.now() + timedelta(hours=1)
            ))
            db.session.commit()

    db.session.remove()
    return "done"

# @celery.task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 10})
# def process_check_orders(self, user_id):
#     from main import User, Order,db,decrypt
#
#     user = User.query.get(user_id)
#     if not user:
#         return "User not found"