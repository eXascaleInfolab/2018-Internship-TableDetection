import subprocess
import shlex
import os
import signal
from helper import path_dict, path_number_of_files, pdf_stats, pdf_date_format_to_datetime, dir_size, url_status
import json
from functools import wraps
from urllib.parse import urlparse
from flask import flash, redirect, url_for, Response, send_file, Markup, logging
from flask_mysqldb import MySQL
from wtforms import Form, StringField, IntegerField, PasswordField, validators
from passlib.hash import sha256_crypt
import time
from threading import Lock
from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit
from celery import Celery, chord
from requests import post
import tabula
import PyPDF2
import shutil
import requests

# ----------------------------- CONSTANTS -----------------------------------------------------------------------------


# --- TODO has to be changed when deploying ---
VIRTUALENV_PATH = '/home/yann/bar/virtualenv/bin/celery'

PDF_TO_PROCESS = 100
MAX_CRAWLING_DURATION = 60 * 15         # in seconds
WAIT_AFTER_CRAWLING = 1000              # in milliseconds
SMALL_TABLE_LIMIT = 10                  # defines what is considered a small table
MEDIUM_TABLE_LIMIT = 20                 # defines what is considered a medium table

# Note that when checking for size folders are not taken into account and thus
# the effective size can be up to 10% higher, also leave enough room for other requests,
# like downloading pdf's from stats page. For those reasons I would not recommend
# using more than 50 % of available disk space.
MB_CRAWL_SIZE = 500
MAX_CRAWL_SIZE = 1024 * 1024 * MB_CRAWL_SIZE       # in bytes (500MB)
CRAWL_REPETITION_WARNING_TIME = 7                  # in days
MAX_CRAWL_DEPTH = 5
DEFAULT_CRAWL_URL = 'https://www.bit.admin.ch'
WGET_DATA_PATH = 'data'


BAR_OUT_LOG_PATH = 'log/bar.out.log'
BAR_ERR_LOG_PATH = 'log/bar.err.log'
CELERY_LOG_PATH = 'log/celery.log'
REDIS_LOG_PATH = 'log/redis.log'
FLOWER_LOG_PATH = 'log/flower.log'
WGET_LOG_PATH = 'log/wget.txt'

switcher = {
        'bar.out.log': BAR_OUT_LOG_PATH,
        'bar.err.log': BAR_ERR_LOG_PATH,
        'celery.log': CELERY_LOG_PATH,
        'redis.log': REDIS_LOG_PATH,
        'flower.log': FLOWER_LOG_PATH,
        'wget.log': WGET_LOG_PATH,
}


# ----------------------------- APP CONFIG ----------------------------------------------------------------------------

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
#app.debug = True
app.secret_key = 'Aj"$7PE#>3AC6W]`STXYLz*[G\gQWA'

# Celery configuration
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

# SocketIO
socketio = SocketIO(app, async_mode=async_mode)

# Lock to limit app to a single user
lock = Lock()

# Initialize Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# Config MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'mountain'
app.config['MYSQL_DB'] = 'bar'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

# Init MySQL
mysql = MySQL(app)


# ----------------------------- CELERY TASKS --------------------------------------------------------------------------

# Background task in charge of crawling
@celery.task(bind=True)                 # time_limit=MAX_CRAWLING_DURATION other possibility
def crawling_task(self, url='', post_url='', domain='',
                  max_crawl_duration=MAX_CRAWLING_DURATION, max_crawl_size=MAX_CRAWL_SIZE,
                  max_crawl_depth=MAX_CRAWL_DEPTH):

    # STEP 1: Start the wget subprocess
    command = shlex.split("timeout %d wget -r -l %d -A pdf %s" % (max_crawl_duration, max_crawl_depth, url,))
    # Note: Consider using --wait flag, takes longer to download but less aggressive crawled server
    # https://www.gnu.org/software/wget/manual/wget.html#Recursive-Download

    # Note: Using timeout is not necessary, but serves as safety, as wget should be used with caution.

    process = subprocess.Popen(command, cwd=WGET_DATA_PATH, stderr=subprocess.PIPE)

    # Set the pid in the state in order to be able to cancel subprocess anytime
    # Note: one could also cancel the celery task which then should kill its subprocess, but again I prefer option one
    self.update_state(state='PROGRESS', meta={'pid': process.pid, })

    # STEP 2: send crawl stderr through WebSocket and save in logfile
    with open(WGET_LOG_PATH, "a") as logfile:
        while True:
            try:
                next_line = process.stderr.readline()
                # Added try/catch after bug that appears when visiting (because of apostrophe "’"):
                # https://www.edi.admin.ch/edi/it/home/fachstellen/ara/domande-e-risposte/Il-SLR-usa-la-definizione-di-antisemitismo-dell%E2%80%99IHRA.html
                # Noticed by Jean-Luc.
                decoded_line = next_line.decode(encoding='utf-8')

                post(post_url, json={'event': 'crawl_update', 'data': decoded_line})
                logfile.write(decoded_line)

            except UnicodeDecodeError as e:
                # Catch Decoding error.
                print("UnicodeDecodeError: " + str(e) + " The bytes trying to get decoded were: " + next_line.hex())

            if process.poll() is not None:
                # Subprocess is finished
                print("Crawling task has successfully terminated.")
                break

            crawled_size = dir_size(WGET_DATA_PATH + "/" + domain)
            if crawled_size is not None and crawled_size > max_crawl_size:
                # Threshold reached
                print("Crawling task terminated, threshold was reached")
                break

    # STEP 3: Kill the subprocess if still alive at this poing
    if process.poll() is None:
        os.kill(process.pid, signal.SIGTERM)

    # STEP 4: Return the exit code
    output = process.communicate()[0]
    exitCode = process.returncode

    # STEP 5: redirect user to crawling end options.
    post(post_url, json={'event': 'redirect', 'data': {'url': '/crawling/autoend'}})

    # TODO consider releasing lock here

    return exitCode


# Background task in charge of performing table detection on a single pdf
@celery.task(bind=True)
def tabula_task(self, file_path='', post_url=''):

    # STEP 0: check if file is already in db
    url = file_path[(len(WGET_DATA_PATH) + 1):]

    try:
        with app.app_context():
            # Create cursor
            cur = mysql.connection.cursor()

            # Get Crawls
            result = cur.execute("""SELECT fid, stats FROM Files WHERE url=%s""", (url,))
            file = cur.fetchone()

            # If there was a result then return stats directly
            # TODO time limit on how long ago pdf was processed?

            if result > 0:
                stats = json.loads(file['stats'])

                # Communicate success to client in a broadcasting manner
                post(post_url, json={'event': 'tabula_success', 'data': {'data': 'Processing time saved, document was '
                                                                                 'already processed '
                                                                                 'at an earlier time: ',
                                     'pages': stats['n_pages'], 'tables': stats['n_tables']}})

                return file['fid']

    except Exception as e:
        # Communicate failure to client
        post(post_url, json={'event': 'processing_failure', 'data': {'pdf_name': file_path,
                                                                     'text': 'PyPDF error on file : ',
                                                                     'trace': str(e)}})
        return -1

    # STEP 1: Otherwise proceed, set all counters to 0
    n_tables = 0
    n_table_rows = 0
    table_sizes = {'small': 0, 'medium': 0, 'large': 0}

    # STEP 2: count total number of pages by reading PDF
    try:
        pdf_file = PyPDF2.PdfFileReader(open(file_path, mode='rb'))
        n_pages = pdf_file.getNumPages()
    except Exception as e:
        # Communicate failure to client
        post(post_url, json={'event': 'processing_failure', 'data': {'pdf_name': file_path,
                                                                     'text': 'PyPDF error on file : ',
                                                                     'trace': str(e)}})
        return -1

    # STEP 3: run TABULA to extract all tables into one pandas data frame
    try:
        df_array = tabula.read_pdf(file_path, pages="all", multiple_tables=True)
    except Exception as e:
        # Communicate failure to client
        post(post_url, json={'event': 'processing_failure', 'data': {'pdf_name': file_path,
                                                                     'text': 'Tabula error on file : ',
                                                                     'trace': str(e)}})
        return -1

    # STEP 4: count number of rows in each data frame
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

    # STEP 5: save stats as intermediary results in db
    try:
        creation_date = pdf_file.getDocumentInfo()['/CreationDate']
        stats = {'n_pages': n_pages, 'n_tables': n_tables,
                 'n_table_rows': n_table_rows, 'creation_date': creation_date,
                 'table_sizes': table_sizes}

        with app.app_context():
            # Create cursor
            cur = mysql.connection.cursor()

            # Execute query
            cur.execute("""INSERT INTO Files(url, stats) VALUES(%s, %s)""",
                        (url, json.dumps(stats, sort_keys=True, indent=4)))

            # Get ID from inserted row
            insert_id = cur.lastrowid

            # Commit to DB
            mysql.connection.commit()

            # Close connection
            cur.close()

    except Exception as e:
        # Communicate failure to client
        post(post_url, json={'event': 'processing_failure', 'data': {'pdf_name': file_path,
                                                                     'text': 'Cannot save stats of file in db : ',
                                                                     'trace': str(e)}})
        return -1

    # STEP 6: Send success message to client
    post(post_url, json={'event': 'tabula_success', 'data': {'data': 'Tabula PDF success: ',
                                                             'pages': n_pages, 'tables': n_tables}})

    # STEP 7: Return db row id
    return insert_id


# Background task serving as callback to save metadata to db
@celery.task(bind=True)
def pdf_stats(self, tabula_list, domain='', url='', crawl_total_time=0, post_url='', processing_start_time=0):

    with app.app_context():
        # STEP 0: Time keeping
        path = "data/%s" % (domain,)

        # STEP 1: Call Helper function to create Json string
        # https://stackoverflow.com/questions/35959580/non-ascii-file-name-issue-with-os-walk works
        # https://stackoverflow.com/questions/2004137/unicodeencodeerror-on-joining-file-name doesn't work
        hierarchy_dict = path_dict(path)  # adding ur does not work as expected either
        hierarchy_json = json.dumps(hierarchy_dict, sort_keys=True, indent=4)  #encoding='cp1252' not needed in python3

        # STEP 2: Call helper function to count number of pdf files
        n_files = path_number_of_files(path)

        # STEP 3: Treat result from Tabula tasks
        n_success = 0
        n_errors = 0
        fid_set = set()
        for fid in tabula_list:
            if fid < 0:
                n_errors += 1
            else:
                n_success += 1
                fid_set.add(fid)

        # STEP 4: Save some additional stats
        disk_size = dir_size(WGET_DATA_PATH + "/" + domain)

        # STEP 5: compute final processing time
        processing_total_time = time.time() - processing_start_time

        # STEP 5: Save query in DB
        # Create cursor
        cur = mysql.connection.cursor()

        # Execute query
        cur.execute("""INSERT INTO Crawls(pdf_crawled, pdf_processed, process_errors, domain, disk_size, 
                    url, hierarchy, crawl_total_time, proc_total_time) 
                    VALUES(%s ,%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (n_files, n_success, n_errors, domain, disk_size, url, hierarchy_json,
                        crawl_total_time, processing_total_time))

        # Commit to DB
        mysql.connection.commit()

        # Get Crawl ID
        cid = cur.lastrowid

        # STEP 6: link all pdf files to this query
        insert_tuples = [(fid, cid) for fid in fid_set]

        cur.executemany("""INSERT INTO Crawlfiles(fid, cid) VALUES (%s, %s)""",
                        insert_tuples)

        # Commit to DB
        mysql.connection.commit()

        # Close connection
        cur.close()

        # Send success message asynchronously to clients
        post(post_url, json={'event': 'redirect', 'data': {'url': '/processing'}})

        return 'success'


# ----------------------------- HELPER FUNCTIONS ----------------------------------------------------------------------
# Wrapper to check if user logged in
def is_logged_in(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'logged_in' in session:
            return f(*args, **kwargs)
        else:
            flash('Unauthorized, Please login', 'danger')
            return redirect(url_for('login'))
    return wrap


# Ability to stream a template (can be used with python generator, was now replaced by flask-socketio interface)
def stream_template(template_name, **context):
    app.update_template_context(context)
    t = app.jinja_env.get_template(template_name)
    rv = t.stream(context)
    rv.disable_buffering()
    return rv


# ----------------------------- APP ROUTES ----------------------------------------------------------------------------

# Crawl from to check user input
class CrawlForm(Form):
    url = StringField('URL', [validators.Length(min=4, max=300)], default=DEFAULT_CRAWL_URL)
    depth = IntegerField('Max Crawl Depth', [validators.NumberRange(min=1, max=10)], default=MAX_CRAWL_DEPTH)
    time = IntegerField('Max Crawl Duration [Minutes]', [validators.NumberRange(min=1, max=1000)],
                        default=int(MAX_CRAWLING_DURATION / 60))
    size = IntegerField('Max Crawl Size [MBytes]', [validators.NumberRange(min=10, max=1000)], default=MB_CRAWL_SIZE)
    pdf = IntegerField('Max Number of PDF to be processed', [validators.NumberRange(min=0, max=10000)],
                       default=PDF_TO_PROCESS)


# Index
@app.route('/', methods=['GET', 'POST'])
def index():
    form = CrawlForm(request.form)

    if request.method == 'POST' and form.validate():

        # Change global variables depending on input
        global MAX_CRAWLING_DURATION, MAX_CRAWL_DEPTH, MAX_CRAWL_SIZE, MB_CRAWL_SIZE, PDF_TO_PROCESS

        # Get Form Fields and update variables
        url = form.url.data
        crawl_again = request.form['crawl_again']
        MAX_CRAWL_DEPTH = form.depth.data
        MB_CRAWL_SIZE = form.size.data
        MAX_CRAWL_SIZE = 1024 * 1024 * MB_CRAWL_SIZE
        MAX_CRAWLING_DURATION = form.time.data * 60
        PDF_TO_PROCESS = form.pdf.data

        # Check if valid URL with function in helper module
        status_code = url_status(url)
        if status_code == -1:
            flash('Impossible to establish contact to given URL, check for typos and format.', 'danger')
            return render_template('home.html', most_recent_url="none", form=form)
        elif status_code is not requests.codes.ok:
            flash('Contact to given url was established, but received back the following status code: '
                  + str(status_code) + '. (Only status code 200 is accepted at the moment)', 'danger')
            return render_template('home.html', most_recent_url="none", form=form)

        # Extract domain name out of url and save in session
        parsed = urlparse(url)
        domain = parsed.netloc
        session['domain'] = domain
        session['url'] = url

        # Check if stats already exist about this domain
        # Create cursor
        cur = mysql.connection.cursor()

        # Get highest crawl_id from the last 7 days
        result = cur.execute("""SELECT COALESCE(MAX(cid), 0) as cid FROM Crawls WHERE domain = %s 
                      AND (crawl_date > DATE_SUB(now(), INTERVAL %s DAY))""", (domain, CRAWL_REPETITION_WARNING_TIME))

        cid = cur.fetchone()["cid"]

        # Closing cursor apparently not needed when using this extension
        if crawl_again != "True" and cid != 0:
            # There was a previous crawl, make button appear to view corresponding stats
            flash("This domain was already crawled in the last " + str(CRAWL_REPETITION_WARNING_TIME) + " days, "
                  + "you have the option to directly view the most recent statistics or restart the crawling process.",
                  "info")

            return render_template('home.html', most_recent_url=url_for("cid_statistics", cid=cid), form=form)

        return redirect(url_for('crawling'))

    return render_template('home.html', most_recent_url="none", form=form)


# Crawling
@app.route('/crawling')
@is_logged_in
def crawling():

    # Check no crawling in progress
    if not lock.acquire(False):
        # Failed to lock the resource
        flash(Markup('There are already Tasks scheduled, please wait before running another query or '
                     'terminate all running processes <a href="/advanced" class="alert-link">here.</a>'), 'danger')
        return redirect(url_for('index'))

    else:
        try:
            # delete previously crawled data
            delete_data()

            # STEP 0: TimeKeeping
            session['crawl_start_time'] = time.time()

            # STEP 1: Prepare WGET command
            url = session.get('url', None)
            post_url = url_for('event', _external=True)

            # STEP 2: Schedule celery task
            result = crawling_task.delay(url=url, post_url=post_url, domain=session.get('domain', ''),
                                         max_crawl_duration=MAX_CRAWLING_DURATION,
                                         max_crawl_depth=MAX_CRAWL_DEPTH,
                                         max_crawl_size=MAX_CRAWL_SIZE)
            session['crawling_id'] = result.id

            return render_template('crawling.html',
                                   max_crawling_duration=MAX_CRAWLING_DURATION,
                                   max_crawl_depth=MAX_CRAWL_DEPTH,
                                   max_crawl_size=MAX_CRAWL_SIZE)
        except Exception as e:
            # Call Terminate function to make sure all started tasks are terminated and lock released
            terminate()
            flash("An error occurred : " + str(e), 'danger')
            return redirect(url_for('index'))


# End Crawling manually
@app.route('/crawling/end')
@is_logged_in
def end_crawling():

    # STEP 0: check crawling process exists
    if session.get('crawling_id', 0) is 0:
        flash("There is no crawling process to kill", 'danger')
        return redirect(url_for('index'))

    # STEP 1: Kill only subprocess, and the celery process will then recognize it and terminate too
    celery_id = session.get('crawling_id', 0)                       # get saved celery task id
    try:
        # This is a hack to kill the spawned subprocess and not only the celery task
        # I read that in some cases the subprocess doesn't get terminated when the Celery task is revoked,
        # though I never observed this behavior.
        pid = crawling_task.AsyncResult(celery_id).info.get('pid')      # get saved subprocess id
        os.kill(pid, signal.SIGTERM)                                    # kill subprocess
    except AttributeError:
        flash("Either the task was not scheduled yet, is already over, or was interrupted from someone else"
              " and thus interruption is not possible", 'danger')
        return redirect(url_for('index'))

    # STEP 2: TimeKeeping
    crawl_start_time = session.get('crawl_start_time', None)
    session['crawl_total_time'] = time.time() - crawl_start_time

    # STEP 3: Successful interruption
    session['crawling_id'] = 0                                      # remove crawling id
    flash('You successfully manually interrupted the crawler.', 'success')

    # STEP 4: Release Lock
    try:
        lock.release()
    except RuntimeError:
        pass

    return render_template('end_crawling.html')


# End Crawling automatically, for this to work the client must still have the tab open !
@app.route('/crawling/autoend')
@is_logged_in
def autoend_crawling():

    # STEP 1: TimeKeeping
    crawl_start_time = session.get('crawl_start_time', None)
    total_time = time.time() - crawl_start_time
    session['crawl_total_time'] = total_time
    crawled_size = dir_size(WGET_DATA_PATH + "/" + session.get('domain'))

    # STEP 2: Successful interruption
    if total_time > MAX_CRAWLING_DURATION:
        flash('Time limit reached - Crawler interrupted automatically', 'success')
    elif crawled_size > MAX_CRAWL_SIZE:
        flash("Size limit reached - Crawler interrupted automatically", 'success')
    else:
        flash("Crawled all PDFs until depth of " + str(MAX_CRAWL_DEPTH) + " - Crawler interrupted automatically",
              'success')

    session['crawling_id'] = 0  # remove crawling id

    # STEP 3: Release Lock
    try:
        lock.release()
    except RuntimeError:
        pass

    return redirect(url_for("table_detection"))


# Start table detection
@app.route('/table_detection')
@is_logged_in
def table_detection():

    # First check if lock can be acquired
    if not lock.acquire(False):
        # Failed to lock the resource
        flash(Markup('There are already Tasks scheduled, please wait before running another query or '
                     'terminate all running processes <a href="/advanced" class="alert-link">here.</a>'), 'danger')
        return redirect(url_for('index'))

    else:
        try:
            # Step 0: take start time and prepare arguments
            processing_start_time = time.time()
            domain = session.get('domain', None)
            url = session.get('url', None)
            crawl_total_time = session.get('crawl_total_time', 0)
            post_url = url_for('event', _external=True)

            path = WGET_DATA_PATH + '/' + domain

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
            chord(header)(callback)

            # STEP 4: If query was empty go straight further
            if count == 0:
                return redirect(url_for('processing'))

            return render_template('table_detection.html', total_pdf=count)

        except Exception as e:
            # If something goes wrong make sure all tasks get revoked and lock released
            terminate()
            flash("Something went wrong: " + str(e) + " --- All tasks were revoked and the lock released")


# End of PDF processing (FIXME name not very fitting anymore)
@app.route('/processing')
@is_logged_in
def processing():
    # Release lock
    try:
        lock.release()
    except RuntimeError:
        pass
    return render_template('processing.html', domain=session.get('domain', ''), )


# Last Crawl Statistics
@app.route('/statistics')
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
def cid_statistics(cid):

    # STEP 1: retrieve all saved stats from DB
    # Create cursor
    cur = mysql.connection.cursor()

    cur.execute("""SELECT * FROM Crawls WHERE cid = %s""", (cid,))
    crawl = cur.fetchone()

    # Get stats by getting all individual files
    cur.execute("""SELECT url, stats FROM Files f JOIN Crawlfiles cf ON f.fid = cf.fid WHERE cid = %s""",
                         (cid,))
    stats_db = cur.fetchall()
    stats = {}
    for stat in stats_db:
        stats[stat['url']] = json.loads(stat['stats'])

    # Close connection
    cur.close()

    # STEP 2: do some processing to retrieve interesting info from stats
    json_hierarchy = json.loads(crawl['hierarchy'])

    stats_items = stats.items()
    n_tables = sum([subdict['n_tables'] for filename, subdict in stats_items])
    n_rows = sum([subdict['n_table_rows'] for filename, subdict in stats_items])
    n_pages = sum([subdict['n_pages'] for filename, subdict in stats_items])

    medium_tables = sum([subdict['table_sizes']['medium'] for filename, subdict in stats_items])
    small_tables = sum([subdict['table_sizes']['small'] for filename, subdict in stats_items])
    large_tables = sum([subdict['table_sizes']['large'] for filename, subdict in stats_items])

    # Find some stats about creation dates
    creation_dates_pdf = [subdict['creation_date'] for filename, subdict in stats_items]
    creation_dates = list(map(lambda s: pdf_date_format_to_datetime(s), creation_dates_pdf))
    disk_size = round(crawl['disk_size'] / (1024*1024), 1)

    if len(creation_dates) > 0:
        oldest_pdf = min(creation_dates)
        most_recent_pdf = max(creation_dates)
    else:
        oldest_pdf = "None"
        most_recent_pdf = "None"

    return render_template('statistics.html', cid=cid, n_files=crawl['pdf_crawled'], n_success=crawl['pdf_processed'],
                           n_tables=n_tables, n_rows=n_rows, n_errors=crawl['process_errors'], domain=crawl['domain'],
                           small_tables=small_tables, medium_tables=medium_tables,
                           large_tables=large_tables, stats=json.dumps(stats, sort_keys=True, indent=4),
                           hierarchy=json_hierarchy, end_time=crawl['crawl_date'],
                           crawl_total_time=round(crawl['crawl_total_time'] / 60.0, 1),
                           proc_total_time=round(crawl['proc_total_time'] / 60.0, 1),
                           oldest_pdf=oldest_pdf, most_recent_pdf=most_recent_pdf, disk_size=disk_size,
                           n_pages=n_pages)


# Form to check User registration data
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
            data = cur.fetchone()                                       # FIXME username should be made primary key
            password = data['password']

            # Compare passwords
            if sha256_crypt.verify(password_candidate, password):

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

        # Note: Closing connection not necessary when using flask mysql db extension

    return render_template('login.html')


# Delete Crawl
@app.route('/delete_crawl', methods=['POST'])
@is_logged_in
def delete_crawl():
        try:

            # Get Form Fields
            cid = request.form['cid']

            # Create cursor
            cur = mysql.connection.cursor()

            # Get user by username
            cur.execute("""DELETE FROM Crawls WHERE cid = %s""", (cid,))

            # Commit to DB
            mysql.connection.commit()

            # Close connection
            cur.close()

            flash('Crawl successfully removed', 'success')

            return redirect(url_for('dashboard'))

        except Exception as e:
            flash('An error occurred while trying to delete the crawl: ' + str(e), 'danger')
            redirect(url_for('dashboard'))


# Logout
@app.route('/logout')
@is_logged_in
def logout():
    session.clear()
    flash('You are now logged out', 'success')
    return redirect(url_for('login'))


# Dashboard
@app.route('/dashboard')
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


# Advanced
@app.route('/advanced')
@is_logged_in
def advanced():
    return render_template('advanced.html')


# Release lock and Terminate all background tasks
@app.route('/terminate')
@is_logged_in
def terminate():

    # Purge all tasks from task queue
    command = shlex.split(VIRTUALENV_PATH + " -f -A bar.celery purge") #FIXME datapath variable
    subprocess.Popen(command)

    # Kill all Celery tasks that have an ETA or are scheduled for later processing
    i = celery.control.inspect()
    scheduled_tasks = i.scheduled()

    # FIXME don't replicate same code 3 times
    for workers in scheduled_tasks:
        for j in range(0, len(scheduled_tasks[workers])):
            celery.control.revoke(scheduled_tasks[workers][j]['id'], terminate=True)

    # Kill all Celery tasks that are currently active.
    active_tasks = i.active()

    for workers in active_tasks:
        for j in range(0, len(active_tasks[workers])):
            celery.control.revoke(active_tasks[workers][j]['id'], terminate=True)

    # Kill all Celery tasks that have been claimed by workers
    reserved_tasks = i.reserved()

    for workers in reserved_tasks:
        for j in range(0, len(reserved_tasks[workers])):
            celery.control.revoke(reserved_tasks[workers][j]['id'], terminate=True)

    # Release Lock if locked
    try:
        lock.release()
    except RuntimeError:
        pass

    # Broadcast the termination messages to users that were potentially still observing task progress
    socketio.emit('redirect', {'url': 'terminated'})

    # Flash success message
    flash("All processes were interrupted and the lock released !", 'success')

    return redirect(url_for('advanced'))


# Page displayed when process terminated by other user
@app.route('/terminated')
@is_logged_in
def terminated():
    return render_template('terminated.html')


# Empty all Tables except for User data
@app.route('/empty_tables')
@is_logged_in
def empty_tables():

    # Create cursor
    cur = mysql.connection.cursor()

    # Truncate all tables, necessary trick because of constrained table
    # https://stackoverflow.com/questions/5452760/how-to-truncate-a-foreign-key-constrained-table
    cur.execute("""SET FOREIGN_KEY_CHECKS = 0""")

    cur.execute("""TRUNCATE TABLE Crawlfiles""")
    cur.execute("""TRUNCATE TABLE Crawls""")
    cur.execute("""TRUNCATE TABLE Files""")

    cur.execute("""SET FOREIGN_KEY_CHECKS = 1""")

    # Close connection
    cur.close()

    flash("All tables were emptied !", 'success')

    return redirect(url_for('advanced'))


# About
@app.route('/about')
def about():
    return render_template('about.html')


# Delete Crawled PDFs
@app.route('/delete_data', methods=['GET', 'POST'])
@is_logged_in
def delete_data():
    # Taken from https://stackoverflow.com/questions/185936/how-to-delete-the-contents-of-a-folder-in-python
    folder = WGET_DATA_PATH
    for the_file in os.listdir(folder):
        file_path = os.path.join(folder, the_file)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path): shutil.rmtree(file_path)
        except Exception as e:
            print(e)

    return "Crawled data deleted successfully"


# Download JSON hierarchy
@app.route('/hierarchy/<int:cid>')
@is_logged_in
def hierarchy_download(cid):

    # Get JSON string
    # Create cursor
    cur = mysql.connection.cursor()

    # Get Crawls
    result = cur.execute("""SELECT hierarchy FROM Crawls WHERE cid = %s""", (cid,))
    if not result > 0:
        return

    hierarchy = cur.fetchone()['hierarchy']

    return Response(hierarchy,
                    mimetype='application/json',
                    headers={'Content-Disposition': 'attachment;filename=hierarchy.json'})


# Download any logfile
@app.route('/log/<string:lid>')
@is_logged_in
def log_download(lid):
    if lid in switcher:
        return send_file(switcher.get(lid))
    else:
        flash('An error occurred while trying to download log', 'error')
        return redirect(url_for('advanced'))


# Delete any logfile
@app.route('/log_del/<string:lid>')
@is_logged_in
def log_delete(lid):
    if lid in switcher:
        open(switcher.get(lid), 'w').close()
        flash('Log was successfully emptied', 'success')
        return  redirect(url_for('advanced'))
    else:
        flash('An error occurred while trying to delete log', 'error')
        return redirect(url_for('advanced'))


# Used to easily emit WebSocket messages from inside tasks
# Pattern taken from https://github.com/jwhelland/flask-socketio-celery-example/blob/master/app.py
@app.route('/event/', methods=['POST'])
def event():
    data = request.json
    if data:
        socketio.emit(data['event'], data['data'])
        return 'ok'
    return 'error', 404


# ----------------------------- ASYNCHRONOUS COMMUNICATION ------------------------------------------------------------
# Note: these are not crucial at the moment,
# though it would be nice to direct messages to clients instead of broadcasting.


@socketio.on('connect')
def test_connect():
    emit('my_response', {'data': 'Connected', 'count': 0})


@socketio.on('disconnect')
def test_disconnect():
    print('Client disconnected', request.sid)


# ----------------------------- RUNNING APPLICATION -------------------------------------------------------------------

if __name__ == '__main__':
    socketio.run(app)
