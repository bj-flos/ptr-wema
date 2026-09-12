# -*- coding: utf-8 -*-
'''

Created on Fri Feb 07,  11:57:41 2020
Updated 20220914 WER   This version does not support color camera channel.
Updates 20231102 WER   This is meant to clean up and refactor wema/obsp architecture.

@author: wrosing

aro-0m30      10.0.0.73
aro-wema      10.0.0.50
Power Control 10.0.0.100   admin arot******
Roof Control  10.0.0.200   admin arot******
Redis         10.0.0.174:6379
'''
#                                                                                                  1         1         1
#        1         2         3         4         5         6         7         8         9         0         1         2
#23456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890
import json
import time
from pprint import pprint


g_dev = None    #???

#MF: Comments Marked #>>  Imply I think should be moved, deleted, renamed, don-not apply to a site, etc.
#    Second, I imagine an obsy_config is created by concationating a site_config + an obsp_config. A
#    specific offset in meters) is in the latter to define exact lat, long, alt for the vertex of the primary.
#10.0.0.200/setup.html    admin arotoo1

degree_symbol = "°"
wema_name = 'aro'
instance_type = 'wema'

wema_config = {

    'wema_name': 'aro',
    'instance_type': 'wema',
    'instance_is_private': False,
    'obsp_ids': ['aro1', 'aro2'], #, 'aro2','aro3', 'aro4']  #Possible hint to site about who are its children.
    
    # These values are to help the weather station self-organise
    # If it is only a nighttime or a daytime observatory, we can restrict
    # fits and predictions of the weather to using data for that period of the day
    # Particularly sky temperature is impacted by daily effects.
    'opens_during_nighttime' : True,
    'opens_during_daytime': False,
    
    # Which emails to send?
    'send_hourly_cloud_forecast_emails' : False,
    
    'debug_mode': False,
    'debug_duration_sec': 80000,
    'admin_owner_commands_only': False,

    'owner':  ['google-oauth2|102124071738955888216',
               'google-oauth2|112401903840371673242'],  #    WER and  Neyle,
    'owner_alias': ['ANS', 'WER', 'TELOPS'],

    #'observatory_location': site_name.lower(),  # Not sure what this has to do with a *site!*.
    'site_desc': "Apache Ridge Observatory, Santa Fe, NM, USA. 2194m",  #Chg name to site_location?
    'airport_codes':  ['SAF', 'ABQ', 'LSN'],   #  Meant to bracket the site so we can probe Obsy Wx reports

    'client_hostnames': ["ARO-0m30"],     # This should be a list corresponding to obsp ID's and maybe an parallel ip# list.

    'wema_is_active':  True,     # True if an agent (ie a wema) is used at a site.   # Wemas are split sites -- at least two CPS's sharing the control.
    'wema_hostname':  'ARO-WEMA',
    'host_wema_site_name':  'ARO',   #do we need this?
    'wema_path': 'C:/ptr/',      #Local storage on Wema disk.
    'plog_path': 'C:/ptr/',
    'encl_coontrolled_by_wema':  True,       #NB NB NB CHange this confusing name. 'dome_controlled_by_wema'
    'site_IPC_mechanism':  'shares',   # ['None', shares', 'shelves', 'redis']
    'wema_write_share_path':  'W:/', #Meant to be a share with to by the Obsp TCS computer
    'dome_on_wema':  True,  #Temporary assignment   20230617 WER
    'redis_available':  True,
    'redis_ip': "10.0.0.174:6379",   # port :6379 None if no redis path present, localhost if redis iself-contained
    'site_is_single_host':  False,   # A simple single computer ASCOM site.

    'name': "Apache Ridge Observatory, Santa Fe, NM, USA. 2194m",
    'location': 'Santa Fe, New Mexico,  USA',
    'observatory_url': 'https://starz-r-us.sky/clearskies2',   # This is meant to be optional, something supplied by the owner.
    'observatory_logo': None,   # I expect a .bmp or.jpeg supplied by the owner
    'dedication':   '''
                    Now is the time for all good persons
                    to get out and vote, lest we lose
                    charge of our democracy.
                    ''',    # i.e, a multi-line text block supplied and formatted by the owner.
    'location_day_allsky':  None,  #  Thus ultimately should be a URL, probably a color camera.
    'location_night_allsky':  None,  #  Thus ultimately should be a URL, usually Mono camera with filters.
    'location_pole_monitor': None,  #This probably gets us to some sort of image (Polaris in the North)
    'location_seeing_report': None,  # Probably a path to ...

    'TZ_database_name':  'America/Denver',
    'mpc_code':  'ZZ24',    # This is made up for now.
    'time_offset':  -6.0,   # -7 Std time, - 6 Daylight Slaving
    'timezone': 'MDT',      # This was meant to be coloquial Time zone abbreviation, alternate for "TZ_data..."
    'latitude': 35.554298,     # Decimal degrees, North is Positive  Meant to be Wx Station coordinates
    'longitude': -105.870197,   # Decimal degrees, West is negative
    'elevation': 2194,    # meters above sea level.  Meant to be elevation of main temp sensor 20' off ground.
    # Clear Sky Chart key from cleardarksky.com, eg. 'SaBarbCA'. The UI builds
    # the chart URLs from this; None means no chart is shown for the site.
    'clear_sky_chart_id': 'LmyRdgObNM',
    'reference_ambient':  10.0,  # Degrees Celsius.  Alternately 12 entries, one for every - mid month.
    'reference_pressure':  775.0,    #mbar   A rough guess 20200315

    'OWM_active': True,   #  Consider splitting out rain and wind from high clouds. Former should usuall always be on.
    'local_weather_active': True,
    'local_weather_always_overrides_OWM': True,  #  This needs inspecting, probably not implemented wer 20231105
    'enclosure_status_check_period': 10,
    'weather_status_check_period': 30,
    'safety_status_check_period': 30,
    'observing_check_period' : 1,    # How many minutes between weather checks   Are these redundant or unused?
    'enclosure_check_period' : 1,    # How many minutes between enclosure checks
    'wema_has_control_of_roof': True,
    'wema_allowed_to_open_roof': True,
    "ARO_wema_patch": True,
    #next few are enclosure parameteers
    'period_of_time_to_wait_for_roof_to_open' : 125, # seconds - needed to check if the roof ACTUALLY opens. ARO takes ~35 seconds as of 20231101
    'only_scope_that_controls_the_roof': True, # If multiple scopes control the roof, set this to False
    'check_time': 300,    #   20231106   Unused WER
    'maximum_roof_opens_per_evening' : 6,

    'roof_open_safety_base_time' : 10, # How many minutes to use as the default retry time to open roof. This will be progressively multiplied as a back-off function.


    # For some sites like schools, we need roof to be shut during work hours so balls don't fall into observatories.
    # 24 hour time in decimal local time according to TZ_database_name
    'absolute_earliest_opening_hour': 15.5, # School definitely closed by then.
    'absolute_latest_shutting_hour' : 10.0, # Kids start arriving after this.



    'site_enclosures_default_mode': "Automatic",   # ["Manual", "Shutdown", "Automatic"]  Was "Simulated' as o 10/14/2023 We
    'automatic_detail_default': "Enclosures are initially set to Automatic by ARO site_config.",

    #Sequencing keys and value, sets up Events
    'auto_eve_bias_dark': True,
    'auto_eve_sky_flat': True,
    'auto_midnight_moonless_bias_dark': False,
    'auto_morn_sky_flat': True,
    'auto_morn_bias_dark': True,

    # NB NB THe following two entries are relevant for SRO

    # WEMA can not have local_weather_info sometimes.. e.g. ECO
    'has_local_weather_info' : True,

    'bias_dark interval':  110.,   # Takes 102 minutes as of 11/1/23 @ ARO
    'eve_cool_down_open': -55.0, # How many minutes before sunset to open. Default -65 = an hour-ish before sunset. Gives time to cool and get narrowband flats
                                 #  Note 15 minutes of cool down provided.
    'eve_sky_flat_sunset_offset': -40.,  # Before Sunset Minutes  neg means before, + after. Flats take about 33 min @ ARO 110123
    'end_eve_sky_flats_offset': -1 ,      # How many minutes after civilDusk to do....
    'clock_and_auto_focus_offset':-10,   #min before start of observing
    'astro_dark_buffer': 15,   #Min before and after AD to extend observing window
    'morn_flat_start_offset': -10,       #min from Sunrise
    'morn_flat_end_offset':  +40,        #min from Sunrise
    'morn_close_and_park': 45.0, # How many minutes after sunrise to close. Default 32 minutes = enough time for narrowband flats
    'end_night_processing_time':  90,   #  A guess#'eve_sky_flat_sunset_offset': -60.0,  # Minutes  neg means before, + after.


    #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Whether these limits are on by default
    'rain_limit_on': True,  #Right now Skyalert Babbles.
    'humidity_limit_on': True,
    'windspeed_limit_on': True,
    'lightning_limit_on': True,
    'temperature_minus_dewpoint_limit_on': True,
    'sky_minus_ambient_limit_on': True,
    'sky_temperature_limit_on': False,
    'local_cloud_cover_limit_on': True,
    'forecast_cloud_cover_limit_on': True,
    'lowest_ambient_temperature_on': True,
    'highest_ambient_temperature_on': True,
    'has_inside_weather_station': False,

    #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Local weather limits   #NB we should move these into OCN config section
    'rain_limit': 1.0,         # NO we shouldn't because it will be different per site
    'humidity_limit': 92,   # With multiple elements etc. I think.
    'windspeed_limit': 24,  #  8 m/s per Neyle 20231226 Units? Some of this could be OWM stuff e.g.
    'gust_decay_rate': 0.98,    #20240426 Totally experimental
    'lightning_limit' : 15, #km
    'temperature_minus_dewpoint_limit': 2,
    'sky_minus_ambient_limit': -1,  #It must be colder than this
    'sky_temperature_limit': -3,
    'local_cloud_cover_limit': 70,
    'forecast_cloud_cover_limit' : 85,
    'lowest_ambient_temperature': -20,
    'highest_ambient_temperature': 40,

    #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Local weather warning limits, will send a warning, but leave the roof alone
    'warning_rain_limit': 3,
    'warning_humidity_limit': 72,
    'warning_windspeed_limit': 6,   #m/s
    'warning_lightning_limit' : 20, #km
    'warning_temperature_minus_dewpoint_limit': 2,
    'warning_sky_minus_ambient_limit': -17,
    'warning_sky_temperature_limit': -6,
    'warning_local_cloud_cover_limit': 25,
    'warning_forecast_cloud_cover_limit': 25,
    'warning_lowest_ambient_temperature': -10,
    'warning_highest_ambient_temperature': 35,

    'get_ocn_status': None,
    'get_enc_status': None,
    'not_used_variable': None,



    'defaults': {
        'observing_conditions': 'observing_conditions1',  # These are used as keys, may go away.
        'enclosure': 'enclosure1',
        'screen': 'screen1',
        'mount': 'mount1',
        'telescope': 'telescope1',     #How do we handle selector here, if at all?
        'focuser': 'focuser1',
        'rotator': 'rotator1',
        'selector': None,
        'filter_wheel': 'filter_wheel1',
        'camera': 'camera_1_1',
        'sequencer': 'sequencer1'
        },
    'device_types': [
        'observing_conditions',
        'enclosure',
        'mount',
        'telescope',
        # 'screen',
        'rotator',
        'focuser',
        'selector',
        'filter_wheel',
        'camera',
        'sequencer',
        ],
    'wema_types': [
       'observing_conditions',
       'enclosure',
       ],
    'enc_types': [
        'enclosure'
    ],
    'short_status_devices':  [
       'mount',
       'telescope',
       # 'screen',
       'rotator',
       'focuser',
       'selector',
       'filter_wheel',
       'camera',
       'sequencer',
       ],

    #'wema_status_span':  ['aro1', 'aro2', 'aro3'],

    'observing_conditions' : {     #for SAF
        'observing_conditions1': {
            'ocn_is_custom':  False,
            'name': 'SkyAlert Custom for ARO',
            'driver': 'ASCOM.SkyAlert.ObservingConditions',  #  'ASCOM.Boltwood.ObservingConditions',

            # From reading the aagsolo manual and papers around it,
            # It seems there isn't one reliable settings for estimating
            # cloud cover or rain for that matter and these values are best
            # set based on experience at each different site and probably
            # each different aagsolo that is set up in different ambient
            # conditions. So these values should be eyeballed from
            # the aagsolo/ webpage on the actual network
            'aagsolo_rain_threshold': 3200,
            'aagsolo_clear_skyT': -4,
            'aagsolo_cloudy_skyT': 19,


            'driver_2':  None,
            'driver_3':  None,
            'redis_ip': '127.0.0.1',   #None if no redis path present
            'has_unihedron':  True,
            'have_local_unihedron': True,
            'uni_driver': 'ASCOM.SQM.serial.ObservingConditions',
            'unihedron_port':  10    # False, None or numeric of COM port.
        },
    },

    'enclosure': {
        'enclosure1': {
            'name': 'Roll Top',
            'encl_is_custom':  False,  ##if custom this config would have routines to monkey patch
            'directly_connected': False, # For ECO and EC2, they connect directly to the enclosure, whereas WEMA are different.
            'hostIP':  '10.0.0.73',
            'driver': 'X322_http',  #     Dragonfly.Dome,  #  'ASCOMDome.Dome',  #ASCOMDome.Dome',  # ASCOM.DeviceHub.Dome',  # ASCOM.DigitalDomeWorks.Dome',  #"  ASCOMDome.Dome',
            "encl_ip": '10.0.0.200',    #'10.0.0.103'Used to be the Drangonfly, no longer used.
            'has_lights':  False,
            'controlled_by': 'mount1',   #This is an obsolete concept.
            #"serving_obsp's": ['aro1', 'aro2', 'aro3'],
			'encl_is_dome': False,   #otherwise a Rool off or Clamshel
            'encl_radius':  None,  #  inches Ok for now.
            'encl_is_roll-off':  True,
            'encl_is_clamshell': False,
            'encl_axis_az': 315.,   #  May be useful for clamshell wind screening.

            #'common_offset_east': -19.5,  # East is negative.  These will vary per telescope. ARO AO1600
            #'common_offset_south': -8,  # South is negative.   So think of these as default.

            #'cool_down': 65.0,     # Minutes prior to sunset.
            'settings': {
                'lights':  ['Auto', 'White', 'Red', 'IR', 'Off'],       #A way to encode possible states or options???
                                                                        #First Entry is always default condition.
                'roof_shutter':  ['Auto', 'Open', 'Close', 'Lock Closed', 'Unlock'],
            },

        },
    },

}

def get_enc_status_custom():
    pass
def get_ocn_status_custom():
    pass

if __name__ == '__main__':
    j_dump = json.dumps(wema_config)
    wema_unjasoned = json.loads(j_dump)
    if str(wema_config)  == str(wema_unjasoned):
        print('Strings matched.')
    if wema_config == wema_unjasoned:
        print('Dictionaries matched.')