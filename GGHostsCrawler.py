# -*- coding: utf-8 -*-

import requests
import re
import platform
import shutil
import time
import os
import getopt
import sys
import tempfile
import collections

PLATFORM = platform.system()


class SessionPool(object):
    __sessions = dict()
    __ip_pattern = re.compile(r'^(([\d]{1,2}|1\d\d|2[1-4]\d|25[1-5])\.){3}([\d]{1,2}|1\d\d|2[1-4]\d|25[1-5])(:\d+)?$')
    __address_pattern = re.compile(r'^(http://|https://)?(([^/?]+\.)?([^/?]+\.[^/?]+))[/?]?')
    @classmethod
    def get_session(cls, url):
        if not isinstance(url, str) or len(url) <= 0:
            return None
        m = cls.__address_pattern.match(url)
        if not m:
            return None
        scheme = m.group(1) if m.group(1) else "http://"
        address = m.group(2)
        prefix = scheme
        if cls.is_ip_address(address):
            prefix += address
        else:
            prefix += m.group(4)
        if not cls.__sessions.has_key(prefix):
            cls.__sessions[prefix] = requests.session()
        return cls.__sessions[prefix]

    @classmethod
    def is_ip_address(cls, addr):
        return cls.__ip_pattern.match(addr)

class HostsFileParser(object):
    USER_AGENT = 'Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/46.0.2490.71 Safari/537.36'
    def __init__(self, file_uri):
        self.file_uri = file_uri
        self.comment_lines = list()
        self.hosts = collections.OrderedDict()

    def parse(self):
        del self.comment_lines[:]
        self.hosts.clear()
        if not isinstance(self.file_uri, str) or len(self.file_uri) <= 0:
            return False
        if self.file_uri.startswith("http"):
            return self._parse_net_file(self.file_uri)
        return self._parse_local_file(self.file_uri)

    def _parse_net_file(self, uri):
        lines = self._get_net_file_lines(uri)
        if not lines:
            return False
        return self._handle_lines(lines)

    def _parse_local_file(self, uri):
        lines = self._get_local_file_lines(uri)
        if not lines:
            return False
        return self._handle_lines(lines)

    def _get_net_file_lines(self, url):
        try:
            ses = SessionPool.get_session(url)
            if not ses:
                print "error: failed to get session for %s"%(url,)
                return False
            resp = ses.get(url, headers={'User-Agent':self.USER_AGENT}, verify=False)
            if not resp or not resp.content:
                print "error: failed to get response from %s"%(url,)
            return re.split(r'\r|\n|\r\n', resp.content)
        except Exception as e:
            print "error: %s" % e
            return None

    def _get_local_file_lines(self, path):
        try:
            with open(path) as f:
                if not f:
                    print "error: failed to open local file %s"% path
                return f.readlines()
        except Exception as e:
            print "error: failed to read local hosts file %s: %s" % (path, e)
            return None

    def _handle_lines(self, lines=[]):
        if not lines:
            return False
        for line in lines:
            line = line.strip('\r\n ')
            if len(line) <= 0:
                continue
            if line.startswith('#'):
                self.comment_lines.append(line+'\n')
            else:
                ip, domain = re.split(r'[\s]+', line, 1)
                if ip and domain:
                    self.hosts[domain] = ip
        return True

TIME_FORMAT = '%Y-%m-%d_%H-%M-%S'
BACKUP_POSTFIX = lambda: '.%s.crlbak' % time.strftime(TIME_FORMAT, time.localtime())
BACKUP_DIR = tempfile.gettempdir() + os.path.sep + 'GGHostsCrawler' + os.path.sep

class GGHostCrawler:

    def __init__(self):
        self.pub_url = r'https://raw.githubusercontent.com/racaljk/hosts/master/hosts'
        self.local_file = None
        if cmp(PLATFORM.lower(), 'windows') == 0:
            self.local_file = r'C:\Windows\System32\Drivers\etc\hosts'
        else:
            self.local_file = r'/etc/hosts'

        self.tag = "### Generated by %s\n" % os.path.abspath(sys.argv[0])
        self.tag += "# source: %s\n" % self.pub_url
        self.tag += "# last update: <update_time>"
        self.tag += "###############################################\n\n"

    def run(self, force=False):
        local_hosts = HostsFileParser(self.local_file)
        if not local_hosts.parse():
            print "error: failed to parse local hosts file %s" % self.local_file
            return False
        remote_hosts = HostsFileParser(self.pub_url)
        if not remote_hosts.parse():
            print "error: failed to parse remote hosts file %s" % self.pub_url
            return False

        update_time = None
        for cmt in remote_hosts.comment_lines:
            m = re.match(r'.*last\s+update\s*:\s*([^\r\n]*)', cmt, re.I)
            if not m:
                continue
            update_time = m.group(1)
            break
        self.tag = self.tag.replace('<update_time>', str(update_time))

        new_add = dict()
        modify = dict()

        for (domain, ip) in remote_hosts.hosts.items():
            if domain == 'localhost' or domain == 'broadcasthost':
                continue
            if domain in local_hosts.hosts:
                if local_hosts.hosts[domain] != ip:
                    modify[domain] = (local_hosts.hosts[domain], ip)
            else:
                new_add[domain] = ip

        if not modify and not new_add:
            print "info: no updates, exit~"
            return True

        print "------------------------------------------------------------"
        if modify:
            print "### %d items will be modified:" % len(modify)
            for (domain, mod) in modify.items():
                print "-- %s: %s => %s" % (domain, mod[0], mod[1])
        if new_add:
            print "### %d items will be added:" % len(new_add)
            for (domain, ip) in new_add.items():
                print "+++ %s: %s" % (domain, ip)
        print "------------------------------------------------------------"
        yesno = 'n'
        if not force:
            yesno = raw_input(r"are you sure to apply this changes to hosts(add %d, modify %d)"
                              r",updated on %s?(y/n)" % (len(new_add), len(modify), update_time))
        if force or yesno == 'y' or yesno == 'Y':
            modify = {k:v[1] for (k,v) in modify.items()}
            local_hosts.hosts.update(modify)
            local_hosts.hosts.update(new_add)
            ret = self.do_update(local_hosts)
            if ret:
                print "successfully update hosts!"
            else:
                print "update hosts failed!"

        return True

    def do_update(self, parser):
        if not parser:
            return False
        backup_file = self.backup_local_file()
        if not backup_file:
            return False
        try:
            with open(self.local_file, 'w') as f:
                if not f:
                    print "error: failed to open local file %s for write"%self.local_file
                    return False
                f.write(self.tag)
                f.writelines(parser.comment_lines)
                hosts_lines = ["%s %s\n" % (ip, domain) for (domain, ip) in parser.hosts.items()]
                f.writelines(hosts_lines)
            return True
        except Exception as e:
            print "error: failed to update local hosts file %s: %s"%(self.local_file, e)
            self.rollback_backup(backup_file)
            return False

    def backup_local_file(self):
        try:
            backup_file = BACKUP_DIR + os.path.basename(self.local_file) + BACKUP_POSTFIX()
            if not os.path.isdir(BACKUP_DIR):
                os.mkdir(BACKUP_DIR)
            shutil.copy2(self.local_file, backup_file)
            return backup_file
        except Exception as e:
            print "error: failed to backup from %s to %s: %s"%(self.local_file, backup_file, e)
            return None

    def rollback_backup(self, backup_file):
        try:
            if not os.path.isfile(backup_file):
                print "warning: backup file %s does not exists!"%backup_file
                return False
            shutil.copy2(backup_file, self.local_file)
            print "info: rollbacked from %s to %s" % (backup_file, self.local_file)
            return True
        except Exception as e:
            print "error: failed to rollback backup file %s to %s" % (backup_file, self.local_file)
            return False


if __name__ == '__main__':
    def usage():
        print "%s [-f] [--force]" %sys.argv[0]
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'f', ['force'])
        force = len(opts) > 0
        crawler = GGHostCrawler()
        crawler.run(force)
    except getopt.GetoptError:
        usage()
        sys.exit(1)
