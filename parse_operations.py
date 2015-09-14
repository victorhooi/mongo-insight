#!/usr/bin/env python3
from influxdb import InfluxDBClient
import json
import argparse
import sys
from dateutil.parser import parse
from utils import grouper, configure_logging, write_points


_MEASUREMENT_PREFIX = "operations_"

__author__ = 'victorhooi'

def create_point(timestamp, measurement_name, values, tags):
    return {
        "measurement": measurement_name,
        "tags": tags,
        "time": timestamp,
        "fields": values
    }


# def create_point(timestamp, metric_name, value, tags):
#     return {
#         "measurement": _MEASUREMENT_PREFIX + metric_name,
#         "tags": tags,
#         "time": timestamp,
#         "fields": {
#             "value": value
#         }
#     }


parser = argparse.ArgumentParser(description='Parse a mongod.log logfile for query timing information, and load it into an InfluxDB instance')
parser.add_argument('-b', '--batch-size', default=5000, help="Batch size to process before writing to InfluxDB.")
parser.add_argument('-d', '--database', default="insight", help="Name of InfluxDB database to write to. Defaults to 'insight'.")
parser.add_argument('-n', '--hostname', required=True, help='Host(Name) of the server')
parser.add_argument('-p', '--project', required=True, help='Project name to tag this with')
# Override or set for 2.4
# parser.add_argument('-t', '--timezone', required=True, help='Hostname of the source system -e.g. "UTC", "US/Eastern", or "US/Pacific"')
parser.add_argument('-i', '--influxdb-host', default='localhost', help='InfluxDB instance to connect to. Defaults to localhost.')
parser.add_argument('-s', '--ssl', action='store_true', default=False, help='Enable SSl mode for InfluxDB.')
parser.add_argument('input_file')
args = parser.parse_args()

def main():
    client = InfluxDBClient(host=args.influxdb_host, ssl=args.ssl, verify_ssl=False, port=8086, database=args.database)
    logger = configure_logging('parse_operations')
    with open(args.input_file, 'r') as f:
        line_count = 0
        for chunk in grouper(f, args.batch_size):
            json_points = []
            for line in chunk:
                # zip_longest will backfill any missing values with None, so we need to handle this, otherwise we'll miss the last batch
                if line:
                    line_count += 1
                    values = {}
                    tags = {
                        'project': args.project,
                        'hostname': args.hostname,
                    }
                    tags['operation'] = line.split("] ", 1)[1].split()[0]
                    if tags['operation'] in ['query', 'getmore', 'insert', 'update', 'remove', 'aggregate', 'mapreduce']:
                        # print(line.strip())
                        thread = line.split("[", 1)[1].split("]")[0]
                        # Alternately - print(split_line[3])
                        if "conn" in thread:
                            tags['connection_id'] = thread
                        split_line = line.split()
                        tags['namespace'] = split_line[5]
                        values['duration_in_milliseconds'] = split_line[-1].rstrip('ms')
                        timestamp = parse(split_line[0])
                        # TODO - Parse locks
                        pre_locks, locks = line.split("locks:{ ", 1)
                        # We work backwards from the end, until we run out of key:value pairs
                        for stat in reversed(pre_locks.split()):
                            if ":" in stat:
                                key, value = stat.split(":", 1)
                                values[key] = value
                            else:
                                break
                        if 'planSummary: ' in line:
                            tags['plan_summary'] = (line.split('planSummary: ', 1)[1].split()[0])
                        json_points.append(create_point(timestamp, "operations", values, tags))
            if json_points:
                print(json_points)
                write_points(logger, client, json_points, line_count)
if __name__ == "__main__":
    sys.exit(main())

