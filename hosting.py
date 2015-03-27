import sqlite3
# import iptc
import argparse
from docker import Client

docker_client = Client(base_url='unix://var/run/docker.sock')


class container(object):
    def __init__(self, name=None, mac=None, container_name=None,
                 mount_loc=None, args=None, dbfile='db.db'):
        self.conn = sqlite3.connect(dbfile)
        try:
            c = self.conn.cursor()
            c.execute('SELECT * FROM containers')
        except sqlite3.OperationalError:
            self.init_db(dbfile)
        if not self.db_to_object(name):
            if not (name and mac and container_name and mount_loc and args):
                raise Exception("You must specify ALL values if name is not "
                                "in the database already")
            else:
                c = self.conn.cursor()
                values = (name, mac, container_name, mount_loc, args)
                c.execute('INSERT INTO containers VALUES (?,?,?,?,?)', values)
            self.db_to_object(name)

    def db_to_object(self, name):
        c = self.conn.cursor()
        c.execute('SELECT * FROM containers WHERE name=?', (name,))
        all_data = c.fetch_one()
        if all_data:
            self.name = name
            self.mac = all_data[1]
            self.container_name = all_data[2]
            self.mount_loc = all_data[3]
            self.args = all_data[4]
            return True
        else:
            return False

    @staticmethod
    def init_db(dbname):
        conn = sqlite3.connect(dbname)
        c = conn.cursor()
        c.execute('''CREATE TABLE containers
                  (name text, mac text, container text, permloc text,
                  args text)''')
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
