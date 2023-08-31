# -*- coding: utf8 -*-

import time
import json
import random
import platform
import configparser
import urllib
import locale
from datetime import datetime, date, timedelta

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


config = configparser.ConfigParser()
config.read('config.ini')

USERNAME_CONSULT = config['USVISA']['USERNAME_CONSULT']
PASSWORD_CONSULT = config['USVISA']['PASSWORD_CONSULT']
SCHEDULE_ID_CONSULT = config['USVISA']['SCHEDULE_ID_CONSULT']
driver = None
driver_consult = None

USERNAME = config['USVISA']['USERNAME']
PASSWORD = config['USVISA']['PASSWORD']
SCHEDULE_ID = config['USVISA']['SCHEDULE_ID']
MY_SCHEDULE_DATE = config['USVISA']['MY_SCHEDULE_DATE']
MAX_SCHEDULE_DATE = config['USVISA']['MAX_SCHEDULE_DATE']
MIN_SCHEDULE_DAYS = int(config['USVISA']['MIN_SCHEDULE_DAYS'])
COUNTRY_CODE = config['USVISA']['COUNTRY_CODE']
FACILITY_ID = config['USVISA']['FACILITY_ID']
FACILITY_ID_CAS = config['USVISA']['FACILITY_ID_CAS']
GROUP_ID = config['USVISA']['GROUP_ID']
MULTIPLE_APPLICANTS = config['USVISA'].getboolean('MULTIPLE_APPLICANTS')

SENDGRID_API_KEY = config['SENDGRID']['SENDGRID_API_KEY']
PUSH_TOKEN = config['PUSHOVER']['PUSH_TOKEN']
PUSH_USER = config['PUSHOVER']['PUSH_USER']

LOCAL_USE = config['CHROMEDRIVER'].getboolean('LOCAL_USE')
HUB_ADDRESS = config['CHROMEDRIVER']['HUB_ADDRESS']

REGEX_CONTINUE = "//a[contains(text(),'Continuar')]"

# check if the available date is later than the current date plus MIN_SCHEDULE_DAYS days (in case you can not assist for an appoinmt in the next day)
def MY_CONDITION(new_date):
    new_date = datetime.strptime(new_date, "%Y-%m-%d")
    min_date = datetime.today() + timedelta(days=MIN_SCHEDULE_DAYS)
    max_date = datetime.strptime(MAX_SCHEDULE_DATE, "%Y-%m-%d")
    result = new_date > min_date and new_date < max_date

    new_date_str = new_date.strftime("%Y-%m-%d")
    min_date_str = min_date.strftime("%Y-%m-%d")
    max_date_str = max_date.strftime("%Y-%m-%d")
    print(f'and is {min_date_str} < {new_date_str} < {max_date_str} :\t{result}')
    print()

    return result

STEP_TIME = 0.5  # time between steps (interactions with forms): 0.5 seconds
RETRY_TIME = 20*60  # wait time between retries: 20 minutes
EXCEPTION_TIME = 45*60  # wait time when an exception occurs: 45 minutes
RUN_FOR_TIME = 150*60  # continue running time before cold down: 150 mins
COOLDOWN_TIME = 90*60  # wait time when temporary banned (empty list): 90 mins

DATE_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/%s/appointment/days/%s.json?appointments[expedite]=false"
TIME_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/%s/appointment/times/%s.json?date=%s&appointments[expedite]=false"
APPOINTMENT_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment"
GROUP_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/groups/{GROUP_ID}"
EXIT = False

old_appointent_date = ""
retry_count = 0
start_running_date = datetime.today()

applicants_appointment_url = None
applicants_ids = []

def send_notification(msg):

    #get username for notification
    username = USERNAME.split("@")[0]
    msg = f"{username}: {msg}"

    if SENDGRID_API_KEY:
        print(f"Sending notification: {msg}")
        message = Mail(
            from_email=USERNAME,
            to_emails=USERNAME,
            subject=msg,
            html_content=msg)
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            response = sg.send(message)
            print(response.status_code)
            print(response.body)
            print(response.headers)
        except Exception as e:
            print(e.message)

    if PUSH_TOKEN:
        print(f"Sending notification: {msg}")
        url = "https://api.pushover.net/1/messages.json"
        data = {
            "token": PUSH_TOKEN,
            "user": PUSH_USER,
            "message": msg
        }
        requests.post(url, data)


def get_driver():
    return webdriver.Chrome()

def login_where_is_needed():
    if (USERNAME_CONSULT == USERNAME):
        login(driver, USERNAME, PASSWORD)
    else:
        login(driver_consult, USERNAME_CONSULT, PASSWORD_CONSULT)
        login(driver, USERNAME, PASSWORD)

def login(driver=driver, username=USERNAME, password=PASSWORD):
    # Bypass reCAPTCHA
    driver.get(f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv")
    time.sleep(STEP_TIME)
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    print("Login start...")
    href = driver.find_element(By.XPATH, '//*[@id="header"]/nav/div[1]/div[1]/div[2]/div[1]/ul/li[3]/a')
    href.click()
    time.sleep(STEP_TIME)
    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))

    print("\tclick bounce")
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    do_login_action(driver, username, password)


def do_login_action(driver, username, password):
    print("\tinput email")
    user = driver.find_element(By.ID, 'user_email')
    user.send_keys(username)
    time.sleep(random.randint(1, 3))

    print("\tinput pwd")
    pw = driver.find_element(By.ID, 'user_password')
    pw.send_keys(password)
    time.sleep(random.randint(1, 3))

    print("\tclick privacy")
    box = driver.find_element(By.CLASS_NAME, 'icheckbox')
    box .click()
    time.sleep(random.randint(1, 3))

    print("\tcommit")
    btn = driver.find_element(By.NAME, 'commit')
    btn.click()
    time.sleep(random.randint(1, 3))

    Wait(driver, 60).until(
        EC.presence_of_element_located((By.XPATH, REGEX_CONTINUE)))
    print("\tlogin successful!")

def set_current_appoiment_date(load_url):
    global MY_SCHEDULE_DATE
    if load_url:
        driver.get(GROUP_URL)
        Wait(driver, 60).until(EC.presence_of_element_located((By.CLASS_NAME, 'card')))

    try:
        app = driver.find_element(By.CLASS_NAME, 'consular-appt')
    except:
        app = driver.find_element(By.CLASS_NAME, 'asc-appt')

    date_list = app.text.split(": ")[1].split(", ")[0 : 2]
    date_str = " ".join(date_list)

    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
    date_time_obj = datetime.strptime(date_str, '%d %B %Y')
    MY_SCHEDULE_DATE = date_time_obj.strftime('%Y-%m-%d')
    print(f"Current appoinment date: {MY_SCHEDULE_DATE}")

def get_dates_from_service(facility_id, consulate_date=None, consulate_time=None):
    date_url = DATE_URL % (SCHEDULE_ID_CONSULT, facility_id)
    #add params if its cas appt
    if consulate_date is not None:
        date_url = date_url + f"&consulate_id={FACILITY_ID}&consulate_date={consulate_date}&consulate_time={consulate_time}"

    session = driver_consult.get_cookie("_yatri_session")["value"]
    NEW_GET = driver.execute_script("var req = new XMLHttpRequest();req.open('GET', '" + str(date_url) + "', false);req.setRequestHeader('Accept', 'application/json, text/javascript, */*; q=0.01');req.setRequestHeader('X-Requested-With', 'XMLHttpRequest'); req.setRequestHeader('Cookie', '_yatri_session=" + session + "'); req.send(null);return req.responseText;")

    if not is_logged_in2():
        login_where_is_needed()
        return get_dates_from_service(facility_id, consulate_date, consulate_time)
    else:
        return json.loads(NEW_GET)


def get_time(facility_id, date, consulate_date=None, consulate_time=None):
    time_url = TIME_URL % (SCHEDULE_ID_CONSULT, facility_id, date)

    #add params if its cas appt
    if consulate_date is not None:
        time_url = time_url + f"&consulate_id={FACILITY_ID}&consulate_date={consulate_date}&consulate_time={consulate_time}"
    
    session = driver.get_cookie("_yatri_session")["value"]

    content = driver.execute_script("var req = new XMLHttpRequest();req.open('GET', '" + str(time_url) + "', false);req.setRequestHeader('Accept', 'application/json, text/javascript, */*; q=0.01');req.setRequestHeader('X-Requested-With', 'XMLHttpRequest'); req.setRequestHeader('Cookie', '_yatri_session=" + session + "'); req.send(null);return req.responseText;")
    data = json.loads(content)

    time = data.get("available_times")[-1]
    print(f"Got time successfully! {date} {time}")
    return time

def url_encode_params(params={}):
    if not isinstance(params, dict):
        raise Exception("You must pass in a dictionary!")
    params_list = []
    for k,v in params.items():
        if isinstance(v, list): params_list.extend([(k, x) for x in v])
        else: params_list.append((k, v))
    return urllib.parse.urlencode(params_list)

def get_applicants_list_if_needed():
    if not MULTIPLE_APPLICANTS: 
        return 

    driver.get(APPOINTMENT_URL)
    applicants_list = driver.find_elements(By.XPATH, '//input[@id="applicants_"]')
    local_applicants_ids = []
    if len(applicants_list) > 0 :
        print("There are more than 1 applicant, selecting all")
        for applicant in applicants_list :
            app_id = applicant.get_attribute('value')
            local_applicants_ids.append(app_id)

        params = {
            'utf8': '✓',
            'applicants[]': local_applicants_ids,
            'confirmed_limit_message':1,
            'commit': 'Continuar'
        }
        url_parts = list(urllib.parse.urlparse(APPOINTMENT_URL))
        url_parts[4] = url_encode_params(params)

        applicants_ids = local_applicants_ids
        applicants_appointment_url = urllib.parse.urlunparse(url_parts)

        print("all applicants has been selected")

        btn = driver.find_element(By.NAME, 'commit')
        btn.click()
        driver.get(applicants_appointment_url)


def step3_reschedule(date, time, date_cas, time_cas):
    global EXIT
    print(f"Starting Reschedule ({date} at {time}) and CAS ({date_cas} at {time_cas})")

    # this is working but i'm trying to avoid extra time
    # driver.get(APPOINTMENT_URL)
    # new_url = APPOINTMENT_URL

    # applicants_list = driver.find_elements(By.XPATH, '//input[@id="applicants_"]')
    # applicant_ids = []
    # if len(applicants_list) > 0 :
    #     print("There are more than 1 applicant, selecting all")
    #     for applicant in applicants_list :
    #         app_id = applicant.get_attribute('value')
    #         applicant_ids.append(app_id)

    #     params = {
    #         'utf8': '✓',
    #         'applicants[]': applicant_ids,
    #         'confirmed_limit_message':1,
    #         'commit': 'Continuar'
    #     }
    #     url_parts = list(urllib.parse.urlparse(APPOINTMENT_URL))
    #     url_parts[4] = url_encode_params(params)
    #     new_url = urllib.parse.urlunparse(url_parts)

    #     print("all applicants has been selected")

    #     btn = driver.find_element(By.NAME, 'commit')
    #     btn.click()
    #     driver.get(new_url)

    utf8 = driver.find_element(by=By.NAME, value='utf8').get_attribute('value')
    authenticity_token = driver.find_element(by=By.NAME, value='authenticity_token').get_attribute('value')
    data = {
        "utf8": utf8,
        "authenticity_token": authenticity_token,
        "confirmed_limit_message": driver.find_element(by=By.NAME, value='confirmed_limit_message').get_attribute('value'),
        "use_consulate_appointment_capacity": driver.find_element(by=By.NAME, value='use_consulate_appointment_capacity').get_attribute('value'),
        "appointments[consulate_appointment][facility_id]": FACILITY_ID,
        "appointments[consulate_appointment][date]": date,
        "appointments[consulate_appointment][time]": time,
        "appointments[asc_appointment][facility_id]": FACILITY_ID_CAS,
        "appointments[asc_appointment][date]": date_cas,
        "appointments[asc_appointment][time]": time_cas
    }

    # this is the new atempt
    new_url = APPOINTMENT_URL
    if applicants_appointment_url is not None:
        new_url = applicants_appointment_url

    if len(applicants_ids) > 0:
        data['applicants[]'] = applicant_ids

    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": new_url,
        "Cookie": "_yatri_session=" + driver.get_cookie("_yatri_session")["value"]
    }

    print(f"lets POST with: {data}")
    r = requests.post(APPOINTMENT_URL, headers=headers, data=data)

    # check appointment date to see if it was successfully rescheduled
    set_current_appoiment_date(True)
    my_date = datetime.strptime(MY_SCHEDULE_DATE, "%Y-%m-%d")
    old_date = datetime.strptime(old_appointent_date, "%Y-%m-%d")

    if my_date < old_date:
        msg = f"Rescheduled Successfully! {date} {time}"
        print(msg)
        print()
        send_notification(msg)
    else:
        msg = f"Reschedule Failed. {date} {time}"
        print(msg)
        print()
        send_notification(msg)


def is_logged_in():
    content = driver.page_source
    if(content.find("error") != -1):
        return False
    return True

def is_logged_in2():
    url = driver.current_url
    if(url == f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv"):
        return False
    if(url == f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/users/sign_in"):
        return False
    return True

def print_dates(dates):
    print("Available dates:")
    for d in dates:
        print("%s" % (d.get('date')))
    print()


last_seen = None


def get_available_date(dates):
    global last_seen

    def is_earlier(date):
        my_date = datetime.strptime(MY_SCHEDULE_DATE, "%Y-%m-%d")
        new_date = datetime.strptime(date, "%Y-%m-%d")
        result = my_date > new_date

        my_date_str = my_date.strftime("%Y-%m-%d")
        new_date_str = new_date.strftime("%Y-%m-%d")
        print(f'Is {new_date_str} < {my_date_str}:\t{result}')

        return result

    print("Checking for an earlier date:")
    for d in dates:
        date = d.get('date')
        if is_earlier(date) and date != last_seen:
            if(MY_CONDITION(date)):
                last_seen = date
                return date


def push_notification(dates):
    msg = "date: "
    for d in dates:
        msg = msg + d.get('date') + '; '
    send_notification(msg)

def step1_get_dates_if_possible():
    global retry_count

    if not is_logged_in2():
        login_where_is_needed()
        return step1_get_dates_if_possible()
    else:
        print()
        print("------------------")
        print(datetime.today().strftime("%d %b %Y, %I:%M:%S %p"))
        print(f"Retry count: {retry_count+1}")

        set_current_appoiment_date(True)
        old_appointent_date = MY_SCHEDULE_DATE


        dates = get_dates_from_service(FACILITY_ID)[:5]
        if not dates:
            return None
        else:
            return dates

def step2_get_dates_for_CAS_if_possible(consulate_date, consulate_time):
    dates = get_dates_from_service(FACILITY_ID_CAS, consulate_date, consulate_time)[:5]
    if not dates:
        return None
    else:
        return dates

def get_time_to_wait():
    current_date = datetime.today()
    current_date_no_secs = current_date.replace(second=0, microsecond=0)
    
    current_seconds = time.mktime(current_date_no_secs.timetuple())
    current_minutes = current_seconds/60
    
    minutes_to_wait = (5 - (int(current_minutes) % 5))
    seconds_to_wait = minutes_to_wait * 60
    
    secs_to_remove = current_date - current_date_no_secs
    secs_to_remove = secs_to_remove.seconds

    seconds_to_wait = seconds_to_wait - secs_to_remove

    seconds_to_wait = seconds_to_wait + random.randint(5, 20) # fire it at o'clock plus X seconds

    return seconds_to_wait


if __name__ == "__main__":
    driver = get_driver()

    # check if there is a consult account
    if USERNAME_CONSULT:
        driver_consult = get_driver()
    else:
        USERNAME_CONSULT = USERNAME
        PASSWORD_CONSULT = PASSWORD
        SCHEDULE_ID_CONSULT = SCHEDULE_ID
        driver_consult = driver

    login_where_is_needed()

    set_current_appoiment_date(False)
    old_appointent_date = MY_SCHEDULE_DATE

    get_applicants_list_if_needed()

    while 1:
        if retry_count > 100:
            break
        try:
            dates = step1_get_dates_if_possible()
            if dates:
                print_dates(dates)

                date_apt = get_available_date(dates)

                print()
                if date_apt:
                    print(f"New date: {date_apt}")
                    time_apt = get_time(FACILITY_ID, date_apt)

                    dates_cas = step2_get_dates_for_CAS_if_possible(date_apt, time_apt)
                    if dates_cas:
                        #lets get the last date in the list
                        date_cas = dates_cas[-1].get('date')
                        time_cas = get_time(FACILITY_ID_CAS, date_cas, date_apt, time_apt)

                        step3_reschedule(date_apt, time_apt, date_cas, time_cas)

                        time_to_wait = get_time_to_wait()
                        time.sleep(time_to_wait)
                        retry_count += 1

                    else:
                        print("NO CAS dates, lets wait")
                        time.sleep(RETRY_TIME)
                        retry_count += 1

                else:

                    # lets cool down after trying for X mins, to try to prevent to be blocked
                    now_date = datetime.today()
                    if now_date > (start_running_date + timedelta(seconds=RUN_FOR_TIME)):
                        print(f"lets cool down for {COOLDOWN_TIME/60} mins after running for {RUN_FOR_TIME/60} mins")
                        time.sleep(COOLDOWN_TIME)
                        start_running_date = datetime.today()
                        retry_count += 1
                        login_where_is_needed()

                    else:
                        time_to_wait = get_time_to_wait()
                        print("Available dates are later than the booked one")
                        print(f"waiting {int(time_to_wait/60)} mins before try again")
                        time.sleep(time_to_wait)
                        retry_count += 1

            else:
                wait_time = COOLDOWN_TIME

                msg = f"no available date, waiting {int(wait_time/60)} mins before try again"
                print(msg)
                send_notification(msg)
                time.sleep(wait_time)
                retry_count += 1
                login_where_is_needed()

            if(EXIT):
                print("------------------exit")
                break
        except:
            retry_count += 1
            time.sleep(EXCEPTION_TIME)

    if(not EXIT):
        send_notification("HELP! Crashed.")
