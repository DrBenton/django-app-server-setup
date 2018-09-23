#!python3

import os
import re
import sys
import subprocess

USAGE = "Usage: sudo python3.6 setup.py"
TARGET_DISTRIBUTION = "Ubuntu 18.04"
TARGET_PYTHON_VERSION = "3.7"


def setup_server():
    flight_precheck()

    install_ppa_if_needed("deadsnakes")
    install_debian_package_if_needed(f"python{TARGET_PYTHON_VERSION}")
    check_cmd_output(
        [f"python{TARGET_PYTHON_VERSION}", "--version"],
        f"Python {TARGET_PYTHON_VERSION}",
    )


def flight_precheck():
    if sys.version_info < (3, 6):
        print(USAGE, "This script must be run with Python 3.6+")
        sys.exit(1)

    if not is_root():
        print(USAGE, "This script must be run as 'root'")
        sys.exit(1)

    _report("Checking distribution...", step_start=True)
    distrib_ok = True  # check_distrib()
    if not distrib_ok:
        print(
            f"This script only works for {TARGET_DISTRIBUTION} ; type `cat /etc/lsb-release` to check yours."
        )
        sys.exit(1)
    _report("Distribution ok.", step_done=True)


def is_debian_package_installed(name: str) -> bool:
    _report(
        f"Checking if the Debian package '{name}' is already installed...",
        step_start=True,
    )
    cmd = ["dpkg", "-s", name]
    try:
        process_result = _run(cmd)
        installed = str(process_result.stdout).find("Status: install ok installed") > -1
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
    return str(process_result.stdout).find(TARGET_DISTRIBUTION) > -1


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


def check_cmd_output(cmd: list, pattern: str) -> None:
    process_result = _run(cmd)
    output = str(process_result.stdout)
    ok = output.find(pattern) > -1
    if not ok:
        print(f"Command output '{output}' does not match '{pattern}' 💀")
        sys.exit(1)


class SubProcessError(RuntimeError):
    def __init__(self, cmd: list, process_result: subprocess.CompletedProcess):
        self.cmd = cmd
        self.process_result = process_result

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.cmd!r}, '${self.process_result}')"


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    # no "capture_output" param in Python < 3.7, so we have to deal with "stdout" & "stderr" manually :-/
    if kwargs.get("stdout") is None:
        kwargs["stdout"] = subprocess.PIPE
    if kwargs.get("stderr") is None:
        kwargs["stderr"] = subprocess.PIPE
    process_result = subprocess.run(cmd, **kwargs)
    if process_result.returncode != 0:
        raise SubProcessError(cmd, process_result)
    return process_result


def _report(
    *args, step_start: bool = False, step_wip: bool = False, step_done: bool = False
):
    prefix = "."
    if step_start:
        prefix = "┌"
        _report._report_nb_levels += 1
    elif step_wip:
        prefix = " │"
    elif step_done:
        _report._report_nb_levels -= 1
        prefix = " └"
    prefix = " " + (" " * _report._report_nb_levels) + prefix
    print(prefix, *args)


_report._report_nb_levels = 0


if __name__ == "__main__":

    setup_server()
