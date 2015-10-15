#!/usr/bin/env python3
import argparse
from influxdb import InfluxDBClient
import json
import sys
from utils import configure_logging, write_points


def extract_metrics_from_mms_dump(mms_dumpfile):
    extracted_metrics = {}
    with open(mms_dumpfile, 'r') as f:
        for line in f:
            if line.startswith("{"):
                line_as_json = json.loads(line)
                project = "SOME_PROJECT"
                hostname = line_as_json['hostId']
                metric_name = line_as_json['metricName']
                if (project, hostname) not in extracted_metrics:
                    extracted_metrics[(project, hostname)] = {}

                for point in line_as_json['dataPoints']:
                    if point['timestamp'] not in extracted_metrics[(project, hostname)]:
                        extracted_metrics[(project, hostname)][point['timestamp']] = {}
                    else:
                        extracted_metrics[(project, hostname)][point['timestamp']][metric_name] = float(point['value'])

    return extracted_metrics

parser = argparse.ArgumentParser(description='Parse iostat output, and load it into an InfluxDB instance')
parser.add_argument('-b', '--batch-size', default=500, type=int, help="Batch size to process before writing to InfluxDB.")
parser.add_argument('-d', '--database', default="insight", help="Name of InfluxDB database to write to. Defaults to 'insight'.")
# parser.add_argument('-n', '--hostname', help='Override the hostname in the iostat header')
parser.add_argument('-p', '--project', required=True, help='Project name to tag this with')
parser.add_argument('-i', '--influxdb-host', default='localhost', help='InfluxDB instance to connect to. Defaults to localhost.')
parser.add_argument('-s', '--ssl', action='store_true', default=False, help='Enable SSl mode for InfluxDB.')
parser.add_argument('input_file')
args = parser.parse_args()


def main():
    json_points = []
    client = InfluxDBClient(host=args.influxdb_host, ssl=args.ssl, verify_ssl=False, port=8086, database=args.database)
    logger = configure_logging('parse_mms_metrics')

    extracted_metrics = extract_metrics_from_mms_dump(args.input_file)


    json_points = []
    for tagset, metrics_for_all_timestamps in extracted_metrics.items():
        for timestamp, metrics_for_one_timestamp in metrics_for_all_timestamps.items():
            json_points.append({
                "timestamp": timestamp,
                "measurement": "cloudmanager_data",
                "tags": {
                    "project": tagset[0], # Magic number - not great
                    "hostname": tagset[1]
                },
                "fields": metrics_for_one_timestamp
            })
            if len(json_points) >= args.batch_size:
                print(len(json_points))
                write_points(logger, client, json_points, "N/A")
                json_points = []

    write_points(logger, client, json_points, "N/A")

if __name__ == "__main__":
    sys.exit(main())