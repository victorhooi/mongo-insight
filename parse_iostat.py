#!/usr/bin/env python3
from datetime import datetime
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError
from requests.exceptions import SSLError
from pytz import timezone
import urllib3
import argparse
import re
import sys
from utils import grouper, configure_logging

urllib3.disable_warnings()

system_stat_headers = ['user_cpu', 'nice_cpu', 'system_cpu', 'iowait', 'steal', 'idle']
disk_stat_headers = ['read_requests_merged', 'write_requests_merged', 'read_requests', 'write_requests', 'read_sectors', 'write_sectors', 'average_request_size', 'average_queue_length', 'average_wait', 'average_service_time', 'utilisation']

# TODO: Parse header line
# E.g.: Linux 2.6.32-358.56.1.el6.x86_64 (db.example.com) 	06/29/15 	_x86_64_	(24 CPU)


def parse_iostat(lines):
    """Parse lines of iostat information, yielding iostat blocks.

    lines should be an iterable yielding separate lines of output
    """
    block = None
    for line in lines:
        line = line.strip()
        try:
            if ' AM' in line or ' PM' in line: # What happens if their device names have AM or PM?
                tm = datetime.strptime(line, "%m/%d/%Y %I:%M:%S %p")
            else:
                tm = datetime.strptime(line, "%m/%d/%y %H:%M:%S")
            if block: yield block
            block = [tm]
        except ValueError:
            # It's not a new timestamp, so add it to the existing block
            # We ignore the iostat startup lines (which deals with random restarts of iostat), as well as empty lines
            if '_x86_64_' not in line:
                block.append(line)
    if block: yield block


parser = argparse.ArgumentParser(description='Parse iostat output, and load it into an InfluxDB instance')
parser.add_argument('-d', '--database', default="insight", help="Name of InfluxDB database to write to. Defaults to 'insight'.")
parser.add_argument('-n', '--hostname', help='Override the hostname in the iostat header')
parser.add_argument('-p', '--project', required=True, help='Project name to tag this with')
parser.add_argument('-t', '--timezone', required=True, help='Hostname of the source system -e.g. "UTC", "US/Eastern", or "US/Pacific"')
parser.add_argument('-i', '--influxdb-host', default='localhost', help='InfluxDB instance to connect to. If this is not provided, we default to localhost.')
parser.add_argument('-s', '--ssl', action='store_true', default=False, help='Enable SSl mode for InfluxDB.')
parser.add_argument('input_file')
args = parser.parse_args()


def main():
    client = InfluxDBClient(host=args.influxdb_host, ssl=args.ssl, verify_ssl=False, port=8086, database=args.database)
    logger = configure_logging('parse_iostat')
    iostat_timezone = timezone(args.timezone)
    with open(args.input_file, 'r') as f:
        if args.hostname:
            f.__next__() # Skip the "Linux..." line
        else:
            hostname = re.split(r'[()]', f.readline())[1]
        logger.info("Found hostname {}".format(hostname))
        f.__next__() # Skip the blank line
        for chunk in grouper(parse_iostat(f), 500):
            json_points = []
            for block in chunk:
                if block:
                    try:
                        for i, line in enumerate(block):
                            if i == 0:
                                timestamp = iostat_timezone.localize(line)
                                # print(timestamp)
                                # import ipdb;ipdb.set_trace()
                                # print("timestamp is {}".format(timestamp))
                                # TODO: Timezone?
                                # TODO: Better way of storing timestamp
                            elif i == 1: # CPU Metric Headings
                                pass
                            elif i==2:
                                system_stats = dict(zip(system_stat_headers, line.split()))
                                values = {}
                                for metric_name, value in system_stats.items():
                                    values[metric_name] = float(value)
                                json_points.append({
                                    "measurement": "iostat",
                                    "tags": {
                                        "project": args.project,
                                        "hostname": hostname
                                    },
                                    "time": timestamp.isoformat(),
                                    "fields": values
                                })
                            elif i==4: # Disk metric headings
                                pass
                            elif i >= 5 and line:
                                disk_stats = {}
                                device = line.split()[0]
                                disk_stats[device] = dict(zip(disk_stat_headers, line.split()[1:]))

                                for disk_name, metrics in disk_stats.items():
                                    values = {}
                                    for metric_name, value in metrics.items():
                                        # Nasty hack to deal with bad data from Morgan Stanley
                                        # if disk_name not in ['sda', 'sdb', 'dm-0', 'dm-1', 'dm-2']:
                                        #     print(block)
                                        #     raise ValueError
                                        values[metric_name] = float(value)
                                    json_points.append({
                                        "measurement": "iostat",
                                        "tags": {
                                            "project": args.project,
                                            "hostname": hostname,
                                            "device": disk_name,
                                        },
                                        "time": timestamp.isoformat(),
                                        "fields": values
                                    })

                    except ValueError as e:
                        print("Bad output seen - skipping")
                        print(e)
                        print(block)
            try:
                client.write_points(json_points)
                logger.info("Wrote in {} points to InfluxDB".format(len(json_points)))
            except InfluxDBClientError as e:
                logger.error('Unable to write to InfluxDB - {}'.format(e))
            except SSLError as e:
                logger.error('SSL error - {}'.format(e))

if __name__ == "__main__":
    sys.exit(main())
