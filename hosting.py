import sqlite3
import argparse
from docker import Client
from pyroute2 import IPRoute
from subprocess import Popen, PIPE, call
import xml.etree.ElementTree as ET

DOCKER_VERSION = '1.14'
d_client = Client(base_url='unix://var/run/docker.sock',
                  version=DOCKER_VERSION)


class Container(object):
    def __init__(self, name=None, mac=None, container_name=None,
                 mount_loc=None, args=None, dbfile='db.db', internal_only=False
                 ):
        self._conn = sqlite3.connect(dbfile)
        try:
            c = self._conn.cursor()
            c.execute('SELECT * FROM containers')
            c.close()
        except sqlite3.OperationalError:
            self.init_db(dbfile)
        if not self.db_to_object(name):
            if not (name and mac and container_name and mount_loc and args):
                raise Exception("You must specify ALL values if name is not "
                                "in the database already")
            else:
                c = self._conn.cursor()
                values = (name, mac, container_name, mount_loc, args,
                          1 if internal_only else 0)
                print(values)
                c.execute('INSERT INTO containers VALUES (?,?,?,?,?,?)',
                          values)
                self._conn.commit()
                c.close()
                if not self.db_to_object(name):
                    raise Exception("Error: db didn't work")
        self.get_state()

    def db_to_object(self, name):
        c = self._conn.cursor()
        c.execute('SELECT * FROM containers WHERE name=?', (name,))
        all_data = c.fetchone()
        if all_data:
            self.name = name
            self.mac = all_data[1]
            self.container_name = all_data[2]
            self.mount_loc = all_data[3]
            self.args = all_data[4]
            self.internal_only = all_data[5]
            c.close()
            return True
        else:
            c.close()
            return False

    def _get_state_ip(self):
        try:
            ip = IPRoute()
            self.ipdev = ip.link_lookup(ifname=self.name)[0]
        except IndexError:
            self.ipdev = False
            self.ip_addr = False
        else:
            try:
                self.ip_addr = {e[0]: e[1] for e in
                                ip.get_addr(index=self.ipdev, family=2)[0]['attrs']
                                }['IFA_ADDRESS']
            except IndexError:
                self.ip_addr = False

    def _get_state_docker(self):
        running = d_client.containers()
        try:
            self._container = {e['Names'][0]: e for e in running}['/' + self.name]
        except KeyError:
            self.container_running = False
            return
        else:
            self.container_running = True
        self.container_id = self._container['Id']
        self._full_container_info = d_client.inspect_container(self.container_id)
        self.container_ip = self._full_container_info['NetworkSettings']['IPAddress']

    @staticmethod
    def _get_rule_by_action(chain, call_name):
        for rule in chain:
            actions = {e.tag: e for e in rule}['actions']
            try:
                call = {e.tag: e for e in actions}['call']
                if call[0].tag == 'BRIDGE-' + call_name.upper():
                    return rule
            except KeyError:
                pass
            except UnboundLocalError:
                pass

        return None

    def _get_state_iptables(self):
        p1 = Popen(['sudo', 'iptables-save', '-t', 'nat'], stdout=PIPE)
        p1.wait()
        p2 = Popen(['iptables-xml'], stdin=p1.stdout, stdout=PIPE)
        p2.wait()
        p1.stdout.close()
        output = p2.communicate()[0]
        p2.stdout.close()

        iptables_root = ET.fromstring(output)
        chains = iptables_root[0]
        chains = {e.attrib['name']: [e, e.attrib] for e in chains}

        try:
            self.bridge = chains['BRIDGE-' + self.name.upper()][0]
        except KeyError:
            self.bridge = None

        self.rule = {}
        rules = ['PREROUTING', 'POSTROUTING', 'OUTPUT']
        for i in rules:
            chain = chains[i][0]
            self.rule[i] = self._get_rule_by_action(chain, self.name.upper())

    def get_state(self):
        self._get_state_ip()
        # self.ipdev: int, dev number
        # self.ip_addr: String, ip address as String

        self._get_state_docker()
        # self.container_running: boolean, is container running

        self._get_state_iptables()
        # self.bridge: bridge (in xml)
        # self.rule: array of iptable rules (in xml)

    def interface_up(self):
        if self.ipdev:
            raise Exception("Interface is already up")

        call(['sudo', 'ip', 'link', 'add', self.name, 'link', 'eth0',
              'address', self.mac, 'type', 'macvlan', 'mode', 'bridge'])

    def dhcp_up(self):
        if self.ip_addr:
            raise Exception("Interface already has IP address")

        call(['sudo', 'dhclient', self.name])

    def dhcp_down(self):
        if not self.ip_addr:
            raise Exception("Interface does not have an IP address")

        call(['sudo', 'dhclient', '-d', '-r', self.name])

    def interface_down(self):
        if not self.ipdev:
            raise Exception("Interface does not exist")

        call(['sudo', 'ip', 'link', 'set', 'dev', self.name, 'down'])
        call(['sudo', 'ip', 'link', 'del', 'dev', self.name])

    @staticmethod
    def init_db(dbname):
        conn = sqlite3.connect(dbname)
        c = conn.cursor()
        c.execute('''CREATE TABLE containers
                  (name text NOT NULL UNIQUE, mac text NOT NULL UNIQUE,
                  container text NOT NULL, permloc text NOT NULL,
                  args text NOT NULL, internal_only integer)''')
        c.execute('''CREATE TABLE requires
                  (requirer text NOT NULL, required text NOT NULL)''')
        conn.commit()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run docker containers.")
    sub = parser.add_subparsers()

    init = sub.add_parser('init', help='Initialize the database')
    init.add_argument('--db', default='db.db', required=False,
                      help="Database file to use")
    args = parser.parse_args()
    print(args)
