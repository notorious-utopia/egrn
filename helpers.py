import os
import requests
import urllib.parse
import re
from flask import redirect, render_template, request, session, send_file
from functools import wraps
import requests, io
from dateutil import tz

api_token = os.environ.get("API_TOKEN") 

def apology(message, code=400):
    """Render message as an apology to user."""
    def escape(s):
        """
        Escape special characters.

        https://github.com/jacebrowning/memegen#special-characters
        """
        for old, new in [("-", "--"), (" ", "-"), ("_", "__"), ("?", "~q"),
                         ("%", "~p"), ("#", "~h"), ("/", "~s"), ("\"", "''")]:
            s = s.replace(old, new)
        return s
    return render_template("apology.html", top=code, bottom=escape(message)), code


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/1.1.x/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

def validate_cad_num(cad_number):
    """Returns True if an input string represents a valid cadastral number or False otherwise"""
    pattern = re.compile('\d{2}:\d{2}:\d{6,7}:\d+')
    return bool(pattern.match(cad_number))

#TODO test
def validate_email(email):    
    """Returns True if an input string represents a valid email address or False otherwise"""
    pattern = re.compile('^([\w-]+(?:\.[\w-]+)*)@((?:[\w-]+\.)*\w[\w-]{0,66})\.([a-z]{2,6}(?:\.[a-z]{2})?)$')
    return bool(pattern.match(email))

def order_extract(cad_number):
    """ Submits a request to EGRN concerning the property object with the cadastral number provided by a user. Returns a string which is an order id designated by API """
    params = {
    'auth_token': api_token,
    }

    data = {
    'cad_num': cad_number,
    'order_type': '1',
    }

    response = requests.post('https://reestr-api.ru/v1/order/create/', params=params, data=data)

    return response.json().get("order_id")

def download_extract(order_id, filename):
    """ Used to download the resulting documents from EGRN in a .zip format """
    params = {
        'auth_token': api_token,
        'order_id': order_id,
        'format': 'zip',
    }

    response = requests.get('https://reestr-api.ru/v1/order/download', params=params)

    return send_file(io.BytesIO(response.content), download_name = (filename + '.zip'))



def check_status(order_id):
    """ Returns a string with the current status of a submitted order. The data is provided by API """

    params = {
        'auth_token': api_token,
    }

    data = {
        'order_id': order_id,
    }

    response = requests.post('https://reestr-api.ru/v1/order/check', params=params, data=data)

    result = response.json().get("info")[0]

    return result

def format_datetime(datetime_object):
    """ Changes the time from CET (render.com server time) to the time in user location assuming it is the Europe/Moscow time """
    
    to_zone = tz.gettz('Europe/Moscow')
    datetime_object = datetime_object.astimezone(to_zone)
    formatted_datetime = datetime_object.strftime("%d.%m.%Y, %H:%M:%S")

    return formatted_datetime