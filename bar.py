import subprocess
import shlex
import os
import signal
from helper import path_dict, path_number_of_files, pdf_stats, pdf_date_format_to_datetime, dir_size, exists
import json
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, render_template, flash, redirect, url_for, session, request, logging, Response
from flask_mysqldb import MySQL
from wtforms import Form, StringField, TextAreaField, PasswordField, validators
from passlib.hash import sha256_crypt
import time

from threading import Lock
from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit

from celery import Celery, chord
from requests import post

import tabula
import PyPDF2

import traceback


# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
app.debug = True
app.secret_key = 'Aj"$7PE#>3AC6W]`STXYLz*[G\gQWA'

# Celery configuration
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

# SocketIO
socketio = SocketIO(app, async_mode=async_mode)

# Deprecated
thread = None
thread_lock = Lock()

# Initialize Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

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
PDF_TO_PROCESS = 12
MAX_CRAWLING_DURATION = 20              # in seconds
WAIT_AFTER_CRAWLING = 1000              # in milliseconds
SMALL_TABLE_LIMIT = 10                  # defines what is considered a small table
MEDIUM_TABLE_LIMIT = 20                 # defines what is considered a medium table
MAX_CRAWL_SIZE = 1024 * 1024 * 500      # in bytes (500MB)


@celery.task(bind=True)                 # time_limit=MAX_CRAWLING_DURATION other possibility
def crawling_task(self, url='', post_url='', domain=''):

    # STEP 1: Start the wget subprocess
    command = shlex.split("timeout %d wget -r -A pdf %s" % (MAX_CRAWLING_DURATION, url,))
    process = subprocess.Popen(command, cwd=WGET_DATA_PATH, stderr=subprocess.PIPE)

    # Set the pid in the state
    self.update_state(state='PROGRESS', meta={'pid': process.pid, })

    # STEP 2: send crawl stderr through WebSocket
    while True:
        next_line = process.stderr.readline()
        next_line = next_line.decode("utf-8")

        if process.poll() is not None:
            # Subprocess is finished
            break

        # TODO
        #crawled_size = dir_size(WGET_DATA_PATH + "/" + domain)
        #if crawled_size is not None and crawled_size > MAX_CRAWL_SIZE:
            # threshold reached
        #    break

        post(post_url, json={'event': 'crawl_update', 'data': next_line})

    # STEP 3: Kill the subprocess if still alive
    if process.poll() is None:
        os.kill(process.pid, signal.SIGTERM)

    # STEP 4: Return the exit code
    output = process.communicate()[0]
    exitCode = process.returncode
    post(post_url, json={'event': 'redirect', 'data': {'url': '/crawling/autoend'}})

    return exitCode


@celery.task(bind=True)
def tabula_task(self, file_path='', post_url=''):

    # STEP 0: set all counter to 0
    n_tables = 0
    n_table_rows = 0
    table_sizes = {'small': 0, 'medium': 0, 'large': 0}

    # STEP 1: count total number of pages
    try:
        pdf_file = PyPDF2.PdfFileReader(open(file_path, mode='rb'))
        n_pages = pdf_file.getNumPages()
    except EOFError:
        post(post_url, json={'event': 'processing_failure', 'data': {'pdf_name': file_path,
                                                                     'text': 'PyPDF error on file : ',
                                                                     'trace': traceback.print_exc()}})
        return 'error',     # important to return tuple

    # STEP 2: run TABULA to extract all tables into one dataframe
    try:
        df_array = tabula.read_pdf(file_path, pages="all", multiple_tables=True)
    except:
        post(post_url, json={'event': 'processing_failure', 'data': {'pdf_name': file_path,
                                                                     'text': 'Tabula error on file : ',
                                                                     'trace': traceback.print_exc()}})
        return 'error',      # important to return tuple

    # STEP 3: count number of rows in each dataframe
    for df in df_array:
        rows = df.shape[0]
        n_table_rows += rows
        n_tables += 1

        # Add table stats
        if rows <= SMALL_TABLE_LIMIT:
            table_sizes['small'] += 1
        elif rows <= MEDIUM_TABLE_LIMIT:
            table_sizes['medium'] += 1
        else:
            table_sizes['large'] += 1

    # STEP 4: save stats
    try:
        creation_date = pdf_file.getDocumentInfo()['/CreationDate']
        stat = (file_path, {'n_pages': n_pages, 'n_tables': n_tables,
                            'n_table_rows': n_table_rows, 'creation_date': creation_date,
                            'table_sizes': table_sizes, 'url': file_path})

    except:
        post(post_url, json={'event': 'processing_failure', 'data': {'pdf_name': file_path,
                                                                     'text': 'Getting document info error on file: ',
                                                                     'trace': traceback.print_exc()}})
        return 'error',      # important to return tuple

    # STEP 5: Send message asynchronously
    post(post_url, json={'event': 'tabula_success', 'data':
        {'data': 'I successfully performed table detection', 'pages': n_pages, 'tables': n_tables}})

    # STEP 6: Return stats
    return stat


@celery.task(bind=True)
def pdf_stats(self, tabula_list, domain='', url='', crawl_total_time=0, post_url='', processing_start_time=0):
    """Background task that runs a long function with progress reports."""
    with app.app_context():
        # STEP 0: Time keeping
        path = "data/%s" % (domain,)

        # STEP 1: Call Helper function to create Json string
        # https://stackoverflow.com/questions/35959580/non-ascii-file-name-issue-with-os-walk works
        # https://stackoverflow.com/questions/2004137/unicodeencodeerror-on-joining-file-name doesn't work
        hierarchy_dict = path_dict(path)  # adding ur does not work as expected either
        hierarchy_json = json.dumps(hierarchy_dict, sort_keys=True, indent=4)  # , encoding='cp1252' not needed in python3

        # STEP 2: Call helper function to count number of pdf files
        n_files = path_number_of_files(path)

        # STEP 3: Treat result from Tabula tasks
        stats = {}
        n_success = 0
        n_errors = 0
        for stat in tabula_list:
            if stat[0] == 'error':
                n_errors += 1
            else:
                n_success += 1
                stats[stat[0]] = stat[1]

        # STEP 4: Save stats
        stats_json = json.dumps(stats, sort_keys=True, indent=4)
        disk_size = dir_size(WGET_DATA_PATH + "/" + domain)

        # STEP 5: compute final processing time
        processing_total_time = time.time() - processing_start_time

        # STEP 5: Save query in DB
        # Create cursor
        cur = mysql.connection.cursor()

        # Execute query
        cur.execute("""INSERT INTO Crawls(cid, crawl_date, pdf_crawled, pdf_processed, process_errors, domain, disk_size, 
                    url, hierarchy, stats, crawl_total_time, proc_total_time) 
                    VALUES(NULL, NULL, %s ,%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (n_files, n_success, n_errors, domain, disk_size, url, hierarchy_json,
                        stats_json, crawl_total_time, processing_total_time))

        # Commit to DB
        cur.connection.commit()

        # Close connection
        cur.close()

        # Send message asynchronously
        post(post_url, json={'event': 'redirect', 'data': {'url': '/processing'}})

        return 'success'


@app.route('/event/', methods=['POST'])
def event():
    data = request.json
    if data:
        socketio.emit(data['event'], data['data'])
        return 'ok'
    return 'error', 404


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


# Ability to stream a template
def stream_template(template_name, **context):
    app.update_template_context(context)
    t = app.jinja_env.get_template(template_name)
    rv = t.stream(context)
    rv.disable_buffering()
    return rv


# Index
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST': #FIXME I didn't handle security yet !! make sure only logged-in people can execute

        # User can type in url
        # The url will then get parsed to extract domain, while the crawler starts at url.

        # Get Form Fields and save
        url = request.form['url']

        # Check if valid URL
        if not exists(url):
            flash('This URL does not exists. Please try another.', 'danger')
            return render_template('home.html')

        parsed = urlparse(url)

        session['domain'] = parsed.netloc
        session['url'] = url

        return redirect(url_for('crawling'))

    return render_template('home.html')


# Crawling
@app.route('/crawling')
@is_logged_in
def crawling():

    # STEP -1: check no crawling in progress
    if session.get('crawling_id', 0) is not 0:
        flash("Crawling already in progress, please wait before "
              "running another query", 'danger') #TODO link to killing query
        return redirect(url_for('index'))

    # STEP 0: TimeKeeping
    session['crawl_start_time'] = time.time()

    # STEP 1: Prepare WGET command
    url = session.get('url', None)
    post_url = url_for('event', _external=True)

    # STEP 2: Schedule celery task
    result = crawling_task.delay(url=url, post_url=post_url, domain=session.get('domain', ''))
    session['crawling_id'] = result.id

    return render_template('crawling.html', max_crawling_duration=MAX_CRAWLING_DURATION)

    # FIXME porblem with automatic redirection if task not started yet


# End Crawling Manual
@app.route('/crawling/end')
@is_logged_in
def end_crawling():

    # STEP 0: check crawling process exists
    if session.get('crawling_id', 0) is 0:
        flash("There is no crawling process to kill", 'danger')
        render_template('crawling.html', max_crawling_duration=MAX_CRAWLING_DURATION)

    # STEP 1: Kill only subprocess, and the celery process will then recognize it and terminate too
    celery_id = session.get('crawling_id', 0)                       # get saved celery task id
    try:
        pid = crawling_task.AsyncResult(celery_id).info.get('pid')      # get saved subprocess id
        os.kill(pid, signal.SIGTERM)                                    # kill subprocess
    except AttributeError:
        flash("Either the task was not scheduled yet or is already over and thus interruption is not possible", 'danger')
        return redirect(url_for('index'))

    # STEP 2: TimeKeeping
    crawl_start_time = session.get('crawl_start_time', None)
    session['crawl_total_time'] = time.time() - crawl_start_time

    # STEP 3: Successful interruption
    session['crawling_id'] = 0                                      # allow crawling again
    flash('You successfully manually interrupted the crawler.', 'success')

    return render_template('end_crawling.html')


# End Crawling Automatic
@app.route('/crawling/autoend')
@is_logged_in
def autoend_crawling():

    # STEP 1: TimeKeeping
    crawl_start_time = session.get('crawl_start_time', None)
    total_time = time.time() - crawl_start_time
    session['crawl_total_time'] = total_time

    # STEP 2: Successful interruption
    if total_time > MAX_CRAWLING_DURATION:
        flash('Time limit reached - Crawler interrupted automatically', 'success')

    crawled_size = dir_size(WGET_DATA_PATH + "/" + session.get('domain'))
    if crawled_size > MAX_CRAWL_SIZE:
        flash("Size limit reached - Crawler interrupted automatically", 'success')

    session['crawling_id'] = 0

    return redirect(url_for("table_detection"))


# Start table detection
@app.route('/table_detection')
@is_logged_in
def table_detection():
    # Step 0: take start time and prepare arguments
    processing_start_time = time.time()
    domain = session.get('domain', None)
    url = session.get('url', None)
    crawl_total_time = session.get('crawl_total_time', 0)
    post_url = url_for('event', _external=True)

    path = "data/%s" % (domain,)
    count = 0
    file_array = []

    # STEP 1: Find PDF we want to process
    for dir_, _, files in os.walk(path):
        for fileName in files:
            if ".pdf" in fileName and count < PDF_TO_PROCESS:
                rel_file = os.path.join(dir_, fileName)
                file_array.append(rel_file)
                count += 1

    # STEP 2: Prepare a celery task for every pdf and then a callback to store result in db
    header = (tabula_task.s(f, post_url) for f in file_array)
    callback = pdf_stats.s(domain=domain, url=url, crawl_total_time=crawl_total_time, post_url=post_url,
                           processing_start_time=processing_start_time)

    # STEP 3: Run the celery Chord
    result = chord(header)(callback)

    # STEP 4: If query was empty go straight further
    if count == 0:
        return redirect(url_for('processing'))

    return render_template('table_detection.html', total_pdf=count)


# PDF processing
@app.route('/processing')
@is_logged_in
def processing():
    return render_template('processing.html', domain=session.get('domain', ''), )


# Last Crawl Statistics
@app.route('/statistics')
@is_logged_in
def statistics():
    # Create cursor
    cur = mysql.connection.cursor()

    # Get user by username
    cur.execute("""SELECT cid FROM Crawls WHERE crawl_date = (SELECT max(crawl_date) FROM Crawls)""")

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

    result = cur.execute("""SELECT * FROM Crawls WHERE cid = %s""", (cid,))
    crawl = cur.fetchall()[0]

    # Close connection
    cur.close();

    # STEP 2: do some processing to retrieve interesting info from stats
    json_stats = json.loads(crawl['stats'])
    json_hierarchy = json.loads(crawl['hierarchy'])

    stats_items = json_stats.items()
    print(stats_items)
    n_tables = sum([subdict['n_tables'] for filename, subdict in stats_items])
    n_rows = sum([subdict['n_table_rows'] for filename, subdict in stats_items])

    medium_tables = sum([subdict['table_sizes']['medium'] for filename, subdict in stats_items])
    small_tables = sum([subdict['table_sizes']['small'] for filename, subdict in stats_items])
    large_tables = sum([subdict['table_sizes']['large'] for filename, subdict in stats_items])

    # Find some stats about creation dates
    creation_dates_pdf = [subdict['creation_date'] for filename, subdict in stats_items]
    creation_dates = list(map(lambda str : pdf_date_format_to_datetime(str), creation_dates_pdf))
    disk_size = round(crawl['disk_size'] / (1024*1024), 1)

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
                           oldest_pdf=oldest_pdf, most_recent_pdf=most_recent_pdf, disk_size=disk_size)


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
        cur.execute("""INSERT INTO Users(name, email, username, password) VALUES(%s, %s, %s, %s)""",
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
        username = request.form['username']
        password_candidate = request.form['password']

        # Create cursor
        cur = mysql.connection.cursor()

        # Get user by username
        result = cur.execute("""SELECT * FROM Users WHERE username = %s""", [username])

        # Note: apparently this is safe from SQL injections see
        # https://stackoverflow.com/questions/7929364/python-best-practice-and-securest-to-connect-to-mysql-and-execute-queries/7929438#7929438

        if result > 0:
            # Get stored hash
            data = cur.fetchone() # FIXME why is username not primary key
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
        result = cur.execute("""DELETE FROM Crawls WHERE cid = %s""", (cid,))

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
    result = cur.execute("""SELECT cid, crawl_date, pdf_crawled, pdf_processed, domain, url FROM Crawls""")

    crawls = cur.fetchall()

    if result > 0:
        return render_template('dashboard.html', crawls=crawls)
    else:
        msg = 'No Crawls Found'
        return render_template('dashboard.html', msg=msg)

    # Close connection FIXME is this code executed
    cur.close()


# About
@app.route('/about')
def about():
    return render_template('about.html')


# Asynchronous Communication wrappers
@socketio.on('connect')
def test_connect():
    emit('my_response', {'data': 'Connected', 'count': 0})


@socketio.on('disconnect')
def test_disconnect():
    print('Client disconnected', request.sid)


if __name__ == '__main__':
    socketio.run(app)
