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

USERNAME = config['USVISA']['USERNAME']
PASSWORD = config['USVISA']['PASSWORD']
SCHEDULE_ID = config['USVISA']['SCHEDULE_ID']
MY_SCHEDULE_DATE = config['USVISA']['MY_SCHEDULE_DATE']
MIN_SCHEDULE_DAYS = int(config['USVISA']['MIN_SCHEDULE_DAYS'])
COUNTRY_CODE = config['USVISA']['COUNTRY_CODE']
FACILITY_ID = config['USVISA']['FACILITY_ID']
GROUP_ID = config['USVISA']['GROUP_ID']

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
    result = new_date > min_date
    print(f'and is {new_date} > {min_date}:\t{result}')
    return result

STEP_TIME = 0.5  # time between steps (interactions with forms): 0.5 seconds
RETRY_TIME = 60*20  # wait time between retries: 20 minutes
EXCEPTION_TIME = 60*45  # wait time when an exception occurs: 45 minutes
COOLDOWN_TIME = 60*90  # wait time when temporary banned (empty list): 90 minutes

DATE_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
TIME_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date=%s&appointments[expedite]=false"
APPOINTMENT_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment"
GROUP_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/groups/{GROUP_ID}"
EXIT = False

old_appointent_date = ""
retry_count = 0

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
    if LOCAL_USE:
        dr = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    else:
        dr = webdriver.Remote(command_executor=HUB_ADDRESS, options=webdriver.ChromeOptions())
    return dr

driver = get_driver()


def login():
    # Bypass reCAPTCHA
    driver.get(f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv")
    time.sleep(STEP_TIME)
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    print("Login start...")
    href = driver.find_element(By.XPATH, '//*[@id="header"]/nav/div[2]/div[1]/ul/li[3]/a')
    href.click()
    time.sleep(STEP_TIME)
    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))

    print("\tclick bounce")
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    do_login_action()


def do_login_action():
    print("\tinput email")
    user = driver.find_element(By.ID, 'user_email')
    user.send_keys(USERNAME)
    time.sleep(random.randint(1, 3))

    print("\tinput pwd")
    pw = driver.find_element(By.ID, 'user_password')
    pw.send_keys(PASSWORD)
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

def get_dates_from_service():
    driver.get(DATE_URL)
    if not is_logged_in():
        login()
        return get_dates_from_service()
    else:
        content = driver.find_element(By.TAG_NAME, 'pre').text
        date = json.loads(content)
        return date


def get_time(date):
    time_url = TIME_URL % date
    driver.get(time_url)
    content = driver.find_element(By.TAG_NAME, 'pre').text
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

def step2_reschedule(date):
    global EXIT
    print(f"Starting Reschedule ({date})")

    time = get_time(date)

    driver.get(APPOINTMENT_URL)
    new_url = APPOINTMENT_URL

    applicants_list = driver.find_elements(By.XPATH, '//input[@id="applicants_"]')
    applicant_ids = []
    if len(applicants_list) > 0 :
        print("There are more than 1 applicant, selecting all")
        for applicant in applicants_list :
            app_id = applicant.get_attribute('value')
            applicant_ids.append(app_id)

        params = {
            'utf8': '✓',
            'applicants[]': applicant_ids,
            'confirmed_limit_message':1,
            'commit': 'Continuar'
        }
        url_parts = list(urllib.parse.urlparse(APPOINTMENT_URL))
        url_parts[4] = url_encode_params(params)
        new_url = urllib.parse.urlunparse(url_parts)
        btn = driver.find_element(By.NAME, 'commit')
        btn.click()
        driver.get(new_url)

    utf8 = driver.find_element(by=By.NAME, value='utf8').get_attribute('value')
    authenticity_token = driver.find_element(by=By.NAME, value='authenticity_token').get_attribute('value')
    data = {
        "utf8": utf8,
        "authenticity_token": authenticity_token,
        "confirmed_limit_message": driver.find_element(by=By.NAME, value='confirmed_limit_message').get_attribute('value'),
        "use_consulate_appointment_capacity": driver.find_element(by=By.NAME, value='use_consulate_appointment_capacity').get_attribute('value'),
        "appointments[consulate_appointment][facility_id]": FACILITY_ID,
        "appointments[consulate_appointment][date]": date,
        "appointments[consulate_appointment][time]": time
    }

    if len(applicant_ids) > 0:
        data['applicants[]'] = applicant_ids

    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": new_url,
        "Cookie": "_yatri_session=" + driver.get_cookie("_yatri_session")["value"]
    }

    r = requests.post(APPOINTMENT_URL, headers=headers, data=data)

    set_current_appoiment_date(True)
    my_date = datetime.strptime(MY_SCHEDULE_DATE, "%Y-%m-%d")
    old_date = datetime.strptime(old_appointent_date, "%Y-%m-%d")

    if my_date < old_date:
        msg = f"Rescheduled Successfully! {date} {time}"
        print(msg)
        send_notification(msg)
        EXIT = True
    else:
        msg = f"Reschedule Failed. {date} {time}"
        print(msg)
        send_notification(msg)


def is_logged_in():
    content = driver.page_source
    if(content.find("error") != -1):
        return False
    return True


def print_dates(dates):
    print("Available dates:")
    for d in dates:
        print("%s \t business_day: %s" % (d.get('date'), d.get('business_day')))
    print()


last_seen = None


def get_available_date(dates):
    global last_seen

    def is_earlier(date):
        my_date = datetime.strptime(MY_SCHEDULE_DATE, "%Y-%m-%d")
        new_date = datetime.strptime(date, "%Y-%m-%d")
        result = my_date > new_date
        print(f'Is {my_date} > {new_date}:\t{result}')
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

    print()
    print("------------------")
    print(datetime.today().strftime("%d %b %Y, %I:%M %p"))
    print(f"Retry count: {retry_count+1}")

    set_current_appoiment_date(True)
    old_appointent_date = MY_SCHEDULE_DATE

    dates = get_dates_from_service()[:5]
    if not dates:
        return None
    else:
        return dates

if __name__ == "__main__":
    login()
    set_current_appoiment_date(False)
    old_appointent_date = MY_SCHEDULE_DATE

    while 1:
        if retry_count > 100:
            break
        try:
            dates = step1_get_dates_if_possible()
            if dates:
                print_dates(dates)

                date = get_available_date(dates)
                print()
                if date:
                    print(f"New date: {date}")
                    step2_reschedule(date)
                else:
                    print("Available dates are later than the booked one")
                    time.sleep(RETRY_TIME)
                    retry_count += 1

            else:
                wait_time = RETRY_TIME
                if retry_count > 14:
                    wait_time = COOLDOWN_TIME

                msg = f"no available date, waiting {int(wait_time/60)} mins before try again"
                print(msg)
                #send_notification(msg)
                time.sleep(wait_time)
                retry_count += 1

            if(EXIT):
                print("------------------exit")
                break
        except:
            retry_count += 1
            time.sleep(EXCEPTION_TIME)

    if(not EXIT):
        send_notification("HELP! Crashed.")
