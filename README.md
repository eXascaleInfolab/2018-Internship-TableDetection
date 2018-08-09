# PDF Crawl App 

Visit the the first deployed version here: zenosyne.ch

TODO add pictures.

## Introduction

### Purpose
Data has become extremely valuable, while some call it the [world's most valuable resource](https://www.economist.com/leaders/2017/05/06/the-worlds-most-valuable-resource-is-no-longer-oil-but-data), there is no doubt that with the recent surge in Machine Learning the demand and impact is extremely high. But for the data to be valuable it has to be in convenient form which sadly is not always the case. The aim of this application is to visualize how much data is hidden in PDF files instead of being stored in more convenient data formats, that would allow third parties to integrate it in their research, business and more.
 
### Implementation Details
The current App works in 3 steps:
1.  The user enters the domain that is to be crawled. If a specific URL is given the crawler will start from there, work recursively  in a breadth-first manner from there. 
2.  After finishing fetching the PDF or being interrupted this tool will perform table detection on the PDFs.
3.  Finally the collected data will be displayed on the Statistics page and it will be listed on the Dashboard.

### Technologies used
The application is written in Python 3 using the [Flask](http://flask.pocoo.org/) micro framework that is based on Werkzeug and Jinja 2. It uses [Celery](http://flask.pocoo.org/docs/1.0/patterns/celery/) as Task queue and [redis](https://redis.io/) as message broker to run the three different types of background tasks:
1. Crawling task that uses [wget](https://www.gnu.org/software/wget/)
2. Table detection task that is performed by [Tabula](https://tabula.technology/)
3. Callback that saves retrieved statistics in database

The Crawl results and statistics for every PDF processed are stored in a [MySQL Server](https://dev.mysql.com/downloads/mysql/) database.

Additionally the [Flask SocketIO](https://flask-socketio.readthedocs.io/en/latest/) plug-in is used in combination with the [eventlet](http://eventlet.net/) to communicate feedback asynchronously to the client.

Finally the Deployment server runs on Ubuntu 16.04. It uses [Supervisor](http://supervisord.org/) to start processes at boot time,  [NGINX](https://www.nginx.com/) as reverse proxy, and [Gunicorn](http://gunicorn.org/) as HTTP server.

![Diagram](https://cdn-images-1.medium.com/max/1400/1*nFxyDwJ2DEH1G5PMKPMj1g.png)

## Deployement

This guide should work you through every step required to install this application on your own server running Ubuntu 16.04, all you need is to have shell access, everything else will be provided in this document.

The approximate time to set this up is about 3 hours if you are at least somewhat familiar with Linux.

### Prerequisites & Setting up Server
If you start with a fresh Ubuntu 16.04 server I would recommend to first follow [these steps](https://www.digitalocean.com/community/tutorials/initial-server-setup-with-ubuntu-16-04) to initialize the server and create a non-root user with sudo privileges. 

TODO fire-wall
 
### Install the Components from the Ubuntu Repositories
First you need to install the required packages.

    $ sudo apt-get update
    $ sudo apt-get install python3-pip python3-dev nginx supervisor

### Other Dependencies and Set up
If you haven't done so already, setting your servers time zone is quite useful for the time-stamps to display meaningful information to the users.

    $ sudo timedatectl set-timezone Europe/Zurich
    
Additionally you should make sure to have the following two packages by typing

    sudo apt-get install wget
    TODO timeout?

### Install MySQL Server
Since some of the Python packages have MySQL server as dependency we will instart the MySQL server first.

    $ sudo apt-get install mysql-server libmysqlclient-dev

You will be prompted to set a password, remember it !
We can now create the database by typing

    $ mysql -u root -p 
    
Again you will be prompted to type your previously chosen password.
Now from inside SQL you can create the database and the required tables by issuing the follwing commands:


```sql
mysql> CREATE DATABASE bar;
mysql> USE bar
mysql> source /home/yann/bar/create_db.sql
```
You can now exit mysql by typing
```sql
mysql> exit
```
### Install JAVA

First download the JRE.
```
$ sudo apt-get install default-jre
```
You won't need to set JAVA_HOME environament variable for this but you can check out [this turorial](https://www.digitalocean.com/community/tutorials/how-to-install-java-with-apt-get-on-ubuntu-16-04) if you want to do so for completeness.

### Create a Python Virtual Environment
Next, you'll need to set up a virtual environment in order to isolate the Flask application from the other Python files on the system.

    $ sudo pip3 install virtualenv

Now you can chose where to store the application. You can do it either under `/opt` or under you home directory. I chose the second option here, with ´/bar´ as parent directory for the application. Make sure to replace `/home/yann/bar` with the path you chose in the following sections. 

> Note: There are other places where this will be important but I will
> also annote these


    $ mkdir ~/bar
    $ cd ~/bar
     
     TODO mkdir log, data
Now it's time to create the virtual environment to store the project's Python requirements.

    $ virtualenv virtualenv

> Note: Again you are free to chose the name of your virtual environment, I will use virtualenv.

This will install a local copy of Python and `pip` into a directory called `myprojectenv` within your project directory.

Before we install applications within the virtual environment, we need to activate it. You can do so by typing:

    $ source virtualenv/bin/activate

Your prompt will change to indicate that you are now operating within the virtual environment. It will look something like this `(virtualenv) user@host:~/bar$`.

### Set up the Application
It is now time to clone the app from GitHub.

    (virtualenv)$ git clone https://github.com/eXascaleInfolab/2018-Internship-TableDetection.git

Now to move all files out of the new directory into the original bar directory we first copy them over and then delete the folder.

    (virtualenv)$ cp -vaR 2018-Internship-TableDetection/. .
    (virtualenv)$ sudo rm -R 2018-Internship-TableDetection/

TODO change name ?

We can now install all Python dependencies by using pip again.

    (virtualenv)$ pip install -r requirements.txt
    (virtualenv)$ pip install gunicorn

The second command installs the HTTP server, it is not in the requirements since a local version for instance could run on Werkzeug, the built in Flask developement server, or Eventlet by itself.

This should terminate without errors, otherwise you might have to install required packages manually using pip install.

### Set up NGINX reverse proxy and Firewall
To add some security the traffic will be routed through NGINX. First add the config file by following the steps below.

    $ sudo nano /etc/nginx/sites-available/bar
You can now copy the following text into it, then close and save.
```nginx
server {
    listen 80;
    server_name zenosyne.ch;

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

> Note: change server_name to your own domain name or IP-address.

To enable the Nginx server block configuration we've just created, link the file to the `sites-enabled` directory:

```
$ sudo ln -s /etc/nginx/sites-available/bar /etc/nginx/sites-enabled
```
With the file in that directory, we can test for syntax errors by typing:

```
$ sudo nginx -t
```

If this returns without indicating any issues, we can restart the Nginx process to read the our new config:

```
$ sudo systemctl restart nginx
```

If you followed the server set-up guide I linked at the beginning you will have the Firewall enabled yet, now we will only allow NGINX and SHH to pass through:

You can see all allowed services by typing:
```
$ sudo ufw app list
```

First
```
$ sudo ufw allow 'Nginx Full'
$ sudo ufw allow OpenSSH 
$ sudo ufw enable
```
Some other useful and self explanatory commands are:
```
$ sudo ufw status
```

### Set up Redis
[Source](https://www.digitalocean.com/community/tutorials/how-to-install-and-configure-redis-on-ubuntu-16-04)

The only other Tool that needs seperate installation is the message broker redis.
Luckily you should be able to use the installation script from the git repo.

First make sure to deactivate your virtual environment

    (virtualenv) $ deactivate

Then you can launch the installation script provided to you.

    $ ./run-redis.sh 

This script will not only install but also run redis right away in the shell. You can press `Ctrl-C` to quit redis, since it will be managed by supervisor like all other services.

#### Redis without supervisor

    ps -u yann -o pid,rss,command | grep redis
    sudo kill -9 2801
    redis-server --daemonize yes


### Set up Supervisor and run Services
Finally you can now configure Supervisor that will be in charge of running and restarting all services when the system reboots for example.

```
$ sudo nano /etc/supervisor/conf.d/bar.conf
```
You can now copy the entire following text inside this config file.
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
; so, if rabbitmq is supervised, it will start first.
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

> Note: You will have to replace /home/yann/bar by your own project directory


You can now restart Supervisor to bring all service on-line.
```
$ sudo supervisorctl reread all
$ sudo supervisorctl restart all
```
Check that all 4 services are running by executing:
```
$ sudo supervisorctl status 
```
If you forgot to adapt the paths to your project directory or made any other changes you might have to reload first.

    $ sudo supervisorctl reload
    
Other usefull commands for Supervisor are

    $ sudo supervisorctl status, reload, start, stop bar

### Other
The following might be necessary
```
$ touch /home/yann/bar/wget_log.txt
$ chmod 777 /home/yann/bar/wget_log.txt
$ mkdir /home/yann/bar/data/
$ chmod 777 /home/yann/bar/data/
``` 
change virtualenv for purge command under /terminate

### Flower 

    $ sudo apt install apache2-utils
    $ sudo htpasswd -c /etc/nginx/.htpasswd admin

you will be promted to choose a password

### Warning
The aformentionned installements and configurations are the minimal configurations to get the server up and running. You might want to configure further for more safety.

## Adding domain name
Adding a domain name to point to your server is extremely simple. There is esentially only two steps. First you must purchase a domain name from a registrar (I chose Hostpoint). Then you need to choose a DNS host
ing service, most of the registrars offer this for free, but I chose to go with DigitalOcean's DNS hosting. It is also free and extremly easy and convenient to set up. All you need to do is to choose which hostname redirects to which IP address, thus setting up the DNS records and you are good to go.

> Note: you might have to change your nginx settings, you can simply change the server_name line from the IP-address to the newly purchased domain name.

TODO add picture

## Sources
The present guide was adapted from these resources:
https://www.digitalocean.com/community/tutorials/initial-server-setup-with-ubuntu-16-04
https://www.digitalocean.com/community/tutorials/initial-server-setup-with-ubuntu-16-04


## Further work
## Acknowledgements
If you wonder where Zenosyne comes from check out the Dictionnary of Obscure sorrows: 
