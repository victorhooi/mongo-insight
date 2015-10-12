#!/usr/bin/env python3
from influxdb import InfluxDBClient
import argparse
from dateutil.parser import parse
from utils import grouper, configure_logging, write_points

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


parser = argparse.ArgumentParser(description='Parse serverStatus() output, and load it into an InfluxDB instance')
parser.add_argument('-b', '--batch-size', default=500, type=int, help="Batch size to process before writing to InfluxDB.")
parser.add_argument('-d', '--database', default="insight", help="Name of InfluxDB database to write to. Defaults to 'insight'.")
parser.add_argument('-n', '--hostname', required=True, help='Host(Name) of the server')
parser.add_argument('-p', '--project', required=True, help='Project name to tag this with')
parser.add_argument('-i', '--influxdb-host', default='localhost', help='InfluxDB instance to connect to. Defaults to localhost.')
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
    # Example of an connection open (3.x)
    # 2015-08-16T22:28:15.350Z I NETWORK  [initandlisten] connection accepted from 10.0.20.7:55317 #32036 (176 connections now open)
    # Example of a connection close (3.x)
    # 2015-08-16T22:28:21.908Z I NETWORK  [conn32033] end connection 10.0.20.8:58809 (176 connections now open)
    # Example of a connection open (2.6):
    # 2015-09-01T01:14:36.759-0700 [initandlisten] connection accepted from 10.106.154.22:44935 #334817 (1394 connections now open)
    # Example of a connection close (2.6):
    # 2015-09-01T01:14:42.066-0700 [conn334811] end connection 10.7.210.44:32916 (1393 connections now open)
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

logger = configure_logging('parse_connections')

with open(args.input_file, 'r', encoding='latin-1') as f:
    line_counter = 0
    for chunk in grouper(f, args.batch_size):
        json_points = []
        for line in chunk:
            line_counter += 1
            # zip_longest will backfill any missing values with None, so we need to handle this, otherwise we'll miss the last batch
            # TODO - Properly handle loglines split over multiple lines, or lines containing just "\n"
            if line:
                # TODO This will work for 3.0 loglines only, which print out ISO8601 time - need to add in parsing 2.4/2.6 loglines
                # Should we be parsing the timestamp into a datetime object, and localising?
                try:
                    timestamp, logline = line.split(maxsplit=1)
                except ValueError as e:
                    logger.error("Error parsing line - {} - {}".format(e, line))
                    break
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
            # TODO - We shouldn't need to wrap this in try/except - should be handled by retry decorator
            try:
                write_points(logger, client, json_points, line_counter)
            except Exception as e:
                logger.error("Retries exceeded. Giving up on this point.")
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