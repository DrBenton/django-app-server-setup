#!python3.6

from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import sys
import typing as t

# Dynamic params, which can be set from env vars:
POSTGRES_DB = os.getenv("POSTGRES_DB", "django_app")
POSTGRES_USER = os.getenv("POSTGRES_USER", "django_app")
# (don't worry, we will generate a secure password on the fly if needed :-)
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
NGINX_SERVER_NAME = os.getenv("NGINX_SERVER_NAME", "")

TARGET_DISTRIBUTION = "Ubuntu 18.04"
TARGET_PYTHON_VERSION = "3.7"
TARGET_NODEJS_VERSION = "10.11.0"
TARGET_POSTGRES_VERSION = "10"
POSTGRES_PASSWORD_MIN_LENGTH = 10

LINUX_USER = "django"
LINUX_GROUP = "www-data"

DJANGO_APP_DIR = f"/home/{LINUX_USER}/django-app/current"
DJANGO_PROJECT_NAME = "project"

# @link https://www.digitalocean.com/community/tutorials/how-to-set-up-django-with-postgres-nginx-and-gunicorn-on-ubuntu-18-04

##################
# High level functions: those that we use to install specific software on the server
##################


def setup_server():
    flight_precheck()

    ensure_base_software()
    ensure_python()
    ensure_nodejs()
    ensure_postgres()
    ensure_nginx()

    ensure_linux_user_setup()

    ensure_postgres_django_setup()
    ensure_python_app_packages_setup()

    ensure_django_app()
    ensure_gunicorn_and_nginx_services_setup()


def flight_precheck():
    USAGE = "Usage: sudo python3.6 setup.py"
    if sys.version_info < (3, 6):
        _report(USAGE, "This script must be run with Python 3.6+", fatal=True)
        sys.exit(1)

    if not is_root():
        _report(USAGE, "This script must be run as 'root'", fatal=True)
        sys.exit(1)

    with _ensuring_step("Linux distribution"):
        distrib_ok = check_distrib()
        if not distrib_ok:
            _report(
                f"This script only works for {TARGET_DISTRIBUTION} ; type `cat /etc/lsb-release` to check yours.",
                fatal=True,
            )
            sys.exit(1)


##################
# "Ensure *" functions
##################


def ensure_base_software():
    with _ensuring_step("Curl"):
        install_debian_package_if_needed("curl")
        _check_cmd_output_or_die(["curl", "--version"], r"^curl \d\.\d+(?:.|\n)+https")
    with _ensuring_step("git"):
        install_debian_package_if_needed("git")
        _check_cmd_output_or_die(["git", "--version"], r"^git version 2\.")


def ensure_python():
    with _ensuring_step("Python"):
        install_ppa_if_needed("deadsnakes")
        install_debian_package_if_needed(f"python{TARGET_PYTHON_VERSION}")
        _check_cmd_output_or_die(
            [f"python{TARGET_PYTHON_VERSION}", "--version"],
            r"^Python " + re.escape(TARGET_PYTHON_VERSION),
        )

        pip_installed = _check_cmd_output(
            ["pip", "--version"], r"^pip .+python" + re.escape(TARGET_PYTHON_VERSION)
        )
        if not pip_installed:
            python_install_pip()
        _check_cmd_output_or_die(
            ["pip", "--version"], r"^pip .+python" + re.escape(TARGET_PYTHON_VERSION)
        )


def ensure_nodejs():
    with _ensuring_step("Node.js"):
        _report(
            f"Checking if Node.js 'v{TARGET_NODEJS_VERSION}' is already installed...",
            step_start=True,
        )
        installed = _check_cmd_output(
            ["node", "--version"], r"^v" + re.escape(TARGET_NODEJS_VERSION)
        )
        if installed:
            _report("Node.js target version already installed.", step_done=True)
            return

        _report("Node.js target version not installed.", step_done=True)
        nodejs_install()


def ensure_postgres():
    with _ensuring_step("Postgres"):
        install_debian_package_if_needed(f"postgresql-{TARGET_POSTGRES_VERSION}")
        install_debian_package_if_needed(f"postgresql-client-{TARGET_POSTGRES_VERSION}")
        _check_cmd_output_or_die(
            "systemctl show postgresql | grep ConsistsOf",
            "^ConsistsOf=postgresql@" + TARGET_POSTGRES_VERSION + r"-main\.service",
            shell=True,
        )
        _check_cmd_output_or_die(
            ["psql", "--version"],
            r"^psql \(PostgreSQL\) " + re.escape(TARGET_POSTGRES_VERSION),
        )


def ensure_nginx():
    with _ensuring_step("Nginx"):
        install_debian_package_if_needed("nginx")
        _check_cmd_output_or_die(
            "systemctl show nginx | grep ExecStart", r".+/usr/sbin/nginx", shell=True
        )


def ensure_postgres_django_setup():
    with _ensuring_step("Posgres config for the Django app"):
        postgres_django_setup_ensure_db(POSTGRES_DB)
        postgres_django_setup_ensure_user(POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)


def ensure_python_app_packages_setup():
    with _ensuring_step("Python packages for our app"):
        install_python_package_if_needed("gunicorn")
        install_python_package_if_needed("psycopg2-binary")
        install_python_package_if_needed("pipenv")


def ensure_linux_user_setup():
    with _ensuring_step("Linux user"):
        if not has_linux_user(LINUX_USER):
            create_linux_user(LINUX_USER, LINUX_GROUP)


def ensure_django_app():
    with _ensuring_step("Django app"):
        create_blank_django_app_if_needed(DJANGO_APP_DIR, DJANGO_PROJECT_NAME)


def ensure_gunicorn_and_nginx_services_setup():
    with _ensuring_step("Gunicorn & Nginx services"):
        create_file_if_needed(
            "/etc/systemd/system/gunicorn.socket", _GUNICORN_SOCKET_FILE
        )
        create_file_if_needed(
            "/etc/systemd/system/gunicorn.service", _GUNICORN_SERVICE_FILE
        )
        create_file_if_needed(
            f"{_NGINX_AVAILABLE_SITES_PATH}/{_NGINX_SITE_NAME}", _NGINX_SITE_FILE
        )
        gunicorn_and_nginx_services_activate_nginx_site_if_needed(
            available_sites_path=_NGINX_AVAILABLE_SITES_PATH,
            enabled_sites_path=_NGINX_ENABLED_SITES_PATH,
            site_name=_NGINX_SITE_NAME,
            site_config=_NGINX_SITE_FILE,
        )
        _enable_and_start_service("gunicorn")
        _enable_and_start_service("nginx")


##################
# Misc general tasks
##################


def is_debian_package_installed(name: str) -> bool:
    _report(
        f"Checking if the Debian package '{name}' is already installed...",
        step_start=True,
    )
    cmd = ["dpkg", "-s", name]
    try:
        process_result = _run(cmd)
        installed = process_result.stdout.find("Status: install ok installed") > -1
    except SubProcessError:
        installed = False
    if installed:
        _report("Debian package already installed.", step_done=True)
    else:
        _report("Debian package not installed.", step_done=True)
    return installed


def is_ppa_installed(name: str) -> bool:
    _report(f"Checking PPA '{name}'...", step_start=True)
    cmd = f"grep -r 'deb http://ppa.launchpad.net/{name}/ppa/ubuntu' /etc/apt/ || true"
    process_result = _run(cmd, shell=True)
    installed = bool(process_result.stdout)
    if installed:
        _report("PPA already installed.", step_done=True)
    else:
        _report("PPA not installed.", step_done=True)
    return installed


def install_ppa(name: str) -> None:
    _report(f"Adding PPA '{name}'...", step_start=True)
    cmd = ["add-apt-repository", "-y", f"ppa:{name}/ppa"]
    _run(cmd, stdout=None)
    apt_update()
    _report("PPA added.", step_done=True)


def is_root() -> bool:
    return os.geteuid() == 0


def check_distrib() -> bool:
    cmd = "cat /etc/lsb-release | grep DESCRIPTION"
    process_result = _run(cmd, shell=True)
    return process_result.stdout.find(TARGET_DISTRIBUTION) > -1


def install_ppa_if_needed(name: str) -> bool:
    installed = is_ppa_installed(name)
    if installed:
        return False
    install_ppa(name)
    return True


def install_debian_package_if_needed(name: str) -> bool:
    installed = is_debian_package_installed(name)
    if installed:
        return False
    apt_install(name)
    return True


def apt_update() -> None:
    _report("Updating APT repositories...", step_start=True)
    cmd = ["apt", "update"]
    _run(cmd)
    _report("Updated.", step_done=True)


def apt_install(name: str) -> None:
    _report(f"Installing Debian package '{name}'...", step_start=True)
    cmd = ["apt", "install", "-y", name]
    _run(cmd)
    _report("Installed.", step_done=True)


def is_python_package_installed(name: str) -> bool:
    _report(f"Checking Python package '{name}'...", step_start=True)
    cmd = f"pip list | grep '{name} '"
    process_result = _run(cmd, die_on_error=False, shell=True)
    installed = process_result.success and process_result.stdout.startswith(name)
    if installed:
        _report("Python package already installed.", step_done=True)
    else:
        _report("Python package not installed.", step_done=True)
    return installed


def install_python_package_if_needed(name: str) -> bool:
    installed = is_python_package_installed(name)
    if installed:
        return False
    install_python_package(name)
    return True


def install_python_package(name: str) -> None:
    _report(f"Installing Python package '{name}'...", step_start=True)
    cmd = ["pip", "install", name]
    _run(cmd)
    _report("Installed.", step_done=True)


def has_linux_user(user: str) -> bool:
    _report(f"Checking if user '{user}' exists...", step_start=True)
    cmd = f"grep '^{user}:' /etc/passwd"
    process_result = _run(cmd, shell=True, die_on_error=False)
    user_exists = process_result.success and process_result.stdout.startswith(user)
    _report(
        f"Checked ({'exists' if user_exists else 'does not exist'}).", step_done=True
    )
    return user_exists


def create_linux_user(user: str, group: str, shell: str = "/bin/bash") -> None:
    _report(
        f"Creating Linux user '{user}:{group}', with shell '{shell}'...",
        step_start=True,
    )
    cmd = ["useradd", "-m", "-s", shell, "-g", group, user]
    _run(cmd)
    _report("Created.", step_done=True)


def check_file_content(path: str, expected_content: str) -> bool:
    try:
        with open(path, mode="r") as f:
            return expected_content == f.read()
    except FileNotFoundError:
        return False


def create_file_if_needed(path: str, content: str) -> None:
    _report(
        f"Checking if the file '{path}' already exists and have the expected content...",
        step_start=True,
    )
    file_is_ok = check_file_content(path, content)
    if not file_is_ok:
        _report("Ok, we have to (re?)create it.", step_done=True)
        create_file(path, content)
    else:
        _report("No need to create it.", step_done=True)


def create_file(path: str, content: str) -> None:
    _report(f"Creating file '{path}'...", step_start=True)
    with open(path, mode="w") as f:
        f.write(content)
    _report(f"File created.", step_done=True)


def nginx_enable_site(site_name: str) -> bool:
    nginx_site_source_path = f"{_NGINX_AVAILABLE_SITES_PATH}/{site_name}"
    nginx_site_target_path = f"{_NGINX_ENABLED_SITES_PATH}/{site_name}"
    if (
        Path(nginx_site_target_path).resolve() == nginx_site_source_path
        and Path(nginx_site_source_path).is_file()
    ):
        return False
    _report(f"Enabling Nginx site '{site_name}'...", step_start=True)
    cmd = ["ln", "-s", "-f", nginx_site_source_path, nginx_site_target_path]
    _run(cmd)
    _report("Nginx site enabled..", step_done=True)
    return True


def nginx_disable_site_if_needed(site_name: str) -> bool:
    nginx_site_path = f"{_NGINX_ENABLED_SITES_PATH}/{site_name}"
    if not Path(nginx_site_path).is_symlink():
        return False
    _report(f"Disabling Nginx site '{site_name}'...", step_start=True)
    cmd = ["rm", nginx_site_path]
    _run(cmd)
    _report("Nginx site disabled..", step_done=True)
    return True


def nginx_check_config() -> bool:
    _report("Checking Nginx config...", step_start=True)
    check_cmd = ["nginx", "-t"]
    process_result = _run(check_cmd, die_on_error=False)
    config_ok = process_result.success
    _report(
        f"Nginx config checked ({'ok' if config_ok else 'broken'}).", step_done=True
    )
    return config_ok


def nginx_check_config_or_die() -> None:
    config_ok = nginx_check_config()
    if not config_ok:
        _report("Nginx config is broken!. Type `nginx -t` to investigate.", fatal=True)
        sys.exit(1)


##################
# Step-specific functions
##################


def python_install_pip() -> None:
    _report(f"Installing pip...", step_start=True)
    dl_cmd = "curl -L -sS 'https://bootstrap.pypa.io/get-pip.py' -o get-pip.py"
    _run(dl_cmd, shell=True)
    install_cmd = f"python{TARGET_PYTHON_VERSION} get-pip.py"
    _run(install_cmd, shell=True)
    _report(f"pip installed.", step_done=True)


def nodejs_install() -> None:
    _report(f"Installing Node.js...", step_start=True)
    cmd = f"curl 'https://nodejs.org/dist/v{TARGET_NODEJS_VERSION}/node-v{TARGET_NODEJS_VERSION}-linux-x64.tar.xz' | sudo tar --file=- --extract --xz --directory /usr/local/ --strip-components=1"
    _run(cmd, shell=True)
    _check_cmd_output_or_die(
        ["node", "--version"], r"^v" + re.escape(TARGET_NODEJS_VERSION)
    )
    _report(f"Node.js installed.", step_done=True)


def postgres_django_setup_ensure_db(db_name: str) -> None:
    def db_exists() -> bool:
        check_db_sql = (
            f"""select datname from pg_database where datname = '{db_name}';"""
        )
        result = _run_sql(check_db_sql)
        return result.find(db_name) > -1

    _report(f"Checking if database '{db_name}' already exists...", step_start=True)
    if not db_exists():
        postgres_django_setup_create_db(db_name=db_name)
        if not db_exists():
            _report("Could not create database", fatal=True)
            sys.exit(1)

    _report(f"Database ok.", step_done=True)


def postgres_django_setup_ensure_user(user: str, password: str, db_name: str) -> None:
    def user_exists() -> bool:
        check_user_sql = f"""\du {user};"""
        result = _run_sql(check_user_sql)
        return result.find(user) > -1

    _report(f"Checking if user '{user}' already exists...", step_start=True)
    if not user_exists():
        postgres_django_setup_create_user(user=user, password=password, db_name=db_name)
        if not user_exists():
            _report("Could not create user", fatal=True)
            sys.exit(1)

    _report(f"User ok.", step_done=True)


def postgres_django_setup_create_db(db_name: str) -> None:
    _report(f"Creating database '{db_name}'...", step_start=True)
    create_db_sql = f"""create database {db_name};"""
    _run_sql(create_db_sql)
    _report(f"Database created.", step_done=True)


def postgres_django_setup_create_user(user: str, password: str, db_name: str) -> None:
    if not password:
        import secrets

        password = secrets.token_urlsafe(16)

    if len(password) < POSTGRES_PASSWORD_MIN_LENGTH:
        print(
            f"Postgres user password is too short (minimum length: {POSTGRES_PASSWORD_MIN_LENGTH}) 💀"
        )
        sys.exit(1)

    _report(
        f"Creating user '{user}' with password '{password}' with all privileges on database '{db_name}'...",
        step_start=True,
    )
    create_user_sql = f"""\
begin;
create user {user} with password '{password}';
alter role {user} set client_encoding to 'utf8';
alter role {user} set default_transaction_isolation to 'read committed';
alter role {user} set timezone to 'UTC';
grant all privileges on database {db_name} to {user};
commit;
"""
    _run_sql(create_user_sql)
    _report(f"User created.", step_done=True)


def gunicorn_and_nginx_services_activate_nginx_site_if_needed(
    available_sites_path: str, enabled_sites_path: str, site_name: str, site_config: str
) -> None:
    nginx_disable_site_if_needed("default")

    nginx_site_target_file = f"{enabled_sites_path}/{site_name}"
    _report(
        f"Checking nginx enabled symlink '{nginx_site_target_file}'...", step_start=True
    )
    nginx_site_target_ok = check_file_content(nginx_site_target_file, site_config)
    if nginx_site_target_ok:
        _report(f"Nginx site already enabled.", step_done=True)
    else:
        nginx_enable_site(site_name)
        nginx_check_config_or_die()
        _report(f"Nginx site enabled.", step_done=True)


def create_blank_django_app_if_needed(app_dir: str, app_project_name: str) -> None:
    _report(
        f"Checking if we have a Django app in the '{app_dir}' folder (project '{app_project_name}')...",
        step_start=True,
    )
    django_settings_file_path = f"{app_dir}/{app_project_name}/wsgi.py"
    if Path(app_dir).is_dir() and Path(django_settings_file_path).is_file():
        _report("Django app found.", step_done=True)
        return
    _report(
        "Django app not found! Let's create a blank one for the moment.", step_wip=True
    )
    create_blank_django_app(app_dir, app_project_name)
    _report("Blank Django app created.", step_done=True)


def create_blank_django_app(app_dir: str, app_project_name: str) -> None:
    _report(
        f"Creating a blank Django project '{app_project_name}' in {app_dir}...",
        step_start=True,
    )

    install_python_package_if_needed("django")

    os.makedirs(app_dir, exist_ok=True)
    create_project_cmd = [
        f"python{TARGET_PYTHON_VERSION}",
        "/usr/local/bin/django-admin",
        "startproject",
        app_project_name,
        app_dir,
    ]
    _run(create_project_cmd)

    _report(f"Blank Django project created.", step_done=True)


##################
# Low level functions
##################


class RunResult(t.NamedTuple):
    success: bool
    stdout: t.Optional[str] = None
    stderr: t.Optional[str] = None
    error: t.Optional[BaseException] = None


class SubProcessError(RuntimeError):
    def __init__(self, cmd: list, process_result: RunResult):
        self.cmd = cmd
        self.process_result = process_result

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.cmd!r}, '${self.process_result}')"


def _run(
    cmd: list, die_on_error: bool = True, capture_output=True, **kwargs
) -> RunResult:
    # no "capture_output" param in Python < 3.7, so we have to deal with "stdout" & "stderr" manually :-/
    if capture_output == True and kwargs.get("stdout") is None:
        kwargs["stdout"] = subprocess.PIPE
    if capture_output == True and kwargs.get("stderr") is None:
        kwargs["stderr"] = subprocess.PIPE

    try:
        process_result = subprocess.run(cmd, **kwargs)
        success = process_result.returncode == 0

        stdout = (
            process_result.stdout.decode("utf-8") if process_result.stdout else None
        )
        stderr = (
            process_result.stderr.decode("utf-8") if process_result.stderr else None
        )
        result = RunResult(success=success, stdout=stdout, stderr=stderr)
    except FileNotFoundError as e:
        result = RunResult(success=False, error=e)
    if die_on_error and not result.success:
        raise SubProcessError(cmd, process_result)
    return result


def _run_sql(sql: str) -> str:
    cmd = ["sudo", "-u", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-c", sql]
    process_result = _run(cmd)
    # print(process_result.stdout)
    return process_result.stdout


def _check_cmd_output_or_die(cmd: list, pattern: str, shell: bool = False) -> None:
    output_ok = _check_cmd_output(cmd, pattern, shell=shell)
    if not output_ok:
        _report(f"Command '{cmd}' output does not match '{pattern}'", fatal=True)
        sys.exit(1)


def _check_cmd_output(cmd: list, pattern: str, shell: bool = False) -> bool:
    process_result = _run(cmd, die_on_error=False, shell=shell)
    if not process_result.success:
        print("process_result.stderr=", process_result.stderr)
        return False
    match: bool = re.match(pattern, process_result.stdout, flags=re.M) != None
    if not match:
        print("process_result.stdout=", process_result.stdout)
    return match


def _enable_and_start_service(service_name: str) -> None:
    _report(
        f"Enabling and starting Systemd service '{service_name}'...", step_start=True
    )

    _report(f"Reloading Systemd...", step_start=True)
    systemd_reload_cmd = ["systemctl", "daemon-reload"]
    _run(systemd_reload_cmd)
    _report(f"Systemd reloaded.", step_done=True)

    _report(f"Restarting Systemd service...", step_start=True)
    cmd = ["systemctl", "restart", service_name]
    _run(cmd)
    _report("Service restarted.", step_done=True)

    _report(f"Enabling Systemd service...", step_start=True)
    cmd = ["systemctl", "enable", service_name]
    _run(cmd)
    _report("Service enabled.", step_done=True)

    _check_service_is_active_or_die(service_name)

    _report(f"Systemd service '{service_name}' enabled and started.", step_done=True)


def _check_service_is_active(service_name: str) -> bool:
    _report(
        f"Checking if Systemd service '{service_name}' is well and truly active...",
        step_start=True,
    )
    cmd = ["systemctl", "status", service_name]
    process_result = _run(cmd, die_on_error=False)
    is_active = (
        process_result.success and process_result.stdout.find("active (running)") > -1
    )
    _report(
        f"Checking done ({'active' if is_active else 'not active'}).", step_done=True
    )
    return is_active


def _check_service_is_active_or_die(service_name: str) -> None:
    is_active = _check_service_is_active(service_name)
    if not is_active:
        _report(f"Service '{service_name}' is not active.", fatal=True)
        sys.exit(1)


def _report(
    *args,
    step_start: bool = False,
    step_wip: bool = False,
    step_done: bool = False,
    fatal: bool = False,
):
    if fatal:
        prefix = " 💀 "
    else:
        prefix = "."
        if step_start:
            prefix = "┌"
        elif step_wip:
            prefix = "│"
        elif step_done:
            prefix = "└"
            _report._report_nb_levels -= 1
        prefix = " " + ("  " * _report._report_nb_levels) + prefix

    print(prefix, *args)

    if step_start and not fatal:
        _report._report_nb_levels += 1


_report._report_nb_levels = 0


@contextmanager
def _ensuring_step(step_name: str) -> None:
    _report(f"Ensuring {step_name} is properly installed...", step_start=True)
    yield
    _report(f"{step_name} setup ok. 👍\n", step_done=True)


_GUNICORN_SOCKET_FILE = """\
# /etc/systemd/system/gunicorn.socket

[Unit]
Description=gunicorn socket

[Socket]
ListenStream=/run/gunicorn.sock

[Install]
WantedBy=sockets.target

"""

_GUNICORN_SERVICE_FILE = f"""\
# /etc/systemd/system/gunicorn.service

[Unit]
Description=gunicorn daemon
Requires=gunicorn.socket
After=network.target

[Service]
User={LINUX_USER}
Group={LINUX_GROUP}
WorkingDirectory={DJANGO_APP_DIR}
ExecStart=/usr/bin/python{TARGET_PYTHON_VERSION} /usr/local/bin/gunicorn \\
          --access-logfile - \\
          --workers 3 \\
          --bind unix:/run/gunicorn.sock \\
          {DJANGO_PROJECT_NAME}.wsgi:application

[Install]
WantedBy=multi-user.target
"""


_NGINX_AVAILABLE_SITES_PATH = "/etc/nginx/sites-available"
_NGINX_ENABLED_SITES_PATH = "/etc/nginx/sites-enabled"
_NGINX_SITE_NAME = "django-app"
_NGINX_SITE_FILE = f"""\
# {_NGINX_AVAILABLE_SITES_PATH}/{_NGINX_SITE_NAME}

server {{
    {('server_name ' + NGINX_SERVER_NAME + ';') if NGINX_SERVER_NAME else ''}
    listen 80;

    location = /favicon.ico {{ access_log off; log_not_found off; }}
    location /static/ {{
        root {DJANGO_APP_DIR};
    }}

    location / {{
        include proxy_params;
        proxy_pass http://unix:/run/gunicorn.sock;
    }}
}}

"""

if __name__ == "__main__":
    setup_server()
