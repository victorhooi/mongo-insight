#!/usr/bin/env python3
import argparse
from datetime import datetime
from influxdb import InfluxDBClient
from pytz import timezone
from utils import configure_logging, write_points
import sys

SAR_DISK_HEADERS = ['timestamp', 'AM_OR_PM', 'device', 'transfers_per_second', 'read_sectors_per_second', 'written_sectors_per_second', 'average_request_size', 'average_queue_size', 'average_wait', 'service_time', 'disk_util_percentage']

parser = argparse.ArgumentParser(description='Parse sar disk output, and load it into an InfluxDB instance')
parser.add_argument('-b', '--batch-size', default=500, type=int, help="Batch size to process before writing to InfluxDB.")
parser.add_argument('-d', '--database', default="insight", help="Name of InfluxDB database to write to. Defaults to 'insight'.")
# parser.add_argument('-n', '--hostname', help='Override the hostname in the sar header')
parser.add_argument('-p', '--project', required=True, help='Project name to tag this with')
parser.add_argument('-t', '--timezone', required=True, help='Hostname of the source system -e.g. "UTC", "US/Eastern", or "US/Pacific"')
parser.add_argument('-i', '--influxdb-host', default='localhost', help='InfluxDB instance to connect to. Defaults to localhost.')
parser.add_argument('-s', '--ssl', action='store_true', default=False, help='Enable SSl mode for InfluxDB.')
parser.add_argument('input_file')
args = parser.parse_args()

def main():
    client = InfluxDBClient(host=args.influxdb_host, ssl=args.ssl, verify_ssl=False, port=8086, database=args.database)
    logger = configure_logging('parse_sar_disk')
    sar_timezone = timezone(args.timezone)
    with open(args.input_file, 'r') as f:
        header_split = f.readline().split()
        hostname = header_split[2].strip("()")
        logger.info("Found hostname {}".format(hostname))
        date = header_split[3]
        logger.info("Found date {} (MM/DD/YYYY)".format(date))
        json_points = []
        for line_number, line in enumerate(f):
            if line.strip() and 'Average:' not in line: # We skip any empty lines, and also the "Average:" lines at the end
                if all(header_keyword in line for header_keyword in ['DEV', 'tps', 'rd_sec/s', 'wr_sec/s']):
                    # Skip the header lines - if a device name contains all of the four keywords below, I will eat my hat
                    pass
                else:
                    disk_stats = dict(zip(SAR_DISK_HEADERS, line.split()))
                    values = {}
                    local_timestamp = datetime.strptime("{} {} {}".format(date, disk_stats['timestamp'], disk_stats['AM_OR_PM']), "%m/%d/%Y %I:%M:%S %p")
                    timestamp = sar_timezone.localize(local_timestamp)
                    for metric_name, value in disk_stats.items():
                        if metric_name == 'device':
                            disk_name = value
                        elif metric_name in ['AM_OR_PM', 'timestamp']:
                            pass
                        else:
                            values[metric_name] = float(value)
                    json_points.append({
                        "measurement": "sar_disk",
                        "tags": {
                            "project": args.project,
                            "hostname": hostname,
                            "device": disk_name,
                        },
                        "time": timestamp.isoformat(),
                        "fields": values
                    })
            if len(json_points) >= args.batch_size:
                write_points(logger, client, json_points, line_number)
                json_points = []
        write_points(logger, client, json_points, line_number)

if __name__ == "__main__":
    sys.exit(main())
