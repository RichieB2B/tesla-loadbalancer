# Loadbalancer for charging Tesla vehicles at home

This is a simple home project that enables me to charge my Tesla at maximum
speed without overloading my home power circuit. 

It uses the mqtt messages published by [DSMR-reader](https://github.com/dsmrreader/dsmr-reader) and calculates the current headroom for charging the Tesla. Using the charging_amps command the Tesla charging speed is scaled up and down as needed. This requires Tesla software 2021.36 or higher to be installed in the car.

Communication with the Tesla API is done using [TeslaPy](https://github.com/tdorssers/TeslaPy).

# Installation
To be able to use this software you need to do a few things first
1. Install DSMR-reader as explained in the [documentation](https://dsmr-reader.readthedocs.io/)
1. Install an mqtt broker. On Raspbian: `apt install mosquitto mosquitto-clients`
1. Configure DSMR-reader to [publish telegrams](https://dsmr-reader.readthedocs.io/en/latest/how-to/admin/mqtt.html#telegram) on the dsmr/mqtt channel. Make sure `phase_power_current_l1` (and l2+l3) are included in the mapping.
1. Install the latest (bleeding edge) [TeslaPy](https://github.com/tdorssers/TeslaPy) version:
   1. `git clone https://github.com/tdorssers/TeslaPy.git`
   1. `cd TeslaPy`
   1. `python3 setup.py --prefix=~/.local`
1. Use `cli.py` to get a Tesla API token. This is explained in the [README](https://github.com/tdorssers/TeslaPy/blob/master/README.md), I used the selenium method.
1. Copy the `cache.json` to the tesla-loadbalancer directory
1. Edit `config.py` to match your settings
1. Start `tesla-mqtt-loadbalancer.py`
