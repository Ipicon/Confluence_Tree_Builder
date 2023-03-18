import getopt
import json
import logging
import math
import os
import re
import sys
import time
from collections import deque

import filetype
import requests
import urllib3
from tinydb import TinyDB, Query

file_html = '<p><ac:structured-macro ac:name=\"view-file\" ac:schema-version=\"1\" ' \
            'ac:macro-id=\"b7348849-e03a-4bb9-a345-955883bb48cd\"><ac:parameter ac:name=\"name\">' \
            '<ri:attachment ri:filename=\"%s\" /></ac:parameter><ac:parameter ' \
            'ac:name=\"height\">250</ac:parameter></ac:structured-macro></p>'
image_html = '<p><ac:image ac:height=\"250\"><ri:attachment ri:filename=\"%s\" /></ac:image></p>'
link_html = '<ac:link><ri:attachment ri:filename=\"%s\" /></ac:link>'
max_retries = 60 * 5  # 5 Hours
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CustomFormatter(logging.Formatter):
    def __init__(self):
        super(CustomFormatter, self).__init__()

    def format(self, record: logging.LogRecord) -> str:
        match record.levelno:
            case logging.INFO:
                self._style._fmt = "INFO - %(asctime)s - %(msg)s"
            case logging.ERROR:
                self._style._fmt = f"ERROR - %(asctime)s - %(msg)s - on line: {sys.exc_info()[-1].tb_lineno}"
            case logging.WARNING:
                self._style._fmt = "WARNING - %(asctime)s - %(msg)s"

        return super().format(record)


def request_request(method, url, **additional_params):
    response = None
    retries = 0

    while retries < max_retries:
        try:
            response = requests.request(method, url, verify=False, **additional_params)
            response.raise_for_status()

            return response.json()
        except requests.exceptions.HTTPError as err_h:
            if "A page with this title already exists:" in response.text:
                raise requests.exceptions.HTTPError
            else:
                smart_logger.error(err_h)
        except requests.exceptions.ConnectionError as err_c:
            smart_logger.error(err_c)
        except requests.exceptions.Timeout as err_t:
            smart_logger.error(err_t)
        except requests.exceptions.RequestException as err:
            smart_logger.error(err)
        except Exception as e:
            smart_logger.error(e)

        retries += 1

        smart_logger.info(f"Retrying request in 1 minute, attempt {retries} out of {max_retries}.")
        time.sleep(60)

    try:
        raise requests.exceptions.RequestException
    except requests.exceptions.RequestException:
        smart_logger.error(
            "Max retries reached, in the next run the system will try to run from this point on. exiting...")
        sys.exit()


def init_db(start=0):
    global constants, auth_details, db

    url = constants['host'] + 'rest/api/content'

    query = {
        "type": "page",
        "space": constants['space_key'],
        "start": start,
        "limit": constants['limit']
    }

    response = request_request(
        "GET",
        url,
        params=query,
        auth=auth_details,
    )

    for result in response['results']:
        db.insert({'title': result['title'], 'occurrences': 1})

    if response['size'] == constants['limit']:
        init_db(start + response['size'])


def init_logger():
    global smart_logger, constants

    smart_logger.setLevel(logging.INFO)
    smart_formatter = CustomFormatter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(smart_formatter)

    file_handler = logging.FileHandler(constants['log_path'])
    file_handler.setFormatter(smart_formatter)

    smart_logger.addHandler(console_handler)
    smart_logger.addHandler(file_handler)


def parse_args():
    global db, passed_table, attachment_html, attachment_label, full_labels

    try:
        arguments, _ = getopt.getopt(sys.argv[1:], 'h',
                                     ['help', 'init-db', 'use-link', 'full-labels', 'attachment-label', 'clear-cache'])

        for current_argument, _ in arguments:
            match current_argument:
                case ('-h' | '--help'):
                    print('optional arguments:')
                    print('  --use-link\t\tto post attachments as hyperlinks.')
                    print('  --clear-cache\t\tto clear cached data and preform a clean run.')
                    print('  --full-labels\t\tto add labels with the added numeric at the end.')
                    print('  --attachment-label\tto add labels to attachments.')

                    sys.exit()

                case '--init-db':
                    print("This flag is deprecated...")
                    db.truncate()
                    init_db()

                case '--clear-cache':
                    print("Clearing Cache...")
                    db.truncate()
                    passed_table.truncate()

                case '--use-link':
                    attachment_html = link_html

                case '--full-labels':
                    full_labels = True

                case '--attachment-label':
                    attachment_label = True

    except getopt.error as err:
        smart_logger.error(str(err))
        sys.exit()


def get_page_id(page_name):
    global constants, auth_details

    url = constants['host'] + 'rest/api/content'

    query = {
        "type": "page",
        "space": constants['space_key'],
        "title": page_name
    }

    response = request_request(
        "GET",
        url,
        params=query,
        auth=auth_details,
    )

    return response['results'][0]['id']


def get_page_data(page_id):
    global constants, auth_details

    url = constants['host'] + f'rest/api/content/{page_id}'

    return request_request(
        "GET",
        url,
        auth=auth_details,
    )


def get_latest_title(title):
    global db, page_query

    query_response = db.search(page_query.title.matches(f'^{re.escape(title)}$', flags=re.IGNORECASE))

    if not query_response:
        db.insert({'title': title, 'occurrences': 1})
    else:
        valid_title = False
        original_title = title
        occurrences = query_response[0]['occurrences'] + 1

        while not valid_title:
            db.update({'occurrences': occurrences},
                      page_query.title.matches(f'^{re.escape(title)}$', flags=re.IGNORECASE))

            title = f"{original_title} - #{occurrences}"
            query_response = db.search(page_query.title.matches(f'^{re.escape(title)}$', flags=re.IGNORECASE))

            if not query_response:
                valid_title = True
                db.insert({'title': title, 'occurrences': occurrences})
            else:
                occurrences += 1

    return title


# DEPRECATED
def get_latest_ancestor(ancestors_name):
    global db, page_query

    query_response = db.search(page_query.title.matches(f'^{re.escape(ancestors_name)}$', flags=re.IGNORECASE))

    occurrences = query_response[0]['occurrences']

    if occurrences != 1:
        ancestors_name = f"{ancestors_name} - #{occurrences}"

    return ancestors_name


def publish_page(title, ancestors_name=None):
    global constants, auth_details, smart_logger

    updated_title = get_latest_title(title)

    url = constants['host'] + 'rest/api/content'

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "type": "page",
        "title": updated_title,
        "space": {
            "key": constants['space_key']
        }
    }

    logger_prefix = f'Publishing page: "{updated_title}"'

    if ancestors_name:
        payload['ancestors'] = [{'id': get_page_id(ancestors_name)}]

        smart_logger.info(f'{logger_prefix} under ancestor: "{ancestors_name}"')

    else:
        smart_logger.info(f"{logger_prefix} as top-level page")

    try:
        response = request_request(
            "POST",
            url,
            json=payload,
            headers=headers,
            auth=auth_details
        )
    except requests.exceptions.HTTPError as _:
        smart_logger.warning(f"This title: '${updated_title}' already exist, retrying with a new one...")
        response = {}
        response['id'], updated_title = publish_page(title, ancestors_name)

    return response['id'], updated_title


def add_page_label(page_id, label, reformat=True, original_label=""):
    global constants, auth_details, smart_logger, full_labels

    url = constants['host'] + f'rest/api/content/{page_id}/label'

    invalid_cars = ['(', '!', '#', '&', '(', ')', '*', '.', ':', ';', '<', '>', '?', '@', '[', ']', '^', ',', '-']

    if not full_labels and reformat:
        label = original_label

    if reformat:
        label = label.strip()
        label = label.translate({ord(char): ' ' for char in invalid_cars})
        label = '_'.join(label.split())

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = [{"name": label}]

    smart_logger.info(f"Adding label: {label}")

    request_request(
        "POST",
        url,
        json=payload,
        headers=headers,
        auth=auth_details
    )


def add_parent_labels(page_id, parent_name):
    global constants, auth_details

    parent_id = get_page_id(parent_name)
    url = constants['host'] + f'rest/api/content/{parent_id}/label'

    ancestor_labels = request_request(
        "GET",
        url,
        auth=auth_details
    )['results']

    for label in ancestor_labels:
        add_page_label(page_id, label['name'], False)


def publish_attachment(page_id, file_path):
    global constants, auth_details, smart_logger

    file_name = os.path.basename(file_path)
    page_data = get_page_data(page_id)
    url = constants['host'] + f'rest/api/content/{page_id}/child/attachment'
    body_url = constants['host'] + f'rest/api/content/{page_id}'

    headers = {
        "X-Atlassian-Token": "nocheck",
    }
    body_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "minorEdit": "true"
    }
    body_payload = {
        "version": {
            "number": page_data['version']['number'] + 1
        },
        "title": page_data['title'],
        "type": "page",
        "body": {
            "storage": {
                "value": (image_html if filetype.is_image(file_path) else attachment_html) % file_name.replace('&',
                                                                                                               '&amp;'),
                "representation": "storage"
            }
        }
    }

    smart_logger.info(f"Attaching: {file_name}")

    request_request(
        "POST",
        url,
        json=payload,
        files={'file': (file_name, open(file_path, 'rb'), 'multipart/form-data')},
        headers=headers,
        auth=auth_details
    )
    request_request(
        "PUT",
        body_url,
        json=body_payload,
        headers=body_headers,
        auth=auth_details
    )


def file_mb_size(path_to_file):
    bytes_size = os.path.getsize(path_to_file)
    return round(bytes_size / (math.pow(1024, 2)), 2)


def cache_page(page_path: str, page_title: str):
    global passed_table, passed_query, smart_logger

    smart_logger.info(f"Caching page: {page_title}.")
    passed_table.insert({'path': page_path, 'title': page_title})


def cached_page(page_path: str):
    global passed_table, passed_query, smart_logger

    query_response = passed_table.search(passed_query.path.matches(f'^{re.escape(page_path)}$', flags=re.IGNORECASE))

    if query_response:
        smart_logger.info(f"{page_path} is cached and is already published, skipping.")
        return query_response[0]['title']
    else:
        return None


if __name__ == '__main__':
    with open('constants.json', encoding="utf8") as const_file:
        constants = json.load(const_file)

    if constants['host'][-1] != '/':
        constants['host'] += '/'

    smart_logger = logging.getLogger()
    attachment_html = file_html
    attachment_label = False
    full_labels = False
    auth_details = (constants['username'], constants['password'])
    db = TinyDB(constants["db"])
    passed_table = db.table('passed')
    page_query = Query()
    passed_query = Query()
    parent_labels = deque([])

    parse_args()
    init_logger()

    for root, sub_dirs, files in os.walk(constants['path']):
        root_absolute_path = os.path.abspath(root)

        try:
            if root == constants['path']:
                root_name = os.path.basename(root)
                page_cache = cached_page(root_absolute_path)

                if page_cache is None:
                    if not constants['root_page_on_confluence']:
                        file_id, latest_title = publish_page(root_name)
                        add_page_label(file_id, latest_title, original_label=root_name)
                    else:
                        file_id, latest_title = publish_page(root_name, constants['root_page_on_confluence'])
                        add_page_label(file_id, latest_title, original_label=root_name)

                    cache_page(root_absolute_path, latest_title)

                else:
                    latest_title = page_cache

                root_name = latest_title

            else:
                root_name = parent_labels.popleft()

            new_subs = []

            for sub_dir in sub_dirs:
                sub_dir_path = os.path.join(root_absolute_path, sub_dir)
                page_cache = cached_page(sub_dir_path)

                if page_cache is None:
                    file_id, latest_title = publish_page(sub_dir, root_name)

                    add_parent_labels(file_id, root_name)
                    add_page_label(file_id, latest_title, original_label=sub_dir)
                    cache_page(sub_dir_path, latest_title)
                else:
                    latest_title = page_cache

                new_subs.append(latest_title)

            parent_labels.extendleft(new_subs[::-1])

            for file in files:
                file_path = os.path.join(root_absolute_path, file)

                if cached_page(file_path) is not None:
                    continue

                try:
                    if file == 'Thumbs.db' or file.startswith('~$'):
                        continue

                    size_of_file = file_mb_size(os.path.join(root, file))

                    if constants['max_attachment_size'] < size_of_file:
                        smart_logger.warning(f"{file} is not published: file weights: {size_of_file} MB, "
                                             f"when max file size is {constants['max_attachment_size']} MB")
                        continue

                    file_id, latest_file = publish_page(file, root_name)
                    publish_attachment(file_id, os.path.join(root, file))
                    add_parent_labels(file_id, root_name)

                    if attachment_label:
                        add_page_label(file_id, latest_file, original_label=file)

                    cache_page(file_path, latest_file)
                except Exception as e:
                    smart_logger.error(e)

        except Exception as err:
            smart_logger.error(err)
