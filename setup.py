#!/usr/bin/python3.6

# pylint: disable=missing-docstring,invalid-name,line-too-long,bad-continuation,too-many-lines

from contextlib import contextmanager
import enum
from functools import partial
import os
from pathlib import Path
import re
import subprocess
import sys
import typing as t

# Dynamic params, which can be set from env vars:
POSTGRES_DB = os.getenv("POSTGRES_DB", "django_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "django_user")
# (don't worry, we will generate a secure password on the fly if needed :-)
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
NGINX_SERVER_NAME = os.getenv("NGINX_SERVER_NAME", "")

TARGET_DISTRIBUTION = "Ubuntu 18.04"
TARGET_PYTHON_VERSION = "3.7"
TARGET_NODEJS_VERSION = "10.11.0"
TARGET_POSTGRES_VERSION = "10"
POSTGRES_PASSWORD_MIN_LENGTH = 10

LINUX_USER_SSH_USERNAME = os.getenv("LINUX_USER_SSH_USERNAME", "sshuser")
LINUX_USER_SSH_GROUPNAME = os.getenv("LINUX_USER_SSH_USERNAME", "sshgroup")

LINUX_USER_DJANGO_USERNAME = os.getenv("LINUX_USER_DJANGO_USERNAME", "django")
LINUX_USER_DJANGO_GROUPNAME = os.getenv("LINUX_USER_DJANGO_GROUPNAME", "www-data")

DJANGO_APP_DIR = f"/home/{LINUX_USER_DJANGO_USERNAME}/django-app/current"
DJANGO_PROJECT_NAME = "project"

# @link https://www.digitalocean.com/community/tutorials/how-to-set-up-django-with-postgres-nginx-and-gunicorn-on-ubuntu-18-04
# @link https://www.digitalocean.com/community/tutorials/initial-server-setup-with-ubuntu-18-04

##################
# High level functions: those that we use to install specific software on the server
##################


def setup_server() -> None:
    flight_precheck()

    ensure_firewall()
    ensure_linux_users_setup()

    ensure_base_software()
    ensure_python()
    ensure_nodejs()
    ensure_postgres()
    ensure_nginx()
    ensure_passenger()

    ensure_postgres_django_setup()
    ensure_python_app_packages_setup()

    ensure_django_app()
    ensure_nginx_and_passenger_setup()


def flight_precheck() -> None:
    USAGE = "Usage: sudo python3.6 setup.py"
    if sys.version_info < (3, 6):
        _panic(USAGE, "This script must be run with Python 3.6+")

    if not is_root():
        _panic(USAGE, "This script must be run as 'root'")

    with _ensuring_step("Linux distribution"):
        distrib_ok = check_distrib()
        if not distrib_ok:
            _panic(
                f"This script only works for {TARGET_DISTRIBUTION} ; type `cat /etc/lsb-release` to check yours."
            )


##################
# "Ensure" functions (our top-level tasks)
##################


def ensure_firewall() -> None:
    with _ensuring_step("Firewall"):
        # Since it's a Web server managed by SSH we must make sure that we always allow SSH
        # (but we may not be able to check it, if the firewall is not active)
        firewall_rule_allow("OpenSSH", check=False)
        firewall_enable_if_needed()

        if firewall_rule_check_status("OpenSSH") is not FirewallRuleStatus.ALLOW:
            _panic("OpenSSH firewall rule is not allowed!")


def ensure_linux_users_setup() -> None:
    with _ensuring_step("Linux users"):
        if not has_linux_user(LINUX_USER_SSH_USERNAME):
            create_linux_user(
                LINUX_USER_SSH_USERNAME,
                LINUX_USER_SSH_GROUPNAME,
                sudoer=True,
                with_root_ssh_authorised_keys=True,
            )
        if not has_linux_user(LINUX_USER_DJANGO_USERNAME):
            create_linux_user(LINUX_USER_DJANGO_USERNAME, LINUX_USER_DJANGO_GROUPNAME)


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
        firewall_rule_allow_if_needed("Nginx Full")


def ensure_passenger() -> None:
    with _ensuring_step("Phusion Passenger"):
        # @link https://www.phusionpassenger.com/library/walkthroughs/deploy/python/ownserver/nginx/oss/bionic/install_passenger.html
        add_apt_repository_if_needed(
            "keyserver.ubuntu.com:80",
            "561F9B9CAC40B2F7",
            "deb https://oss-binaries.phusionpassenger.com/apt/passenger bionic main",
            "passenger",
            "Phusion Automated Software Signing",
        )
        install_debian_package_if_needed("libnginx-mod-http-passenger")
        _check_cmd_output_or_die(
            "/usr/bin/passenger-config validate-install --auto | tail -n 1",
            r"Everything looks good",
            shell=True,
        )


def ensure_postgres_django_setup() -> None:
    with _ensuring_step("Posgres config for the Django app"):
        postgres_django_setup_ensure_db(POSTGRES_DB)
        postgres_django_setup_ensure_user(POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB)


def ensure_python_app_packages_setup() -> None:
    with _ensuring_step("Python packages for our app"):
        install_python_package_if_needed("psycopg2-binary")
        install_python_package_if_needed("pipenv")


def ensure_django_app() -> None:
    with _ensuring_step("Django app"):
        create_blank_django_app_if_needed(DJANGO_APP_DIR, DJANGO_PROJECT_NAME)


def ensure_nginx_and_passenger_setup() -> None:
    with _ensuring_step("Nginx & Passenger setup"):
        with _ensuring_step("Passenger setup"):
            passenger_wsgi_path = f"{DJANGO_APP_DIR}/passenger_wsgi.py"
            create_file_if_needed(passenger_wsgi_path, _PASSENGER_WSGI_FILE)
        with _ensuring_step("Nginx setup"):
            create_file_if_needed(
                f"{_NGINX_AVAILABLE_SITES_PATH}/{_NGINX_SITE_NAME}", _NGINX_SITE_FILE
            )
            nginx_activate_nginx_site_if_needed(
                available_sites_path=_NGINX_AVAILABLE_SITES_PATH,
                enabled_sites_path=_NGINX_ENABLED_SITES_PATH,
                site_name=_NGINX_SITE_NAME,
                site_config=_NGINX_SITE_FILE,
            )
            systemd_enable_and_start_service("nginx")


##################
# Misc general tasks
##################


class FirewallRuleStatus(enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    UNKNOWN = "UNKNOWN"


def firewall_is_enabled() -> bool:
    with _step(f"Checking firewall status...") as step:
        cmd = ["ufw", "status"]
        process_result = _run(cmd, panic_on_error=False)
        is_active = process_result.success and process_result.stdout_starts_with(
            "Status: active"
        )
        step.done(f"Checked ({'active' if is_active else 'inactive'}).")
        return is_active


def firewall_enable() -> None:
    with _step(f"Enabling firewall...") as step:
        cmd = ["ufw", "--force", "enable"]
        _run(cmd)
        if not firewall_is_enabled():
            _panic("Couldn't enable the firewall")
        step.done("Firewall enabled.")


def firewall_enable_if_needed() -> bool:
    is_enabled = firewall_is_enabled()
    if is_enabled:
        return False
    firewall_enable()
    return True


def firewall_rule_check_status(rule: str) -> FirewallRuleStatus:
    with _step(f"Checking firewall rule '{rule}' status...") as step:
        cmd = f"ufw status | grep '^{rule}'"
        process_result = _run(cmd, shell=True, panic_on_error=False)
        status = FirewallRuleStatus.UNKNOWN
        if process_result.success:
            if process_result.stdout_matches(
                f"^{rule}\\s+{FirewallRuleStatus.ALLOW.value}"
            ):
                status = FirewallRuleStatus.ALLOW
            elif process_result.stdout_matches(
                f"^{rule}\\s+{FirewallRuleStatus.DENY.value}"
            ):
                status = FirewallRuleStatus.DENY
        step.done(f"Firewall rule checked ({status.value}).")
        return status


def firewall_rule_allow(rule: str, check: bool = True) -> None:
    with _step(f"Allowing firewall rule '{rule}'...") as step:
        cmd = ["ufw", "allow", rule]
        _run(cmd)
        if check and firewall_rule_check_status(rule) is not FirewallRuleStatus.ALLOW:
            _panic("Couldn't allow the firewall rule!")
        step.done("Firewall rule allowed.")


def firewall_rule_allow_if_needed(rule: str) -> bool:
    firewall_rule_status = firewall_rule_check_status(rule)
    if firewall_rule_status is FirewallRuleStatus.ALLOW:
        return False
    firewall_rule_allow(rule)
    return True


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


def is_apt_repository_installed(expected_repo_name: str) -> bool:
    with _step(f"Checking APT repository '{expected_repo_name}'...") as step:
        cmd = f"(APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=1 apt-key list | grep '{expected_repo_name}') || true"
        process_result = _run(cmd, shell=True)
        installed = bool(process_result.stdout)
        if installed:
            step.nothing_to_do("APT repository already installed.")
        else:
            step.done("APT repository not installed.")
        return installed


def install_ppa(name: str) -> None:
    with _step(f"Adding PPA '{name}'...") as step:
        cmd = ["add-apt-repository", "-y", f"ppa:{name}/ppa"]
        _run(cmd, stdout=None)
        apt_update()
        step.done("PPA added.")


def add_apt_repository(
    keyserver: str,
    key: str,
    deb_definition: str,
    repo_name: str,
    expected_repo_name: str,
) -> None:
    with _step(f"Adding APT repository '{repo_name}'...") as step:
        apt_key_cmd = [
            "apt-key",
            "adv",
            "--keyserver",
            f"hkp://{keyserver}",
            "--recv-keys",
            key,
        ]
        _run(apt_key_cmd, stdout=None)
        create_file_if_needed(
            f"/etc/apt/sources.list.d/{repo_name.lower()}.list", deb_definition
        )
        apt_update()
        step.done("APT repository added.")


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


def add_apt_repository_if_needed(
    keyserver: str,
    key: str,
    deb_definition: str,
    repo_label: str,
    expected_repo_name: str,
) -> bool:
    installed = is_apt_repository_installed(expected_repo_name)
    if installed:
        return False
    add_apt_repository(keyserver, key, deb_definition, repo_label, expected_repo_name)
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
        process_result = _run(cmd, panic_on_error=False, shell=True)
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
        process_result = _run(cmd, shell=True, panic_on_error=False)
        user_exists = process_result.success and process_result.stdout_starts_with(user)
        if user_exists:
            step.nothing_to_do("User checked (already exists).")
        else:
            step.done("User checked (doesn't exist').")
        return user_exists


def create_linux_user(
    user: str,
    group: str,
    shell: str = "/bin/bash",
    sudoer: bool = False,
    with_root_ssh_authorised_keys: bool = False,
) -> None:
    with _step(
        f"Creating Linux user '{user}:{group}', with shell '{shell}'..."
    ) as step:
        add_group_if_not_exists_cmd = ["groupadd", "-f", group]
        _run(add_group_if_not_exists_cmd)

        add_user_cmd = ["useradd", "-m", "-s", shell, "-g", group, user]
        _run(add_user_cmd)

        if sudoer:
            with _step(f"Adding the user to the 'sudoers'...") as sudoer_step:
                add_to_sudoers_cmd = ["usermod", "-aG" "sudo", user]
                _run(add_to_sudoers_cmd)
                sudoer_step.done("Added.")
        if with_root_ssh_authorised_keys:
            with _step(
                f"Giving this user the same '~/.ssh/authorized_keys' than the root user..."
            ) as ssh_authorised_keys_step:
                target_file_dir = f"/home/{user}/.ssh"
                copy_keys_cmd = f"mkdir -p '{target_file_dir}' && cp '/root/.ssh/authorized_keys' '{target_file_dir}/' && chown -R '{user}:{group}' '{target_file_dir}'"
                _run(copy_keys_cmd, shell=True)
                ssh_authorised_keys_step.done(
                    "'Authorised keys' copied from root user."
                )

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


def nginx_enable_site(
    available_sites_path: str, enabled_sites_path: str, site_name: str
) -> bool:
    site_available_path = f"{available_sites_path}/{site_name}"
    site_enabled_path = f"{enabled_sites_path}/{site_name}"
    if (
        Path(site_enabled_path).resolve() == site_available_path
        and Path(site_available_path).is_file()
    ):
        return False

    with _step(f"Enabling Nginx site '{site_name}'...") as step:
        cmd = ["ln", "-s", "-f", site_available_path, site_enabled_path]
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
        process_result = _run(check_cmd, panic_on_error=False)
        config_ok = process_result.success
        step.done(f"Nginx config checked ({'ok' if config_ok else 'broken'}).")
        return config_ok


def nginx_check_config_or_die() -> None:
    config_ok = nginx_check_config()
    if not config_ok:
        _panic("Nginx config is broken!. Type `nginx -t` to investigate.")


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
        process_result = _run(cmd, panic_on_error=False)
        is_active = process_result.success and process_result.stdout_has_content(
            "active (running)"
        )
        step.done(f"Checking done ({'active' if is_active else 'not active'}).")
        return is_active


def systemd_check_service_is_active_or_die(service_name: str) -> None:
    is_active = systemd_check_service_is_active(service_name)
    if not is_active:
        _panic(f"Service '{service_name}' is not active.")


def db_database_exists(db_name: str) -> bool:
    check_db_sql = f"""select datname from pg_database where datname = '{db_name}';"""
    result = _run_sql(check_db_sql)
    return result is not None and result.find(db_name) > -1


def db_user_exists(user: str) -> bool:
    check_user_sql = f"""\\du {user};"""
    result = _run_sql(check_user_sql)
    return result is not None and result.find(user) > -1


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
    db_exists = partial(db_database_exists, db_name)
    with _step(f"Checking database '{db_name}' status...") as step:
        if db_exists():
            step.nothing_to_do("Database exists.")
            return False

        postgres_django_setup_create_db(db_name=db_name)
        if not db_exists():
            _panic("Could not create database")
        step.done("Database created.")
        return True


def postgres_django_setup_ensure_user(user: str, password: str, db_name: str) -> bool:
    user_exists = partial(db_user_exists, user)
    with _step(f"Checking database user '{user}' status...") as step:
        if user_exists():
            step.nothing_to_do("Database user exists.")
            return False

        postgres_django_setup_create_user(user=user, password=password, db_name=db_name)
        if not user_exists():
            _panic("Could not create user")
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
        _panic(
            f"Postgres user password is too short (minimum length: {POSTGRES_PASSWORD_MIN_LENGTH})"
        )

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


def nginx_activate_nginx_site_if_needed(
    available_sites_path: str, enabled_sites_path: str, site_name: str, site_config: str
) -> None:
    nginx_disable_site_if_needed("default")

    nginx_site_target_file = f"{enabled_sites_path}/{site_name}"
    with _step(f"Checking nginx enabled symlink '{nginx_site_target_file}'...") as step:
        nginx_site_target_ok = check_file_content(nginx_site_target_file, site_config)
        if nginx_site_target_ok:
            step.nothing_to_do("Nginx site already enabled.")
        else:
            nginx_enable_site(available_sites_path, enabled_sites_path, site_name)
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

        chown_cmd = [
            "chown",
            "-R",
            f"{LINUX_USER_DJANGO_USERNAME}:{LINUX_USER_DJANGO_GROUPNAME}",
            app_dir,
        ]
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


Cmd = t.Union[list, str]


class SubProcessError(RuntimeError):
    def __init__(self, cmd: Cmd, process_result: RunResult) -> None:
        super().__init__()
        self.cmd = cmd
        self.process_result = process_result

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.cmd}, '${self.process_result}')"


def _run(
    cmd: Cmd, panic_on_error: bool = True, capture_output=True, **kwargs
) -> RunResult:
    # pylint: disable=E1120
    # (@link https://github.com/PyCQA/pylint/issues/1898)

    # No "capture_output" param in Python < 3.7, so we have to deal with "stdout" & "stderr" manually :-/
    if capture_output is True and kwargs.get("stdout") is None:
        kwargs["stdout"] = subprocess.PIPE
    if capture_output is True and kwargs.get("stderr") is None:
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

        if panic_on_error and not result.success:
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
        _panic(f"Command '{cmd}' output does not match '{pattern}'")


def _check_cmd_output(cmd: Cmd, pattern: str, shell: bool = False) -> bool:
    process_result = _run(cmd, panic_on_error=False, shell=shell)
    if not process_result.success:
        return False
    return process_result.stdout_matches(pattern)


def _report(
    *args,
    step_start: bool = False,
    step_wip: bool = False,
    step_done: bool = False,
    fatal: bool = False,
) -> None:
    # pylint: disable=protected-access
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


def _panic(*args) -> None:
    _report(*args, fatal=True)
    sys.exit(1)


# pylint: disable=protected-access
_report._report_nb_levels = 0  # type: ignore
# pylint: enable=protected-access


@contextmanager
def _ensuring_step(step_name: str) -> t.Generator[None, None, None]:
    _report(f"Ensuring {step_name} setup...", step_start=True)
    yield
    _report(f"{step_name} setup ok.\n", step_done=True)


class StepReporter:
    @staticmethod
    def wip(caption: str) -> None:
        _report(caption, step_wip=True)

    @staticmethod
    def nothing_to_do(caption: str) -> None:
        _report(f"{caption} ✓", step_done=True)

    @staticmethod
    def done(caption: str) -> None:
        _report(caption, step_done=True)


@contextmanager
def _step(step_init_caption: str) -> t.Generator[StepReporter, None, None]:
    _report(step_init_caption, step_start=True)
    yield StepReporter()


_NGINX_AVAILABLE_SITES_PATH = "/etc/nginx/sites-available"
_NGINX_ENABLED_SITES_PATH = "/etc/nginx/sites-enabled"
_NGINX_SITE_NAME = "django-app"
_NGINX_SITE_FILE = f"""\
# {_NGINX_AVAILABLE_SITES_PATH}/{_NGINX_SITE_NAME}

server {{
    {('server_name ' + NGINX_SERVER_NAME + ';') if NGINX_SERVER_NAME else ''}
    listen 80;

    location = /favicon.ico {{ access_log off; log_not_found off; }}

    location / {{
        passenger_enabled on;
        passenger_app_type wsgi;
        # passenger_startup_file passenger_wsgi.py;
        
        passenger_python /usr/bin/python{TARGET_PYTHON_VERSION};
        root {DJANGO_APP_DIR}/static;
    }}
}}

"""

_PASSENGER_WSGI_FILE = f"""\
import {DJANGO_PROJECT_NAME}.wsgi

application = {DJANGO_PROJECT_NAME}.wsgi.application
"""

if __name__ == "__main__":
    setup_server()
