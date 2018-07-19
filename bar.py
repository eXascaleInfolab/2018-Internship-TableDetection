import subprocess
import shlex
import os
import signal
from helper import path_dict, path_number_of_files, pdf_stats, pdf_date_format_to_datetime
import json
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, render_template, flash, redirect, url_for, session, request, logging
from flask_mysqldb import MySQL
from wtforms import Form, StringField, TextAreaField, PasswordField, validators
from passlib.hash import sha256_crypt
import time

app = Flask(__name__)
app.secret_key = 'Aj"$7PE#>3AC6W]`STXYLz*[G\gQWA'


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
PDF_TO_PROCESS = 10
MAX_CRAWLING_DURATION = 60 # 15 minutes
WAIT_AFTER_CRAWLING = 1000


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
    # STEP 0: TimeKeeping
    session['crawl_start_time'] = time.time()

    # STEP 1: Prepare WGET command
    url = session.get('url', None)

    command = shlex.split("timeout %d wget -r -A pdf %s" % (MAX_CRAWLING_DURATION, url,)) #FIXME timeout remove
    #command = shlex.split("wget -r -A pdf %s" % (url,))

    #TODO use celery
    #TODO give feedback how wget is doing

    #TODO https://stackoverflow.com/questions/15041620/how-to-continuously-display-python-output-in-a-webpage

    # STEP 2: Execute command in subdirectory
    process = subprocess.Popen(command, cwd=WGET_DATA_PATH)
    session['crawl_process_id'] = process.pid

    return render_template('crawling.html', max_crawling_duration=MAX_CRAWLING_DURATION)


# End Crawling Manual
@app.route('/crawling/end')
@is_logged_in
def end_crawling():

    # STEP 1: Kill crawl process
    p_id = session.get('crawl_process_id', None)
    os.kill(p_id, signal.SIGTERM)

    session['crawl_process_id'] = -1

    # STEP 2: TimeKeeping
    crawl_start_time = session.get('crawl_start_time', None)
    session['crawl_total_time'] = time.time() - crawl_start_time

    # STEP 3: Successful interruption
    flash('You successfully interrupted the crawler', 'success')

    return render_template('end_crawling.html')


# End Crawling Automatic
@app.route('/crawling/autoend')
@is_logged_in
def autoend_crawling():

    # STEP 0: Check if already interrupted
    p_id = session.get('crawl_process_id', None)
    if p_id < 0:
        return "process already killed"
    else:
        # STEP 1: Kill crawl process
        os.kill(p_id, signal.SIGTERM)

        # STEP 2: TimeKeeping
        crawl_start_time = session.get('crawl_start_time', None)
        session['crawl_total_time'] = time.time() - crawl_start_time

        # STEP 3: Successful interruption
        flash('Time Limit reached - Crawler interrupted automatically', 'success')

        return redirect(url_for("table_detection"))


# Start table detection
@app.route('/table_detection')
@is_logged_in
def table_detection():
    return render_template('table_detection.html', wait=WAIT_AFTER_CRAWLING)


# About
@app.route('/about')
def about():
    return render_template('about.html')


# PDF processing
@app.route('/processing')
@is_logged_in
def processing():

    # STEP 0: Time keeping
    proc_start_time = time.time()

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
    hierarchy_json = json.dumps(hierarchy_dict, sort_keys=True, indent=4)  # , encoding='cp1252' not needed in python3

    # FIXME remove all session stores

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

    # STEP 5: Time Keeping
    proc_over_time = time.time()
    proc_total_time = proc_over_time - proc_start_time

    # STEP 6: Save query in DB
    # Create cursor
    cur = mysql.connection.cursor()

    # Execute query
    cur.execute("INSERT INTO Crawls(cid, crawl_date, pdf_crawled, pdf_processed, process_errors, domain, url, hierarchy, stats, crawl_total_time, proc_total_time) VALUES(NULL, NULL, %s ,%s, %s, %s, %s, %s, %s, %s, %s)",
                (n_files, n_success, n_error, domain, session.get('url', None), hierarchy_json, stats_json, session.get('crawl_total_time', None), proc_total_time))

    # Commit to DB
    mysql.connection.commit()

    # Close connection
    cur.close()

    return render_template('processing.html', n_files=n_success, domain=domain, cid=0)

# Last Crawl Statistics
@app.route('/statistics')
@is_logged_in
def statistics():
    # Create cursor
    cur = mysql.connection.cursor()

    # Get user by username
    cur.execute("SELECT cid FROM Crawls WHERE crawl_date = (SELECT max(crawl_date) FROM Crawls)")

    result = cur.fetchone()

    # Close connection
    cur.close()

    if result:
        cid_last_crawl = result["cid"]
        return redirect(url_for("cid_statistics", cid=cid_last_crawl))
    else:
        flash("There are no statistics to display, please start a new query and wait for it to complete.", "danger")
        return redirect(url_for("index"))


# CID specific Statistics
@app.route('/statistics/<int:cid>')
@is_logged_in
def cid_statistics(cid):

    # STEP 1: retrieve all saved stats from DB
    # Create cursor
    cur = mysql.connection.cursor()

    result = cur.execute('SELECT * FROM Crawls WHERE cid = %s' % cid)
    crawl = cur.fetchall()[0]

    # Close connection
    cur.close();

    print(session.get('stats', None))
    print(crawl['stats'])

    # STEP 2: do some processing to retrieve interesting info from stats
    json_stats = json.loads(crawl['stats'])
    json_hierarchy = json.loads(crawl['hierarchy'])

    stats_items = json_stats.items()
    n_tables = sum([subdict['n_tables_pages'] for filename, subdict in stats_items])
    n_rows = sum([subdict['n_table_rows'] for filename, subdict in stats_items])

    medium_tables = sum([subdict['table_sizes']['medium'] for filename, subdict in stats_items])
    small_tables = sum([subdict['table_sizes']['small'] for filename, subdict in stats_items])
    large_tables = sum([subdict['table_sizes']['large'] for filename, subdict in stats_items])

    # Find some stats about creation dates
    creation_dates_pdf = [subdict['creation_date'] for filename, subdict in stats_items]
    creation_dates = list(map(lambda str : pdf_date_format_to_datetime(str), creation_dates_pdf))

    if len(creation_dates) > 0:
        oldest_pdf = min(creation_dates)
        most_recent_pdf = max(creation_dates)
    else:
        oldest_pdf = "None"
        most_recent_pdf = "None"

    return render_template('statistics.html', n_files=crawl['pdf_crawled'], n_success=crawl['pdf_processed'],
                           n_tables=n_tables, n_rows=n_rows, n_errors=crawl['process_errors'], domain=crawl['domain'],
                           small_tables=small_tables, medium_tables=medium_tables,
                           large_tables=large_tables, stats=json_stats, hierarchy=json_hierarchy,
                           end_time=crawl['crawl_date'], crawl_total_time=round(crawl['crawl_total_time'] / 60.0, 1),
                           proc_total_time=round(crawl['proc_total_time'] / 60.0, 1),
                           oldest_pdf=oldest_pdf, most_recent_pdf=most_recent_pdf)


class RegisterForm(Form):
    name = StringField('Name', [validators.Length(min=1, max=50)])
    username = StringField('Username', [validators.Length(min=4, max=25)])
    email = StringField('Email', [validators.Length(min=6, max=50)])
    password = PasswordField('Password', [validators.DataRequired(),
                                          validators.EqualTo('confirm', message='Passwords do not match')])
    confirm = PasswordField('Confirm Password')


# Register
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
        cur.execute("INSERT INTO Users(name, email, username, password) VALUES(%s, %s, %s, %s)",
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
        result = cur.execute("SELECT * FROM Users WHERE username = %s", [username])

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


# Delete Crawl
@app.route('/delete_crawl', methods=['POST'])
@is_logged_in
def delete_crawl():

        # Get Form Fields
        cid = request.form['cid']

        # Create cursor
        cur = mysql.connection.cursor()

        # Get user by username
        result = cur.execute("DELETE FROM Crawls WHERE cid = %s" % cid)

        # Commit to DB
        mysql.connection.commit()

        # Close connection
        cur.close()

        # FIXME check if successfull first, return message
        flash('Crawl successfully removed', 'success')

        return redirect(url_for('dashboard'))


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
    result = cur.execute("SELECT cid, crawl_date, pdf_crawled, pdf_processed, domain, url FROM Crawls")

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
    app.run(debug=True)
    #app.run(host='0.0.0.0')

