# mongo-insight

[![Join the chat at https://gitter.im/victorhooi/mongo-insight](https://badges.gitter.im/Join%20Chat.svg)](https://gitter.im/victorhooi/mongo-insight?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

Collection of utilities to capture, parse and graph MongoDB and system metrics

# Prerequisites

You should ensure you have all of the packages installed in `REQUIREMENTS.txt`. For example:

```
pip install -r REQUIREMENTS.txt
```

(NB: In order to keep things tidy, I recommend you use [venv](https://docs.python.org/dev/library/venv.html) or [virtualenv](https://virtualenv.pypa.io/en/latest/) to setup a self-contained Python environment.)

The script by default also uses a InfluxDB database named `insight`. You can override the default using the `-d`/`--database` flag. You can create a new InfluxDB database from the `influx` shell as follows:
```
# influx
Connected to http://localhost:8086 version 0.9.4-HEAD
InfluxDB shell 0.9.4-HEAD
> create database insight
```
