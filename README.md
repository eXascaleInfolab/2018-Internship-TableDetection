﻿# PDF Crawl App 

Visit the the first deployed version [here](http://www.zenosyne.ch).

![SCREENSHOT](images/IMG1.png)

## Introduction

### Purpose
Data has become extremely valuable, some going as far as calling it the [world's most valuable resource.](https://www.economist.com/leaders/2017/05/06/the-worlds-most-valuable-resource-is-no-longer-oil-but-data) However, for the data to be valuable it has to be findable and stored in data formats that allow further exploitation. The aim of this application is to visualize how much data is hidden in PDF files.

### How to use the application
The current application works in 3 steps:
1.  The user enters the domain that is to be crawled. If a specific URL is given the crawler will start from there, working recursively  in a breadth-first manner. 
2.  After finishing fetching the PDF files or being interrupted this tool will perform table detection on the PDFs.
3.  Finally the collected data will be displayed on the Statistics page and will be listed on the Dashboard.

### Implementation Details

- There is a simple Registration and Login system in place. Currently everyone can register and use this tool.
- There is a Lock to prevent multiple users to start queries at the same time. Only one query can run at the same time, other users will have to wait until the query terminates.
- The table detection only starts if the Crawling tab is kept open, or table detection is started manually.
- Once table detection is started it will finish even if the tab is closed (though as of now the lock has to be released manually in that case).

### Technologies used

The application is written in Python 3 using the [Flask](http://flask.pocoo.org/) micro framework that is based on Werkzeug and Jinja 2. Built using the well known Bootstrap [SB Admin 2](https://startbootstrap.com/template-overviews/sb-admin-2/) theme as front-end, it uses [Celery](http://flask.pocoo.org/docs/1.0/patterns/celery/) as Task queue and [Redis](https://redis.io/) as message broker to run three different types of background tasks in the following order:
1. A Crawling task is run using the [wget](https://www.gnu.org/software/wget/) command line tool.
2. The Table detection tasks are performed in parallel using [Tabula](https://tabula.technology/), an open-source tool running on the JVM.
3. A Callback will save the insights won in a [MySQL Server](https://dev.mysql.com/downloads/mysql/) database.

The [Flask SocketIO](https://flask-socketio.readthedocs.io/en/latest/) plug-in is used in combination with [eventlet](http://eventlet.net/) to communicate feedback asynchronously to the client.

Finally the Deployment server runs on Ubuntu 16.04. It uses [Supervisor](http://supervisord.org/) to start processes at boot time,  [NGINX](https://www.nginx.com/) as reverse proxy, and [Gunicorn](http://gunicorn.org/) as HTTP server.

![Diagram](https://cdn-images-1.medium.com/max/1400/1*nFxyDwJ2DEH1G5PMKPMj1g.png)

## Deployement

This guide should work you through every step required to install this application on your own server running Ubuntu 16.04, all you need is to have shell access, everything else will be provided in this document. 

I used the 5$/month Digital Ocean droplet option that comes with 1GB memory, 25GB disk space and a single core CPU. This is perfectly sufficient for demonstration purposes but probably too slow to perform table detection on large datasets. You will find more about execution speed in the Performance section at the end of this document.

![IMG3](images/IMG3.png)

### Prerequisites & Setting up the Server
If you start with a fresh Ubuntu 16.04 server I would recommend to first follow [these steps](https://www.digitalocean.com/community/tutorials/initial-server-setup-with-ubuntu-16-04) to initialize the server and create a non-root user with sudo privileges. 

If you haven't done so already, setting your servers time zone is quite useful for the time-stamps to display meaningful information to the users.

```
$ sudo timedatectl set-timezone Europe/Zurich
```

### Install the Components from the Ubuntu Repositories
First, install the required packages.

    $ sudo apt-get update
    $ sudo apt-get install python3-pip python3-dev nginx supervisor

> If you are using Ubuntu 16.04 as recommended you will have **timeout** and **wget** already installed, otherwise you might have to fetch theses packages yourself.

### Install Java

First download the JRE.
```
$ sudo apt-get install default-jre
```
You won't need to set JAVA_HOME environment variable for the application to run but you can check out [this turorial](https://www.digitalocean.com/community/tutorials/how-to-install-java-with-apt-get-on-ubuntu-16-04) if you want to do so for completeness.

### Create a Python Virtual Environment
Next, you'll need to set up a virtual environment in order to isolate the Flask application from the other Python files on the system.

    $ sudo pip3 install virtualenv

Now you can chose where to store the application. You can do it either under `/opt` or under your home directory. I chose the second option here, with `/bar` as parent directory for the application. Make sure to replace `/home/yann/bar` with the path you chose in every snippet that follows. 


    $ mkdir ~/bar
    $ cd ~/bar
Now it's time to create the virtual environment to store the project's Python requirements.

    $ virtualenv virtualenv

> Note: Again you are free to chose the name of your virtual environment, I will use `virtualenv` as my virtual environments name.

This will install a local copy of Python and `pip` into a directory called `virtualenv` within your project directory.

Before we install applications within the virtual environment, we need to activate it. You can do so by typing:

    $ source virtualenv/bin/activate

Your prompt will change to indicate that you are now operating within the virtual environment. It will look something like this `(virtualenv) user@host:~/bar $`.

### Clone the Application
It is now time to clone the application's code from GitHub.

    (virtualenv)$ git clone https://github.com/eXascaleInfolab/2018-Internship-TableDetection.git

 To move all files out of the new directory into the original bar directory we first copy them over and then delete the original folder.

    (virtualenv)$ cp -vaR 2018-Internship-TableDetection/. .
    (virtualenv)$ sudo rm -R 2018-Internship-TableDetection/

### Install MySQL Server

Since some of the Python packages have MySQL server as dependency we will start the MySQL server first.

```
(virtualenv)$ sudo apt-get install mysql-server libmysqlclient-dev
```

You will be prompted to set a password for the db. We can now access the database by typing:

```
(virtualenv)$ mysql -u root -p 
```

Again you will be prompted to type your previously chosen password.
Now from inside SQL you can create the database and the required tables by issuing the following commands:

```sql
mysql> CREATE DATABASE bar;
mysql> USE bar
mysql> source /home/yann/bar/create_db.sql
```

We can then exit mysql again.

```sql
mysql> exit
```

### Install Python Dependencies

We can now install all Python dependencies by using pip.

    (virtualenv)$ pip install -r requirements.txt
    (virtualenv)$ pip install gunicorn

The first command installs a multitude of dependencies such as celery, flask, flask-socketIO and many more. The second command installs the HTTP server. It is not in the requirements file since a local version of the application could run on it's own using Werkzeug, the built in Flask developement server for example, or Eventlet is by itself a production ready Web server.

These commands should terminate without errors, otherwise you might have to install required packages manually using `pip install` which would be extremely inconvenient.

### Code changes

This should be fixed soon, but for now there is a single line of code that you will have to change before running the application. In the main module called `bar.py` you will have to set the variable `VIRTUALENV_PATH` to the path to your virtual environment. 

### NGINX reverse proxy and Firewall set up
To add some security the traffic will be routed through NGINX. First you should create a config file.

    $ sudo nano /etc/nginx/sites-available/bar
You can now copy the following text into it, then save and close.

```nginx
server {
    listen 80;
    server_name zenosyne.ch, 138.68.102.72; #add your server IP, domain or both here.

    location / {
        include proxy_params;
        proxy_pass http://127.0.0.1:5000;
    }

    location /socket.io {
        include proxy_params;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_pass http://127.0.0.1:5000/socket.io;
    }

    location /flower/static {
        # Change this path to your virtual environment
        alias /home/yann/bar/virtualenv/lib/python3.5/site-packages/flower/static;
    }

    location /flower {
        rewrite ^/flower/(.*)$ /$1 break;
        proxy_pass http://localhost:5555;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Host $host;
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }
}
```

> Note: change server_name to your own domain name or IP-address and /home/yann/bar to your project directories path

To enable the NGINX server block configuration we've just created, we link the file to the `sites-enabled` directory.

```
$ sudo ln -s /etc/nginx/sites-available/bar /etc/nginx/sites-enabled
```
With the file in that directory, we can test for syntax errors by typing:

```
$ sudo nginx -t
```

If this returns without indicating any issues, we can restart the Nginx process to read our new configuration.

```
$ sudo systemctl restart nginx
```

If you followed the server set-up guide I linked at the beginning you will have the Firewall enabled already, in that case you only need to allow NGINX. If not, the following commands will set up a basic Firewall.

You can see all allowed services by typing:
```
$ sudo ufw app list
```

You should now allow SSH and NGINX connections.
```
$ sudo ufw allow 'Nginx Full'
$ sudo ufw allow OpenSSH 
```
> Make sure to allow ssh, otherwise you won't be able to log back into your server !

Finally you can start the Firewall.

```
$ sudo ufw enable
```

If you desire you can check the status. 

```
$ sudo ufw status
```

### Redis
The only other Tool that needs seperate installation is the message broker Redis.
Luckily you should be able to use the installation script provided in the cloned git repository.

First make sure to deactivate your virtual environment if you haven't done so before.

    (virtualenv) $ deactivate

Then you can launch the installation script provided to you.

    $ ./run-redis.sh 

This script will not only install but also run redis in the shell. You can press `Ctrl-C` to quit redis, since like all other services it will be managed by supervisor and doesn't require manual start-up.

#### [Deprecated] Redis without supervisor

For completeness I added some the commands that where useful to me when I used Redis without Supervisor.

```
$ redis-server --daemonize yes
```

    $ ps -u <your_username> -o pid,rss,command | grep redis
    $ sudo kill -9 <pid>


### Set up Supervisor and start application
Finally you can now configure Supervisor that will be in charge of running and restarting all services when the system reboots for example.

```
$ sudo nano /etc/supervisor/conf.d/bar.conf
```
You can now copy the entire following text inside this configuration file.
```supervisor
[program:bar]
directory=/home/yann/bar
command=/home/yann/bar/virtualenv/bin/gunicorn --worker-class eventlet -w 1 --bind localhost:5000 bar:app
autostart=true
autorestart=true
stderr_logfile=/home/yann/bar/log/bar.err.log
stdout_logfile=/home/yann/bar/log/bar.out.log


[program:celery]
; Set full path to celery program if using virtualenv
command=/home/yann/bar/virtualenv/bin/celery worker -A bar.celery --loglevel=INFO
directory=/home/yann/bar
user=nobody
numprocs=1
stdout_logfile=/home/yann/bar/log/celery.log
stderr_logfile=/home/yann/bar/log/celery.log
autostart=true
autorestart=true
startsecs=10

; Need to wait for currently executing tasks to finish at shutdown.
; Increase this if you have very long running tasks.
stopwaitsecs = 600

; Causes supervisor to send the termination signal (SIGTERM) to the whole process group.
stopasgroup=true

; Set Celery priority higher than default (999)
priority=1000

[program:redis]
command=/usr/local/bin/redis-server /etc/redis/redis.conf
autostart=true
autorestart=true
user=root
stdout_logfile=/home/yann/bar/log/redis.log
stderr_logfile=/home/yann/bar/log/redis.log
stopsignal=QUIT

[program:flower]
directory = /home/yann/bar/
command=/home/yann/bar/virtualenv/bin/flower -A bar.celery --port=5555  --url-prefix=flower
autostart=true
autorestart=true
stdout_logfile=/home/yann/bar/log/flower.log
stderr_logfile=/home/yann/bar/log/flower.log
stopsignal=QUIT

```

> Note: As before you will have to replace /home/yann/bar by your own project directory path!


You can now restart Supervisor to bring all service on-line.
```
$ sudo supervisorctl reread all
$ sudo supervisorctl restart all
```
This will start up the flask-app that I called **bar** and the **celery**, **redis** and **flower** processes. Check that all four services are running by executing:
```
$ sudo supervisorctl status 
```
If you forgot to adapt the paths to your project directory or made any other changes you might have to reload first.

    $ sudo supervisorctl reload

Other usefull commands for Supervisor are

    $ sudo supervisorctl status, start <service>, stop <service>

### Authentication for Flower 

![IMG4](images/IMG4.png)[Flower](http://flower.readthedocs.io/en/latest/) is a web based tool for monitoring and administrating [Celery](http://celeryproject.org) clusters. It will allow you to see how busy the server is and check what tasks are currently running, how long they took to complete and much more. It was installed through pip already, so now all you need to do is set up an htpasswd file. This basic access control is important to protect Flower from unwanted access if your application runs on the Internet. 

    $ sudo apt install apache2-utils
    $ sudo htpasswd -c /etc/nginx/.htpasswd admin

This sets *admin* as username, but you can choose any username you want of course, you will then be prompted to choose a password.

> Note: this step is crucial to access Flower, since in the NGINX config file the last two lines require authentication. You can remove the authentication entirely by removing those two lines.

You can now access the Flower task monitoring interface by going to <server-IP-or-domain>/flower or under the Advanced tab of the application.

### Final touches: Creating log and data directories

To log the Crawler output you should create a log file, and allow a non-sudo user to alter it.

```
$ mkdir /home/yann/bar/log && touch /home/yann/bar/log/wget.txt
$ chmod 777 /home/yann/bar/wget.txt
```

The temporarily stored crawled data will be located in the /data directory. You should create and allow access to it.

```
$ mkdir /home/yann/bar/data/
$ chmod 777 /home/yann/bar/data/
```

### Access Control

In the current version everyone is allowed to register and set up an account. You could restrict the application to a small set of users easily by removing the possibility to register freely. 

Currently the Dashboard and Statistics are open to every visitor of the website, while the crawling and table detection process as well as the deletion and other irreversible actions are restricted to authenticated users.

### Warning

The aforementioned configurations are the minimal configurations to get the server up and running. You might want to configure further for more safety and stability if this is a concern for you.



## [Optional] Adding domain name

Adding a domain name to point to your server is extremely simple. There is essentially only two steps. First you must purchase a domain name from a registrar (I chose Hostpoint). Then you need to choose a DNS hosting service. While most of the registrars offer this for free, I chose to go with DigitalOcean's DNS hosting. It is also free and extremely easy and convenient to set up. All you need to do is to choose which host name redirects to which IP-address, thus setting up the DNS records and you are good to go.

> Note: you might have to change your nginx settings, you can simply change the server_name line from the IP-address to the newly purchased domain name.

![DigitalOcean as DNS host](images/IMG2.png)

## Performance Evaluation

I plan to add some Benchmarking results here, to get an idea of how fast a query should terminate.

In general a single page will take between 0.1 and 1 second of processing time depending on the amount of lines and tables present. Additionally for each PDF file there is some constant overhead. I have observed that datasets of 100 PDFs take between 10 to 120 minutes processing time on a single core CPU.

Of course since we are using Celery we could take full advantage of a multi-core architecture to further speed up the table-detection tasks.

## Further work

- [ ] Cleaner pipeline (for example implement automatic start to table detection after crawling)
- [ ] Deploy application on Docker
- [ ] Allow multiple simultaneous users
- [ ] Improve Table Detection speed and accuracy by training a Neural Net
- [ ] Better logging
- [ ] Improve use of Locks
- [ ] [Opt] Adding SSL encryption



## Advanced Comments

- Celery can use multiple workers on different machines, with each worker taking advantage of multi-core systems. The table detection step can thus be accelerated by more powerful hardware.
- When using Gunicorn you can only use one eventlet worker process, which does not matter for this application.



## Sources

-  Deploy flask app with nginx using gunicorn and supervisor. https://medium.com/ymedialabs-innovation/deploy-flask-app-with-nginx-using-gunicorn-and-supervisor-d7a93aa07c18
- How To Serve Flask Applications with Gunicorn and Nginx on Ubuntu 16.04. https://www.digitalocean.com/community/tutorials/how-to-serve-flask-applications-with-gunicorn-and-nginx-on-ubuntu-16-04
- Deploying a Flask Site Using NGINX Gunicorn, Supervisor and Virtualenv on Ubuntu. http://alexandersimoes.com/hints/2015/10/28/deploying-flask-with-nginx-gunicorn-supervisor-virtualenv-on-ubuntu.html
- The Flask Mega-Tutorial Part XVII: Deployment on Linux. https://blog.miguelgrinberg.com/post/the-flask-mega-tutorial-part-xvii-deployment-on-linux
- Using Celery With Flask. https://blog.miguelgrinberg.com/post/using-celery-with-flask
- Asynchronous updates to a webpage with Flask and Socket.io. https://www.shanelynn.ie/asynchronous-updates-to-a-webpage-with-flask-and-socket-io/
- How To Install and Configure Redis on Ubuntu 16.04. https://www.digitalocean.com/community/tutorials/how-to-install-and-configure-redis-on-ubuntu-16-04
- Domains and DNS. https://www.digitalocean.com/docs/networking/dns/