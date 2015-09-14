#!/usr/bin/env python3
from influxdb import InfluxDBClient
import json
import argparse
import sys
from utils import get_nested_items, grouper, configure_logging
from serverstatus_metrics import common_metrics, mmapv1_metrics, wiredtiger_metrics
from requests.exceptions import RequestException

_MEASUREMENT_PREFIX = "ss_"
_BATCH_SIZE = 50

__author__ = 'victorhooi'


def create_point(timestamp, measurement_name, values, tags):
    return {
        "measurement": measurement_name,
        "tags": tags,
        "time": timestamp,
        "fields": values
    }


def strip_floatApprox_wrapping(field):
    """
    Strip the wrapping dict (floatApprox) around a value, if it exists.
    :param field:
    :return:
    """
    if isinstance(field, dict):
        return field['floatApprox']
    else:
        return field


def get_metrics(measurement_name, server_status_json, metrics_to_extract, line_number):
    """
    Extracts a list of metrics from a server-status JSON object.
    We also take a line-number, so that we can print it in any error messages.
    Returns a list of metric tuples (timestamp, metric_name, value and tags)
    :return:
    """
    values = {}

    timestamp = server_status_json['localTime']

    # TODO - Deal with missing tags - e.g. storageEngine is only in 3.0+
    tags = {
        'project': args.project,
        'hostname': server_status_json['host'].split(":")[0],
        'version': server_status_json['version'],
        # 'storage_engine': server_status_json['storageEngine']['name'],
        'pid': strip_floatApprox_wrapping(server_status_json['pid'])
    }

    for metric_name, location in metrics_to_extract.items():
        try:
            value = strip_floatApprox_wrapping(get_nested_items(server_status_json, *location))
            values[metric_name] = float(value) # Should this always be a float?
        # Handle missing fields.
        except KeyError:
            print("Unable to find the metric \"{}\" in line {}.".format(metric_name, line_number))
        except TypeError:
            print(line_number, metric_name, location)

    # print(values)
    # metrics.append((timestamp, metric_name, value, tags))

    return (timestamp, measurement_name, values, tags)


parser = argparse.ArgumentParser(description='Parse serverStatus() output, and load it into an InfluxDB instance')
parser.add_argument('-d', '--database', default="insight", help="Name of InfluxDB database to write to. Defaults to 'insight'.")
parser.add_argument('-p', '--project', required=True, help='Project name to tag this with')
parser.add_argument('-i', '--influxdb-host', default='localhost', help='InfluxDB instance to connect to. If this is not provided, we default to localhost.')
parser.add_argument('-s', '--ssl', action='store_true', default=False, help='Enable SSl mode for InfluxDB.')
parser.add_argument('input_file')
args = parser.parse_args()

def main():
    logger = configure_logging('parse_serverstatus')
    client = InfluxDBClient(host=args.influxdb_host, ssl=args.ssl, verify_ssl=False, port=8086, database=args.database)
    with open(args.input_file, 'r') as f:
        for line_number, chunk in enumerate(grouper(f, _BATCH_SIZE)):
            # print(line_number)
            json_points = []
            for line in chunk:
                # zip_longest will backfill any missing values with None, so we need to handle this, otherwise we'll miss the last batch
                if line:
                    try:
                        server_status_json = json.loads(line)
                        # print((line_number + 0) * _BATCH_SIZE)
                        # print((line_number + 1) * _BATCH_SIZE)
                        common_metric_data = get_metrics("serverstatus", server_status_json, common_metrics, line_number)
                        json_points.append(create_point(*common_metric_data))
                        wiredtiger_metric_data = get_metrics("serverstatus_wiredtiger", server_status_json, wiredtiger_metrics, line_number)
                        json_points.append(create_point(*wiredtiger_metric_data))
                        # for metric_data in get_metrics(server_status_json, common_metrics, line_number):
                        #     import ipdb; ipdb.set_trace()
                        #     print(json_points)
                        #     json_points.append(create_point(*metric_data))
                        # # for metric in get_metrics(server_status_json, wiredtiger_metrics, line_number):
                        #     json_points.append(create_point(*metric))
                        # for metric in get_metrics(server_status_json, mmapv1_metrics, line_number):
                        #     json_points.append(create_point(*metric))
                    except ValueError:
                        logger.error("Line {} does not appear to be valid JSON - \"{}\"".format(line_number, line.strip()))
            try:
                client.write_points(json_points)
                logger.info("Wrote in {} points to InfluxDB. Processed up to line {}.".format(len(json_points), line_number))
            except RequestException as e:
                logger.error("Unable to connect to InfluxDB at {} - {}".format(client._host, e))
if __name__ == "__main__":
    sys.exit(main())

