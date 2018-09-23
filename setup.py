#!python3

from contextlib import contextmanager
import os
import re
import subprocess
import sys
import typing as t

TARGET_DISTRIBUTION = "Ubuntu 18.04"
TARGET_PYTHON_VERSION = "3.7"
TARGET_NODEJS_VERSION = "10.11.0"
TARGET_POSTGRES_VERSION = "10"

POSTGRES_DB = os.getenv("POSTGRES_DB", "django_app")
POSTGRES_USER = os.getenv("POSTGRES_USER", "django_app")
# don't worry, we will generate a secure on the fly if needed :-)
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PASSWORD_MIN_LENGTH = 10

# @link https://www.digitalocean.com/community/tutorials/how-to-set-up-django-with-postgres-nginx-and-gunicorn-on-ubuntu-18-04

##################
# High level functions: those that we use to install specific software on the server
##################


def setup_server():
    flight_precheck()

    ensure_curl()
    ensure_python()
    ensure_nodejs()
    ensure_postgres()
    ensure_nginx()

    ensure_postgres_django_setup()


def flight_precheck():
    USAGE = "Usage: sudo python3.6 setup.py"
    if sys.version_info < (3, 6):
        print(USAGE, "This script must be run with Python 3.6+")
        sys.exit(1)

    if not is_root():
        print(USAGE, "This script must be run as 'root'")
        sys.exit(1)

    with _ensuring_step("Linux distribution"):
        distrib_ok = check_distrib()
        if not distrib_ok:
            print(
                f"This script only works for {TARGET_DISTRIBUTION} ; type `cat /etc/lsb-release` to check yours."
            )
            sys.exit(1)


##################
# "Ensure *" functions
##################


def ensure_curl():
    with _ensuring_step("Curl"):
        install_debian_package_if_needed("curl")
        _check_cmd_output_or_die(["curl", "--version"], r"^curl \d\.\d+(?:.|\n)+https")


def ensure_python():
    with _ensuring_step("Python"):
        install_ppa_if_needed("deadsnakes")
        install_debian_package_if_needed(f"python{TARGET_PYTHON_VERSION}")
        _check_cmd_output_or_die(
            [f"python{TARGET_PYTHON_VERSION}", "--version"],
            r"^Python " + re.escape(TARGET_PYTHON_VERSION),
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


##################
# Step-specific functions
##################


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
            print("Could not create database 💀")
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
            print("Could not create user 💀")
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
        print(f"Command '{cmd}' output does not match '{pattern}' 💀")
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


def _report(
    *args, step_start: bool = False, step_wip: bool = False, step_done: bool = False
):
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
    if step_start:
        _report._report_nb_levels += 1


_report._report_nb_levels = 0


@contextmanager
def _ensuring_step(step_name: str) -> None:
    _report(f"Ensuring {step_name} is properly installed...", step_start=True)
    yield
    _report(f"{step_name} setup ok. 👍\n", step_done=True)


if __name__ == "__main__":
    setup_server()
