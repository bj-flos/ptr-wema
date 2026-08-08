"""
This module contains the weather class. When get_status() is called, the weather situation
is evaluated and self.wx_is_ok and self.open_is_ok are evaluated and published along
with self.status, a dictionary.

This module should be expanded to integrate multiple Wx sources, particularly Davis and
SkyAlert.

Weather holds are counted only when they INITIATE within the Observing window. So if a
hold started just before the window and opening was late that does not count for anti-
flapping purposes.

This module sends 'signals' through the Events layer then TO the enclosure by checking
as sender that an OPEN for example can get through the Events layer. It is Mandatory
the receiver (the enclosure in this case) also checks the Events layer. The events layer
is populated once per observing day with default values. However the dictionary entries
can be modified for debugging or simulation purposes.
"""

import json
import socket
import time
import os
try:
    import win32com.client
except ImportError:  # not on Windows -- Alpaca drivers do not need it
    win32com = None
from devices.alpaca_driver import is_alpaca, dispatch
# import redis
import traceback

from global_yard import g_dev
# from site_config import get_ocn_status
from wema_utility import plog

import requests
import json

import datetime



def linearize_unihedron(uni_value):  # Need to be coefficients in config.
    #  Based on 20180811 data
    uni_value = float(uni_value)
    if uni_value < -1.9:
        uni_corr = 2.5 ** (-5.85 - uni_value)
    elif uni_value < -3.8:
        uni_corr = 2.5 ** (-5.15 - uni_value)
    elif uni_value <= -12:
        uni_corr = 2.5 ** (-4.88 - uni_value)
    else:
        uni_corr = 6000
    return uni_corr


#  Unused
def f_to_c(f):
    return round(5 * (f - 32) / 9, 2)


class ObservingConditions:
    def __init__(self, driver: str, name: str, config: dict, astro_events):
        self.name = name
        self.astro_events = astro_events
        self.siteid = config["wema_name"]
        self.config = config
        g_dev["ocn"] = self
        # g_dev['obs'].night_fitzgerald_number = 0,  # 20230709 initialse this varable to permissive state WER
        self.sample_time = 0
        #self.ok_to_open = "n/a"  # This is a default on startup.
        self.wet_flag = False
        self.gust_memory = 0.0
        self.observing_condtions_message = "-"
        self.wx_is_ok = False
        self.clamp_latch = False
        self.wait_time = 0  # A countdown to re-open
        self.wx_system_enable = True  # Purely a debugging aid.
        self.wx_test_cycle = 0
        self.prior_status = None
        self.prior_status_2 = None
        self.wmd_fail_counter = 0
        self.temperature = self.config["reference_ambient"]  # Index needs
        self.pressure = self.config["reference_pressure"]  # to be months.
        self.unihedron_connected = True  # NB NB NB His needs improving, drive from config
        self.hostname = socket.gethostname()

        self.driver=driver

        self.aagsolo=False

        if driver is not None:



            
            if driver == 'aagsolo':
                self.aagsolo=True
                
            if is_alpaca(driver):
                # ObservingConditions over Alpaca. alpyca exposes the same
                # members as the COM object, so readings below are unchanged.
                self.sky_monitor = dispatch(driver)
                self.sky_monitor.Connected = True
                plog('Alpaca observing_conditions connected: ' + str(driver))

                # A SafetyMonitor, where configured, stands in for the COM
                # ok-to-open monitor: both answer the same question.
                driver_2 = config["observing_conditions"]["observing_conditions1"].get("driver_2")
                if is_alpaca(driver_2):
                    self.sky_monitor_oktoopen = dispatch(driver_2)
                    self.sky_monitor_oktoopen.Connected = True
                    plog('Alpaca safety monitor connected: ' + str(driver_2))

            elif not self.aagsolo and not self.config['observing_conditions']['observing_conditions1']["name"] == 'SkyAlert Custom for ARO':
                win32com.client.pythoncom.CoInitialize()
                self.sky_monitor = win32com.client.Dispatch(driver)
                self.sky_monitor.connected = True
                try:
                    driver_2 = config["observing_conditions"]["observing_conditions1"][
                        "driver_2"
                    ]
                    self.sky_monitor_oktoopen = win32com.client.Dispatch(driver_2)
                    self.sky_monitor_oktoopen.Connected = True
                    driver_3 = config["observing_conditions"]["observing_conditions1"][
                        "driver_3"
                    ]

                except:
                    plog('ocn Drivers 2 or 3 not present.')
                    driver_2 = None
                    driver_3 = None
                if driver_3 is not None:
                    self.sky_monitor_oktoimage = win32com.client.Dispatch(driver_3)
                    self.sky_monitor_oktoimage.Connected = True
                    plog("observing_conditions: sky_monitors connected = True")

                if config["observing_conditions"]["observing_conditions1"]["has_unihedron"]:

                    unihedron_path = self.config['wema_path'] + self.config['wema_name'] + "/unihedron"
                    if not os.path.exists(unihedron_path):
                        os.makedirs(unihedron_path)

                    self.unihedron_connected = True
                    try:
                        driver = config["observing_conditions"]["observing_conditions1"][
                            "uni_driver"
                        ]
                        port = config["observing_conditions"]["observing_conditions1"][
                            "unihedron_port"
                        ]
                        self.unihedron = win32com.client.Dispatch(driver)
                        self.unihedron.Connected = True
                        plog(
                            "observing_conditions: Unihedron is connected, on COM"
                            + str(port)
                        )
                    except:
                        plog(
                            "Unihedron on Port COM" + str(port) + " is disconnected. Observing will proceed."
                        )
                        self.unihedron_connected = False
                        # NB NB if no unihedron is installed the status code needs to not report it.
                else:
                    self.unihedron_connected = False



        # self.wx_hold = False
        self.last_wx = None

    def get_status(self):
        """
        Regularly calling this routine returns weather status dict for AWS,
        evaluates the Wx reporting and manages temporary closes,
        known as weather-holds

        Returns
        -------
        status : TYPE
            DESCRIPTION.

        """
        # Just need to initialise this.
        status = None
        
        
        if self.aagsolo:


            # URL of the AAG Solo last data endpoint
            url = "http://aagsolo/cgi-bin/cgiLastData"

            # Fetch the data
            response = requests.get(url)



            # Check if the request was successful
            if response.status_code == 200:
                # Parse the key-value data
                data_lines = response.text.strip().split("\n")

                # Convert to dictionary
                weather_data = {}
                for line in data_lines:
                    key, value = line.split("=")
                    try:
                        # Try converting numerical values to float or int where possible
                        if "." in value:
                            weather_data[key] = float(value)
                        else:
                            weather_data[key] = int(value)
                    except ValueError:
                        # Keep string values as they are
                        weather_data[key] = value.strip()


            else:
                print("Failed to fetch data. HTTP Status:", response.status_code)            
           
            # rain_rate is either on or off
            # so one or zero
            if weather_data['rain'] < self.config["observing_conditions"]["observing_conditions1"]['aagsolo_rain_threshold']:
                self.rain_rate=1
            else:
                self.rain_rate=0

            # Other things ocn creates
            status = {}
            illum, mag = self.astro_events.illuminationNow()
            if illum > 500:
                illum = int(illum)
            else:
                illum = round(illum, 3)
            if self.unihedron_connected:
                try:
                    uni_measure = (
                        self.unihedron.SkyQuality
                    )  # Provenance of 20.01 is dubious 20200504 WER
                except:
                    uni_measure = 0
            else:
                uni_measure = 0

            # Forming standard variables.
            self.temperature=weather_data['temp']
            try:
                self.new_pressure=weather_data['relpress']
            except:
                self.new_pressure=1000

            self.humidity=weather_data['hum']
            self.dewpoint=weather_data['dewp']
            self.sky_minus_ambient=weather_data['clouds']-weather_data['temp']
            self.windspeed=weather_data['wind']
            
            # Parse it into a datetime object
            dt_obj = datetime.datetime.strptime(weather_data['dataGMTTime'], "%Y/%m/%d %H:%M:%S")
            
            # Convert to timestamp
            timestamp = dt_obj.timestamp()
            

            status = {
                "temperature_C": self.temperature,
                "pressure_mbar": self.new_pressure,
                "humidity_%": self.humidity,
                "dewpoint_C": self.dewpoint,
                "sky_temp_C": weather_data['clouds'],
                "last_sky_update_s": timestamp,
                "wind_m/s": self.windspeed,
                "rain_rate": self.rain_rate,
                "solar_flux_w/m^2": None,
                "calc_HSI_lux": illum,
                "calc_sky_mpsas": round(uni_measure, 2),  
                "lightning_strike_radius km": 'n/a',
                "general_obscuration %": 'n/a',
                "photometric extinction k'": 'n/a',
            }


            print (" **** AAGSOLO READOUT *******")
            print (weather_data)
            print (" **** PTR STATUS **********")
            print (status)

            return status


        elif self.config['observing_conditions']['observing_conditions1']["name"] == 'SkyAlert Custom for ARO':
# =============================================================================
#         #This is the normal path for ARO
#         20200514 decommisioning SkyAlert for two skywatchers.  No Solo yet.
# =============================================================================
        #NB NB NB 20240218  Boltwood bw1[15] reporting 3 all the time. WE may need to mask this out.
        #DO NOT RELY ON THE BOLTWOOD FOR SKY TEMP
        #10.0.0.195 is NWEST (Black Cube), detects wind and moisture
        #10.0.0.196 is NEAST, detects no wind, but yes to moisture

        # THIS IS ARO CUSTOM - THE OTHER VERSION
        #    try:
        #        with open('c://users//obs//Documents//AAG_sld.dat', 'r') as sa_rec:
        #            sa_ne = sa_rec.readline().split()
        #       # with open('W:\skyalert\weatherdata_ne.txt', 'r') as sa_rec:
        #            #sa_ne = sa_rec.readline().split()
        #        #print('SkyAlert NW: w wind ', sa_nw, '\n')
        #        print('SkyAlert NE: ', sa_ne, '\n')
                
                


        #C:/Users/obs/Documents
            try:
# <<<<<<< Updated upstream
                with open('C://Users//obs//Documents//AAG_SLD.dat', 'r') as sa_rec:
                    #with open('W:\skyalert\weatherdata_nw.txt', 'r') as sa_rec:
                    sa_nw = sa_rec.readline().split()
                with open('Q://Documents//AAG_SLD.dat', 'r') as sa_rec:
                    #with open('W:\skyalert\weatherdata_ne.txt', 'r') as sa_rec:
                        #****Note not reading second cloudwatcher yet.
                    sa_ne = sa_rec.readline().split()
                    sa_nw = sa_ne
                print('Cloud_watcher NW: ', sa_nw, '\n')
                print('Cloud_watcher NE: no Hum, Press ', sa_ne, '\n')

# =======
                # with open('W:\skyalert\weatherdata_nw.txt', 'r') as sa_rec:
                #     sa_nw = sa_rec.readline().split()
                # with open('W:\skyalert\weatherdata_ne.txt', 'r') as sa_rec:
                #     sa_ne = sa_rec.readline().split()
                # print('SkyAlert NW: w wind ', sa_nw, '\n')
                # print('SkyAlert NE: no wind ', sa_ne, '\n')
                
# >>>>>>> Stashed changes
                #The datetime for the data above needs to be verified as current,
                #if not current go directly to commanding a close.

                

                rate = ["Unk.", 'Dry', 'Wet', 'Raining']
                cover = ["Unk.", 'Clear',' Cloudy', 'Very Cloudy']
                self.temperature = round(float(sa_ne[5]), 1)
                self.sky_temp = round(float(sa_ne[4]), 1)# + float(sa_nw[4]))/2, 1)
                self.windspeed = round(float(sa_ne[7]), 1)  # incoming is km/h  Note change os skyalert
                if self.windspeed > self.gust_memory:
                    self.gust_memory = self.windspeed
# <<<<<<< Updated upstream
                self.humidity = round(float(sa_ne[8]), 1)
                self.dewpoint = round(float(sa_ne[9]), 1)
                
                # self.rain_alert = int(sa_ne[11])

                self.rain_alert = int(sa_nw[11]) or int(sa_ne[11])

                self.wet_alert = int(sa_ne[12])
                time_since = int(float(sa_ne[13]))
                plog("time since:  ", time_since)
                
                timestamp=time.time()-time_since
                self.time_of_update = round(float(sa_ne[14]), 5)


                self.cloud_condition = int(sa_ne[15]) # unk, Clear, Cloudy, Very Cloudy
                self.wind_condition = int(sa_ne[16]) # unk, Calm, Windy, Very Windy
                self.rain_condition = int(sa_ne[17]) # unk, Dry, Wet, Raining  #NB NB NB 20250102 NW unit shows rain at -2C  WER
                self.daylight_condition = bool(sa_ne[18]) # unk Dark, Light, Very Light
                self.close_requested = bool(sa_ne[19])
# =======
                # self.humidity = round(float(sa_nw[8]), 1)
                # self.dewpoint = round(float(sa_nw[9]), 1)
                # #Fixed gross error mixing mph and m/s 20231226 WER
                # #breakpoint()
                
                # self.rain_alert = int(sa_nw[11]) or int(sa_ne[11])
                # self.wet_alert = int(sa_nw[12])
                # self.time_since = int(float(sa_nw[13]))
                # plog("time since:  ", self.time_since)
                # timestamp=time.time()-self.time_since
                # self.time_of_update = round(float(sa_nw[14]), 5)


                # self.cloud_condition = int(sa_nw[15]) # unk, Clear, Cloudy, Very Cloudy
                # self.wind_condition = int(sa_nw[16]) # unk, Calm, Windy, Very Windy
                # self.rain_condition = int(sa_nw[17]) # unk, Dry, Wet, Raining  #NB NB NB 20250102 NW unit shows rain at -2C  WER
                # self.daylight_condition = bool(sa_nw[18]) # unk Dark, Light, Very Light
                # self.close_requested = bool(sa_nw[19])
# >>>>>>> Stashed changes
                #Note the rates and cover are synthesized by a lookup.
                self.rain_rate = rate[self.rain_condition]
                self.cloud_cover = cover[self.cloud_condition]
                # This is important new code for ARO and evntually MRC -- add lightning later.

                if self.rain_alert or self.wet_alert or self.rain_condition in \
                    ['Wet', 'Raining']:
                    self.wet_flag = True   #This is intended to latch the roof closed for the night
                    self.rain_rate = 1
                else:
                    self.rain_rate = 0

                if self.cloud_condition==1:
                    self.cloud_cover = 0
                elif self.cloud_condition==2:
                    self.cloud_cover = 40
                elif self.cloud_condition==3:
                    self.cloud_cover=100

                #
                status = {}
                illum, mag = self.astro_events.illuminationNow()
                # illum = float(redis_monitor["illum lux"])
                if illum > 500:
                    illum = int(illum)
                else:
                    illum = round(illum, 3)
                if self.unihedron_connected:
                    try:
                        uni_measure = (
                            self.unihedron.SkyQuality
                        )  # Provenance of 20.01 is dubious 20200504 WER
                    except:
                        uni_measure = 0
                else:
                    uni_measure = 0
                if uni_measure == 0:
                    uni_measure = round(
                        (mag - 20.01), 2
                    )  # Fixes Unihedron when sky is too bright
                    status["meas_sky_mpsas"] = uni_measure
                    self.meas_sky_lux = illum
                else:
                    self.meas_sky_lux = linearize_unihedron(uni_measure)
                    status["meas_sky_mpsas"] = uni_measure

                # self.temperature = round((bw1[5] + sa_nw[5])/2., 2)
                self.humidity
                try:  # NB NB Boltwood vs. SkyAlert difference.
                    self.pressure = self.sky_monitor.Pressure
                    assert self.pressure > 200

                except:
                    self.pressure = self.config["reference_pressure"]


                try:
                    self.new_pressure = round(float(self.pressure), 2)  # was [0]), 2)
                except:
                    self.new_pressure = round(float(self.pressure), 2)

                '''
                #Now let us check for lightning:  Read a file from ARO-0m30
                '''
               
                status = {
                    "temperature_C": self.temperature,
                    "pressure_mbar": self.new_pressure,
                    "humidity_%": self.humidity,
                    "dewpoint_C": self.dewpoint,
                    "sky_temp_C": self.sky_temp,
                    "last_sky_update_s": timestamp,
                    "wind_m/s": self.windspeed,
                    "rain_rate": self.rain_rate,
                    "solar_flux_w/m^2": None,
                    "calc_HSI_lux": illum,
                    "calc_sky_mpsas": round(uni_measure, 2),
                    "lightning_strike_radius km": 'n/a',
                    "general_obscuration %": 'n/a',
                    "photometric extinction k'": 'n/a',
                }

                # Store status in self.status
                self.status=status

                return status
            except:
                plog(traceback.format_exc())

                plog('something went wrong with the boltwood stuff')
                plog('above is an unglamourous traceback but continuing onwards')
                
                return self.status
            
        elif self.config['observing_conditions']['observing_conditions1']["name"] == 'SkyAlert Custom for MRC':
# =============================================================================
#         #This is the normal path for ARO
#         20200514 decommisioning SkyAlert for two skywatchers.  No Solo yet.
# =============================================================================
        #NB NB NB 20240218  Boltwood bw1[15] reporting 3 all the time. WE may need to mask this out.
        #DO NOT RELY ON THE BOLTWOOD FOR SKY TEMP
        #10.0.0.195 is NWEST (Black Cube), detects wind and moisture
        #10.0.0.196 is NEAST, detects no wind, but yes to moisture
 

        # THIS IS ARO CUSTOM - THE OTHER VERSION
        #    try:
        #        with open('c://users//obs//Documents//AAG_sld.dat', 'r') as sa_rec:
        #            sa_ne = sa_rec.readline().split()
        #       # with open('W:\skyalert\weatherdata_ne.txt', 'r') as sa_rec:
        #            #sa_ne = sa_rec.readline().split()
        #        #print('SkyAlert NW: w wind ', sa_nw, '\n')
        #        print('SkyAlert NE: ', sa_ne, '\n')
                
                


        #C:/Users/obs/Documents
            try:
                # with open('C://Users//obs//Documents//AAG_SLD.dat', 'r') as sa_rec:
                #     #with open('W:\skyalert\weatherdata_nw.txt', 'r') as sa_rec:
                #     sa_nw = sa_rec.readline().split()
                # with open('Q://Documents//AAG_SLD.dat', 'r') as sa_rec:
                #     #with open('W:\skyalert\weatherdata_ne.txt', 'r') as sa_rec:
                #         #****Note not reading second cloudwatcher yet.
                #     sa_ne = sa_rec.readline().split()
                #     sa_nw = sa_ne
                # print('Cloud_watcher NW: ', sa_nw, '\n')
                # print('Cloud_watcher NE: no Hum, Press ', sa_ne, '\n')
                
                with open('c://users//obs//Documents//AAG_sld.dat', 'r') as sa_rec:
                    sa_ne = sa_rec.readline().split()
                  
                    print('SkyAlert NE: ', sa_ne, '\n')

                #The datetime for the data above needs to be verified as current,
                #if not current go directly to commanding a close.



                rate = ["Unk.", 'Dry', 'Wet', 'Raining']
                cover = ["Unk.", 'Clear',' Cloudy', 'Very Cloudy']
                self.temperature = round(float(sa_ne[5]), 1)
                self.sky_temp = round(float(sa_ne[4]), 1)# + float(sa_nw[4]))/2, 1)
                self.windspeed = round(float(sa_ne[7]), 1)  # incoming is km/h  Note change os skyalert
                if self.windspeed > self.gust_memory:
                    self.gust_memory = self.windspeed
                self.humidity = round(float(sa_ne[8]), 1)
                self.dewpoint = round(float(sa_ne[9]), 1)
                
               # self.rain_alert = int(sa_ne[11])

                self.rain_alert = int(sa_ne[11])

                self.wet_alert = int(sa_ne[12])
                time_since = int(float(sa_ne[13]))
                plog("time since:  ", time_since)
                
                timestamp=time.time()-time_since
                self.time_of_update = round(float(sa_ne[14]), 5)


                self.cloud_condition = int(sa_ne[15]) # unk, Clear, Cloudy, Very Cloudy
                self.wind_condition = int(sa_ne[16]) # unk, Calm, Windy, Very Windy
                self.rain_condition = int(sa_ne[17]) # unk, Dry, Wet, Raining  #NB NB NB 20250102 NW unit shows rain at -2C  WER
                self.daylight_condition = bool(sa_ne[18]) # unk Dark, Light, Very Light
                self.close_requested = bool(sa_ne[19])
                #Note the rates and cover are synthesized by a lookup.
                self.rain_rate = rate[self.rain_condition]
                self.cloud_cover = cover[self.cloud_condition]
                # This is important new code for ARO and evntually MRC -- add lightning later.

                if self.rain_alert or self.wet_alert or self.rain_condition in \
                    ['Wet', 'Raining']:
                    self.wet_flag = True   #This is intended to latch the roof closed for the night
                    self.rain_rate = 1
                else:
                    self.rain_rate = 0

                if self.cloud_condition==1:
                    self.cloud_cover = 0
                elif self.cloud_condition==2:
                    self.cloud_cover = 40
                elif self.cloud_condition==3:
                    self.cloud_cover=100

                #
                status = {}
                illum, mag = self.astro_events.illuminationNow()
                # illum = float(redis_monitor["illum lux"])
                if illum > 500:
                    illum = int(illum)
                else:
                    illum = round(illum, 3)
                if self.unihedron_connected:
                    try:
                        uni_measure = (
                            self.unihedron.SkyQuality
                        )  # Provenance of 20.01 is dubious 20200504 WER
                    except:
                        uni_measure = 0
                else:
                    uni_measure = 0
                if uni_measure == 0:
                    uni_measure = round(
                        (mag - 20.01), 2
                    )  # Fixes Unihedron when sky is too bright
                    status["meas_sky_mpsas"] = uni_measure
                    self.meas_sky_lux = illum
                else:
                    self.meas_sky_lux = linearize_unihedron(uni_measure)
                    status["meas_sky_mpsas"] = uni_measure

                # self.temperature = round((bw1[5] + sa_nw[5])/2., 2)
                self.humidity
                try:  # NB NB Boltwood vs. SkyAlert difference.
                    self.pressure = self.sky_monitor.Pressure
                    assert self.pressure > 200

                except:
                    self.pressure = self.config["reference_pressure"]


                try:
                    self.new_pressure = round(float(self.pressure), 2)  # was [0]), 2)
                except:
                    self.new_pressure = round(float(self.pressure), 2)

                '''
                #Now let us check for lightning:  Read a file from ARO-0m30
                '''
               
                status = {
                    "temperature_C": self.temperature,
                    "pressure_mbar": self.new_pressure,
                    "humidity_%": self.humidity,
                    "dewpoint_C": self.dewpoint,
                    "sky_temp_C": self.sky_temp,
                    "last_sky_update_s": timestamp,
                    "wind_m/s": self.windspeed,
                    "rain_rate": self.rain_rate,
                    "solar_flux_w/m^2": None,
                    "calc_HSI_lux": illum,
                    "calc_sky_mpsas": round(uni_measure, 2),
                    "lightning_strike_radius km": 'n/a',
                    "general_obscuration %": 'n/a',
                    "photometric extinction k'": 'n/a',
                }

                # Store status in self.status
                self.status=status

                return status
            except:
                plog(traceback.format_exc())

                plog('something went wrong with the boltwood stuff')
                plog('above is an unglamourous traceback but continuing onwards')
                
                return self.status

        elif self.driver is not None:  # These operations are common to a generic single computer or wema site.
            ## Here we get the status from local devices, including MRC

            status = {}
            illum, mag = self.astro_events.illuminationNow()
            # illum = float(redis_monitor["illum lux"])
            if illum > 500:
                illum = int(illum)
            else:
                illum = round(illum, 3)
            if self.unihedron_connected:
                try:
                    uni_measure = (
                        self.unihedron.SkyQuality
                    )  # Provenance of 20.01 is dubious 20200504 WER
                except:
                    uni_measure = 0
            else:
                uni_measure = 0
            if uni_measure == 0:
                uni_measure = round(
                    (mag - 20.01), 2
                )  # Fixes Unihedron when sky is too bright
                status["meas_sky_mpsas"] = uni_measure
                self.meas_sky_lux = illum
            else:
                self.meas_sky_lux = linearize_unihedron(uni_measure)
                status["meas_sky_mpsas"] = uni_measure

            self.temperature = round(self.sky_monitor.Temperature, 2)
            try:  # NB NB Boltwood vs. SkyAlert difference.  What about SRO?
                self.pressure = self.sky_monitor.Pressure
                assert self.pressure > 200

            except:
                self.pressure = self.config["reference_pressure"]

            # NB NB NB This is a very odd problem which showed up at MRC.


            try:
                # was [0]), 2) -- self.pressure is a float, so indexing it
                # threw TypeError on every call and fell through to the
                # except below. Matches the fix already applied above.
                self.new_pressure = round(float(self.pressure), 2)

            except:
                self.new_pressure = round(float(self.pressure), 2)
            try:
                status = {
                    "temperature_C": round(self.temperature, 2),
                    "pressure_mbar": self.new_pressure,
                    "humidity_%": self.sky_monitor.Humidity,
                    "dewpoint_C": self.sky_monitor.DewPoint,
                    "sky_temp_C": round(self.sky_monitor.SkyTemperature, 2),
                    "last_sky_update_s": round(
                        self.sky_monitor.TimeSinceLastUpdate("SkyTemperature"), 2
                    ),
                    "wind_m/s": abs(round(self.sky_monitor.WindSpeed, 2)),
                    "rain_rate": self.sky_monitor.RainRate,
                    "solar_flux_w/m^2": None,
                    "calc_HSI_lux": illum,
                    "calc_sky_mpsas": round(
                        uni_measure, 2
                    ), 
                    "lightning_strike_radius km": 'n/a',
                    "general_obscuration %": 'n/a',
                    "photometric extinction k'": 'n/a',
                }
            except:
                status = {
                    "temperature_C": round(self.temperature, 2),
                    "pressure_mbar": self.new_pressure,
                    "humidity_%": self.sky_monitor.Humidity,
                    "dewpoint_C": self.sky_monitor.DewPoint,
                    "sky_temp_C": round(self.sky_monitor.SkyTemperature, 2),
                    "last_sky_update_s": round(
                        self.sky_monitor.TimeSinceLastUpdate("SkyTemperature"), 2
                    ),
                    "wind_m/s": abs(round(self.sky_monitor.WindSpeed, 2)),
                    "rain_rate": self.sky_monitor.RainRate,
                    "solar_flux_w/m^2": None,
                    "calc_HSI_lux": illum,
                    "calc_sky_mpsas": round(
                        uni_measure, 2
                    ), 
                    "lightning_strike_radius km": 'n/a',
                    "general_obscuration %": 'n/a',
                    "photometric extinction k'": 'n/a',
                }

            

            # Only write when around dark, put in CSV format, used to calibrate Unihedron.
            #
            sunZ88Op, sunZ88Cl, sunrise, ephemNow = g_dev[
                "wema"
            ].astro_events.getSunEvents()
            two_hours = (
                    2 / 24
            )  # Note changed to 2 hours. NB NB NB The times need changing to bracket skyflats.
            if (sunZ88Op - two_hours < ephemNow < sunZ88Cl + two_hours) and (
                    time.time() >= self.sample_time + 60
            ):  # Once a minute.

                try:
                    wl = open(self.config['wema_path'] + self.config['wema_name'] + "/unihedron/wx_log.txt", "a")
                    wl.write(
                        str(time.time())
                        + ", "
                        + str(illum)
                        + ", "
                        + str(mag - 20.01)
                        + ", "
                        + str(uni_measure)
                        + ", \n"
                    )
                    wl.close()
                    self.sample_time = time.time()
                except:
                    self.sample_time = time.time() - 61

            status["hold_duration"] = 0.0

            self.status = status
            g_dev["ocn"].status = status

            return status


def get_quick_status(self, quick):

    if self.obsid_is_specific:
        self.status = self.get_status(g_dev)  # Get current state.
    else:
        self.status = self.get_status()
    illum, mag = g_dev["evnt"].illuminationNow()
    # NB NB NB it is safer to make this a dict rather than a positionally dependant list.
    quick.append(time.time())
    quick.append(float(self.status["sky_temp_C"]))
    quick.append(float(self.status["temperature_C"]))
    quick.append(float(self.status["humidity_%"]))
    quick.append(float(self.status["dewpoint_C"]))
    quick.append(float(abs(self.status["wind_m/s"])))
    quick.append(float(self.status["pressure_mbar"]))  # 20200329 a SWAG!
    quick.append(float(illum))  # Add Solar, Lunar elev and phase
    if self.unihedron_connected:
        uni_measure = 0  # wx['meas_sky_mpsas']   #NB NB note we are about to average logarithms.
    else:
        uni_measure = 0
    if uni_measure == 0:
        uni_measure = round(
            (mag - 20.01), 2
        )  # Fixes Unihedron when sky is too bright
        quick.append(float(uni_measure))
        self.meas_sky_lux = illum
    else:
        self.meas_sky_lux = linearize_unihedron(uni_measure)
        quick.append(float(self.meas_sky_lux))  # intended for Unihedron
    return quick

def get_average_status(self, pre, post):
    average = []
    average.append(round((pre[0] + post[0]) / 2, 3))
    average.append(round((pre[1] + post[1]) / 2, 1))
    average.append(round((pre[2] + post[2]) / 2, 1))
    average.append(round((pre[3] + post[3]) / 2, 1))
    average.append(round((pre[4] + post[4]) / 2, 1))
    average.append(round((pre[5] + post[5]) / 2, 1))
    average.append(round((pre[6] + post[6]) / 2, 2))
    average.append(round((pre[7] + post[7]) / 2, 3))
    average.append(round((pre[8] + post[8]) / 2, 1))
    return average




if __name__ == "__main__":
    pass