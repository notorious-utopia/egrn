import os
import copy
import logging
from flask import Flask, flash, redirect, render_template, request, session, send_file
from flask_session import Session
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
import datetime
from helpers import apology, login_required, validate_cad_num, validate_email, order_extract, check_status, download_extract, format_datetime
from sqlalchemy import DateTime, desc, event
from flask_sqlalchemy import SQLAlchemy, SignallingSession
from flask_apscheduler import APScheduler
from flask_mail import Mail, Message

# Configure application
app = Flask(__name__)
# set up scheduler for checking order status
scheduler = APScheduler()
scheduler.init_app(app)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Turn on pessimistic testing of db connections via 'pool_pre_ping' argument
SQLALCHEMY_ENGINE_OPTIONS = {'pool_size': 10,'pool_recycle': 60,'pool_pre_ping': True} 
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = SQLALCHEMY_ENGINE_OPTIONS 

db = SQLAlchemy(session_options={"autocommit": False, "autoflush": False})

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

app.jinja_env.globals.update(download_extract=download_extract)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"

# Configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") 

# Configure email notifications
app.config['MAIL_SERVER']= os.environ.get("MAIL_SERVER") 
app.config['MAIL_PORT'] = os.environ.get('MAIL_PORT')
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = True
mail = Mail(app)

db.init_app(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, unique=True, nullable=False)
    hash = db.Column(db.String)
    email = db.Column(db.String, unique=True, nullable=False)

class Order(db.Model):
    order_id = db.Column(db.Integer, primary_key=True)
    order_API_id = db.Column(db.String, nullable=False)
    user = db.Column(db.String, nullable=False)
    property_object = db.Column(db.String, unique=False, nullable=False)
    status = db.Column(db.String, nullable=False) 
    rosreestr_id = db.Column(db.String, nullable=False)
    time = db.Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))

class Extract(db.Model):
    extract_id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String, nullable=False)

with app.app_context():
    db.create_all()

@scheduler.task('interval', id='do_get_updates', seconds=60) 
def get_updates():
    
    with app.app_context():
        users = db.session.query(User.id, User.username).all()
    
        for user in users:
            currentUser = User.query.filter_by(id=user[0]).first()
            user_orders_list = db.session.query(Order.order_id, Order.order_API_id, Order.property_object, Order.status, Order.rosreestr_id, Order.time).filter(Order.user==currentUser.username).all()
            actual_order_data_list = []

            for i in user_orders_list:
                actual_order_data_list.append(check_status(i[1]))

            for i in actual_order_data_list:
                # Get orders that were already sent for processing 
                if i['status'] == 'В работе':
                    logging.info("there is a sent order!")
                    order_to_update = Order.query.filter_by(order_API_id=i['order_id']).first()
                    
                    # Update its status 
                    api_status = i['status']

                    if order_to_update.status != api_status:                    
                            logging.info("there is an order to update!")
                            order_to_update.status = api_status
                            db.session.commit()

                # Get finished orders
                if i['status'] == 'Завершен':
                    order_to_update = Order.query.filter_by(order_API_id=i['order_id']).first()

                    # Update its status 
                    api_status = i['status']
                    if order_to_update.status != api_status: 
                        order_to_update.status = api_status
                        db.session.commit()

                        # Notify user that the documents are ready for downloading
                        msg = Message('EGRN Helper: обновлен статус заявки', sender = 'egrn_helper@notoriousutopia.org', recipients = [currentUser.email])
                        msg.body = "Добрый день, \r\n\nПолучены документы от Росреестра по вашей заявке от {}. Ознакомиться с ними можно в личном кабинете. \r\n\nС уважением, \r\nEGRN Helper".format(format_datetime(order_to_update.time))
                        mail.send(msg)

            logging.info("Update finished")

scheduler.start()

Session(app)

@app.route("/", methods=["GET", "POST"])
# @login_required
@app.route("/index", methods=["GET", "POST"])
@login_required
def index():
    """Show pending and completed orders"""
    if request.method == "POST":

        # Get current user
        currentUser = User.query.filter_by(id=session["user_id"]).first()

        user_orders_list = db.session.query(Order.order_id, Order.order_API_id, Order.property_object, Order.status, Order.rosreestr_id, Order.time).filter(Order.user==currentUser.username).order_by(desc(Order.time)).all()

        # Converting list of tuples to nested list to be able to format the datetime of each order
        user_orders_list = [list(order) for order in user_orders_list]

        formatted_user_orders_list = copy.deepcopy(user_orders_list)

        for i in range(len(user_orders_list)):
            for j in range(len(user_orders_list[i])):
                if isinstance(user_orders_list[i][j], datetime.datetime):                    
                    formatted_user_orders_list[i][j] = format_datetime(formatted_user_orders_list[i][j])

        # Logic behind the Download button
        if request.form.get('download'):

            val = request.form.get('download')
            filename = request.form.get('filename')

            return download_extract(val, "Extract based on an order dated " + filename)
    
        else:
            return render_template("index.html", user_orders = formatted_user_orders_list)
    
    # User reached route via GET (as by clicking a link or via redirect)
    else:
        currentUser = User.query.filter_by(id=session["user_id"]).first()

        user_orders_list = db.session.query(Order.order_id, Order.order_API_id, Order.property_object, Order.status, Order.rosreestr_id, Order.time).filter(Order.user==currentUser.username).order_by(desc(Order.time)).all()
        
        # Converting list of tuples to nested list to be able to format the datetime of each order
        user_orders_list = [list(order) for order in user_orders_list]

        formatted_user_orders_list = copy.deepcopy(user_orders_list)
        
        for i in range(len(user_orders_list)):
            for j in range(len(user_orders_list[i])):
                if isinstance(user_orders_list[i][j], datetime.datetime):                    
                    formatted_user_orders_list[i][j] = format_datetime(formatted_user_orders_list[i][j])

        logging.info(formatted_user_orders_list)

        return render_template("index.html", user_orders = formatted_user_orders_list)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id, but maintain flashed message if present
    if session.get("_flashes"):
        flashes = session.get("_flashes")
        session.clear()
        session["_flashes"] = flashes
    else:
        session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        user = User.query.filter_by(username=request.form.get("username")).first()

        # Ensure username exists and password is correct
        if not user or not check_password_hash(user.hash, request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = user.id

        # Flash message after the successful login
        flash('Вы вошли')

        # Redirect user to home page
        return redirect("/index")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")

@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Flash message after the successful logout
    flash("Вы вышли")

    # Redirect user to login form
    return redirect("/login")

@app.route("/order", methods=["GET", "POST"])
@login_required
def order():
    """Order extract using cadastral number"""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        
        # Get current user and cadastral number of the property object in question
        currentUser = User.query.filter_by(id=session["user_id"]).first()
        session["user_id"] = currentUser.id

        property_object = request.form.get("property_object")

        if not property_object:
            return apology("User input is blank", 400)

        # Validate the provided cadastral number
        if not validate_cad_num(property_object):
            return apology("not a valid cadastral number", 400)

        else:
            api_order_id = order_extract(property_object)

            order = Order(
                user = currentUser.username, 
                property_object = property_object, 
                status = 'Заявка только что создана', 
                rosreestr_id = 'Номер заявке не присвоен, заявка ждет отправки в Росреестр',
                order_API_id = api_order_id
                )
            db.session.add(order)
            db.session.commit()

            # Flash message after the order was submitted
            flash("Выписка заказана")

            return redirect("/") 

    else:
        return render_template("order.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        username = str(request.form.get("username"))

        # Validate email
        email = str(request.form.get("email"))
        if not validate_email(email):
            return apology("No valid email provided")

        username_exists = db.session.query(User.id).filter_by(username=username).first() is not None
        
        if not username:
            return apology("Username input is blank")

        elif username_exists:
            return apology("Username already exists")

        email_exists = db.session.query(User.id).filter_by(email=email).first() is not None
        
        if not email:
            return apology("Email input is blank")

        elif email_exists:
            return apology("Email already used")

        password = str(request.form.get("password"))
        confirmation = request.form.get("confirmation")

        if not password or not confirmation or (password != confirmation):
            return apology("Password is blank or passwords don't match")

        hash = generate_password_hash(password, method='pbkdf2:sha256', salt_length=8)

        user = User(
            username=username,
            hash=hash,
            email=email
        )
        db.session.add(user)
        
        db.session.commit()
        
        # Flash message after the succesful registration
        flash('Вы зарегистрировались')

        return redirect("/login")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")

@app.route("/legal")
def legal():
    return apology("Page under development")

def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)

# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
