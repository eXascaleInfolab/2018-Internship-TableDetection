import subprocess
import shlex
from functools import wraps

from flask import Flask, render_template, flash, redirect, url_for, session, request, logging
from data import Articles
from flask_mysqldb import MySQL
from wtforms import Form, StringField, TextAreaField, PasswordField, validators
from passlib.hash import sha256_crypt

app = Flask(__name__)

# Config MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'mountain'
app.config['MYSQL_DB'] = 'bar'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

# init MySQL
mysql = MySQL(app)

Articles = Articles()


# Index
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST': #FIXME I didn't handle security yet !!

        # Get Form Fields
        domain = request.form['domain']

        command = shlex.split("wget -r -A pdf https://%s" % (domain,))
        print(subprocess.call(command))

        return "crawling"
        #redirect(url_for('crawling'))

    return render_template('home.html')


#Crawling
@app.route('/crawling')
def crawling():
    return render_template('crawling.html')


# About
@app.route('/about')
def about():
    return render_template('about.html')

# Articles
@app.route('/articles')
def articles():
    return render_template('articles.html', articles=Articles)


#Single Article
@app.route('/article/<string:id>/')
def article(id):

    return render_template('article.html', id=id)


class RegisterForm(Form):
    name = StringField('Name', [validators.Length(min=1, max=50)])
    username = StringField('Username', [validators.Length(min=4, max=25)])
    email = StringField('Email', [validators.Length(min=6, max=50)])
    password = PasswordField('Password', [validators.DataRequired(),
                                          validators.EqualTo('confirm', message='Passwords do not match')])
    confirm = PasswordField('Confirm Password')


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm(request.form)
    if request.method == 'POST' and form.validate():
        name = form.name.data
        email = form.email.data
        username = form.username.data
        password = sha256_crypt.encrypt(str(form.password.data))

        # Create cursor
        cur = mysql.connection.cursor()

        # Execute query
        cur.execute("INSERT INTO users(name, email, username, password) VALUES(%s, %s, %s, %s)",
                    (name, email, username, password))

        # Commit to DB
        mysql.connection.commit()

        # Close connection
        cur.close()

        flash('You are now registered and can log in', 'success')

        return redirect(url_for('login'))

    return render_template('register.html', form=form)


#User login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Get Form Fields
        username = request.form['username'] # FIXME SQL_injection danger?
        password_candidate = request.form['password']

        # Create cursor
        cur = mysql.connection.cursor()

        # Get user by username
        result = cur.execute("SELECT * FROM users WHERE username = %s", [username])

        if result > 0:
            # Get stored hash
            data = cur.fetchone() # FIXME fucking stupid username is not primary key
            password = data['password']

            # Compare passwords
            if sha256_crypt.verify(password_candidate, password): # FIXME how does sha256 work?

                # Check was successful -> create session variables
                session['logged_in'] = True
                session['username'] = username

                flash('You are now logged in', 'success')
                return redirect(url_for('dashboard'))
            else:
                error = 'Invalid login'
                return render_template('login.html', error=error)

        else:
            error = 'Username not found'
            return render_template('login.html', error=error)

        # Close connection
        cur.close() # FIXME shouldn't that happen before return?

    return render_template('login.html')


# Check if user logged in
def is_logged_in(f): # FIXME check other way of having login control !
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            flash('Unauthorized, Please login', 'danger')
            return redirect(url_for('login'))
    return wrap


# Logout
@app.route('/logout')
@is_logged_in
def logout():
    session.clear()
    flash('You are now logged out', 'success')
    return redirect(url_for('login'))


# Dashboard
@app.route('/dashboard')
@is_logged_in
def dashboard():
    return render_template('dashboard.html')


# Crawling
@app.route('/crawl/<string:domain>')
@is_logged_in
def crawl():
    return 'crawling..'



if __name__ == '__main__':
    app.secret_key='Aj"$7PE#>3AC6W]`STXYLz*[G\gQWA'
    app.run(debug=True) # application is in debug mode

