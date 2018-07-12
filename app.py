import subprocess
import shlex
import os
import signal
from helper import path_dict, path_number_of_files, pdf_stats
from heuristic_table_detection import count_tables_dir
import tabula
import json
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, render_template, flash, redirect, url_for, session, request, logging
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

# CONSTANTS
WGET_DATA_PATH = 'data'
PDF_TO_PROCESS = 1


# Helper Function

# Check if user logged in
def is_logged_in(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            flash('Unauthorized, Please login', 'danger')
            return redirect(url_for('login'))
    return wrap


# Index
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST': #FIXME I didn't handle security yet !! make sure only logged-in people can execute

        # User can type in url
        # The url will then get parsed to extract domain, while the crawler starts at url.

        # Get Form Fields and save
        url = request.form['url']
        parsed = urlparse(url)

        session['domain'] = parsed.netloc
        session['url'] = url

        # TODO use WTForms to get validation

        return redirect(url_for('crawling'))

    return render_template('home.html')


# Crawling
@app.route('/crawling')
@is_logged_in
def crawling():

    # Prepare WGET command
    url = session.get('url', None)

    command = shlex.split("wget -r -A pdf %s" % (url,))

    #TODO use celery
    #TODO give feedback how wget is doing

    #TODO https://stackoverflow.com/questions/15041620/how-to-continuously-display-python-output-in-a-webpage

    # Execute command in subdirectory
    process = subprocess.Popen(command, cwd=WGET_DATA_PATH)
    session['crawl_process_id'] = process.pid

    exitCode = process.returncode

    return render_template('crawling.html')


# End Crawling
@app.route('/crawling/end')
@is_logged_in
def end_crawling():
    p_id = session.get('crawl_process_id', None)

    #FIXME this way of handling the subprocess is quick and dirty
    #FIXME for more control we could switch to Celery or another library

    #TODO stop process after reaching a certain size like 2GB
    os.kill(p_id, signal.SIGTERM)

    flash('You interrupted the crawler', 'success')

    return render_template('end_crawling.html')


# About
@app.route('/about')
def about():
    return render_template('about.html')


# PDF processing
@app.route('/processing')
@is_logged_in
def processing():

    domain = session.get('domain', None)
    if domain == None:
        pass
        # TODO think of bad cases

    path = "data/%s" % (domain,)

    # STEP 1: Call Helper function to create Json string

    # FIXME workaround to weird file system bug with latin/ cp1252 encoding..
    # https://stackoverflow.com/questions/35959580/non-ascii-file-name-issue-with-os-walk works
    # https://stackoverflow.com/questions/2004137/unicodeencodeerror-on-joining-file-name doesn't work
    hierarchy_dict = path_dict(path)  # adding ur does not work as expected either

    hierarchy_stats = json.dumps(hierarchy_dict, sort_keys=True, indent=4)  # , encoding='cp1252' not needed in python3

    # Store json file in corresponding directory
    jason_file = open("static/json/%s.json" % (domain,), "w")
    jason_file.write(hierarchy_stats)
    jason_file.close()

    # STEP 2: Call helper function to count number of pdf files
    n_files = path_number_of_files(path)
    session['n_files'] = n_files

    # STEP 3: Extract tables from pdf's
    stats, n_error, n_success = pdf_stats(path, PDF_TO_PROCESS)

    # STEP 4: Save stats
    session['n_error'] = n_error
    session['n_success'] = n_success
    stats_json = json.dumps(stats, sort_keys=True, indent=4)
    session['stats'] = stats_json

    # Store json file in corresponding directory
    jason_file = open("static/json/%s.stats.json" % (domain,), "w")
    jason_file.write(hierarchy_stats)
    jason_file.close()

    # STEP 5: Save query in DB

    # Create cursor
    cur = mysql.connection.cursor()

    # Execute query
    cur.execute("INSERT INTO Crawls(crawl_date, pdf_crawled, pdf_processed, domain, url, hierarchy, stats) VALUES(NULL, %s ,%s, %s, %s, %s, %s)",
                (n_files, n_success, domain, session.get('url', None), hierarchy_dict, stats))

    # Commit to DB
    mysql.connection.commit()

    # Close connection
    cur.close()

    return render_template('processing.html', n_files=n_files, domain=domain)


# General Statistics
@app.route('/stats')
@is_logged_in
def stats():

    # STEP 1: retrieve all saved stats
    n_files = session.get('n_files', None)
    n_success = session.get('n_success', None)
    domain = session.get('domain', None)
    url = session.get('url', None)
    n_success = session.get('n_success', None)
    n_errors = session.get('n_error', None)
    json_stats = json.loads(session.get('stats', None))

    # STEP 2: do some processing to retrieve interesting info from stats
    n_tables = sum([subdict['n_tables_pages'] for filename, subdict in json_stats.items()])
    n_rows = sum([subdict['n_table_rows'] for filename, subdict in json_stats.items()])

    medium_tables = sum([subdict['table_sizes']['medium'] for filename, subdict in json_stats.items()])
    small_tables = sum([subdict['table_sizes']['small'] for filename, subdict in json_stats.items()])
    large_tables = sum([subdict['table_sizes']['large'] for filename, subdict in json_stats.items()])

    return render_template('statistics.html', n_files=n_files, n_success=n_success, n_tables=n_tables, n_rows=n_rows,
                           n_errors=n_errors, domain=domain, small_tables=small_tables, medium_tables=medium_tables,
                           large_tables=large_tables, stats=session.get('stats', None))


# Test site
@app.route('/test1')
def test1():
    return render_template('stats.html', domain=session.get('domain',None))


# Test site2
@app.route('/test2')
def test2():
    return render_template('test2.html')

# Test site3
@app.route('/test3')
def test3():
    return render_template('index.html')


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


# User login
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
                return redirect(url_for('index'))
            else:
                error = 'Invalid login'
                return render_template('login.html', error=error)

        else:
            error = 'Username not found'
            return render_template('login.html', error=error)

        # Close connection
        cur.close() # FIXME shouldn't that happen before return?

    return render_template('login.html')


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

    # Create cursor
    cur = mysql.connection.cursor()

    # Get Crawls
    result = cur.execute("SELECT crawl_date, pdf_crawled, pdf_processed, domain, url FROM Crawls")

    crawls = cur.fetchall()

    if result > 0:
        return render_template('dashboard.html', crawls=crawls)
    else:
        msg = 'No Crawls Found'
        return render_template('dashboard.html', msg=msg)

    # Close connection FIXME is this code executed
    cur.close()

if __name__ == '__main__':
    app.secret_key='Aj"$7PE#>3AC6W]`STXYLz*[G\gQWA'
    app.run(debug=True) # application is in debug mode

