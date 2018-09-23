# Django server quick setup

This is a all-in-one-with-no-dependencies Python script to provision a freshly created [Digital Ocean](https://www.digitalocean.com/) Droplet for Django.

It installs the following:

- Python 3.7 (and pip)
- Postgres 10 (server and client)
- Node.js 10 (can always be useful in order to handle front-end assets)
- Nginx
- Gunicorn
- pipenv

It also sets up the following:

- a Systemd service for Gunicorn, and configures Nginx to be a proxy to Gunicorn.
- a "django" Linux user, belonging to the "www-data" group
- a "django" Postgres user, dedicated to our app

If no Django app is found in the "_/home/django/django-app/current_" folder, a blank one is created there: all you have to do is to `git clone` your own app somewhere on the server, and symlink it to that folder when it's ready.

Sure, I could have used real tools like Ansible (that's why I do at work to provision servers) rather than doing all this myself, but sometimes I like doing such quick-n-dirty scripts :-)

Like in Ansible, before doing anything, that script always tries to check that the operation has not been done already (i.e. it won't try to install a Debian or Python package if it's already installed, for example).

## Usage

```bash
$ git clone https://github.com/DrBenton/django-app-server-setup.git
$ cd django-app-server-setup
$ scp ./setup.py root@[DROPLET IP]:/root/django_setup.py
$ ssh root@[DROPLET IP]
# (optional but recommended: update the server and reboot it)
root@droplet:~ apt update && apt upgrade && reboot
$ ssh root@[DROPLET IP] # if you updated and rebooted the server
root@droplet:~ chmod +x django_setup.py
root@droplet:~ python3.6 django_setup.py
# Visit "http://[DROPLET IP]", and you should see the Django "Welcome" page! :-)
```

## Requirements

- Ubuntu 18.04
- Python 3.6 (already installed in Ubuntu 18.04)

That's all! :-)

## Disclaimer

This is a quick-n-dirty provisioning script; it works for me, but use it at your own risk!

> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE AND NON-INFRINGEMENT. IN NO EVENT SHALL THE COPYRIGHT HOLDERS OR ANYONE DISTRIBUTING THE SOFTWARE BE LIABLE FOR ANY DAMAGES OR OTHER LIABILITY, WHETHER IN CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Troubleshooting

- "_DisallowedHost at /_" Django error:
  ```bash
  root@droplet:~ sed -i -r \
    "s~^ALLOWED_HOSTS = .+$~ALLOWED_HOSTS = ['$(hostname -I | cut -d ' ' -f 1)']~" \
    django-app/current/project/settings.py
  root@droplet:~ systemctl restart gunicorn
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
