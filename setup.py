#!/usr/bin/python3.6

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


def setup_server() -> None:
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


def flight_precheck() -> None:
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


def ensure_base_software() -> None:
    with _ensuring_step("Curl"):
        install_debian_package_if_needed("curl")
        _check_cmd_output_or_die(["curl", "--version"], r"^curl \d\.\d+(?:.|\n)+https")
    with _ensuring_step("git"):
        install_debian_package_if_needed("git")
        _check_cmd_output_or_die(["git", "--version"], r"^git version 2\.")


def ensure_python() -> None:
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


def ensure_nodejs() -> None:
    with _ensuring_step("Node.js"):
        with _step(
            f"Checking Node.js 'v{TARGET_NODEJS_VERSION}' status..."
        ) as nodejs_step:
            installed = _check_cmd_output(
                ["node", "--version"], r"^v" + re.escape(TARGET_NODEJS_VERSION)
            )
            if installed:
                nodejs_step.nothing_to_do("Node.js target version already installed.")
            else:
                nodejs_step.done("Node.js target version not installed.")
                nodejs_install()

        with _step("Checking Yarn status...") as yarn_step:
            installed = _check_cmd_output(["yarn", "--version"], r"^\d\.\d")
            if installed:
                yarn_step.nothing_to_do("Yarn already installed.")
            else:
                yarn_step.done("Yarn not installed.")
                nodejs_install_yarn()


def ensure_postgres() -> None:
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


def ensure_nginx() -> None:
    with _ensuring_step("Nginx"):
        install_debian_package_if_needed("nginx")
        _check_cmd_output_or_die(
            "systemctl show nginx | grep ExecStart", r".+/usr/sbin/nginx", shell=True
        )


def ensure_postgres_django_setup() -> None:
    with _ensuring_step("Posgres config for the Django app"):
        postgres_django_setup_ensure_db(POSTGRES_DB)
        postgres_django_setup_ensure_user(POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)


def ensure_python_app_packages_setup() -> None:
    with _ensuring_step("Python packages for our app"):
        install_python_package_if_needed("gunicorn")
        install_python_package_if_needed("psycopg2-binary")
        install_python_package_if_needed("pipenv")


def ensure_linux_user_setup() -> None:
    with _ensuring_step("Linux user"):
        if not has_linux_user(LINUX_USER):
            create_linux_user(LINUX_USER, LINUX_GROUP)


def ensure_django_app() -> None:
    with _ensuring_step("Django app"):
        create_blank_django_app_if_needed(DJANGO_APP_DIR, DJANGO_PROJECT_NAME)


def ensure_gunicorn_and_nginx_services_setup() -> None:
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
        systemd_enable_and_start_service("gunicorn")
        systemd_enable_and_start_service("nginx")


##################
# Misc general tasks
##################


def is_debian_package_installed(name: str) -> bool:
    with _step(
        f"Checking if the Debian package '{name}' is already installed..."
    ) as step:
        cmd = ["dpkg", "-s", name]
        try:
            process_result = _run(cmd)
            installed = process_result.stdout_has_content(
                "Status: install ok installed"
            )
        except SubProcessError:
            installed = False
        if installed:
            step.nothing_to_do("Debian package already installed.")
        else:
            step.done("Debian package not installed.")
        return installed


def is_ppa_installed(name: str) -> bool:
    with _step(f"Checking PPA '{name}'...") as step:
        cmd = f"grep -r 'deb http://ppa.launchpad.net/{name}/ppa/ubuntu' /etc/apt/ || true"
        process_result = _run(cmd, shell=True)
        installed = bool(process_result.stdout)
        if installed:
            step.nothing_to_do("PPA already installed.")
        else:
            step.done("PPA not installed.")
        return installed


def install_ppa(name: str) -> None:
    with _step(f"Adding PPA '{name}'...") as step:
        cmd = ["add-apt-repository", "-y", f"ppa:{name}/ppa"]
        _run(cmd, stdout=None)
        apt_update()
        step.done("PPA added.")


def is_root() -> bool:
    return os.geteuid() == 0


def check_distrib() -> bool:
    cmd = "cat /etc/lsb-release | grep DESCRIPTION"
    process_result = _run(cmd, shell=True)
    return process_result.stdout_has_content(TARGET_DISTRIBUTION)


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
    with _step("Updating APT repositories...") as step:
        cmd = ["apt", "update"]
        _run(cmd)
        step.done("Updated.")


def apt_install(name: str) -> None:
    with _step(f"Installing Debian package '{name}'...") as step:
        cmd = ["apt", "install", "-y", name]
        _run(cmd)
        step.done("Installed.")


def is_python_package_installed(name: str) -> bool:
    with _step(f"Checking Python package '{name}'...") as step:
        cmd = f"pip list | grep '{name} '"
        process_result = _run(cmd, die_on_error=False, shell=True)
        installed = process_result.success and process_result.stdout_starts_with(name)
        if installed:
            step.nothing_to_do("Python package already installed.")
        else:
            step.done("Python package not installed.")
        return installed


def install_python_package_if_needed(name: str) -> bool:
    installed = is_python_package_installed(name)
    if installed:
        return False
    install_python_package(name)
    return True


def install_python_package(name: str) -> None:
    with _step(f"Installing Python package '{name}'...") as step:
        cmd = ["pip", "install", name]
        _run(cmd)
        step.done("Installed.")


def has_linux_user(user: str) -> bool:
    with _step(f"Checking user '{user}' status...") as step:
        cmd = f"grep '^{user}:' /etc/passwd"
        process_result = _run(cmd, shell=True, die_on_error=False)
        user_exists = process_result.success and process_result.stdout_starts_with(user)
        if user_exists:
            step.nothing_to_do("User checked (already exists).")
        else:
            step.done("User checked (doesn't exist').")
        return user_exists


def create_linux_user(user: str, group: str, shell: str = "/bin/bash") -> None:
    with _step(
        f"Creating Linux user '{user}:{group}', with shell '{shell}'..."
    ) as step:
        cmd = ["useradd", "-m", "-s", shell, "-g", group, user]
        _run(cmd)
        step.done("Created.")


def check_file_content(path: str, expected_content: str) -> bool:
    try:
        with open(path, mode="r") as f:
            return expected_content == f.read()
    except FileNotFoundError:
        return False


def create_file_if_needed(path: str, content: str) -> None:
    with _step(
        f"Checking if the file '{path}' already exists and have the expected content..."
    ) as step:
        file_is_ok = check_file_content(path, content)
        if file_is_ok:
            step.nothing_to_do("No need to create it.")
        else:
            step.done("Ok, we have to (re?)create it.")
            create_file(path, content)


def create_file(path: str, content: str) -> None:
    with _step(f"Creating file '{path}'...") as step:
        with open(path, mode="w") as f:
            f.write(content)
        step.done(f"File created.")


def nginx_enable_site(site_name: str) -> bool:
    nginx_site_source_path = f"{_NGINX_AVAILABLE_SITES_PATH}/{site_name}"
    nginx_site_target_path = f"{_NGINX_ENABLED_SITES_PATH}/{site_name}"
    if (
        Path(nginx_site_target_path).resolve() == nginx_site_source_path
        and Path(nginx_site_source_path).is_file()
    ):
        return False

    with _step(f"Enabling Nginx site '{site_name}'...") as step:
        cmd = ["ln", "-s", "-f", nginx_site_source_path, nginx_site_target_path]
        _run(cmd)
        step.done("Nginx site enabled.")
        return True


def nginx_disable_site_if_needed(site_name: str) -> bool:
    nginx_site_path = f"{_NGINX_ENABLED_SITES_PATH}/{site_name}"
    if not Path(nginx_site_path).is_symlink():
        return False

    with _step(f"Disabling Nginx site '{site_name}'...") as step:
        cmd = ["rm", nginx_site_path]
        _run(cmd)
        step.done("Nginx site disabled.")
        return True


def nginx_check_config() -> bool:
    with _step("Checking Nginx config...") as step:
        check_cmd = ["nginx", "-t"]
        process_result = _run(check_cmd, die_on_error=False)
        config_ok = process_result.success
        step.done(f"Nginx config checked ({'ok' if config_ok else 'broken'}).")
        return config_ok


def nginx_check_config_or_die() -> None:
    config_ok = nginx_check_config()
    if not config_ok:
        _report("Nginx config is broken!. Type `nginx -t` to investigate.", fatal=True)
        sys.exit(1)


def systemd_enable_and_start_service(service_name: str) -> None:
    with _step(f"Enabling and starting Systemd service '{service_name}'...") as step:

        with _step("Reloading Systemd...") as reloading_systemd_step:
            systemd_reload_cmd = ["systemctl", "daemon-reload"]
            _run(systemd_reload_cmd)
            reloading_systemd_step.done("Systemd reloaded.")

        with _step("Restarting Systemd service...") as restarting_service_step:
            cmd = ["systemctl", "restart", service_name]
            _run(cmd)
            restarting_service_step.done("Service restarted.")

        with _step("Enabling Systemd service...") as enabling_service_step:
            cmd = ["systemctl", "enable", service_name]
            _run(cmd)
            enabling_service_step.done("Service enabled.")

        systemd_check_service_is_active_or_die(service_name)

        step.done(f"Systemd service '{service_name}' enabled and started.")


def systemd_check_service_is_active(service_name: str) -> bool:
    with _step(
        f"Checking if Systemd service '{service_name}' is well and truly active..."
    ) as step:
        cmd = ["systemctl", "status", service_name]
        process_result = _run(cmd, die_on_error=False)
        is_active = process_result.success and process_result.stdout_has_content(
            "active (running)"
        )
        step.done(f"Checking done ({'active' if is_active else 'not active'}).")
        return is_active


def systemd_check_service_is_active_or_die(service_name: str) -> None:
    is_active = systemd_check_service_is_active(service_name)
    if not is_active:
        _report(f"Service '{service_name}' is not active.", fatal=True)
        sys.exit(1)


##################
# Step-specific functions
##################


def python_install_pip() -> None:
    with _step("Installing pip...") as step:
        dl_cmd = "curl -L -sS 'https://bootstrap.pypa.io/get-pip.py' -o get-pip.py"
        _run(dl_cmd, shell=True)
        install_cmd = f"python{TARGET_PYTHON_VERSION} get-pip.py"
        _run(install_cmd, shell=True)
        step.done("pip installed.")


def nodejs_install() -> None:
    with _step("Installing Node.js...") as step:
        cmd = f"""\
curl 'https://nodejs.org/dist/v{TARGET_NODEJS_VERSION}/node-v{TARGET_NODEJS_VERSION}-linux-x64.tar.xz' \
| sudo tar --file=- --extract --xz --directory /usr/local/ --strip-components=1 \
"""
        _run(cmd, shell=True)
        _check_cmd_output_or_die(
            ["node", "--version"], r"^v" + re.escape(TARGET_NODEJS_VERSION)
        )
        step.done(f"Node.js installed.")


def nodejs_install_yarn() -> None:
    with _step("Installing Yarn...") as step:
        # @link https://yarnpkg.com/en/docs/install#debian-stable
        cmd = """\
curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add - && \
echo "deb https://dl.yarnpkg.com/debian/ stable main" | tee /etc/apt/sources.list.d/yarn.list && \
apt-get update && \
apt install --no-install-recommends yarn
"""
        _run(cmd, shell=True)
        _check_cmd_output_or_die(["yarn", "--version"], r"^\d\.\d")
        step.done("Yarn installed.")


def postgres_django_setup_ensure_db(db_name: str) -> bool:
    def db_exists() -> bool:
        check_db_sql = (
            f"""select datname from pg_database where datname = '{db_name}';"""
        )
        result = _run_sql(check_db_sql)
        return result is str and result.find(db_name) > -1  # type: ignore

    with _step(f"Checking database '{db_name}' status...") as step:
        if db_exists():
            step.nothing_to_do("Database exists.")
            return False
        else:
            postgres_django_setup_create_db(db_name=db_name)
            if not db_exists():
                _report("Could not create database", fatal=True)
                sys.exit(1)
            step.done("Database created.")
            return True


def postgres_django_setup_ensure_user(user: str, password: str, db_name: str) -> bool:
    def user_exists() -> bool:
        check_user_sql = f"""\\du {user};"""
        result = _run_sql(check_user_sql)
        return result is str and result.find(user) > -1  # type: ignore

    with _step(f"Checking database user '{user}' status...") as step:
        if user_exists():
            step.nothing_to_do("Database user exists.")
            return False
        else:
            postgres_django_setup_create_user(
                user=user, password=password, db_name=db_name
            )
            if not user_exists():
                _report("Could not create user", fatal=True)
                sys.exit(1)
            step.done("User ok.")
            return True


def postgres_django_setup_create_db(db_name: str) -> None:
    with _step(f"Creating database '{db_name}'...") as step:
        create_db_sql = f"""create database {db_name};"""
        _run_sql(create_db_sql)
        step.done(f"Database created.")


def postgres_django_setup_create_user(user: str, password: str, db_name: str) -> None:
    if not password:
        import secrets

        password = secrets.token_urlsafe(16)

    if len(password) < POSTGRES_PASSWORD_MIN_LENGTH:
        _report(
            f"Postgres user password is too short (minimum length: {POSTGRES_PASSWORD_MIN_LENGTH})",
            fatal=True,
        )
        sys.exit(1)

    with _step(
        f"Creating user '{user}' with password '{password}' with all privileges on database '{db_name}'..."
    ) as step:
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
        step.done("User created.")


def gunicorn_and_nginx_services_activate_nginx_site_if_needed(
    available_sites_path: str, enabled_sites_path: str, site_name: str, site_config: str
) -> None:
    nginx_disable_site_if_needed("default")

    nginx_site_target_file = f"{enabled_sites_path}/{site_name}"
    with _step(f"Checking nginx enabled symlink '{nginx_site_target_file}'...") as step:
        nginx_site_target_ok = check_file_content(nginx_site_target_file, site_config)
        if nginx_site_target_ok:
            step.nothing_to_do("Nginx site already enabled.")
        else:
            nginx_enable_site(site_name)
            nginx_check_config_or_die()
            step.done("Nginx site enabled.")


def create_blank_django_app_if_needed(app_dir: str, app_project_name: str) -> bool:
    with _step(
        f"Checking if we have a Django app in the '{app_dir}' folder (project '{app_project_name}')..."
    ) as step:
        django_settings_file_path = f"{app_dir}/{app_project_name}/wsgi.py"
        if Path(app_dir).is_dir() and Path(django_settings_file_path).is_file():
            step.nothing_to_do("Django app found.")
            return False
        step.wip("Django app not found! Let's create a blank one for the moment.")
        create_blank_django_app(app_dir, app_project_name)
        step.done("Blank Django app created.")
        return True


def create_blank_django_app(app_dir: str, app_project_name: str) -> None:
    with _step(
        f"Creating a blank Django project '{app_project_name}' in {app_dir}..."
    ) as step:

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

        chown_cmd = ["chown", "-R", f"{LINUX_USER}:{LINUX_GROUP}", app_dir]
        _run(chown_cmd)

        with _step(
            "Adding the server IP address to Django's ALLOWED_HOSTS..."
        ) as django_hosts_step:
            update_django_allowed_hosts_cmd = f"""\
sed -i -r \
"s~^ALLOWED_HOSTS = .+$~ALLOWED_HOSTS = ['$(hostname -I | cut -d ' ' -f 1)']~" \
{app_dir}/{app_project_name}/settings.py    
"""
            _run(update_django_allowed_hosts_cmd, shell=True)
            django_hosts_step.done("Django ALLOWED_HOSTS updated.")

        step.done("Blank Django project created.")
        _report(r"/!\ Beware! This app is in DEBUG mode at the moment.")


##################
# Low level functions
##################


class RunResult(t.NamedTuple):
    success: bool
    stdout: t.Optional[str] = None
    stderr: t.Optional[str] = None
    error: t.Optional[BaseException] = None

    def has_non_blank_stdout(self) -> bool:
        return self.stdout is not None and len(self.stdout) > 0

    def stdout_has_content(self, search: str) -> bool:
        return self.stdout is not None and self.stdout.find(search) > -1

    def stdout_starts_with(self, search: str) -> bool:
        return self.stdout is not None and self.stdout.startswith(search)

    def stdout_matches(self, pattern: str) -> bool:
        return (
            self.stdout is not None
            and re.match(pattern, self.stdout, flags=re.M) is not None
        )


class SubProcessError(RuntimeError):
    def __init__(self, cmd: Cmd, process_result: RunResult) -> None:
        self.cmd = cmd
        self.process_result = process_result

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.cmd!r}, '${self.process_result!r}')"


Cmd = t.Union[list, str]


def _run(
    cmd: Cmd, die_on_error: bool = True, capture_output=True, **kwargs
) -> RunResult:
    # pylint: disable=E1120
    # (@link https://github.com/PyCQA/pylint/issues/1898)

    # No "capture_output" param in Python < 3.7, so we have to deal with "stdout" & "stderr" manually :-/
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

        if die_on_error and not result.success:
            raise SubProcessError(cmd, result)

    except FileNotFoundError as e:
        result = RunResult(success=False, error=e)

    return result


def _run_sql(sql: str) -> t.Optional[str]:
    cmd = ["sudo", "-u", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-c", sql]
    process_result = _run(cmd)
    return process_result.stdout


def _check_cmd_output_or_die(cmd: Cmd, pattern: str, shell: bool = False) -> None:
    output_ok = _check_cmd_output(cmd, pattern, shell=shell)
    if not output_ok:
        _report(f"Command '{cmd}' output does not match '{pattern}'", fatal=True)
        sys.exit(1)


def _check_cmd_output(cmd: Cmd, pattern: str, shell: bool = False) -> bool:
    process_result = _run(cmd, die_on_error=False, shell=shell)
    if not process_result.success:
        return False
    return process_result.stdout_matches(pattern)


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
            _report._report_nb_levels -= 1  # type: ignore
        prefix = " " + ("  " * _report._report_nb_levels) + prefix  # type: ignore

    print(prefix, *args)

    if step_start and not fatal:
        _report._report_nb_levels += 1  # type: ignore


_report._report_nb_levels = 0  # type: ignore


@contextmanager
def _ensuring_step(step_name: str) -> t.Generator[None, None, None]:
    _report(f"Ensuring {step_name} is properly installed...", step_start=True)
    yield
    _report(f"{step_name} setup ok.\n", step_done=True)


class StepReporter:
    def wip(self, caption: str) -> None:
        _report(caption, step_wip=True)

    def nothing_to_do(self, caption: str) -> None:
        _report(f"{caption} ✓", step_done=True)

    def done(self, caption: str) -> None:
        _report(caption, step_done=True)


@contextmanager
def _step(step_init_caption: str) -> t.Generator[StepReporter, None, None]:
    _report(step_init_caption, step_start=True)
    yield StepReporter()


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
