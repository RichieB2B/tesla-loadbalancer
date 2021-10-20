# tesla-loadbalancer
Loadbalancer for charging Tesla vehicles at home

This is a simple home project that enables me to charge my Tesla at maximum
speed without overloading my home power circuit. 

It uses the mqtt messages published by [DSMR-reader](https://github.com/dsmrreader/dsmr-reader) and calculates the current headroom for charging the Tesla. Using the charging_amps command the Tesla charging speed is scaled up and down as needed. This requires Tesla software 2021.36 or higher to be installed in the car.

Communication with the Tesla API is done using [TeslaPy](https://github.com/tdorssers/TeslaPy).
