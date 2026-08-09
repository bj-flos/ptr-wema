# WEMA `DPO` -- host enclosure for the CDK17 observatory.
#
# Derived from configs/tbo (the all-dummy simulator site), matching how
# ptr-observatory's configs/dpo17 was derived. Differences:
#
#   * the enclosure and weather drivers are Alpaca URLs served by the ASCOM
#     Alpaca Simulators on 127.0.0.1:11111, rather than COM ProgIDs or 'dummy'
#   * driver_2 is the Alpaca SafetyMonitor, standing in for the COM
#     ok-to-open monitor
#   * identity matches configs/dpo17/wema-dpo.json in ptr-observatory
#
# Select it with PTR_WEMA_SITE=dpo, since the hostname heuristic in
# ptr_config.py cannot find it.


'''
FIRST Created on Fri Aug  2 11:57:41 2019

Refactored on 20230407

@author: wrosing, et al.
'''
import json

'''                                                                                                1         1         1       1
         1         2         3         4         5         6         7         8         9         0         1         2       2
12345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789012345678
'''

# NB NB NB json is not bi-directional with tuples (), instead, use lists [], nested if tuples are needed.
degree_symbol = "°"
wema_name = 'DPO'
instance_type = 'wema'

wema_config = {

    #'wema': 'eco',
    'wema_name': 'DPO',
    'instance_type': 'wema',
    'instance_is_private': False,

    'obsp_ids': ['DPO17'],  # a list of the obsp's in an enclosure.  

    #'obs_id': None,  # a WEMA is not a telescope aka Observatory
    #'observatory_location': site_name.lower(),  # in LCO case, an airport code such as OGG
    
    # These values are to help the weather station self-organise
    # If it is only a nighttime or a daytime observatory, we can restrict
    # fits and predictions of the weather to using data for that period of the day
    # Particularly sky temperature is impacted by daily effects.
    'opens_during_nighttime' : True,
    # True to make the WEMA evaluate weather around the clock, rather than
    # restricting its fits and predictions to night-time data.
    'opens_during_daytime': True,

    # Which emails to send?
    'send_hourly_cloud_forecast_emails' : False,

    # These are just the bootup default values.
    # On. wema.py calls pro.openweathermap.org/data/3.0/onecall, which needs
    # a One Call subscription on the key in secrets.txt. While that returns
    # 401 the report reads negative, and since wx_ok is the AND of every
    # active source, the combined verdict is false regardless of local
    # conditions.
    'OWM_active': True,
    # On, so wx_ok reflects the Alpaca ObservingConditions readings.
    # With every source off, wema.py reports wx_ok as "Not considered",
    # which photonranch-status coerces to false and ptr_ui draws as
    # "poor" -- indistinguishable from genuinely bad weather.
    'local_weather_active': True,
    #'debug_site_mode': False,

    'debug_mode': False,
    'admin_owner_commands_only': False,
    'debug_duration_sec': 3600,
    #'local_weather_always_overrides_OWM': False,
    'enclosure_status_check_period': 30,
    'weather_status_check_period': 30,
    'safety_status_check_period': 30,

    'owner':  ['google-oauth2|112401903840371673242'],  # Wayne

    'owner_alias': ['WER', 'TELOPS'],
    'admin_aliases': ["ANS", "WER", "TELOPS", "TB", "DH", "KVH", "KC"],

    'client_hostname':  'MRC-0m35',  # This is also the long-name  Client is confusing!
    # NB NB disk D at mrc may be faster for temp storage
    'client_path':  'C:/ptr/',  # Generic place for client host to stash misc stuff
    'alt_path':  'C:/ptr/',  # Generic place for this host to stash misc stuff
    'plog_path':  'C:/ptr/tbo/',  # place where night logs can be found.
    'save_to_alt_path': 'no',
    'archive_path':  'C:/ptr/',

    'archive_age': -99.9,  # Number of days to keep files in the local archive before deletion. Negative means never delete
    # For low bandwidth sites, do not send up large files until the end of the night. set to 'no' to disable
    #'send_files_at_end_of_night': 'no',

    # For low diskspace sites (or just because they aren't needed), don't save a separate raw file to disk after conversion to fz.
    #'save_raw_to_disk': True,
    # PTR uses the reduced file for some calculations (focus, SEP, etc.). To save space, this file can be removed after usage or not saved.
    #'keep_reduced_on_disk': True,
    #'keep_focus_images_on_disk': True,  # To save space, the focus file can not be saved.


    # Minimum realistic seeing at the site.
    # This allows culling of unphysical results in photometry and other things
    # Particularly useful for focus
    #'minimum_realistic_seeing': 1.0,

    'aux_archive_path':  None,  # NB NB we might want to put Q: here for MRC
    'wema_is_active':  True,          # True if the split computers used at a site.  NB CHANGE THE DAMN NAME!
    'wema_hostname': 'ECO-WMS-ENC',   # Prefer the shorter version
    'wema_path':  'C:/ptr/',  # '/wema_transfer/',

    #'site_is_custom': False,  # Indicates some special code for this site, found at end of config. Set True if SRO


    'dome_on_wema':   True,
    #'site_IPC_mechanism':  'redis',   # ['None', shares', 'shelves', 'redis']  Pick One
    'site_IPC_mechanism':  'aws',   # ['None', 'aws', shares', 'shelves', 'redis']  Pick One
    'wema_write_share_path': 'C:/ptr/',  # Meant to be where Wema puts status data.
    'client_read_share_path':  'C:/ptr/',  # NB these are all very confusing names.
    'client_write_share_path': 'C:/ptr/',
    #'redis_ip': '10.15.0.109',  # '127.0.0.1', None if no redis path present,
    'redis_ip': None,  # '127.0.0.1', None if no redis path present,
    #'obsid_is_generic':  False,   # A simply  single computer ASCOM site.
    'site_is_specific':  False,  # Indicates some special code for this site, found at end of config.


    'host_wema_site_name':  'TBO',  # The umbrella header for obsys in close geographic proximity,
                                    #  under the control of one wema
    'name': 'Photon Ranch Dimension Point',
    'airport_code':  'BWT: Wynyard',
    'location': 'Mayhill, New Mexico, USA',
    'telescope_description': 'n.a.',
    'observatory_url': '',   #  This is meant to be optional
    'observatory_logo': None,   # I expect these will ususally end up as .png format icons
    'description':  '''Burnie.
                    ''',    #  i.e, a multi-line text block supplied and eventually mark-up formatted by the owner.
    'location_day_allsky':  None,  # Thus ultimately should be a URL, probably a color camera.
    'location_night_allsky':  None,  # Thus ultimately should be a URL, usually Mono camera with filters.
    'location _pole_monitor': None,  # This probably gets us to some sort of image (Polaris in the North)
    'location_seeing_report': None,  # Probably a path to a jpeg or png graph.
    'debug_flag': False,  # Be careful about setting this flag True when pushing up to dev!
    'TZ_database_name':  'America/Denver',
    'mpc_code':  'ZZ23',    #  This is made up for now.
    'time_offset':  -7,   #  These two keys may be obsolete given the new TZ stuff
    'timezone': 'MST',      #  This was meant to be coloquial Time zone abbreviation, alternate for "TX_data..."
    # 'latitude': -41.063610,     #  Decimal degrees, North is Positive
    # 'longitude': 145.875275,   #  Decimal degrees, West is negative
    'latitude': 32.913,     #  Decimal degrees, North is Positive
    'longitude': -105.52528,   #  Decimal degrees, West is negative
    'elevation': 2194.56,    #  meters above sea level
    'reference_ambient':  10,  #  Degrees Celsius.  Alternately 12 entries, one for every - mid month.
    'reference_pressure':  776.0,    #mbar   A rough guess 20200315
    
    'wema_has_control_of_roof': True,
    'wema_allowed_to_open_roof': True,

    #'site_roof_control': True,  # MTF entered this in to remove sro specific code  NB 'site_is_specifc' also deals with this
    #'site_allowed_to_open_roof': True,
    'period_of_time_to_wait_for_roof_to_open': 5,  # seconds - needed to check if the roof ACTUALLY opens.
    #'only_scope_that_controls_the_roof': False,  # If multiple scopes control the roof, set this to False
    'check_time': 300,  # MF's original setting.
    'maximum_roof_opens_per_evening': 4,
    # How many minutes to use as the default retry time to open roof. This will be progressively multiplied as a back-off function.
    'roof_open_safety_base_time': 15,
    
    # For some sites like schools, we need roof to be shut during work hours so balls don't fall into observatories.
    # 24 hour time in decimal local time according to TZ_database_name
    'absolute_earliest_opening_hour': 16.5, # School definitely closed by then.
    'absolute_latest_shutting_hour' : 8.0, # Kids start arriving after this.


    'site_enclosures_default_mode': "Automatic",  # "Manual", "Shutdown"
    'automatic_detail_default': "Enclosure is set to Automatic mode.",

    # =============================================================================
    # At somepoint here some of this might better be associated with the Telescope not the site -- or
    # consider them to be site-wide rules.
    # =============================================================================

    #'closest_distance_to_the_sun': 45,  # Degrees. For normal pointing requests don't go this close to the sun.

    #'closest_distance_to_the_moon': 10,  # Degrees. For normal pointing requests don't go this close to the moon.

    #'lowest_requestable_altitude': -5,  # Degrees. For normal pointing requests don't allow requests to go this low.

    'observing_check_period': 5,    # How many minutes between weather checks
    'enclosure_check_period': 5,    # How many minutes between enclosure checks

    #'auto_eve_bias_dark': True,

    ##'auto_midnight_moonless_bias_dark': False,
    #'auto_eve_sky_flat': False,

    #'eve_sky_flat_sunset_offset': -60.,  # 40 before Minutes  neg means before, + after.

    'eve_cool_down_open': -65.0, # How many minutes after sunrise to open. Default -65 = an hour-ish before sunset. Gives time to cool and get narrowband flats
    'morn_close_and_park': 32.0, # How many minutes after sunrise to close. Default 32 minutes = enough time for narrowband flats




    #'auto_morn_sky_flat': False,
    #'auto_morn_bias_dark': False,
    #'re-calibrate_on_solve': True,
    #'pointing_calibration_on_startup': False,  # MF I am leaving this alone.
    # This is a time, in hours, over which to bypass automated focussing (e.g. at the start of a project it will not refocus if a new project starts X hours after the last focus)
    #'periodic_focus_time': 0.5,
    #'stdev_fwhm': 0.5,  # This is the expected variation in FWHM at a given telescope/camera/site combination. This is used to check if a fwhm is within normal range or the focus has shifted
    #'focus_exposure_time': 10,  # Exposure time in seconds for exposure image
    #'focus_trigger': 0.75,  # What FWHM increase is needed to trigger an autofocus
    #'solve_nth_image': 1,  # Only solve every nth image
    #'solve_timer': 0.05,  # Only solve every X minutes
    #'threshold_mount_update': 100,  # only update mount when X arcseconds away

    # WEMA can not have local_weather_info sometimes.. e.g. ECO
    'has_local_weather_info' : False,

    # # Whether these limits are on by default
    # 'rain_limit_on': False,
    # 'humidity_limit_on': True,
    # 'windspeed_limit_on': True,
    # 'lightning_limit_on': True,
    # 'temperature_minus_dewpoint_limit_on': True,
    # 'sky_temperature_limit_on': True,
    # 'cloud_cover_limit_on': False,
    # 'lowest_ambient_temperature_on': True,
    # 'highest_ambient_temperature_on': True,

    # # Local weather DANGER limits - will cause the roof to shut
    # 'rain_limit': 0,
    # 'humidity_limit': 80,
    # 'windspeed_limit': 25,
    # 'lightning_limit': 15,
    # 'temperature_minus_dewpoint_limit': 2,
    # 'sky_temperature_limit': -12,
    # 'cloud_cover_limit': 50,
    # 'lowest_ambient_temperature': 1,
    # 'highest_ambient_temperature': 40,

    # # Local weather warning limits, will send a warning, but leave the roof alone
    # 'warning_rain_limit': 0,
    # 'warning_humidity_limit': 75,
    # 'warning_windspeed_limit': 15,
    # 'warning_lightning_limit': 10,
    # 'warning_temperature_minus_dewpoint_limit': 2,
    # 'warning_sky_temperature_limit': -17,
    # 'warning_cloud_cover_limit': 25,
    # 'warning_lowest_ambient_temperature': 5,
    # 'warning_highest_ambient_temperature': 35,
    
    #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Whether these limits are on by default
    'rain_limit_on': True,
    'humidity_limit_on': True,
    'windspeed_limit_on': False,
    'lightning_limit_on': False,
    'temperature_minus_dewpoint_limit_on': False,
    'sky_minus_ambient_limit_on': True,    
    'sky_temperature_limit_on': True,
    'local_cloud_cover_limit_on': True,
    'forecast_cloud_cover_limit_on': True,
    'lowest_ambient_temperature_on': False,
    'highest_ambient_temperature_on': False,
    
    #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Local weather DANGER limits - will cause the roof to shut
    'rain_limit': 0,
    'humidity_limit': 98,
    'windspeed_limit': 25,
    'lightning_limit': 15,
    'temperature_minus_dewpoint_limit': 2,
    'sky_minus_ambient_limit': -12,
    'sky_temperature_limit': -1,
    'local_cloud_cover_limit': 70,
    'forecast_cloud_cover_limit' : 90,
    'lowest_ambient_temperature': -5,
    'highest_ambient_temperature': 60,
    
    #############################################################
    #### BE AWARE THAT THESE VALUES ARE JUST FOR INITILIASATION!#
    ## THEY WILL BE STORED IN A SHELF AND CHANGES SHOULD BE MADE#
    ## THROUGH THE UI IN THE LONG TERM!                         #
    #############################################################

    # Local weather warning limits, will send a warning, but leave the roof alone
    'warning_rain_limit': 0,
    'warning_humidity_limit': 75,
    'warning_windspeed_limit': 15,
    'warning_lightning_limit': 10,
    'warning_temperature_minus_dewpoint_limit': 2,
    'warning_sky_minus_ambient_limit': -17,
    'warning_sky_temperature_limit': -6,
    'warning_local_cloud_cover_limit': 25,
    'warning_forecast_cloud_cover_limit': 25,
    'warning_lowest_ambient_temperature': 5,
    'warning_highest_ambient_temperature': 35,


    'defaults': {
        'observing_conditions': 'observing_conditions1',
        'enclosure': 'enclosure1',
        #'mount': 'mount1',
        #'telescope': 'telescope1',
        #'focuser': 'focuser1',
        #'rotator': 'rotator1',
        #'selector':  None,
        #'screen': 'screen1',
        #'filter_wheel': 'filter_wheel1',
        #'camera': 'camera_1_1',
        'sequencer': 'sequencer1'
    },
    'device_types': [
        'observing_conditions',
        'enclosure',
        #'mount',
        #'telescope',
        # 'screen',
        #'rotator',
        #'focuser',
        #'selector',
        #'filter_wheel',
        #'camera',

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
        # 'observing_conditions',
        # 'enclosure',
        #'mount',
        #'telescope',
        # 'screen',
        #'rotator',
        #'focuser',
        #'selector',
        #'filter_wheel',
        #'camera',

        'sequencer',
    ],
    
    'observing_conditions' : {
        'observing_conditions1': {
            'parent': 'site',
            'ocn_is_custom':  False, 
            # Intention it is found in this file.
            'name': 'Alpaca Observing Conditions Simulator',
            'driver': 'alpaca://127.0.0.1:11111/observingconditions/0',
            'share_path_name': 'F:/ptr/',
            'driver_2':  'alpaca://127.0.0.1:11111/safetymonitor/0',
            'driver_3':  None,    # 'ASCOM.Boltwood.OkToImage.SafetyMonitor'
            'ocn_has_unihedron':  False,
            'have_local_unihedron': False,     #  Need to add these to setups.
            'uni_driver': 'ASCOM.SQM.serial.ObservingConditions',
            'unihedron_port':  10    #  False, None or numeric of COM port.
        },
    },
    
    'enclosure': {
        'enclosure1': {
            'parent': 'site',
            'encl_is_custom':  False,   #SRO needs sorting, presuambly with this flag.
            'directly_connected': True, # For ECO and EC2, they connect directly to the enclosure, whereas WEMA are different.
            'name': 'Alpaca Dome Simulator',
            'hostIP':  None,
            'driver': 'alpaca://127.0.0.1:11111/dome/0',
            'has_lights':  False,
            'controlled_by': 'mount1',
			'encl_is_dome': True,   # the Alpaca simulator reports azimuth
            'encl_is_rolloff': False,
            'rolloff_has_endwall': False,
            'mode': 'Automatic',
            #'cool_down': -90.0,    #  Minutes prior to sunset.
            'settings': {
                'lights':  ['Auto', 'White', 'Red', 'IR', 'Off'],       #A way to encode possible states or options???
                                                                        #First Entry is always default condition.
                'roof_shutter':  ['Auto', 'Open', 'Close', 'Lock Closed', 'Unlock'],
            },
            #'eve_bias_dark_dur':  2.0,   #  hours Duration, prior to next.
            #'eve_screen_flat_dur': 1.0,   #  hours Duration, prior to next.
            #'operations_begin':  -1.0,   #  - hours from Sunset
            #'eve_cooldown_offset': -.99,   #  - hours beforeSunset
            #'eve_sky_flat_offset':  0.5,   #  - hours beforeSunset
            #'morn_sky_flat_offset':  0.4,   #  + hours after Sunrise
            #'morning_close_offset':  0.41,   #  + hours after Sunrise
            #'operations_end':  0.42,
        },
    },
}

def get_enc_status_custom():
    pass
def get_ocn_status_custom():
    pass


if __name__ == '__main__':
    '''
    This is a simple test to send and receive via json.
    '''

    j_dump = json.dumps(site_config)
    site_unjasoned = json.loads(j_dump)
    if str(site_config) == str(site_unjasoned):
        print('Strings matched.')
    if site_config == site_unjasoned:
        print('Dictionaries matched.')
