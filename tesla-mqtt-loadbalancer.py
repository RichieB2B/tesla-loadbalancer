#!/usr/bin/python3 -u

import paho.mqtt.client as mqtt
from flask import Flask, render_template, request
import flask.cli
import sys
import json
import time
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
import teslapy
import requests
import threading
import logging
import config

# Initial values
current1 = current2 = current3 = -1
ev_current1 = ev_current2 = ev_current3 = ev_power = -1
p1_delivered = p1_returned = p1_voltage_sum = 0
last_amps = 0
max_tesla = config.twc_safe
pv_mode = config.pv_mode
p1_updated = ev_updated = datetime.min
last_printed = datetime.min
settings_file = 'settings.json'

# Flash web server
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

def tprint(*objects, **argv):
  now=datetime.now().strftime("%b %e %H:%M:%S")
  print(now, *objects, **argv)
  sys.stdout.flush()

def dprint(*objects, **argv):
  if config.debug:
    now=datetime.now().strftime("%b %e %H:%M:%S")
    print(now, *objects, **argv)
    sys.stdout.flush()

@app.route("/")
def index():
  return render_template('main.html', amps=max_tesla, pvmode=pv_mode)

@app.route("/save", methods=['POST'])
def save():
  global pv_mode
  global max_tesla
  if request.form.get('mode','') == 'pv':
    pv_mode = True
  else:
    pv_mode = False
  amps = request.form.get('amps','')
  if amps and amps.isdigit():
    amps = int(amps)
    if amps > config.twc_max:
      amps = config.twc_max
    if amps < config.twc_min:
      amps = config.twc_min
    max_tesla = amps
  tprint(f"Web interface saved: pv_mode = {pv_mode}, amps = {max_tesla}")
  with open(settings_file, 'w') as outfile:
    json.dump({ 'pv_mode': pv_mode, 'max_tesla': max_tesla}, outfile)
  return render_template('saved.html'), {"Refresh": "3; url=/"}

def set_amps(vehicle, amps):
  if amps < 1:
    return {}
  try:
    # set it twice if < 5A, see https://github.com/tdorssers/TeslaPy/pull/42
    if amps < 5:
      vehicle.command('CHARGING_AMPS', charging_amps=amps)
      time.sleep(5)
    result = vehicle.command('CHARGING_AMPS', charging_amps=amps)
  except teslapy.HTTPError as e:
    print(f"{type(e).__name__} during CHARGING_AMPS: {str(e)}")
    result = {}
  # let things settle after changing amps
  time.sleep(15)
  return result

def set_safe_amps(vehicle):
  global last_amps
  tprint(f"Changing seems over, setting Tesla to {config.twc_safe:>2}A.")
  last_amps = config.twc_safe
  set_amps(vehicle, config.twc_safe)

def get_distance(latitude, longitude):
  # https://www.kite.com/python/answers/how-to-find-the-distance-between-two-lat-long-coordinates-in-python
  R = 6373.0
  lat1 = radians(latitude)
  lon1 = radians(longitude)
  lat2 = radians(config.twc_latitude)
  lon2 = radians(config.twc_longitude)
  dlon = lon2 - lon1
  dlat = lat2 - lat1
  a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
  c = 2 * atan2(sqrt(a), sqrt(1 - a))
  distance = R * c
  dprint(f"distance = {distance}")
  return distance

def on_p1_message(client, userdata, msg):
  global current1, current2, current3, p1_delivered, p1_returned, p1_voltage_sum, p1_updated
  m_decode=str(msg.payload.decode("utf-8","ignore"))
  m=json.loads(m_decode)
  current1 = m.get('phase_power_current_l1', current1)
  current2 = m.get('phase_power_current_l2', current2)
  current3 = m.get('phase_power_current_l3', current3)
  p1_delivered = float(m.get('electricity_currently_delivered', p1_delivered))
  p1_returned = float(m.get('electricity_currently_returned', p1_returned))
  v1 = float(m.get('phase_voltage_l1', 230))
  v2 = float(m.get('phase_voltage_l2', 230))
  v3 = float(m.get('phase_voltage_l3', 230))
  p1_voltage_sum = v1 + v2 + v3
  p1_updated = datetime.now()

def on_ev_message(client, userdata, msg):
  global ev_current1, ev_current2, ev_current3, ev_power, ev_updated
  m_decode=str(msg.payload.decode("utf-8","ignore"))
  m=json.loads(m_decode)
  ev_current1 = m.get('CurrentL1', ev_current1)
  ev_current2 = m.get('CurrentL2', ev_current2)
  ev_current3 = m.get('CurrentL3', ev_current3)
  ev_power = m.get('Power', ev_power * 1000.0) / 1000.0
  ev_updated = datetime.now()

def mqtt_init():
  client = mqtt.Client("P1")
  client.message_callback_add(config.mqtt_p1_topic,on_p1_message)
  client.connect(config.mqtt_broker)
  client.subscribe(config.mqtt_p1_topic)
  if config.mqtt_ev_topic:
    client.message_callback_add(config.mqtt_ev_topic,on_ev_message)
    client.subscribe(config.mqtt_ev_topic)
  client.loop_start()

def get_ev_meter(url):
  global ev_current1, ev_current2, ev_current3, ev_power
  try:
    result = requests.get(url, timeout=5)
  except requests.exceptions.ReadTimeout as e:
    return max(ev_current1, ev_current2, ev_current3)
  try:
    data = result.json()
  except Exception as e:
    print(f'{type(e).__name__}: {str(e)}')
    print(result.text)
    return max(ev_current1, ev_current2, ev_current3)
  my_current1 = data.get('CurrentL1', ev_current1)
  my_current2 = data.get('CurrentL2', ev_current2)
  my_current3 = data.get('CurrentL3', ev_current3)
  my_power = data.get('Power', ev_power * 1000.0) / 1000.0
  ev_current1 = my_current1
  ev_current2 = my_current2
  ev_current3 = my_current3
  ev_power = my_power
  return (round(max(my_current1, my_current2, my_current3)), my_power)

def get_tesla_amps(charger_current, charger_power):
  global ev_updated
  if config.ev_meter_url:
    (amps, power) = get_ev_meter(config.ev_meter_url)
  elif config.mqtt_ev_topic:
    amps = max(ev_current1, ev_current2, ev_current3)
    power = ev_power
  else:
    amps = charger_current
    power = float(charger_power)
  ev_updated = datetime.now()
  return (amps, power)

if __name__ == "__main__":
  mqtt_init()
  try:
    with open(settings_file, 'r') as f:
      s = json.load(f)
      pv_mode = s['pv_mode']
      max_tesla = s['max_tesla']
      tprint(f"Read from {settings_file}: pv_mode = {pv_mode}, max_tesla = {max_tesla}")
  except (FileNotFoundError, KeyError):
    pass
  if not config.debug:
    flask.cli.show_server_banner = lambda *args: None
  threading.Thread(target=lambda: app.run(host=config.listen, port=config.port, debug=config.debug, use_reloader=False)).start()
  with teslapy.Tesla(config.tesla_user) as tesla:
    try:
      tesla.fetch_token()
      vehicles = tesla.vehicle_list()
    except teslapy.HTTPError as e:
      print(f"{type(e).__name__}: {str(e)}")
      sys.exit(1)
    charging = False
    debounce = 0
    retry=0
    old_shift_state=''
    last_poll=parked_since=datetime.utcfromtimestamp(0)
    while True:
      current_max = max(current1, current2, current3)
      now=datetime.now()
      if (now - last_printed).total_seconds() >= 3600:
        tprint(f"P1 last updated at {p1_updated}, EV last updated at {ev_updated}")
        last_printed = now
      if p1_updated > datetime.min and p1_updated < now - timedelta(minutes=10):
        tprint(f"P1 last updated at {p1_updated}, EV last updated at {ev_updated}")
        tprint(f"P1 reading too old: exiting")
        sys.exit(0)
      if ev_updated > datetime.min and ev_updated < now - timedelta(days=1):
        tprint(f"P1 last updated at {p1_updated}, EV last updated at {ev_updated}")
        tprint(f"EV reading too old: exiting")
        sys.exit(0)
      # could a Tesla charge session be going on?
      # assume PV production during daytime
      pv_production = pv_mode and (8 < now.hour < 21)
      dprint(f'p1_delivered = {p1_delivered}')
      dprint(f'ev_power = {ev_power}')
      if current_max >= config.baseload + last_amps or pv_production:
        # poll the Tesla for charging state only when online
        try:
          vehicles = tesla.vehicle_list()
          # poll the Tesla for charging state only when online
          if vehicles[0]['state'] == 'online':
            # only poll:
            # - during charging
            # - when power usage is high
            # - while driving (to notice parking)
            # - right after parking
            # - every X minutes to allow sleeping
            if (
                 charging or
                 current_max >= config.baseload + last_amps or
                 (old_shift_state and old_shift_state != 'P') or
                 now - parked_since < timedelta(minutes=config.sleep) or
                 now - last_poll > timedelta(minutes=config.sleep)
              ):
              dprint('Polling Tesla for charging state')
              vehicle_data = vehicles[0].get_vehicle_data()
              shift_state = vehicle_data.get('drive_state',{}).get('shift_state','')
              if old_shift_state and old_shift_state != 'P' and shift_state == 'P':
                parked_since = now
              old_shift_state = shift_state
              last_poll=now
          else:
            vehicle_data = {}
          retry=0
        except Exception as e:
          tprint(f"{type(e).__name__}: {str(e)}")
          vehicle_data = {}
          if retry > 60:
            print(f"{now} Too many errors, exiting.")
            sys.exit(1)
          retry += 1
          time.sleep(30)
          continue
        # only actually do something if the Tesla is charging
        charge_state = vehicle_data.get('charge_state',{})
        if charge_state.get('charging_state') and charge_state['charging_state'] == "Charging":
          # is the Tesla within 500 meters from home?
          drive_state = vehicle_data.get('drive_state',{})
          local_charge = get_distance(drive_state.get('latitude',0), drive_state.get('longitude',0)) < 0.5
          (tesla_amps, tesla_power) = get_tesla_amps(charge_state['charger_actual_current'], charge_state['charger_power'])
          last_amps = tesla_amps
          charge_amps = charge_state['charge_amps']
          overshoot  = min(charge_amps, tesla_amps) > max_tesla or  current_max > config.max_current
          undershoot = max(charge_amps, tesla_amps) < max_tesla and current_max < config.max_current - 1
          if pv_production:
            undershoot = p1_returned * 1000 / p1_voltage_sum >= 0.5
            overshoot = p1_delivered * 1000 / p1_voltage_sum >= 0.5
            dprint("PV production detected")
            dprint(f"returned     = {p1_returned * 1000 / p1_voltage_sum}")
            dprint(f"delivered    = {p1_delivered * 1000 / p1_voltage_sum}")
          dprint(f"charge_amps  = {charge_amps}")
          dprint(f"tesla_amps   = {tesla_amps}")
          dprint(f"max_tesla    = {max_tesla}")
          dprint(f"current_max  = {current_max}")
          dprint(f"local_charge = {local_charge}")
          dprint(f"overshoot    = {overshoot}")
          dprint(f"undershoot   = {undershoot}")
          # is this a charge at home?
          if local_charge:
            charging = True
            # reset debounce counter
            debounce = 0
            # is there a need to adjust the charging speed?
            if overshoot or undershoot:
              if pv_production:
                if overshoot:
                  pv_amps = p1_delivered * 1000 / p1_voltage_sum
                  new_amps = last_amps - int(pv_amps)
                  usage_str = f"P1 delivery is {pv_amps:4.1f}A"
                else:
                  pv_amps = p1_returned * 1000 / p1_voltage_sum
                  new_amps = last_amps + round(pv_amps)
                  usage_str = f"P1 returned is {pv_amps:4.1f}A"
              else:
                headroom = int(config.max_current - max(current_max,tesla_amps))
                new_amps = min(headroom + tesla_amps, max_tesla)
                usage_str = f"Power usage is {current_max:>2}A"
              dprint(f"new_amps     = {new_amps}")
              if overshoot:
                max_amps = max(new_amps, config.twc_min)
              else:
                max_amps = min(new_amps, config.twc_max)
              dprint(f"max_amps     = {max_amps}")
              tprint(f"{usage_str}, Tesla is using {tesla_amps:>2}A. Changing Tesla to {max_amps:>2}A.")
              # set the new charging speed
              set_amps(vehicles[0], max_amps)
        else:
          # was a charging session just stopped?
          if charging and debounce > 3:
            # set safe amps in case load balancing is not running at next charge
            set_safe_amps(vehicles[0])
            charging = False
          # increase debounce counter
          debounce += 1
        # always wait at least 10 seconds between Tesla polls
        time.sleep(10)
      else:
        # was a charging session just stopped?
        if charging and debounce > 3:
          # set safe amps in case load balancing is not running at next charge
          set_safe_amps(vehicles[0])
          charging = False
        # increase debounce counter
        debounce += 1
        # Tesla was not polled, check DSMR data again soon
        time.sleep(2)
