# Django server quick setup

![https://travis-ci.org/DrBenton/django-app-server-setup](https://travis-ci.org/DrBenton/django-app-server-setup.svg?branch=master)
![https://github.com/ambv/black](https://img.shields.io/badge/code%20style-black-000000.svg)

This is a all-in-one-with-no-dependencies Python script to provision a freshly created [Digital Ocean](https://www.digitalocean.com/) Droplet for Django.  
_(it can likely be used on any other server running Ubuntu 18.04, but I only used and tested it on Digital Ocean ones :-)_

It installs these softwares:

- Python 3.7 (and pip)
- Postgres 10 (server and client)
- Node.js 10 and Yarn
- Nginx
- Gunicorn
- Pipenv

It also sets up the following:

- firewall ([ufw](https://en.wikipedia.org/wiki/Uncomplicated_Firewall)) rules which only allow OpenSSH and Nginx ports
- a Systemd service for Gunicorn, and configures Nginx to be a proxy to Gunicorn.
- a "sshuser" Linux user (group "sshgroup") with `sudo` access and the same authorized keys than the _root_ user (which has your public key if you create the Droplet with that option - which is very likely)
- a "django" Linux user, belonging to the "www-data" group
- a "django_app" Postgres database, with a "django_app" Postgres user, both dedicated to our app

![screenshot](/.README/screenshot.png)

If no Django app is found in the "_/home/django/django-app/current_" folder, a blank one is created there: all you have to do is to `git clone` your own app somewhere on the server, and symlink it to that folder when it's ready.

Sure, I could have used real tools like Ansible (that's why I do at work to provision servers) rather than doing all this myself, but sometimes I like doing such quick-n-dirty scripts :-)

Like in Ansible, before doing anything, that script always tries to check that the operation has not been done already (i.e. it won't try to install a Debian or Python package if it's already installed, for example).

## Usage

On a newly created Ubuntu 18.04 server:

```bash
$ git clone https://github.com/DrBenton/django-app-server-setup.git
$ cd django-app-server-setup
$ scp ./setup.py root@[SERVER IP]:/root/django_setup.py
$ ssh root@[SERVER IP]
# (optional but recommended: update the server and reboot it)
root@droplet:~ apt update && apt upgrade && reboot
$ ssh root@[SERVER IP] # if you updated and rebooted the server
root@droplet:~ chmod +x django_setup.py
root@droplet:~ python3.6 django_setup.py
# Visit "http://[SERVER IP]", and you should see the Django "Welcome" page! :-)
```

## Customising the setup

Here are a few environment variables you can set prior to running this script, if you want to customise some things:

- `POSTGRES_DB` _(default: "django_app")_
- `POSTGRES_USER` _(default: "django_app")_
- `POSTGRES_PASSWORD` _(default: a new one will be generated, and displayed once during the setup)_
- `NGINX_SERVER_NAME` _(default: no `server_name` directive in the Nginx site config)_
- `LINUX_USER_DJANGO_USERNAME` _(default: "django")_ the Linux username for the django app (it will have a home directory and the Systemd service will belong to that user)
- `LINUX_USER_DJANGO_GROUPNAME` _(default: "www-data")_ the Linux groupname for that same Linux user
- `LINUX_USER_SSH_USERNAME` _(default: "sshuser")_ the Linux username for the SSH app (it will have a home directory and have access to `sudo`)
- `LINUX_USER_SSH_GROUPNAME` _(default: "sshgroup")_ the Linux groupname for that same Linux user

## Requirements

- Ubuntu 18.04
- Python 3.6 (already installed in Ubuntu 18.04)

That's all! :-)

## Code quality

The code itself is formatted with Black and checked with PyLint and MyPy.

```bash
$ make --no-print-directory check-code-quality
```

## Disclaimer

This is a quick-n-dirty provisioning script; it works for me, but use it at your own risk!

> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE AND NON-INFRINGEMENT. IN NO EVENT SHALL THE COPYRIGHT HOLDERS OR ANYONE DISTRIBUTING THE SOFTWARE BE LIABLE FOR ANY DAMAGES OR OTHER LIABILITY, WHETHER IN CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## How-to & troubleshooting

- Reload Gunicorn gracefully after a code update:
  ```bash
  $ GUNICORN_PID=$(systemctl show -p MainPID gunicorn 2>/dev/null | cut -d= -f2)
  $ sudo kill -HUP ${GUNICORN_PID}
  ```
- Connect to Postgres with the "django_app" user:
  ```bash
  $ psql django_app -h 127.0.0.1 -d django_app
  ```
- Change the password for the "django" Postgres user:
  ```bash
  $ sudo -u postgres psql -c "alter role django_app with password '${NEW_PASSWORD}'"
  ```
- Solve the "_DisallowedHost at /_" Django error:

  ```bash
  root@droplet:~ sed -i -r \
    "s~^ALLOWED_HOSTS = .+$~ALLOWED_HOSTS = ['$(hostname -I | cut -d ' ' -f 1)']~" \
    django-app/current/project/settings.py
  root@droplet:~ systemctl restart gunicorn # or graceful restart
  ```

## Testing

Because Docker is really not the right tool to test a provisioning script that deal with Systemd, this script has been tested with good ol'[Vagrant](https://www.vagrantup.com/).

```bash
$ cd django-app-server-setup
$ cd .vagrant
$ vagrant up
$ vagrant ssh
vagrant@ubuntu-bionic:~$ sudo python3.6 /server-setup/setup.py
```

## Kudos

I only automated the steps described there on this (yet another) brillant tutorial at Digital Ocean:

> https://www.digitalocean.com/community/tutorials/how-to-set-up-django-with-postgres-nginx-and-gunicorn-on-ubuntu-18-04
