#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Brew-file: Manager for packages of Homebrew
https://github.com/rcmdnk/homebrew-file

requirement: Python 3.7 or later
"""

import argparse
import copy
import glob
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from io import StringIO
from urllib.parse import quote

__prog__ = os.path.basename(__file__)
__description__ = __doc__
__author__ = "rcmdnk"
__copyright__ = "Copyright (c) 2013 rcmdnk"
__credits__ = ["rcmdnk"]
__license__ = "MIT"
__version__ = "v8.5.6"
__date__ = "2/Nov/2021"
__maintainer__ = "rcmdnk"
__email__ = "rcmdnk@gmail.com"
__status__ = "Prototype"


def is_mac():
    if platform.system() == "Darwin":
        return True
    return False


def open_output_file(name, mode="w"):
    """Helper function to open a file even if it doesn't exist."""
    if os.path.dirname(name) != "" and \
            not os.path.exists(os.path.dirname(name)):
        os.makedirs(os.path.dirname(name))
    return open(name, mode)


def to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
        return bool(int(val))
    if isinstance(val, str):
        if val.lower() == "true":
            return True
    return False


def to_num(val):
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
        return int(val)
    if isinstance(val, str):
        if val.lower() == "true":
            return 1
    return 0


shell_envs = {
    'HOSTNAME': os.uname().nodename,
    'HOSTTYPE': os.uname().machine,
    'OSTYPE': subprocess.run(["bash", "-c", "echo $OSTYPE"],
                             capture_output=True, text=True).stdout.strip(),
    'PLATFORM': sys.platform
}


def expandpath(path):
    path = os.path.expanduser(path)
    for k in shell_envs:
        for kk in [f"${k}", f"${{{k}}}"]:
            if kk in path:
                path = path.replace(kk, shell_envs[k])
    return re.sub(r'(?<!\\)\$(\w+|\{([^}]*)\})',
                  lambda x: os.environ.get(x.group(2) or x.group(1), ''),
                  os.path.expanduser(path)).replace('\\$', '$')


class Tee:
    """Module to write out in two ways at once."""

    def __init__(self, out1, out2=sys.stdout, use2=True):
        """__init__"""

        if isinstance(out1, str):
            self.out1name = out1
            self.out1 = StringIO()
        else:
            self.out1name = ""
            self.out1 = out1
        self.use2 = use2
        if self.use2:
            if isinstance(out2, str):
                self.out2name = out2
                self.out2 = StringIO()
            else:
                self.out2name = ""
                self.out2 = out2

    def __del__(self):
        """__del__"""

        if self.out1name != "":
            self.out1.close()
        if self.use2:
            if self.out2name != "":
                self.out2.close()

    def write(self, text):
        """Write w/o line break."""

        self.out1.write(text)
        if self.use2:
            self.out2.write(text)

    def writeln(self, text):
        """Write w/ line break."""

        self.out1.write(text + "\n")
        if self.use2:
            self.out2.write(text + "\n")

    def flush(self):
        """Flush the output"""

        self.out1.flush()
        if self.use2:
            self.out2.flush()

    def close(self):
        """Close output files."""

        if self.out1name != "":
            f = open_output_file(self.out1name, "w")
            f.write(self.out1.getvalue())
            f.close()
        if self.use2:
            if self.out2name != "":
                f = open(self.out2name, "w")
                f.write(self.out2.getvalue())
                f.close()
        self.__del__()


class BrewHelper:
    """Helper functions for BrewFile."""

    def __init__(self, opt):
        self.opt = opt
        self.colors = {"black": "30", "red": "31", "green": "32",
                       "yellow": "33", "blue": "34", "magenta": "35",
                       "lightblue": 36, "white": 37}

    def readstdout(self, proc):
        for line in iter(proc.stdout.readline, ''):
            line = line.rstrip()
            if line == '':
                continue
            yield line

    def proc(self, cmd, print_cmd=True, print_out=True,
             exit_on_err=True, separate_err=False, print_err=True,
             verbose=1, env={}):
        """ Get process output."""
        if not isinstance(cmd, list):
            cmd = shlex.split(cmd)
        cmd_orig = " ".join(["$"] + cmd)
        if cmd[0] == "brew":
            cmd[0] = self.opt["brew_cmd"]
        if print_cmd:
            self.info(cmd_orig, verbose)
        all_env = os.environ.copy()
        for k, v in env.items():
            all_env[k] = v
        lines = []
        try:
            if separate_err:
                if print_err:
                    stderr = None
                else:
                    stderr = open(os.devnull, 'w')
            else:
                stderr = subprocess.STDOUT
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=stderr,
                                 text=True, env=all_env)
            if hasattr(stderr, 'close'):
                stderr.close()
            for line in self.readstdout(p):
                lines.append(line)
                if print_out:
                    self.info(line, verbose)
            ret = p.wait()
        except OSError as e:
            if print_out:
                lines = [" ".join(cmd) + ": " + str(e)]
                self.info(lines[0].strip(), verbose)
            ret = -1

        if exit_on_err and ret != 0:
            if not (print_out and self.opt["verbose"] >= verbose):
                print("\n".join(lines))
            self.err("Failed at command: " + " ".join(cmd))
            sys.exit(ret)

        return ret, lines

    def out(self, text, verbose=100, color=""):
        if self.opt["verbose"] < verbose:
            return
        pre = post = ""
        if color != "" and sys.stdout.isatty():
            if color in self.colors:
                pre = "\033[" + self.colors[color] + ";1m"
                post = "\033[m"
        print(pre + text + post)

    def info(self, text, verbose=2):
        self.out(text, verbose)

    def warn(self, text, verbose=1):
        self.out("[WARNING]: " + text, verbose, "yellow")

    def err(self, text, verbose=0):
        self.out("[ERROR]: " + text, verbose, "red")

    def banner(self, text, verbose=1):
        width = 0
        for line in text.split("\n"):
            if width < len(line):
                width = len(line)
        self.out("\n" + "#" * width + "\n" + text + "\n" + "#" * width + "\n",
                 verbose)

    def brew_val(self, name):
        if name not in self.opt:
            self.opt[name] = self.proc("brew --" + name, False, False)[1][0]
        return self.opt[name]


class BrewInfo:
    """Homebrew information storage."""

    def __init__(self, helper, filename=""):

        self.brew_input_opt = {}

        self.brew_input = []
        self.tap_input = []
        self.cask_input = []
        self.appstore_input = []
        self.main_input = []
        self.file_input = []

        self.before_input = []
        self.after_input = []
        self.cmd_input = []

        self.brew_list_opt = {}

        self.brew_list = []
        self.brew_full_list = []
        self.tap_list = []
        self.cask_list = []
        self.appstore_list = []
        self.main_list = []
        self.file_list = []

        self.cask_nocask_list = []

        self.list_dic = {
            "brew_input_opt": self.brew_input_opt,
            "brew_input": self.brew_input,
            "tap_input": self.tap_input,
            "cask_input": self.cask_input,
            "appstore_input": self.appstore_input,
            "main_input": self.main_input,
            "file_input": self.file_input,
            "before_input": self.before_input,
            "after_input": self.after_input,
            "cmd_input": self.cmd_input,
            "brew_list_opt": self.brew_list_opt,
            "brew_list": self.brew_list,
            "brew_full_list": self.brew_full_list,
            "tap_list": self.tap_list,
            "cask_list": self.cask_list,
            "cask_nocask_list": self.cask_nocask_list,
            "appstore_list": self.appstore_list,
            "main_list": self.main_list,
            "file_list": self.file_list,
        }
        self.filename = filename
        self.helper = helper

    def get_dir(self):
        return os.path.dirname(self.filename)

    def check_file(self):
        if os.path.exists(self.filename):
            return True
        return False

    def check_dir(self):
        if os.path.exists(self.get_dir()):
            return True
        return False

    def clear(self):
        self.clear_input()
        self.clear_list()

    def clear_input(self):
        self.brew_input_opt.clear()

        del self.brew_input[:]
        del self.tap_input[:]
        del self.cask_input[:]
        del self.appstore_input[:]
        del self.main_input[:]
        del self.file_input[:]

        del self.before_input[:]
        del self.after_input[:]
        del self.cmd_input[:]

    def clear_list(self):
        self.brew_list_opt.clear()

        del self.brew_list[:]
        del self.brew_full_list[:]
        del self.tap_list[:]
        del self.cask_list[:]
        del self.cask_nocask_list[:]
        del self.appstore_list[:]
        del self.main_list[:]
        del self.file_list[:]

    def input_to_list(self):
        self.clear_list()
        self.clear_list()
        self.brew_list.extend(self.brew_input)
        self.brew_list_opt.update(self.brew_input_opt)
        self.tap_list.extend(self.tap_input)
        self.cask_list.extend(self.cask_input)
        self.appstore_list.extend(self.appstore_input)
        self.main_list.extend(self.main_input)
        self.file_list.extend(self.file_input)

    def sort(self):
        core_tap = []
        cask_tap = []
        brew_taps = []
        other_taps = []
        for t in self.tap_list:
            if t == "homebrew/core":
                core_tap.append(t)
            elif t == self.helper.opt["cask_repo"]:
                cask_tap.append(t)
            elif t.startswith("homebrew/"):
                brew_taps.append(t)
            else:
                other_taps.append(t)
        brew_taps.sort()
        other_taps.sort()
        self.tap_list = core_tap + brew_taps + cask_tap + other_taps

        self.brew_list.sort()
        self.brew_full_list.sort()
        self.cask_list.sort()
        self.main_list.sort()
        self.file_list.sort()
        self.cask_nocask_list.sort()

        self.appstore_list.sort(
            key=lambda x: x.split()[1].lower() if len(x.split()) > 1
            else x.split()[0])

    def get(self, name):
        return copy.deepcopy(self.list_dic[name])

    def get_files(self):
        files = {'main': self.get('main_input')}
        files.update({'ext': self.get('file_input')})
        return files

    def remove(self, name, package):
        if isinstance(self.list_dic[name], list):
            self.list_dic[name].remove(package)
        elif isinstance(self.list_dic[name], dict):
            del self.list_dic[name][package]

    def set_val(self, name, val):
        if isinstance(self.list_dic[name], list):
            del self.list_dic[name][:]
            self.list_dic[name].extend(val)
        elif isinstance(self.list_dic[name], dict):
            self.list_dic[name].clear()
            self.list_dic[name].update(val)

    def add(self, name, val):
        if isinstance(self.list_dic[name], list):
            self.list_dic[name].extend(
                [x for x in val if x not in self.list_dic[name]])
        elif isinstance(self.list_dic[name], dict):
            self.list_dic[name].update(val)

    def read(self, filename=""):
        self.clear_input()

        try:
            if filename == "":
                f = open(self.filename, "r")
            else:
                f = open(filename, "r")
        except IOError:
            return False

        lines = f.readlines()
        f.close()
        is_ignore = False
        self.tap_input.append("direct")
        for line in lines:
            if re.match("# *BREWFILE_ENDIGNORE", line):
                is_ignore = False
            if re.match("# *BREWFILE_IGNORE", line):
                is_ignore = True
            if is_ignore:
                continue
            if re.match(" *$", line) is not None or\
                    re.match(" *#", line) is not None:
                continue
            args = line.replace("'", "").replace('"', "").\
                replace(",", " ").replace("[", "").replace("]", "").split()
            cmd = args[0]
            p = args[1] if len(args) > 1 else ""
            if len(args) > 2 and p in ["tap", "cask"]:
                args.pop(0)
                cmd = args[0]
                p = args[1]
                if self.helper.opt["form"] == "none":
                    self.helper.opt["form"] = "cmd"
            if len(args) > 2 and cmd in ["brew", "cask"] and \
                    p == "install":
                args.pop(1)
                p = args[1]
                if self.helper.opt["form"] == "none":
                    self.helper.opt["form"] = "cmd"

            if len(args) > 2:
                if args[2] == "args:":
                    opt = " " + " ".join(["--" + x for x in args[3:]]).strip()
                    if self.helper.opt["form"] == "none":
                        self.helper.opt["form"] = "bundle"
                else:
                    opt = " " + " ".join(args[2:]).strip()
            else:
                opt = ""
            excmd = " ".join(line.split()[1:]).strip()

            if self.helper.opt["form"] == "none":
                if cmd in ["brew", "tap", "tapall"]:
                    if '"' in line or "'" in line:
                        self.helper.opt["form"] = "bundle"

            if cmd in ("brew", "install"):
                self.brew_input.append(p)
                self.brew_input_opt[p] = (opt)
            elif cmd == "tap":
                self.tap_input.append(p)
            elif cmd == "tapall":
                self.tap_input.append(p)
                for tp in self.get_tap_packs(p):
                    self.brew_input.append(tp)
                    self.brew_input_opt[tp] = ""
                for tp in self.get_tap_casks(p):
                    self.cask_input.append(tp)
            elif cmd == "cask":
                self.cask_input.append(p)
            elif cmd == "mas" and line.find(',') != -1:
                if self.helper.opt["form"] == "none":
                    self.helper.opt["form"] = "bundle"
                p = line.split()[1].strip(",").strip("'").strip('"')
                pid = line.split()[3]
                self.appstore_input.append(pid + ' ' + p)
            elif cmd in ("appstore", "mas"):
                self.appstore_input.append(re.sub("^ *appstore *", "", line).
                                           strip().strip("'").strip('"'))
            elif cmd == "main":
                self.main_input.append(p)
                self.file_input.append(p)
            elif cmd == "file" or cmd.lower() == "brewfile":
                self.file_input.append(p)
            elif cmd == "before":
                self.before_input.append(excmd)
            elif cmd == "after":
                self.after_input.append(excmd)
            else:
                self.cmd_input.append(line.strip())

    def get_tap_path(self, tap):
        """Get tap path"""
        if tap == "direct":
            return self.helper.brew_val("cache") + "/Formula"

        tap_user = os.path.dirname(tap)
        tap_repo = os.path.basename(tap)
        return self.helper.brew_val("repository") + "/Library/Taps" +\
            "/" + tap_user + "/homebrew-" + tap_repo

    def get_tap_packs(self, tap):
        """Helper for tap configuration file"""
        packs = []
        tap_path = self.get_tap_path(tap)
        if not os.path.isdir(tap_path):
            return packs
        packs = list(map(lambda x: x.replace(".rb", ""),
                         filter(lambda y: y.endswith(".rb"),
                                os.listdir(tap_path))))
        path = tap_path + "/Formula"
        if os.path.isdir(path):
            packs += list(map(lambda x: x.replace(".rb", ""),
                              filter(lambda y: y.endswith(".rb"),
                                     os.listdir(path))))
        return sorted(packs)

    def get_tap_casks(self, tap):
        """Helper for tap configuration file"""
        tap_path = self.get_tap_path(tap)
        casks = []
        if not os.path.isdir(tap_path):
            return casks
        path = tap_path + "/Casks"
        if os.path.isdir(path):
            casks = list(map(lambda x: x.replace(".rb", ""),
                             filter(lambda y: y.endswith(".rb"),
                                    os.listdir(tap_path + "/Casks"))))
        return sorted(casks)

    def get_leaves(self):
        leavestmp = self.helper.proc("brew leaves", False, False)[1]
        leaves = []
        for line in leavestmp:
            leaves.append(line.split("/")[-1])
        return leaves

    def get_info(self, package=""):
        if package == "":
            package = "--installed"
        infotmp = json.loads(
            ''.join(self.helper.proc("brew info --json=v1 " + package,
                                     print_cmd=False, print_out=False,
                                     exit_on_err=True, separate_err=True)[1]))
        info = {}
        for i in infotmp:
            info[i["name"]] = i
        return info

    def get_installed(self, package, package_info=""):
        """get installed version of brew package"""
        if not isinstance(package_info, dict):
            package_info = self.get_info(package)[package]

        installed = package_info["installed"][0]
        version = ""
        if package_info["linked_keg"] is None:
            version = self.helper.proc(
                "ls -l " + self.helper.brew_val("prefix") + "/opt/" + package,
                print_cmd=False, print_out=False, exit_on_err=False,
                separate_err=False)[1][0]
            version = version.split("/")[-1]
            if "No such file or directory" in version:
                version = ""
        else:
            version = package_info["linked_keg"]

        if version != "":
            for i in package_info["installed"]:
                if i["version"].replace(".reinstall", "") == version:
                    installed = i
                    break
        return installed

    def get_option(self, package, package_info=""):
        """get install options from brew info"""

        # Get options for build
        if not isinstance(package_info, dict):
            package_info = self.get_info(package)[package]

        opt = ""
        installed = self.get_installed(package, package_info)
        if installed["used_options"]:
            opt = " " + " ".join(installed["used_options"])
        for k, v in package_info["versions"].items():
            if installed["version"] == v and k != "stable":
                if k == "head":
                    opt += " --HEAD"
                else:
                    opt += " --" + k
        return opt

    def convert_option(self, opt):
        if opt != "" and self.helper.opt["form"] in ["brewdler", "bundle"]:
            opt = ", args: [" + ", ".join(
                ["'" + re.sub("^--", "", x) + "'" for x in opt.split()]) + "]"
        return opt

    def packout(self, pack):
        if self.helper.opt["form"] in ["brewdler", "bundle"]:
            return "'" + pack + "'"
        return pack

    def mas_pack(self, pack):
        if self.helper.opt["form"] in ["brewdler", "bundle"]:
            pack_split = pack.split()
            pid = pack_split[0]
            name = pack_split[1:]
            return "'" + ' '.join(name) + "', id: " + pid
        return pack

    def write(self):
        output_prefix = ""
        output = ""

        # commands for each format
        # if self.helper.opt["form"] in ["file", "none"]:
        cmd_before = "before "
        cmd_after = "after "
        cmd_other = ""
        cmd_install = "brew "
        cmd_tap = "tap "
        cmd_cask = "cask "
        cmd_cask_nocask = "#cask "
        cmd_appstore = "appstore "
        cmd_main = "main "
        cmd_file = "file "
        if self.helper.opt["form"] in ["brewdler", "bundle"]:
            cmd_before = "#before "
            cmd_after = "#after "
            cmd_other = "#"
            cmd_install = "brew "
            cmd_tap = "tap "
            cmd_cask = "cask "
            cmd_cask_nocask = "#cask "
            cmd_appstore = "mas "
            cmd_main = "#main "
            cmd_file = "#file "
        elif self.helper.opt["form"] in ["command", "cmd"]:
            # Shebang for command format
            output_prefix += """#!/usr/bin/env bash

#BREWFILE_IGNORE
if ! which brew >& /dev/null;then
  brew_installed=0
  echo Homebrew is not installed!
  echo Install now...
  echo /bin/bash -c \\\"\\$\\(curl -fsSL
https://raw.githubusercontent.com/Homebrew/
install/master/install.sh\\)\\\
  /bin/bash -c \"$(curl -fsSL
https://raw.githubusercontent.com/Homebrew/
install/master/install.sh)\
  echo
fi
#BREWFILE_ENDIGNORE

"""

            cmd_before = ""
            cmd_after = ""
            cmd_other = ""
            cmd_install = "brew install "
            cmd_tap = "brew tap "
            cmd_cask = "brew install "
            cmd_cask_nocask = "#brew install "
            cmd_appstore = "mas purchase "
            cmd_main = "#main "
            cmd_file = "#file "

        # sort
        self.sort()

        # Before commands
        if self.before_input:
            output += "# Before commands\n"
            for c in self.before_input:
                output += cmd_before + c + "\n"

        # Taps
        if self.tap_list:
            isfirst = True

            def first_tap_pack_write(isfirst, direct_first, isfirst_pack, tap,
                                     cmd_tap):
                output = ""
                if isfirst:
                    output += "\n# tap repositories and their packages\n"
                if not direct_first and isfirst_pack:
                    output += "\n" + cmd_tap + self.packout(tap) + "\n"
                return output

            for t in self.tap_list:
                isfirst_pack = True
                direct_first = False
                tap_packs = self.get_tap_packs(t)

                if t == "direct":
                    if not tap_packs:
                        continue
                    direct_first = True

                if not self.helper.opt["caskonly"]:
                    output += first_tap_pack_write(isfirst, direct_first,
                                                   isfirst_pack, t, cmd_tap)
                    isfirst = isfirst_pack = False

                    for p in self.brew_list[:]:
                        if p.split("/")[-1].replace(
                                ".rb", "") in tap_packs:
                            if direct_first:
                                direct_first = False
                                output += "\n## " + "Direct install\n"
                            pack = self.packout(p) +\
                                self.convert_option(self.brew_list_opt[p])
                            output += cmd_install + pack + "\n"
                            self.brew_list.remove(p)
                            del self.brew_list_opt[p]
                if not is_mac():
                    continue
                tap_casks = self.get_tap_casks(t)
                for p in self.cask_list[:]:
                    if p in tap_casks:
                        output += first_tap_pack_write(
                            isfirst, False, isfirst_pack, t, cmd_tap)
                        isfirst = isfirst_pack = False
                        output += cmd_cask + self.packout(p) + "\n"
                        self.cask_list.remove(p)

        # Brew packages
        if not self.helper.opt["caskonly"] and self.brew_list:
            output += "\n# Other Homebrew packages\n"
            for p in self.brew_list:
                pack = self.packout(p) +\
                    self.convert_option(self.brew_list_opt[p])
                output += cmd_install + pack + "\n"

        # Casks
        if is_mac() and self.cask_list:
            output += "\n# Other Cask applications\n"
            for c in self.cask_list:
                output += cmd_cask + self.packout(c) + "\n"

        # Installed by cask, but cask files were not found...
        if is_mac() and self.cask_nocask_list:
            output += "\n# Below applications were installed by Cask,\n"
            output += "# but do not have corresponding casks.\n\n"
            for c in self.cask_nocask_list:
                output += cmd_cask_nocask + self.packout(c) + "\n"

        # App Store applications
        if is_mac() and self.helper.opt["appstore"] \
                and self.appstore_list:
            output += "\n# App Store applications\n"
            for a in self.appstore_list:
                output += cmd_appstore + self.mas_pack(a) + "\n"

        # Main file
        if self.main_list:
            output += "\n# Main file\n"
            for f in self.main_list:
                output += cmd_main + self.packout(f) + "\n"

        # Additional files
        if len(self.file_list) > len(self.main_list):
            output += "\n# Additional files\n"
            for f in self.file_list:
                if f not in self.main_list:
                    output += cmd_file + self.packout(f) + "\n"

        # Other commands
        if self.cmd_input:
            output += "\n# Other commands\n"
            for c in self.cmd_input:
                output += cmd_other + c + "\n"

        # After commands
        if self.after_input:
            output += "\n# After commands\n"
            for c in self.after_input:
                output += cmd_after + c + "\n"

        # Write to Brewfile
        if output:
            output = output_prefix + output
            out = Tee(self.filename, sys.stdout,
                      self.helper.opt["verbose"] > 1)
            out.write(output)
            out.close()

        # Change permission for exe/normal file
        if self.helper.opt["form"] in ["command", "cmd"]:
            self.helper.proc(
                "chmod 755 %s" % self.filename, print_cmd=False,
                print_out=False, exit_on_err=False)
        else:
            self.helper.proc(
                "chmod 644 %s" % self.filename, print_cmd=False,
                print_out=False, exit_on_err=False)


class BrewFile:

    """Main class of Brew-file."""

    def __init__(self):
        """initialization."""

        # Set default values
        self.opt = {}

        # Prepare helper, need verbose first
        self.opt["verbose"] = int(
            os.environ.get("HOMEBREW_BREWFILE_VERBOSE", 1))
        self.helper = BrewHelper(self.opt)

        # Other default values
        self.opt["command"] = ""
        self.opt["input"] = os.environ.get("HOMEBREW_BREWFILE", "")
        brewfile_config = os.environ["HOME"] + "/.config/brewfile/Brewfile"
        brewfile_home = os.environ["HOME"] + "/.brewfile/Brewfile"
        if self.opt["input"] == "":
            if not os.path.isfile(brewfile_config) and\
                    os.path.isfile(brewfile_home):
                self.opt["input"] = brewfile_home
            else:
                self.opt["input"] = brewfile_config
        self.opt["backup"] = os.environ.get("HOMEBREW_BREWFILE_BACKUP", "")
        self.opt["leaves"] = to_bool(
            os.environ.get("HOMEBREW_BREWFILE_LEAVES", False))
        self.opt["on_request"] = to_bool(
            os.environ.get("HOMEBREW_BREWFILE_ON_REQUEST", False))
        self.opt["top_packages"] = os.environ.get(
            "HOMEBREW_BREWFILE_TOP_PACKAGES", "")
        self.opt["form"] = "none"
        self.opt["repo"] = ""
        self.opt["noupgradeatupdate"] = False
        self.opt["link"] = True
        self.opt["caskonly"] = False
        self.opt["dryrun"] = True
        self.opt["initialized"] = False
        self.opt["cask_repo"] = "homebrew/cask"
        self.opt["reattach_formula"] = "reattach-to-user-namespace"
        self.opt["mas_formula"] = "mas"
        self.opt["my_editor"] = os.environ.get(
            "HOMEBREW_BREWFILE_EDITOR", os.environ.get("EDITOR", "vim"))
        self.opt["is_brew_cmd"] = False
        self.opt["brew_cmd"] = ""
        self.opt["mas_cmd"] = "mas"
        self.opt["is_mas_cmd"] = 0
        self.opt["mas_cmd_installed"] = False
        self.opt["reattach_cmd_installed"] = False
        self.opt["args"] = []
        self.opt["yn"] = False
        self.opt["brew_packages"] = ""
        self.opt["homebrew_ruby"] = False

        # Check Homebrew
        self.check_brew_cmd()

        # Check Homebrew variables
        cask_opts = self.parse_env_opts(
            "HOMEBREW_CASK_OPTS", {"--appdir": "", "--fontdir": ""})

        if not os.path.isdir(self.brew_val("prefix") + "/Caskroom") and\
                os.path.isdir("/opt/homebrew-cask/Caskroom"):
            self.opt["caskroom"] = "/opt/homebrew-cask/Caskroom"
        else:
            self.opt["caskroom"] =\
                self.brew_val("prefix") + "/Caskroom"
        self.opt["appdir"] = cask_opts["--appdir"].rstrip("/") \
            if cask_opts["--appdir"] != ""\
            else os.environ["HOME"] + "/Applications"
        self.opt["appdirlist"] = ["/Applications",
                                  os.environ["HOME"] + "/Applications"]
        if self.opt["appdir"].rstrip("/") not in self.opt["appdirlist"]:
            self.opt["appdirlist"].append(self.opt["appdir"])
        self.opt["appdirlist"] += [x.rstrip("/") + "/Utilities"
                                   for x in self.opt["appdirlist"]]
        self.opt["appdirlist"] = [x for x in self.opt["appdirlist"]
                                  if os.path.isdir(x)]
        # fontdir may be used for application search, too
        self.opt["fontdir"] = cask_opts["--fontdir"]

        self.opt["appstore"] = to_num(
            os.environ.get("HOMEBREW_BREWFILE_APPSTORE", -1))

        self.opt["no_appstore"] = to_num(
            os.environ.get("HOMEBREW_BREWFILE_APPSTORE", 1))

        self.int_opts = ["verbose"]
        self.float_opts = []

        self.brewinfo = BrewInfo(self.helper, self.opt["input"])
        self.brewinfo_ext = []
        self.brewinfo_main = self.brewinfo
        self.opt["read"] = False

        self.pack_deps = {}
        self.top_packs = []

        self.editor = ""

    def parse_env_opts(self, env_var, base_opts=None):
        """Returns a dictionary parsed from an environment variable"""

        if base_opts is not None:
            opts = base_opts.copy()
        else:
            opts = {}

        env_var = env_var.upper()
        env_opts = os.environ.get(env_var, None)
        if env_opts:

            # these can be flags ("--flag") or values ("--key=value")
            # but not weirdness ("--foo=bar=baz")
            user_opts = {key.lower(): value for (key, value) in
                         [pair.partition("=")[::2] for pair in env_opts.split()
                          if pair.count("=") < 2]}

            if user_opts:
                opts.update(user_opts)
            else:
                self.warn("%s: \"%s\" is not a proper format." %
                          (env_var, env_opts), 0)
                self.warn("Ignoring the value.\n", 0)

        return opts

    def set_args(self, **kw):
        """Set arguments."""
        for k, v in kw.items():
            self.opt[k] = v

        for k in self.int_opts:
            self.opt[k] = int(self.opt[k])
        for k in self.float_opts:
            self.opt[k] = float(self.opt[k])

        # fix appstore option
        appstore = 1
        if self.opt["appstore"] != -1:
            appstore = self.opt["appstore"]
        elif not self.opt["no_appstore"]:
            appstore = 0
        self.opt["appstore"] = to_num(appstore)

        self.brewinfo.filename = self.opt["input"]

    def ask_yn(self, question):
        """Helper for yes/no."""
        if self.opt["yn"]:
            print(question + " [y/n]: y")
            return True

        yes = ["yes", "y", ""]
        no = ["no", "n"]

        yn = input(question + " [y/n]: ").lower()
        while True:
            if yn in yes:
                return True
            if yn in no:
                return False
            yn = input("Answer with yes (y) or no (n): ").lower()

    def verbose(self):
        try:
            v = self.opt["verbose"]
        except KeyError:
            v = 10
        return v

    def proc(self, cmd, print_cmd=True, print_out=True,
             exit_on_err=True, separate_err=False, print_err=True,
             verbose=1, env={"HOMEBREW_NO_AUTO_UPDATE": "1"}):
        return self.helper.proc(
            cmd=cmd, print_cmd=print_cmd, print_out=print_out,
            exit_on_err=exit_on_err, separate_err=separate_err,
            print_err=print_err, verbose=verbose, env=env)

    def info(self, text, verbose=2):
        self.helper.info(text, verbose)

    def warn(self, text, verbose=1):
        self.helper.warn(text, verbose)

    def err(self, text, verbose=1):
        self.helper.err(text, verbose)

    def banner(self, text, verbose=1):
        self.helper.banner(text, verbose)

    def remove(self, path):
        """Helper to remove file/directory."""
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            self.warn("Tried to remove non usual file/directory:" + path, 0)

    def brew_val(self, name):
        return self.helper.brew_val(name)

    def read_all(self, force=False):
        if not force and self.opt["read"]:
            return
        self.brewinfo_ext = [self.brewinfo]
        self.brewinfo_main = self.read(self.brewinfo, is_main=True)
        if self.brewinfo_main in self.brewinfo_ext:
            self.brewinfo_ext.remove(self.brewinfo_main)
        if self.opt["mas_cmd_installed"]:
            p = os.path.basename(self.opt["mas_formula"])
            if p not in self.get("brew_input"):
                self.brewinfo_main.brew_input.append(p)
                self.brewinfo_main.brew_input_opt[p] = ""
        if self.opt["reattach_cmd_installed"]:
            p = os.path.basename(self.opt["reattach_formula"])
            if p not in self.get("brew_input"):
                self.brewinfo_main.brew_input.append(p)
                self.brewinfo_main.brew_input_opt[p] = ""
        self.opt["read"] = True

    def read(self, brewinfo, is_main=False):
        if is_main:
            main = brewinfo
        else:
            main = None
        brewinfo.read()
        files = brewinfo.get_files()
        for f in files['ext']:
            is_next_main = f in files['main']
            f = expandpath(f)
            if os.path.isabs(f):
                b = BrewInfo(self.helper, f)
            else:
                this_dir = brewinfo.get_dir()
                if not this_dir:
                    path_prefix = './'
                else:
                    path_prefix = this_dir + '/'
                b = BrewInfo(self.helper, path_prefix + f.lstrip('./'))
            self.brewinfo_ext.append(b)
            if main is not None and is_next_main:
                main = b
                main_tmp = self.read(b, True)
            else:
                main_tmp = self.read(b, False)
            if main_tmp is not None:
                main = main_tmp
        return main

    def list_to_main(self):
        if self.brewinfo == self.brewinfo_main:
            return
        self.brewinfo_main.add("brew_list", self.brewinfo.brew_list)
        self.brewinfo_main.add("brew_full_list", self.brewinfo.brew_list)
        self.brewinfo_main.add("tap_list", self.brewinfo.tap_list)
        self.brewinfo_main.add("cask_list", self.brewinfo.cask_list)
        self.brewinfo_main.add("cask_nocask_list", self.brewinfo.cask_list)
        self.brewinfo_main.add("appstore_list", self.brewinfo.appstore_list)
        self.brewinfo_main.add("brew_list_opt", self.brewinfo.brew_list_opt)

    def input_to_list(self, only_ext=False):
        if not only_ext:
            self.brewinfo_main.input_to_list()
        for b in self.brewinfo_ext:
            b.input_to_list()

    def write(self):
        self.banner("# Initialize " + self.brewinfo_main.filename)
        self.brewinfo_main.write()
        for b in self.brewinfo_ext:
            self.banner("# Initialize " + b.filename)
            b.write()

    def get(self, name, only_ext=False):
        list_copy = self.brewinfo_main.get(name)
        if isinstance(list_copy, list):
            if only_ext:
                del list_copy[:]
            for b in self.brewinfo_ext:
                list_copy += b.get(name)
        elif isinstance(list_copy, dict):
            if only_ext:
                list_copy.clear()
            for b in self.brewinfo_ext:
                list_copy.update(b.get(name))
        return list_copy

    def remove_pack(self, name, package):
        if package in self.brewinfo_main.get(name):
            self.brewinfo_main.remove(name, package)
        else:
            for b in self.brewinfo_ext:
                if package in b.get(name):
                    b.remove(name, package)

    def repo_name(self):
        return self.opt["repo"].split("/")[-1].split(".git")[0]

    def user_name(self):
        try:
            user = self.opt["repo"].split("/")[-2].split(":")[-1]
        except Exception:
            user = self.proc(
                "git config --get github.user", print_cmd=False,
                print_out=False, exit_on_err=False, separate_err=False)[1]
            if user:
                user = user[0]
            else:
                user = self.proc(
                    "git config --get user.name", print_cmd=False,
                    print_out=False, exit_on_err=False, separate_err=False)[1]
                if user:
                    user = user[0]
                else:
                    user = ""
            if user == "":
                self.err("Can not find git (github) user name")
                sys.exit(1)
        return user

    def input_dir(self):
        return os.path.dirname(self.opt["input"])

    def input_file(self):
        return self.opt["input"].split("/")[-1]

    def repo_file(self):
        """Helper to build Brewfile path for the repository."""
        return self.input_dir() + "/" +\
            self.user_name() + "_" + self.repo_name() + "/" + self.input_file()

    def init_repo(self):
        dirname = self.brewinfo.get_dir()
        os.chdir(dirname)
        branches = self.proc("git branch", print_cmd=False, print_out=False,
                             exit_on_err=True, separate_err=True)[1]
        if branches:
            return

        self.info("Initialize the repository with README.md/Brewfile.", 1)
        if not os.path.exists("README.md"):
            f = open("README.md", "w")
            f.write(
                "# " + self.repo_name() + "\n\n"
                "Package list for [homebrew](http://brew.sh/).\n\n"
                "Managed by "
                "[homebrew-file](https://github.com/rcmdnk/homebrew-file).")
            f.close()
        open(self.brewinfo.filename, "a").close()

        if self.check_gitconfig():
            self.proc("git add -A")
            self.proc(["git", "commit", "-m",
                       "\"Prepared by " + __prog__ + "\""])
            self.proc("git push -u origin master")

    def clone_repo(self, exit_on_err=True):
        ret = self.proc(
            "git clone " + self.opt["repo"] + " \"" + self.brewinfo.get_dir()
            + "\"", print_cmd=True, print_out=True, exit_on_err=False)[0]
        if ret != 0:
            if exit_on_err:
                self.err(
                    "can nott clone " + self.opt["repo"] + ".\n"
                    "please check the repository, or reset with\n"
                    "    $ " + __prog__ + " set_repo", 0)
                sys.exit(ret)
            else:
                return False
        self.init_repo()
        return True

    def check_github_repo(self):
        """helper to check and create GitHub repository."""

        # Check if the repository already exists or not.
        if self.clone_repo(exit_on_err=False):
            return

        # Create new repository #
        print("GitHub repository: " + self.user_name() + "/"
              + self.repo_name() + " doesn't exist.")
        print("Please create the repository first, then try again")
        sys.exit(1)

    def check_local_repo(self):
        dirname = self.opt["repo"].replace("file:///", "")
        if not os.path.isdir(dirname):
            os.makedirs(dirname)
        os.chdir(dirname)
        self.proc("git init --bare")
        self.clone_repo()

    def check_repo(self):
        """Check input file for Git repository."""
        # Check input file
        if not os.path.exists(self.opt["input"]):
            return

        self.brewinfo.filename = self.opt["input"]

        # Check input file if it points repository or not
        self.opt["repo"] = ""
        f = open(self.opt["input"], "r")
        lines = f.readlines()
        f.close()
        for line in lines:
            if re.match(" *git ", line) is None:
                continue
            git_line = line.split()
            if len(git_line) > 1:
                self.opt["repo"] = git_line[1]
                break
        if self.opt["repo"] == "":
            return

        # Check repository name and add git@github.com: if necessary
        if ("@" not in self.opt["repo"]
                and not self.opt["repo"].startswith("git://")
                and not self.opt["repo"].startswith("http://")
                and not self.opt["repo"].startswith("file:///")
                and not self.opt["repo"].startswith("/")):
            self.opt["repo"] = "git@github.com:" + self.user_name() \
                + "/" + self.repo_name()

        # Set Brewfile in the repository
        self.brewinfo.filename = self.repo_file()

        # If repository does not have a branch, make it
        if self.brewinfo.check_dir():
            self.init_repo()
            return

        # Check and prepare repository
        if "github" in self.opt["repo"]:
            self.check_github_repo()
        elif (self.opt["repo"].startswith("file:///")
              or self.opt["repo"].startswith("/")):
            self.check_local_repo()
        else:
            self.clone_repo()

    def check_gitconfig(self):
        if (self.opt["repo"].startswith("git://")
                or self.opt["repo"].startswith("http")):
            self.info(
                "You are using repository of %s" % self.opt["repo"]
                + "\nUse ssh protocol to push your Brewfile update.", 0)
            return False
        name = self.proc("git config user.name", print_cmd=False,
                         print_out=False, exit_on_err=False,
                         separate_err=True)[1]
        email = self.proc(
            "git config user.email", print_cmd=False, print_out=False,
            exit_on_err=False, separate_err=True)[1]
        if not name or not email:
            self.warn(
                "You don't have user/email information in your .gitconfig.\n"
                "To commit and push your update, run\n"
                '  git config --global user.email "you@example.com"\n'
                '  git config --global user.name "Your Name"\n'
                'and try again.', 0)
            return False
        return True

    def repomgr(self, cmd="pull"):
        """Helper of repository management."""

        # Check the repository
        if self.opt["repo"] == "":
            self.err("Please set a repository, or reset with:", 0)
            self.err("    $ " + __prog__ + " set_repo\n", 0)
            sys.exit(1)

        # Clone if it doesn't exist
        if not self.brewinfo.check_dir():
            self.clone_repo()

        # pull/push
        self.info(f"$ cd {self.brewinfo.get_dir()}", 1)
        os.chdir(self.brewinfo.get_dir())

        ret, lines = self.proc("git status -s -uno", print_cmd=False,
                               print_out=False, exit_on_err=True)
        if ret != 0:
            self.err('\n'.join(lines))
            sys.exit(ret)
        if (lines):
            if self.check_gitconfig():
                self.proc("git add -A")
                self.proc(["git", "commit", "-m",
                           "\"Update the package list\""],
                          exit_on_err=False)

        self.proc(f"git {cmd}")

    def brew_cmd(self):
        noinit = False
        if self.opt["args"] and "noinit" in self.opt["args"]:
            noinit = True
            self.opt["args"].remove("noinit")

        exe = ["brew"]
        cmd = self.opt["args"][0] if self.opt["args"] else ""
        subcmd = self.opt["args"][1] if len(self.opt["args"]) > 1 else ""
        args = self.opt["args"]
        env = {}
        if cmd == "mas":
            exe = ["mas"]
            self.opt["args"].pop(0)
            if subcmd == "uninstall":
                exe = ["sudo", "mas"]
            package = self.opt["args"][1:] if len(self.opt["args"]) > 1 else ""
            if self.check_mas_cmd(True) != 1:
                self.err("\n'mas' command is not available.\n")
                if package:
                    self.err("Please install 'mas' or "
                             f"{subcmd} {' '.join(package)} manually", 0)

        ret, lines = self.proc(
            exe + self.opt["args"], print_cmd=False, print_out=True,
            exit_on_err=False, env=env)

        if (noinit or (cmd == "mas" and subcmd != "uninstall"
                       and self.opt["appstore"] != 1)) \
                or (ret != 0 and "Not installed" not in ' '.join(lines)
                    and "No installed keg or cask with the name"
                    not in ' '.join(lines)):
            sys.exit(ret)

        if cmd in ["cask"]:
            args = self.opt["args"][2:]
        else:
            args = self.opt["args"][1:]
        nargs = len(args)

        if cmd not in ["instal", "install", "reinstall", "tap",
                       "rm", "remove", "uninstall", "untap", "cask", "mas"] \
                or nargs == 0 \
                or (cmd == "cask" and subcmd not in
                    ["instal", "install", "rm", "remove", "uninstall"]) \
                or (cmd == "mas" and subcmd not in
                    ["purchase", "install", "uninstall"]):
            # Not install/remove command, no init.
            sys.exit(0)

        self.initialize(check=False)

    def check_brew_cmd(self):
        """Check Homebrew"""
        if self.opt["is_brew_cmd"]:
            return True

        ret, cmd = self.proc("which brew", print_cmd=False, print_out=False,
                             exit_on_err=False, verbose=1)
        if ret == 0:
            self.opt["brew_cmd"] = cmd[0]
            self.opt["is_brew_cmd"] = True
            return True

        if ret != 0:
            print("Homebrew has not been installed, install now...")
            cmd = "curl -O https://raw.githubusercontent.com/" \
                + "Homebrew/install/master/install.sh"
            self.proc(cmd, print_cmd=True, print_out=True, exit_on_err=False,
                      verbose=0)
            cmd = "bash install.sh"
            self.proc(cmd, print_cmd=True, print_out=True, exit_on_err=False,
                      verbose=0)
            cmd = "rm -f install.sh"
            self.proc(cmd, print_cmd=True, print_out=True, exit_on_err=False,
                      verbose=0)
            ret, lines = self.proc("brew doctor", print_cmd=True,
                                   print_out=True, exit_on_err=False,
                                   verbose=0)
            if ret != 0:
                for line in lines:
                    sys.stdout.write(line)
                self.warn("\n\nCheck brew environment and fix problems\n"
                          "# You can check with:\n"
                          "#     $ brew doctor", 0)
                return False
            ret, cmd = self.proc("which brew", print_cmd=False,
                                 print_out=False, exit_on_err=False,
                                 verbose=1)
            if ret == 0:
                self.opt["brew_cmd"] = cmd[0]
                self.opt["is_brew_cmd"] = True
                return True
        return False

    def check_mas_cmd(self, force=False):
        """Check mas is installed or not"""
        if self.opt["is_mas_cmd"] != 0:
            return self.opt["is_mas_cmd"]

        if not is_mac():
            print("mas is not available on Linux!")
            sys.exit(1)

        if self.proc("type mas", print_cmd=False, print_out=False,
                     exit_on_err=False)[0] != 0:
            sw_vers = self.proc(
                "sw_vers -productVersion", print_cmd=False, print_out=False,
                exit_on_err=False)[1][0].split(".")
            if int(sw_vers[0]) < 10 or (int(sw_vers[0]) == 10
                                        and int(sw_vers[1]) < 11):
                self.warn("You are using older OS X. mas is not used.", 3)
                self.opt["is_mas_cmd"] = -1
                return self.opt["is_mas_cmd"]
            self.info(self.opt["mas_formula"] + " has not been installed.")
            if not force:
                ans = self.ask_yn("Do you want to install %s?" %
                                  self.opt["mas_formula"])
                if not ans:
                    self.warn("If you need it, please do:")
                    self.warn("    $ brew install %s"
                              % (self.opt["mas_formula"]))
                    self.opt["is_mas_cmd"] = -2
                    return self.opt["is_mas_cmd"]
            ret = self.proc(["brew", "install", self.opt["mas_formula"]],
                            print_cmd=True, print_out=True,
                            exit_on_err=False)[0]
            if ret != 0:
                self.err("\nFailed to install "
                         + self.opt["mas_formula"] + "\n", 0)
                self.opt["is_mas_cmd"] = -1
                return self.opt["is_mas_cmd"]
            p = os.path.basename(self.opt["mas_formula"])
            if p not in self.get("brew_list"):
                self.brewinfo.brew_list.append(p)
                self.brewinfo.brew_list_opt[p] = ""

        if self.proc(self.opt["mas_cmd"], print_cmd=False, print_out=False,
                     exit_on_err=False)[0] != 0:
            sys.exit(1)

        if self.proc(self.opt["mas_cmd"] + " account", print_cmd=False,
                     print_out=False, exit_on_err=False)[0] != 0:
            self.err("\nPlease sign in to the App Store", 0)
            sys.exit(1)

        self.opt["is_mas_cmd"] = 1

        is_tmux = os.environ.get("TMUX", "")
        if is_tmux != "":
            if self.proc("type reattach-to-user-namespace",
                         print_cmd=False, print_out=False,
                         exit_on_err=False)[0] != 0:
                if not force:
                    ans = self.ask_yn(
                        "You need %s in tmux. Do you want to install it?" %
                        self.opt["reattach_formula"])
                    if not ans:
                        self.warn("If you need it, please do:")
                        self.warn("    $ brew install %s"
                                  % (self.opt["reattach_formula"]))
                        return self.opt["is_mas_cmd"]
                ret = self.proc(
                    ["brew", "install", self.opt["reattach_formula"]],
                    print_cmd=True, print_out=True, exit_on_err=False)[0]
                if ret != 0:
                    self.err("\nFailed to install "
                             + self.opt["reattach_formula"] + "\n", 0)
                    self.opt["is_mas_cmd"] = -1
                    return self.opt["is_mas_cmd"]
                p = os.path.basename(self.opt["reattach_formula"])
                if p not in self.get("brew_list"):
                    self.brewinfo.brew_list.append(p)
                    self.brewinfo.brew_list_opt[p] = ""
                self.opt["reattach_cmd_installed"] = True
            self.opt["mas_cmd"] = "reattach-to-user-namespace mas"

        return self.opt["is_mas_cmd"]

    def get_appstore_list(self):
        """Get AppStore Application List"""

        apps = []

        if self.check_mas_cmd(True) == 1:
            lines = self.proc(self.opt["mas_cmd"] + " list", print_cmd=False,
                              print_out=False, separate_err=True)[1]
            apps = sorted(lines, key=lambda x: " ".join(x.split()[1:]).lower())
            if apps and apps[0] == "No installed apps found":
                apps = []
        else:
            apps_tmp = []
            for d in self.opt["appdirlist"]:
                apps_tmp += [
                    ("/".join(x.split("/")[:-3]).split(".app")[0])
                    for x in glob.glob(d + "/*/Contents/_MASReceipt/receipt")]
            # Another method
            # Sometime it can not find applications which have not been used?
            # (ret, app_tmp) = self.proc(
            #     "mdfind 'kMDItemAppStoreHasReceipt=1'", print_cmd=False,
            #     print_out=False)
            for a in apps_tmp:
                apps_id = self.proc(
                    "mdls -name kMDItemAppStoreAdamID -raw '%s.app'" % a,
                    print_cmd=False, print_out=False)[1][0]
                apps.append("%s %s" %
                            (apps_id, a.split("/")[-1].split(".app")[0]))

        return apps

    def get_cask_list(self):
        """Get Cask List"""

        lines = self.proc("brew list --cask", print_cmd=False, print_out=False,
                          separate_err=True, print_err=False)[1]
        packages = []
        for line in lines:
            if "Warning: nothing to list" in line or "=>" in line \
                    or "->" in line:
                continue
            packages.append(line)
        return (True, packages)

    def get_list(self, force_appstore_list=False):
        """Get Installed Package List"""

        # Clear lists
        self.brewinfo.clear_list()

        # Brew packages
        if not self.opt["caskonly"]:
            info = self.brewinfo.get_info()
            full_list = self.proc("brew list --formula", print_cmd=False,
                                  print_out=False)[1]
            del self.brewinfo.brew_full_list[:]
            self.brewinfo.brew_full_list.extend(full_list)
            if self.opt["on_request"]:
                leaves = []
                for p in info:
                    installed = self.brewinfo.get_installed(p, info[p])
                    if installed["installed_on_request"] is True or\
                            installed["installed_on_request"] is None:
                        leaves.append(p)

            elif self.opt["leaves"]:
                leaves = self.brewinfo.get_leaves()
            else:
                leaves = copy.deepcopy(full_list)

            for p in self.opt["top_packages"].split(","):
                if p == "":
                    continue
                if p in full_list and p not in leaves:
                    leaves.append(p)

            for p in info:
                if p not in leaves:
                    continue
                self.brewinfo.brew_list.append(p)
                self.brewinfo.brew_list_opt[p] =\
                    self.brewinfo.get_option(p, info[p])

        # Taps
        lines = self.proc("brew tap", print_cmd=False, print_out=False,
                          env={"HOMEBREW_NO_AUTO_UPDATE": "1"})[1]

        self.brewinfo.set_val("tap_list", lines)
        self.brewinfo.add("tap_list", ["direct"])

        # Casks
        if is_mac():
            for p in self.get_cask_list()[1]:
                if len(p.split()) == 1:
                    self.brewinfo.cask_list.append(p)
                else:
                    self.warn("The cask file of " + p
                              + " doesn't exist.", 0)
                    self.warn("Please check later.\n\n", 0)
                    self.brewinfo.cask_nocask_list.append(p)

        # App Store
        if is_mac():
            if self.opt["appstore"] == 1 \
                    or (self.opt["appstore"] == 2 and force_appstore_list):
                self.brewinfo.set_val("appstore_list",
                                      self.get_appstore_list())
            elif self.opt["appstore"] == 2:
                if self.brewinfo.check_file():
                    self.read_all()
                self.brewinfo.set_val("appstore_list",
                                      self.get("appstore_input"))

    def clean_list(self):
        """Remove duplications between brewinfo.list to extra files' input"""

        # Cleanup extra files
        for b in self.brewinfo_ext + [self.brewinfo_main]:
            for line in ["brew", "tap", "cask", "appstore"]:
                for p in b.get(line + "_input"):
                    if p not in self.brewinfo.get(line + "_list"):
                        b.remove(line + "_input", p)

        # Copy list to main file
        self.list_to_main()

        # Loop over lists to remove duplications.
        # tap_list is not checked for overlap removal.
        # Keep it in main list in any case.
        for name in ["brew", "cask", "cask_nocask", "appstore"]:
            if name == "cask_nocask":
                i = "cask"
            else:
                i = name
            for p in self.brewinfo_main.get(name + "_list"):
                if p in self.get(i + "_input", True):
                    self.brewinfo_main.remove(name + "_list", p)

        # Keep mian/file in main Brewfile
        self.brewinfo_main.add("main_list", self.brewinfo_main.main_input)
        self.brewinfo_main.add("file_list", self.brewinfo_main.file_input)

        # Copy input to list for extra files.
        self.input_to_list(only_ext=True)

    def input_backup(self):
        if self.opt["backup"] != "":
            os.rename(self.opt["input"], self.opt["backup"])
            self.info("Old input file was moved to " + self.opt["backup"], 1)
        else:
            ans = self.ask_yn("Do you want to overwrite it?")
            if not ans:
                sys.exit(0)

    def set_brewfile_repo(self):
        """Set Brewfile repository"""

        # Check input file
        if os.path.exists(self.opt["input"]):
            prev_repo = ""
            f = open(self.opt["input"], "r")
            lines = f.readlines()
            f.close()
            for line in lines:
                if re.match(" *git ", line) is None:
                    continue
                git_line = line.split()
                if len(git_line) > 1:
                    prev_repo = git_line[1]
                    break
            if self.opt["repo"] == "":
                print("Input file: " + self.opt["input"]
                      + " is already there.")
                if prev_repo != "":
                    print("git repository for Brewfile is already set as "
                          + prev_repo + ".")

            self.input_backup()

        # Get repository
        if self.opt["repo"] == "":
            print("\nSet repository,\n"
                  "\"non\" (or empty) for local Brewfile "
                  "(" + self.opt["input"] + "),\n"
                  "/path/to/repo for local git repository,\n"
                  "https://your/git/repository "
                  "(or ssh://user@server.project.git) for git repository,\n"
                  "or (<user>/)<repo> for github repository,")
            self.opt["repo"] = input(
                "or full path for other git repository: ")
            self.banner("# Set Brewfile repository as "
                        + self.opt["repo"])

        if self.opt["repo"] in ["non", ""]:
            self.set_brewfile_local()
        else:
            # Write repository to the input file
            f = open_output_file(self.opt["input"], "w")
            f.write("git " + self.opt["repo"])
            f.close()
            self.check_repo()

    def set_brewfile_local(self):
        """Set Brewfile to local file"""
        self.opt["repo"] = ""
        self.initialize(check=False, check_input=False)

    def initialize(self, check=True, check_input=True):
        """Initialize Brewfile"""
        if self.opt["initialized"]:
            return

        if check:
            if not os.path.exists(self.opt["input"]):
                ans = self.ask_yn("Do you want to set a repository (y)? "
                                  "((n) for local Brewfile).")
                if ans:
                    self.set_brewfile_repo()
            else:
                if self.opt["repo"] != "":
                    print("You are using Brewfile of " + self.opt["repo"]
                          + ".")
                else:
                    print(self.opt["input"] + " is already there.")
                    self.input_backup()

        # Get installed package list
        self.get_list()

        # Read inputs
        if check_input:
            if self.brewinfo.check_file():
                self.read_all()

            # Remove duplications between brewinfo.list to extra files' input
            self.clean_list()

        # write out
        self.initialize_write()

    def initialize_write(self):
        self.write()
        self.banner("# You can edit " + self.brewinfo.filename + " with:\n"
                    "#     $ " + __prog__ + " edit")
        self.opt["initialized"] = True

    def check_input_file(self):
        """Check input file"""

        if not self.brewinfo.check_file():
            self.warn(
                "Input file " + self.brewinfo.filename + " is not found.", 0)
            ans = self.ask_yn(
                "Do you want to initialize from installed packages?")
            if ans:
                self.initialize(check=False)
                return

            self.err("Ok, please prepare brewfile", 0)
            self.err("or you can initialize "
                     + self.brewinfo.filename + " with:", 0)
            self.err("    $ " + __prog__ + " init", 0)
            sys.exit(1)

    def get_files(self, is_print=False):
        """Get Brewfiles"""
        self.read_all()
        files = [x.filename for x in [self.brewinfo_main] + self.brewinfo_ext]
        if is_print:
            print("\n".join(files))
        return files

    def edit_brewfile(self):
        """Edit brewfiles"""
        if not self.editor:
            self.editor = shlex.split(self.opt["my_editor"])
        subprocess.call(self.editor + self.get_files())

    def cat_brewfile(self):
        """Cat brewfiles"""
        subprocess.call(["cat"] + self.get_files())

    def clean_non_request(self):
        """Clean up non requested packages."""
        if self.opt["dryrun"]:
            self.banner("# This is dry run.")

        info = self.brewinfo.get_info()
        leaves = self.brewinfo.get_leaves()
        for p in info:
            if p not in leaves:
                continue
            installed = self.brewinfo.get_installed(p, info[p])
            if installed["installed_on_request"] is False:
                cmd = "brew uninstall " + p
                if self.opt["dryrun"]:
                    print(cmd)
                else:
                    self.proc(cmd, print_cmd=False, print_out=True)

        if self.opt["dryrun"]:
            self.banner("# This is dry run.\n"
                        "# If you want to enforce cleanup, use '-C':\n"
                        "#     $ " + __prog__ + " clean_non_request -C")

    def cleanup(self):
        """Clean up."""
        if self.opt["dryrun"]:
            self.banner("# This is dry run.")

        # Get installed package list
        self.get_list()

        # Check up packages in the input file
        self.read_all()
        info = self.brewinfo.get_info()

        def add_dependncies(package):
            for pac in info[package]["dependencies"]:
                p = pac.split("/")[-1]
                if p not in info:
                    continue
                if p not in self.get("brew_input"):
                    self.brewinfo.brew_input.append(p)
                    self.brewinfo.brew_input_opt[p] = ""
                    add_dependncies(p)
        for p in self.get("brew_input"):
            if p not in info:
                continue
            add_dependncies(p)

        # Clean up App Store applications
        if self.opt["appstore"] == 1 and self.get("appstore_list"):
            self.banner("# Clean up App Store applications")

            for p in self.get("appstore_list"):
                identifier = p.split()[0]
                if identifier.isdigit():
                    package = " ".join(p.split()[1:])
                else:
                    identifier = ""
                    package = p
                if re.match(r".*\(\d+\.\d+.*\)$", package):
                    package = ' '.join(package.split(' ')[:-1])

                isinput = False
                for pi in self.get("appstore_input"):
                    i_identifier = pi.split()[0]
                    if i_identifier.isdigit():
                        i_package = " ".join(pi.split()[1:])
                    else:
                        i_identifier = ""
                        i_package = pi
                    if re.match(r".*\(\d+\.\d+.*\)$", i_package):
                        i_package = ' '.join(i_package.split(' ')[:-1])
                    if (identifier != "" and identifier == i_identifier) \
                            or package == i_package:
                        isinput = True
                        break
                if isinput:
                    continue

                if identifier and self.check_mas_cmd(True) == 1:
                    cmd = "sudo " + self.opt["mas_cmd"] + " uninstall " \
                        + identifier
                else:
                    uninstall = self.proc("type uninstall", print_cmd=False,
                                          print_out=False, exit_on_err=False)
                    if uninstall == 0:
                        cmd = "sudo uninstall"
                    else:
                        cmd = "sudo rm -rf"
                    tmpcmd = cmd
                    for d in self.opt["appdirlist"]:
                        a = "%s/%s.app" % (d, package)
                        if os.path.isdir(a):
                            if uninstall == 0:
                                cmd += " file:///" + quote(a)
                            else:
                                cmd += " '%s'" % a
                            continue
                    if cmd == tmpcmd:
                        self.warn(f"Package {package} was not found:"
                                  "nothing to do.\n")
                        self.remove_pack("appstore_list", p)
                        continue
                if self.opt["dryrun"]:
                    print(cmd)
                else:
                    self.proc(cmd, print_cmd=True, print_out=True,
                              exit_on_err=False)
                self.remove_pack("appstore_list", p)

        # Clean up cask packages
        if is_mac() and self.get("cask_list"):
            self.banner("# Clean up cask packages")
            for p in self.get("cask_list"):
                if p in self.get("cask_input"):
                    continue
                cmd = "brew uninstall " + p
                if self.opt["dryrun"]:
                    print(cmd)
                else:
                    self.proc(cmd, print_cmd=True, print_out=True)
                self.remove_pack("cask_list", p)

        # Skip clean up cask at tap if any cask packages exist
        if is_mac() and self.get("cask_list"):
            self.remove_pack("tap_list", self.opt["cask_repo"])

        # Clean up brew packages
        if self.get("brew_list"):
            self.banner("# Clean up brew packages")
            for p in self.get("brew_list"):
                if p in self.get("brew_input"):
                    continue
                # Use --ignore-dependencies option to remove packages w/o
                # formula (tap of which could be removed before).
                cmd = "brew uninstall --ignore-dependencies " + p
                if self.opt["dryrun"]:
                    print(cmd)
                else:
                    self.proc(cmd, print_cmd=False, print_out=True)

        # Clean up tap packages
        if self.get("tap_list"):
            self.banner("# Clean up tap packages")
            for p in self.get("tap_list"):
                if p in self.get("tap_input"):
                    continue
                untapflag = True
                for tp in self.brewinfo.get_tap_packs(p):
                    if tp in self.get("brew_input"):
                        # Keep the Tap as related package is remained
                        untapflag = False
                        break
                if not untapflag:
                    continue
                if is_mac():
                    for tc in self.brewinfo.get_tap_casks(p):
                        if tc in self.get("cask_input"):
                            # Keep the Tap as related cask is remained
                            untapflag = False
                            break
                if not untapflag:
                    continue
                cmd = "brew untap " + p
                if self.opt["dryrun"]:
                    print(cmd)
                else:
                    self.proc(cmd, print_cmd=True, print_out=True)

        # Clean up cashe
        self.banner("# Clean up cache")
        cmd0 = "brew cleanup"
        cmd1 = "rm -rf " + self.brew_val("cache")
        if self.opt["dryrun"]:
            print(cmd0)
            print(cmd1)
        else:
            self.proc(cmd0, print_cmd=True, print_out=True)
            self.proc(cmd1, print_cmd=True, print_out=True)

        if self.opt["dryrun"]:
            # Dry run message
            self.banner("# This is dry run.\n"
                        "# If you want to enforce cleanup, use '-C':\n"
                        "#     $ " + __prog__ + " clean -C")

    def install(self):
        """Install"""
        # Reinit flag
        reinit = 0

        # Get installed package list
        self.get_list(force_appstore_list=True)

        # Check packages in the input file
        self.read_all()

        # before commands
        for c in self.get("before_input"):
            self.proc(c)

        # Tap
        for p in self.get("tap_input"):
            if p in self.get("tap_list") or p == "direct":
                continue
            self.proc("brew tap " + p)

        # Cask
        if is_mac():
            for p in self.get("cask_input"):
                if p in self.get("cask_list"):
                    continue
                self.proc("brew install --cask --force " + p)

        # brew
        if not self.opt["caskonly"]:
            # Brew
            for p in self.get("brew_input"):
                cmd = "install"
                if p in self.get("brew_full_list"):
                    if p not in self.get("brew_list_opt") \
                            or sorted(self.get("brew_input_opt")[p].split()) \
                            == sorted(self.get("brew_list_opt")[p].split()):
                        continue
                    else:
                        cmd = "reinstall"
                ret, lines = self.proc("brew " + cmd + " " + p
                                       + self.get("brew_input_opt")[p])
                if ret != 0:
                    self.warn("Can not install " + p + "."
                              "Please check the package name.\n"
                              "" + p + " may be installed "
                              "by using web direct formula.", 0)
                    continue
                for line in lines:
                    if line.find("ln -s") != -1:
                        if self.opt["link"]:
                            cmdtmp = line.split()
                            cmd = []
                            for c in cmdtmp:
                                cmd.append(expandpath(c))
                            self.proc(cmd)
                    if line.find("brew linkapps") != -1:
                        if self.opt["link"]:
                            self.proc("brew linkapps")
                if p in self.get("brew_list") and\
                        self.get("brew_input_opt")[p] !=\
                        self.get("brew_list_opt")[p]:
                    self.brewinfo.add("brew_input_opt",
                                      {p: self.brewinfo.get_option(p)})
                    reinit = 1

        # App Store
        if is_mac() and self.opt["appstore"]:
            for p in self.get("appstore_input"):
                if p in self.get("appstore_list"):
                    continue
                identifier = p.split()[0]
                if identifier.isdigit() and len(identifier) >= 9:
                    package = " ".join(p.split()[1:])
                else:
                    identifier = ""
                    package = p
                islist = False
                for pl in self.get("appstore_list"):
                    l_identifier = pl.split()[0]
                    if l_identifier.isdigit() and len(l_identifier) >= 9:
                        l_package = " ".join(pl.split()[1:])
                    else:
                        l_identifier = ""
                        l_package = pl
                    if package == l_package:
                        islist = True
                        break
                if islist:
                    continue
                self.info("Installing " + package)
                if identifier != "":
                    if self.check_mas_cmd(True) == 1:
                        self.proc(self.opt["mas_cmd"] + " purchase "
                                  + identifier)
                    else:
                        self.info("Please install %s from AppStore." %
                                  package, 0)
                        self.proc(
                            "open -W 'macappstore://itunes.apple.com/app/id%s'"
                            % (identifier))
                else:
                    self.warn("No id or wrong id information was given for "
                              "AppStore App: %s.\n"
                              "Please install it manually." % package, 0)

        # Other commands
        for c in self.get("cmd_input"):
            self.proc(c)

        # after commands
        for c in self.get("after_input"):
            self.proc(c)

        # Initialize if commands are installed
        if self.opt["mas_cmd_installed"] \
                or self.opt["reattach_cmd_installed"] \
                or reinit:
            self.opt["mas_cmd_installed"] \
                = self.opt["reattach_cmd_installed"]
            self.input_to_list()
            self.initialize_write()
        return 0

    def find_app(self, app, taps, casks, nonapp_casks,
                 casks_noinst, nonapp_casks_noinst):
        """Helper function for Cask"""
        cask_namer = self.brewinfo.get_tap_path(self.opt["cask_repo"]) +\
            "/developer/bin/generate_cask_token"
        tap_cands = []
        name_cands = []
        lines = self.proc([cask_namer, '"' + app.split("/")[-1].lower() + '"'],
                          print_cmd=False, print_out=False,
                          exit_on_err=False)[1]
        for line in lines:
            if line.find("Proposed token") != -1:
                name_cands.append(line.split()[2])
            if line.find("already exists") != -1:
                for t in taps:
                    tname = t.split('/')[0] + "/homebrew-" + t.split('/')[1]
                    if line.split("'")[1].find(tname) != -1:
                        tap_cands.append(t)
                        break
        if not tap_cands:
            del name_cands[:]

        installed = False
        clist = list(casks.values()) + nonapp_casks +\
            [x for x_list in casks_noinst.values() for x in x_list] +\
            nonapp_casks_noinst
        if name_cands and [x for x in clist if x[0] == name_cands[0] and x[2]]:
            installed = True
        else:
            for c in [x for x in clist if app in x[5]]:
                if c[2]:
                    installed = True
                    tap_cands = [c[1]]
                    name_cands = [c[0]]
                    break
                if c[0] not in name_cands:
                    tap_cands.append(c[1])
                    name_cands.append(c[0])
        if not name_cands:
            self.info("Non Cask app: " + app, 2)
        elif installed:
            self.info("Installed by Cask:" + app + name_cands[0], 2)
        else:
            self.info("Installed directly, instead of by Cask:"
                      + app + ", Cask candidates: " + ", ".join(name_cands), 2)
        return (tap_cands, installed, name_cands)

    def find_brew_app(self, name, tap):
        """Helper function for Cask to find app installed by brew install"""

        check = "has_cask"
        tap_brew = tap
        opt = ""
        if os.path.isfile(self.brew_val("repository")
                          + "/Library/Formula/" + name + ".rb"):
            if isinstance(self.opt["brew_packages"], str):
                self.opt["brew_packages"] = self.proc(
                    "brew list --formula", print_cmd=False, print_out=False)[1]
            if name in self.opt["brew_packages"]:
                check = "brew"
                opt = self.brewinfo.get_option(name)
                if os.path.islink(self.brew_val("repository")
                                  + "/Library/Formula/" + name + ".rb"):
                    link = os.readlink(self.brew_val("repository")
                                       + "/Library/Formula/" + name + ".rb")
                    tap_brew = link.replace("../Taps/", "").\
                        replace("homebrew-").replace("/" + name + ".rb")
                else:
                    tap_brew = ""
        return (check, tap_brew, opt)

    def check_cask(self):
        """Check applications for Cask"""
        if not is_mac():
            print("Cask is not available on Linux!")
            sys.exit(1)

        self.banner("# Starting to check applications for Cask...")

        # First, get App Store applications
        appstore_list = {}
        for p in self.get_appstore_list():
            pinfo = p.split()
            identifier = pinfo[0]
            if identifier.isdigit() and len(identifier) == 9:
                package = " ".join(pinfo[1:])
            else:
                identifier = ""
                package = p
            (pname, version) = package.split("(")
            appstore_list[pname.strip()] = [identifier, "(" + version]

        # Get cask list, force to install brew-cask
        # if it has not been installed.
        installed_casks = self.get_cask_list()[1]

        # Set cask directories and reset application information list
        taps = list(filter(
            lambda t: os.path.isdir(self.brewinfo.get_tap_path(t) + "/Casks"),
            self.proc("brew tap", print_cmd=False, print_out=False,
                      env={"HOMEBREW_NO_AUTO_UPDATE": "1"})[1]))
        apps = {d: {True: [], False: []} for d in taps + ["", "appstore"]}
        brew_apps = {}

        # Set applications directories
        app_dirs = self.opt["appdirlist"]
        apps_check = {"cask": {d: 0 for d in app_dirs},
                      "has_cask": {d: 0 for d in app_dirs},
                      "brew": {d: 0 for d in app_dirs},
                      "appstore": {d: 0 for d in app_dirs},
                      "no_cask": {d: 0 for d in app_dirs}}

        # Load casks
        casks = {}
        nonapp_casks = []
        casks_noinst = {}
        nonapp_casks_noinst = []
        for t in taps:
            d = self.brewinfo.get_tap_path(t) + "/Casks"
            for cask in list(map(
                    lambda x: x.replace(".rb", ""),
                    filter(lambda y: y.endswith(".rb"), os.listdir(d)))):
                cask_apps = []
                installed = False
                noinst = True
                if cask in installed_casks:
                    noinst = False
                with open(d + "/" + cask + ".rb", "r") as f:
                    content = f.read()
                for line in content.split("\n"):
                    cask_app = ""
                    if re.search("^ *name ", line):
                        cask_app = re.sub("^ *name ", "",
                                          line).strip('"\' ') + ".app"
                    elif re.search("^ *app ", line):
                        cask_app = re.sub("^ *app ", "",
                                          line).strip('"\' ').split("/")[-1]
                    elif re.search("\\.app", line):
                        cask_app = line.split(".app")[0].split("/")[-1].\
                            split("'")[-1].split('"')[-1]
                    elif re.search("^ *pkg ", line):
                        cask_app = re.sub("^ *pkg ", "", line).strip('"\' ').\
                            split("/")[-1].replace(".pkg", "")
                    if cask_app != "" and cask_app not in cask_apps:
                        cask_apps.append(cask_app)

                    if not noinst and re.search("^ *version ", line):
                        if os.path.isdir(
                                self.opt["caskroom"] + "/" + cask + "/"
                                + re.sub("^ *version ", "", line).strip(
                                    '"\': ')):
                            installed = True
                if noinst:
                    if not cask_apps:
                        nonapp_casks_noinst.append([cask, t, installed,
                                                    False, content, cask_apps])
                    else:
                        for a in cask_apps:
                            if a in casks_noinst:
                                casks_noinst[a].append(
                                    [cask, t, installed, False,
                                     content, cask_apps])
                            else:
                                casks_noinst[a] = [[cask, t, installed,
                                                    False, content, cask_apps]]
                else:
                    if not cask_apps:
                        nonapp_casks.append([cask, t, installed,
                                             False, content, cask_apps])
                    else:
                        for a in cask_apps:
                            casks[a] = [cask, t, installed, False,
                                        content, cask_apps]

        # Get applications
        napps = 0
        for d in app_dirs:
            for app in [x for x in os.listdir(d)
                        if not x.startswith(".") and x != "Utilities"
                        and os.path.isdir(d + "/" + x)]:
                check = "no_cask"
                tap = ""
                opt = ""
                aname = app.replace(".app", "")
                if aname in appstore_list:
                    tap = "appstore"
                    installed = False
                    if appstore_list[aname][0] != "":
                        name = appstore_list[aname][0] + " " + aname \
                            + " " + appstore_list[aname][1]
                    else:
                        name = ""
                    check = "appstore"
                elif app in casks or app.split(".")[0] in casks:
                    app_key = app if app in casks else app.split(".")[0]
                    tap = casks[app_key][1]
                    installed = casks[app_key][2]
                    name = casks[app_key][0]
                    for a in filter(lambda k, n=name: casks[k][0] == n, casks):
                        casks[a][3] = True
                    casks[app_key][3] = True
                    if installed or name != "":
                        installed = True
                        check = "cask"
                else:
                    app_find = app
                    if not app.endswith(".app"):
                        app_find = d + "/" + app
                    (tap_cands, installed, name_cands) = self.find_app(
                        app_find, taps, casks, nonapp_casks,
                        casks_noinst, nonapp_casks_noinst)
                    if name_cands:
                        for name in name_cands:
                            for c in filter(lambda x, n=name: x[0] == n,
                                            nonapp_casks):
                                nonapp_casks.remove(c)
                            for a in filter(lambda k, n=name: casks[k][0] == n,
                                            casks):
                                casks[a][3] = True
                    name = ""
                    if installed:
                        check = "cask"
                        name = name_cands[0]
                        tap = tap_cands[0]
                    elif name_cands:
                        for n, t in zip(name_cands, tap_cands):
                            (check, tap, opt) =\
                                self.find_brew_app(n, t)
                            if check == "brew":
                                name = n
                                break
                    if name == "":
                        if tap_cands:
                            for n, t in zip(name_cands, tap_cands):
                                apps[t][installed].append(
                                    (n, d + "/" + app, check))
                        else:
                            name = tap = ""
                if check != "has_cask":
                    if check != "brew":
                        apps[tap][installed].append(
                            (name, d + "/" + app, check))
                    else:
                        if tap not in brew_apps:
                            brew_apps[tap] = []
                        brew_apps[tap].append((name, d + "/" + app, opt))
                apps_check[check][d] += 1
                napps += 1

        # Make list
        casks_in_others = []
        out = Tee("Caskfile", sys.stdout, self.verbose() > 1)

        out.writeln("# Cask applications")
        out.writeln("# Please copy these lines to your Brewfile"
                    " and use with `" + __prog__ + " install`.\n")

        out.writeln("# Main tap repository for " + self.opt["cask_repo"])
        out.writeln("tap " + self.opt["cask_repo"])
        out.writeln("")
        if apps[self.opt["cask_repo"]][True]:
            out.writeln("# Apps installed by Cask in " + self.opt["cask_repo"])
            for (name, app_path, check) in\
                    sorted(apps[self.opt["cask_repo"]][True]):
                if name not in casks_in_others:
                    out.writeln("cask " + name + " # "
                                + app_path.replace(os.environ["HOME"],
                                                   "~"))
                    casks_in_others.append(name)
                else:
                    out.writeln("#cask " + name + " # "
                                + app_path.replace(os.environ["HOME"],
                                                   "~"))

            out.writeln("")

        if [x[0] for x in list(casks.values()) + nonapp_casks
                if x[1] == self.opt["cask_repo"] and not x[3]]:
            out.writeln("# Cask is found, but no applications are found "
                        + "(could be fonts, system settins, "
                        + "or installed in other directory.)")
            for name in sorted(
                    x[0] for x in list(casks.values()) + nonapp_casks
                    if x[1] == self.opt["cask_repo"] and x[2] and not x[3]):
                if name not in casks_in_others:
                    out.writeln("cask " + name)
                    casks_in_others.append(name)
            if [x[0] for x in list(casks.values()) + nonapp_casks
                    if x[1] == self.opt["cask_repo"]
                    and not x[2] and not x[3]]:
                out.writeln(
                    "\n# There are new version for following applications.")
                for name in sorted(x[0] for x in list(casks.values())
                                   + nonapp_casks
                                   if x[1] == self.opt["cask_repo"]
                                   and not x[2] and not x[3]):
                    if name not in casks_in_others:
                        out.writeln("cask install " + name)
                        casks_in_others.append(name)
            out.writeln("")

        if apps[self.opt["cask_repo"]][False]:
            out.writeln("# Apps installed directly instead of by Cask in "
                        + self.opt["cask_repo"])
            for (name, app_path, check) in\
                    sorted(x for x in apps[self.opt["cask_repo"]][False]):
                out.writeln("#cask " + name
                            + " # " + app_path.replace(os.environ["HOME"],
                                                       "~"))
            out.writeln("")

        for t in filter(lambda x: x not in
                        (self.opt["cask_repo"], "", "appstore"), taps):
            out.writeln("# Casks in " + t)
            out.writeln("tap " + t)
            out.writeln("")
            if apps[t][True]:
                out.writeln("# Apps installed by Cask in " + t)
                for (name, app_path, check) in sorted(apps[t][True]):
                    if name not in casks_in_others:
                        out.writeln("cask " + name + " # "
                                    + app_path.replace(os.environ["HOME"],
                                                       "~"))
                        casks_in_others.append(name)
                    else:
                        out.writeln("#cask " + name + " # "
                                    + app_path.replace(os.environ["HOME"],
                                                       "~"))

                out.writeln("")

            if [x[0] for x in list(casks.values()) + nonapp_casks
                    if x[1] == t and not x[3]]:
                out.writeln("# Cask is found, but no applications are found.\n"
                            "# (fonts, system settins, "
                            "or installed in other directory.)")
                for name in sorted(x[0]
                                   for x in list(casks.values()) + nonapp_casks
                                   if x[1] == t and x[2] and not x[3]):
                    if name not in casks_in_others:
                        out.writeln("cask " + name)
                        casks_in_others.append(name)
                if [x[0] for x in list(casks.values()) + nonapp_casks
                        if x[1] == t and not x[2] and not x[3]]:
                    out.writeln(
                        "# There are new version for following applications.")
                    for name in sorted(x[0]
                                       for x in list(casks.values())
                                       + nonapp_casks
                                       if x[1] == t and not x[2] and not x[3]):
                        if name not in casks_in_others:
                            out.writeln("cask " + name)
                            casks_in_others.append(name)
                out.writeln("")

            if apps[t][False]:
                out.writeln(
                    "# Apps installed directly instead of by Cask in " + t)
                for (name, app_path, check) in apps[t][False]:
                    out.writeln("#cask " + name + " # "
                                + app_path.replace(os.environ["HOME"], "~"))
                out.writeln("")

        if brew_apps:
            out.writeln("# Apps installed by brew install command")
            if "" in brew_apps:
                for (name, app_path, opt) in brew_apps[""]:
                    out.writeln("brew " + name + " " + opt + " # "
                                + app_path.replace(os.environ["HOME"], "~"))
            for tap in [x for x in brew_apps if x != ""]:
                out.writeln("tap " + tap)
                for (name, app_path, opt) in brew_apps[tap]:
                    out.writeln("brew " + name + " " + opt + " # "
                                + app_path.replace(os.environ["HOME"], "~"))
            out.writeln("")

        if apps["appstore"][False]:
            out.writeln("# Apps installed from AppStore")
            for x in apps["appstore"][False]:
                print(" ".join(x[0].split()[1:]).lower())
            for (name, app_path, check) in sorted(
                    apps["appstore"][False],
                    key=lambda x: " ".join(x[0].split()[1:]).lower()):
                if name != "":
                    out.writeln("appstore " + name + " # " + app_path)
                else:
                    out.writeln("#appstore # " + app_path)
            out.writeln("")

        if apps[""][False]:
            out.writeln("# Apps installed but no casks are available")
            out.writeln("# (System applications or directory installed.)")
            for (name, app_path, check) in apps[""][False]:
                out.writeln("# " + app_path)

        out.close()

        # Summary
        self.banner("# Summary")
        if self.verbose() > 0:
            print("Total:", napps, "apps have been checked.")
            print("Apps in",
                  [d.replace(os.environ["HOME"], "~") for d in app_dirs], "\n")
            maxlen = max(len(x.replace(os.environ["HOME"], "~"))
                         for x in app_dirs)
            if sum(apps_check["cask"].values()) > 0:
                print("Installed by Cask:")
                for d in app_dirs:
                    if apps_check["cask"][d] == 0:
                        continue
                    print("{0:<{1}s} : {2:d}".format(
                        d.replace(os.environ["HOME"], "~"),
                        maxlen, apps_check["cask"][d]))
                print("")
            if sum(apps_check["brew"].values()) > 0:
                print("Installed by brew install command")
                for d in app_dirs:
                    if apps_check["brew"][d] == 0:
                        continue
                    print("{0:<{1}s} : {2:d}".format(
                        d.replace(os.environ["HOME"], "~"),
                        maxlen, apps_check["brew"][d]))
                print("")
            if sum(apps_check["has_cask"].values()) > 0:
                print("Installed directly, but casks are available:")
                for d in app_dirs:
                    if apps_check["has_cask"][d] == 0:
                        continue
                    print("{0:<{1}s} : {2:d}".format(
                        d.replace(os.environ["HOME"], "~"),
                        maxlen, apps_check["has_cask"][d]))
                print("")
            if sum(apps_check["appstore"].values()) > 0:
                print("Installed from Appstore")
                for d in app_dirs:
                    if apps_check["appstore"][d] == 0:
                        continue
                    print("{0:<{1}s} : {2:d}".format(
                        d.replace(os.environ["HOME"], "~"),
                        maxlen, apps_check["appstore"][d]))
                print("")
            if sum(apps_check["no_cask"].values()) > 0:
                print("No casks")
                for d in app_dirs:
                    if apps_check["no_cask"][d] == 0:
                        continue
                    print("{0:<{1}s} : {2:d}".format(
                        d.replace(os.environ["HOME"], "~"),
                        maxlen, apps_check["no_cask"][d]))
                print("")

    def make_pack_deps(self):
        """Make package dependencies"""
        packs = self.get("brew_list")
        self.pack_deps = {}
        for p in packs:
            deps = self.proc("brew deps --1 " + p, print_cmd=False,
                             print_out=False)[1]
            self.pack_deps[p] = []
            for d in deps:
                if d in packs:
                    self.pack_deps[p].append(d)
        dep_packs = []
        for v in self.pack_deps.values():
            dep_packs.extend(v)
        self.top_packs = [x for x in packs if x not in dep_packs]
        if self.opt["verbose"] > 1:
            def print_dep(p, depth=0):
                if depth > 2:
                    print("#" + " " * (depth - 2), end="")
                print(p)
                for deps in self.pack_deps[p]:
                    print_dep(deps, depth + 2)
            for p in packs:
                if p not in dep_packs:
                    print_dep(p)

    def my_test(self):
        self.make_pack_deps()

        out = Tee("test_file")
        out.write("test\n")
        out.close()
        out = Tee(sys.stdout, "test_file")
        out.write("test\n")
        out.flush()
        out.close()
        self.remove("test_file")
        os.mkdir("dir")
        self.remove("dir")
        self.remove("aaa")
        self.brewinfo.read()
        print("read input:", len(self.brewinfo.brew_input))
        self.brewinfo.clear()
        print("read input cleared:", len(self.brewinfo.brew_input))
        self.brewinfo.filename = "/test/not/correct/file/path"
        self.brewinfo.read()
        self.brewinfo.check_dir()
        self.brewinfo.set_val("brew_input_opt", {"test_pack": "test opt"})
        self.brewinfo.add("brew_input_opt", {"test_pack2": "test opt2"})
        print(self.brewinfo.get("brew_input_opt"))
        self.brewinfo.read("testfile")

    def execute(self):
        """Main execute function"""
        # Cask list check
        if self.opt["command"] == "casklist":
            self.check_cask()
            sys.exit(0)

        # Set BREWFILE repository
        if self.opt["command"] == "set_repo":
            self.set_brewfile_repo()
            sys.exit(0)

        # Set BREWFILE to local file
        if self.opt["command"] == "set_local":
            self.set_brewfile_local()
            sys.exit(0)

        # Change brewfile if it is repository's one or not.
        self.check_repo()

        # Do pull/push for the repository.
        if self.opt["command"] in ["pull", "push"]:
            self.repomgr(self.opt["command"])
            sys.exit(0)

        # brew command
        if self.opt["command"] == "brew":
            self.brew_cmd()
            sys.exit(0)

        # Initialize
        if self.opt["command"] in ["init", "dump"]:
            self.initialize()
            sys.exit(0)

        # Check input file
        # If the file doesn't exist, initialize it.
        self.check_input_file()

        # Edit
        if self.opt["command"] == "edit":
            self.edit_brewfile()
            sys.exit(0)

        # Cat
        if self.opt["command"] == "cat":
            self.cat_brewfile()
            sys.exit(0)

        # Get files
        if self.opt["command"] == "get_files":
            self.get_files(is_print=True)
            sys.exit(0)

        # Cleanup
        if self.opt["command"] == "clean_non_request":
            self.clean_non_request()
            sys.exit(0)

        # Cleanup
        if self.opt["command"] == "clean":
            self.cleanup()
            sys.exit(0)

        # Install
        if self.opt["command"] == "install":
            self.install()
            sys.exit(0)

        # Update
        if self.opt["command"] == "update":
            if not self.opt["noupgradeatupdate"]:
                self.proc("brew update")
                self.proc("brew upgrade --fetch-HEAD")
                self.proc("brew upgrade --cask")
            if self.opt["repo"] != "":
                self.repomgr("pull")
            self.install()
            if not self.opt["dryrun"]:
                self.cleanup()
            self.initialize(check=False)
            if self.opt["repo"] != "":
                self.repomgr("push")
            sys.exit(0)

        # test
        if self.opt["command"] == "test":
            self.my_test()
            sys.exit(0)

        # No command found
        self.err("Wrong command: " + self.opt["command"], 0)
        self.err("Execute `" + __prog__ + " help` for more information.", 0)
        sys.exit(1)


def main():
    # Prepare BrewFile
    b = BrewFile()

    # Pre Parser
    arg_parser_opts = {'add_help': False, 'allow_abbrev': False}
    pre_parser = argparse.ArgumentParser(usage=__prog__ + "...",
                                         **arg_parser_opts)
    group = pre_parser.add_mutually_exclusive_group()
    group.add_argument("-i", "--init", action="store_const",
                       dest="command", const="init")
    group.add_argument("-s", "--set_repo", action="store_const",
                       dest="command", const="set_repo")
    group.add_argument("--set_local", action="store_const",
                       dest="command", const="set_local")
    group.add_argument("-c", "--clean", action="store_const",
                       dest="command", const="clean")
    group.add_argument("-u", "--update", action="store_const",
                       dest="command", const="update")
    group.add_argument("-e", "--edit", action="store_const",
                       dest="command", const="edit")
    group.add_argument("--cat", action="store_const",
                       dest="command", const="cat")
    group.add_argument("--test", action="store_const",
                       dest="command", const="test")
    group.add_argument("--commands", action="store_const",
                       dest="command", const="commands")
    group.add_argument("-v", "--version", action="store_const",
                       dest="command", const="version")

    # Parent parser
    file_parser = argparse.ArgumentParser(**arg_parser_opts)
    file_parser.add_argument(
        "-f", "--file", action="store", dest="input",
        default=b.opt["input"],
        help="Set input file (default: %(default)s). \n"
             "You can set input file by environmental variable,\n"
             "HOMEBREW_BREWFILE, like:\n"
             "    export HOMEBREW_BREWFILE=~/.brewfile")

    backup_parser = argparse.ArgumentParser(**arg_parser_opts)
    backup_parser.add_argument(
        "-b", "--backup", action="store", dest="backup",
        default=b.opt["backup"],
        help="Set backup file (default: %(default)s). \n"
             "If it is empty, no backup is made.\n"
             "You can set backup file by environmental variable,\n"
             " HOMEBREW_BREWFILE_BACKUP, like:\n"
             "    export HOMEBREW_BREWFILE_BACKUP=~/brewfile.backup")

    format_parser = argparse.ArgumentParser(**arg_parser_opts)
    format_parser.add_argument(
        "-F", "--format", "--form", action="store", dest="form",
        default=b.opt["form"],
        help="Set input file format (default: %(default)s). \n"
             "file (or none)    : brew vim --HEAD --with-lua\n"
             "brewdler or bundle: brew 'vim', args: ['with-lua', 'HEAD']\n"
             "  Compatible with "
             "[homebrew-bundle]"
             "(https://github.com/Homebrew/homebrew-bundle).\n"
             "command or cmd    : brew install vim --HEAD --with-lua\n"
             "  Can be used as a shell script.\n")

    leaves_parser = argparse.ArgumentParser(**arg_parser_opts)
    leaves_parser.add_argument(
        "--leaves", action="store_true", default=b.opt["leaves"],
        dest="leaves",
        help="Make list only for leaves (taken by `brew leaves`).\n"
             "You can set this by environmental variable,"
             " HOMEBREW_BREWFILE_LEAVES, like:\n"
             "    export HOMEBREW_BREWFILE_LEAVES=1")

    on_request_parser = argparse.ArgumentParser(**arg_parser_opts)
    on_request_parser.add_argument(
        "--on_request", action="store_true", default=b.opt["on_request"],
        dest="on_request",
        help="Make list only for packages installed on request.\n"
             "This option is given priority over 'leaves'.\n"
             "You can set this by environmental variable,"
             " HOMEBREW_BREWFILE_ON_REQUEST, like:\n"
             "    export HOMEBREW_BREWFILE_ON_REQUEST=1")

    top_packages_parser = argparse.ArgumentParser(**arg_parser_opts)
    top_packages_parser.add_argument(
        "--top_packages", action="store", default=b.opt["top_packages"],
        dest="top_packages",
        help="Packages to be listed even if they are under dependencies\n"
             "and `leaves`/'on_request' option is used.\n"
             "You can set this by environmental variable,\n"
             " HOMEBREW_BREWFILE_TOP_PACKAGES (',' separated), like:\n"
             "    export HOMEBREW_BREWFILE_TOP_PACKAGES=go,coreutils")

    noupgradeatupdate_parser = argparse.ArgumentParser(**arg_parser_opts)
    noupgradeatupdate_parser.add_argument(
        "-U", "--noupgrade", action="store_true",
        default=b.opt["noupgradeatupdate"], dest="noupgradeatupdate",
        help="Do not execute `brew update/brew upgrade`"
             " at `brew file update`.")

    repo_parser = argparse.ArgumentParser(**arg_parser_opts)
    repo_parser.add_argument(
        "-r", "--repo", action="store", default=b.opt["repo"], dest="repo",
        help="Set repository name. Use with set_repo.")

    link_parser = argparse.ArgumentParser(**arg_parser_opts)
    link_parser.add_argument(
        "-n", "--nolink", action="store_false", default=b.opt["link"],
        dest="link", help="Don't make links for Apps.")

    caskonly_parser = argparse.ArgumentParser(**arg_parser_opts)
    caskonly_parser.add_argument(
        "--caskonly", action="store_true", default=b.opt["caskonly"],
        dest="caskonly", help="Write out only cask related packages")

    appstore_parser = argparse.ArgumentParser(**arg_parser_opts)
    appstore_parser.add_argument(
        "--appstore", action="store", default=b.opt["appstore"],
        dest="appstore", help="Set AppStore application check level.\n"
        "0: do not check,\n1: check and manage,\n"
        "2: check for installation,"
        "but do not add to Brewfile when Apps are added.\n"
        "You can set the level by environmental variable:\n"
        "    export HOMEBREW_BREWFILE_APPSTORE=0")

    no_appstore_parser = argparse.ArgumentParser(**arg_parser_opts)
    no_appstore_parser.add_argument(
        "--no_appstore", action="store_false", default=b.opt["no_appstore"],
        dest="no_appstore", help="Set AppStore application check level to 0.\n"
        "(legacy option, works same as '--appstore 0'.)\n")

    dryrun_parser = argparse.ArgumentParser(**arg_parser_opts)
    dryrun_parser.add_argument(
        "-C", action="store_false", default=b.opt["dryrun"],
        dest="dryrun", help="Run clean as non dry-run mode.\n"
        "Use this option to run clean at update command, too.")

    yn_parser = argparse.ArgumentParser(**arg_parser_opts)
    yn_parser.add_argument(
        "-y", "--yes", action="store_true", default=b.opt["yn"],
        dest="yn", help="Answer yes to all yes/no questions.")

    verbose_parser = argparse.ArgumentParser(**arg_parser_opts)
    verbose_parser.add_argument("-V", "--verbose", action="store",
                                default=b.opt["verbose"],
                                dest="verbose", help="Verbose level 0/1/2")

    help_parser = argparse.ArgumentParser(**arg_parser_opts)
    help_parser.add_argument("-h", "--help", action="store_true",
                             default=False, dest="help",
                             help="Print Help (this message) and exit.")

    min_parsers = [file_parser, backup_parser, format_parser, leaves_parser,
                   on_request_parser, top_packages_parser, appstore_parser,
                   no_appstore_parser, caskonly_parser, yn_parser,
                   verbose_parser]
    formatter = argparse.RawTextHelpFormatter
    subparser_opts = {'formatter_class': formatter, 'allow_abbrev': False}

    # Main parser
    parser = argparse.ArgumentParser(
        prog=__prog__,
        parents=[file_parser, backup_parser, format_parser, leaves_parser,
                 on_request_parser, top_packages_parser,
                 noupgradeatupdate_parser, repo_parser, link_parser,
                 caskonly_parser, appstore_parser, no_appstore_parser,
                 dryrun_parser, yn_parser, verbose_parser, help_parser],
        formatter_class=formatter,
        description=__description__,
        epilog="Check https://homebrew-file.readthedocs.io for more details.",
        **arg_parser_opts
    )

    subparsers = parser.add_subparsers(
        title="subcommands", metavar="[command]", help="", dest="command")

    help_doc = "Install packages in BREWFILE if no <package> is given.\n"\
        "If <package> is given, the package is installed and it is added\n"\
        "in BREWFILE."
    subparsers.add_parser("install", description=help_doc, help=help_doc,
                          parents=min_parsers, **subparser_opts)
    help_doc = "Execute brew command, and update BREWFILE.\n"\
        "Use 'brew noinit <brew command>' to suppress Brewfile initialization."
    subparsers.add_parser("brew", description=help_doc, help=help_doc,
                          parents=min_parsers, **subparser_opts)
    help_doc = "or dump/-i/--init\nInitialize/Update BREWFILE "\
        "with installed packages."
    subparsers.add_parser(
        "init", description=help_doc, help=help_doc,
        parents=min_parsers + [link_parser, repo_parser],
        **subparser_opts)
    subparsers.add_parser(
        "dump",
        parents=min_parsers + [link_parser, repo_parser],
        **subparser_opts)
    help_doc = "or -s/--set_repo\nSet BREWFILE repository "\
        "(e.g. rcmdnk/Brewfile or full path to your repository)."
    subparsers.add_parser(
        "set_repo", description=help_doc, help=help_doc,
        parents=min_parsers + [repo_parser],
        **subparser_opts)
    help_doc = "or --set_local\nSet BREWFILE to local file."
    subparsers.add_parser("set_local", description=help_doc, help=help_doc,
                          parents=min_parsers, **subparser_opts)
    help_doc = "Update BREWFILE from the repository."
    subparsers.add_parser("pull", description=help_doc, help=help_doc,
                          parents=min_parsers, **subparser_opts)
    help_doc = "Push your BREWFILE to the repository."
    subparsers.add_parser("push", description=help_doc, help=help_doc,
                          parents=min_parsers, **subparser_opts)
    help_doc = "or -c/--clean\nCleanup.\n"\
        "Uninstall packages not in the list.\n"\
        "Untap packages not in the list.\n"\
        "Cleanup cache (brew cleanup)\n"\
        "By default, cleanup runs as dry-run.\n"\
        "If you want to enforce cleanup, use '-C' option."
    subparsers.add_parser("clean", description=help_doc, help=help_doc,
                          parents=min_parsers + [dryrun_parser],
                          **subparser_opts)
    help_doc = "or --clean_non_request.\n"\
        "Uninstall packages which were installed as dependencies \n"\
        "but parent packages of which were already uninstalled.\n"\
        "By default, cleanup runs as dry-run.\n"\
        "If you want to enforce cleanup, use '-C' option."
    subparsers.add_parser(
        "clean_non_request", description=help_doc, help=help_doc,
        parents=min_parsers + [dryrun_parser],
        **subparser_opts)
    help_doc = "or -u/--update\nDo brew update/upgrade, cask upgrade, pull,"\
        "install,\n"\
        "init and push.\n"\
        "In addition, pull and push\n"\
        "will be done if the repository is assigned.\n"\
        "'clean' is also executed after install if you give -C option."
    subparsers.add_parser(
        "update", description=help_doc, help=help_doc,
        parents=min_parsers + [link_parser, noupgradeatupdate_parser,
                               dryrun_parser],
        **subparser_opts)
    help_doc = "or -e/--edit\nEdit input files."
    subparsers.add_parser("edit", description=help_doc, help=help_doc,
                          parents=[file_parser],
                          **subparser_opts)
    help_doc = "or --cat\nShow contents of input files."
    subparsers.add_parser("cat", description=help_doc, help=help_doc,
                          parents=[file_parser],
                          **subparser_opts)
    help_doc = "Check applications for Cask."
    subparsers.add_parser("casklist", description=help_doc, help=help_doc,
                          parents=[verbose_parser],
                          **subparser_opts)
    help_doc = "or --test. Used for test."
    subparsers.add_parser("test", description=help_doc, help=help_doc,
                          parents=min_parsers, **subparser_opts)
    help_doc = "Get Brewfile's full path, including additional files."
    subparsers.add_parser("get_files", description=help_doc, help=help_doc,
                          parents=[file_parser],
                          **subparser_opts)
    help_doc = "or --commands\nShow commands."
    subparsers.add_parser("commands", description=help_doc, help=help_doc,
                          **subparser_opts)
    help_doc = "or -v/--version\nShow version."
    subparsers.add_parser("version", description=help_doc, help=help_doc,
                          **subparser_opts)
    help_doc = "or -h/--help\nPrint Help (this message) and exit."
    subparsers.add_parser("help", description=help_doc, help=help_doc,
                          **subparser_opts)

    if len(sys.argv) == 1:
        parser.print_usage()
        print("")
        print("Execute `" + __prog__ + " help` to get help.")
        print("")
        print("Refer https://homebrew-file.readthedocs.io for more details.")
        sys.exit(1)

    if sys.argv[1] == "brew":
        args = sys.argv[1:]
    else:
        (ns, args) = pre_parser.parse_known_args()
        if ns.command is not None:
            args = [ns.command] + args
        else:
            for a in args[:]:
                if a in subparsers.choices:
                    args.remove(a)
                    args = [a] + args
                    break
        if args[0] in ["-h", "--help"]:
            args[0] = "help"
    (ns, args_tmp) = parser.parse_known_args(args)
    args = vars(ns)
    args.update({"args": args_tmp})
    if args['command'] in ('install') and args['args']:
        cmd = args['command']
        args['command'] = 'brew'
        args['args'].insert(0, cmd)

    b.set_args(**args)

    if b.opt["command"] == "help":
        parser.print_help()
        sys.exit(0)
    elif b.opt["command"] == "brew":
        if args_tmp and args_tmp[0] in ["-h", "--help"]:
            subparsers.choices[b.opt["command"]].print_help()
            sys.exit(0)
    elif "help" in args_tmp:
        subparsers.choices[b.opt["command"]].print_help()
        sys.exit(0)
    elif b.opt["command"] == "commands":
        commands = ["install", "brew", "init", "dump", "set_repo", "set_local",
                    "pull", "push", "clean", "clean_non_request", "update",
                    "edit", "cat", "casklist", "test",
                    "get_files", "commands", "version", "help"]
        commands_hyphen = ["-i", "--init", "-s", "--set_repo", "--set_local",
                           "-c", "--clean", "--clean_non_request", "-u",
                           "--update", "-e", "--edit", "--cat", "--test",
                           "--commands", "-v", "--version", "-h", "--help"]
        options = ["-f", "--file", "-b", "--backup",
                   "-F", "--format", "--form", "--leaves", "--on_request",
                   "--top_packages", "-U", "--noupgrade", "-r", "--repo", "-n",
                   "--nolink", "--caskonly", "--appstore", "--no_appstore",
                   "-C", "-y", "--yes", "-V", "--verbose"]
        print("commands:", " ".join(commands))
        print("commands_hyphen:", " ".join(commands_hyphen))
        print("options:", " ".join(options))
        sys.exit(0)
    elif b.opt["command"] == "version":
        b.proc("brew -v", print_cmd=False)
        print(__prog__ + " " + __version__ + " " + __date__)
        sys.exit(0)

    try:
        b.execute()
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
