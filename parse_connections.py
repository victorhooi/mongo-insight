#!/usr/bin/env python3
from influxdb import InfluxDBClient
import pprint
import argparse
from itertools import zip_longest
from dateutil.parser import parse

pp = pprint.PrettyPrinter(indent=4)

__author__ = 'victorhooi'

def create_generic_point(name, value, timestamp, tags):
    return {
        "measurement": name,
        "tags": tags,
        "time": timestamp,
        "fields": {
            "value": float(value)
        }
    }


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    args = [iter(iterable)] * n
    return zip_longest(fillvalue=fillvalue, *args)

parser = argparse.ArgumentParser(description='Parse serverStatus() output, and load it into an InfluxDB instance')
parser.add_argument('-d', '--database', default="insight", help="Name of InfluxDB database to write to. Defaults to 'insight'.")
parser.add_argument('-n', '--hostname', required=True, help='Host(Name) of the server')
parser.add_argument('-p', '--project', required=True, help='Project name to tag this with')
parser.add_argument('-s', '--ssl', action='store_true', default=False, help='Enable SSl mode for InfluxDB.')
parser.add_argument('input_file')
args = parser.parse_args()

client = InfluxDBClient(host=args.influxdb_host, ssl=args.ssl, verify_ssl=False, port=8086, database=args.database)

connections = {}
connection_counters = []
connection_events = []

base_tags = {
    'project': args.project,
    'hostname': args.hostname,
}

class ConnectionEvent:
    # Example of an connection open
    # 2015-08-16T22:28:15.350Z I NETWORK  [initandlisten] connection accepted from 10.0.20.7:55317 #32036 (176 connections now open)
    # Example of a connection close
    # 2015-08-16T22:28:21.908Z I NETWORK  [conn32033] end connection 10.0.20.8:58809 (176 connections now open)
    def __init__(self, timestamp, logline):
        self.timestamp = timestamp

    def get_tags(self):
        tags = {
                'project': args.project,
                'hostname': args.hostname,
                'connection_id': self.connection_id,
                'socket_address': self.socket_address,
                'event_type': self.event_type,
        }
        return tags

    def get_json(self):
        return {
            "measurement": "connection_events",
            "tags": self.get_tags(),
            "time": self.timestamp,
            "fields": self.fields # What should we be storing, if duration doesn't exist?
    }


class OpenConnectionEvent(ConnectionEvent):
    def __init__(self, timestamp, logline):
        super(OpenConnectionEvent, self).__init__(timestamp, logline)
        self.connection_id = logline.split("#")[1].split()[0]  # Should this be a tag?
        self.socket_address = logline.split("accepted from ")[1].split()[0]  # Should this be a tag?
        self.event_type = 'open_connection'
        connections[self.connection_id] = {'start_time': parse(timestamp)}
        self.fields = {"value": float(0)}

class CloseConnectionEvent(ConnectionEvent):
    def __init__(self, timestamp, logline):
        super(CloseConnectionEvent, self).__init__(timestamp, logline)
        self.connection_id = logline.split("[conn")[1].split("]")[0]  # Should this be a tag?
        self.socket_address = logline.split("end connection ")[1].split()[0]  # Should this be a tag?
        self.event_type = 'close_connection'
        if self.connection_id in connections:
            connections[self.connection_id]['end_time'] = parse(timestamp)
            self.duration = connections[self.connection_id]['end_time'] - connections[self.connection_id]['start_time']
            self.matching_connection_open = True
            self.fields = {"value": float(self.duration.total_seconds())}
        else:
            connections[self.connection_id] = {'end_time': parse(timestamp)}
            self.matching_connection_open = False
            self.fields = {"value": float(0)}

    def get_tags(self):
        tags = super(CloseConnectionEvent, self).get_tags()
        tags['matching_connection_open'] = self.matching_connection_open
        return tags

with open(args.input_file, 'r') as f:
    for chunk in grouper(f, 100):
        json_points = []
        for line in chunk:
            # zip_longest will backfill any missing values with None, so we need to handle this, otherwise we'll miss the last batch
            if line:
                # TODO This will work for 3.0 loglines only, which print out ISO8601 time - need to add in parsing 2.4/2.6 loglines
                # Should we be parsing the timestamp into a datetime object, and localising?
                timestamp, logline = line.split(maxsplit=1)
                if ' connections now open)' in line:
                    connection_count = line.split("(")[1].split()[0]
                    # TODO - We should be sending an int, not a float - connection counters are integral values
                    json_points.append(create_generic_point('connection_counters', connection_count, timestamp, base_tags))
                if '[initandlisten] connection accepted from' in line:
                    event = OpenConnectionEvent(timestamp, logline)
                    json_points.append(event.get_json())
                elif '] end connection ' in line:
                    event = CloseConnectionEvent(timestamp, logline)
                    json_points.append(event.get_json())
        if json_points:
            # We need to deal with 500: timeout - some kind of retry behaviour
            try:
                client.write_points(json_points)
                print("Wrote in {} points.".format(len(json_points)))
            except Exception as e:
                print(e)
            # print(json_points)
        else:
            print("empty points!!!")

print("Number of connections: {}".format(len(connections)))
i = 0
for connection in connections.items():
    if i < 10:
        print(connection)
        i += 1
    else:
        break