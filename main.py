import getopt
import json
import logging
import os
import sys

import filetype
import requests
from tinydb import TinyDB, Query

file_html = '<p><ac:structured-macro ac:name=\"view-file\" ac:schema-version=\"1\" ' \
            'ac:macro-id=\"b7348849-e03a-4bb9-a345-955883bb48cd-ss\"><ac:parameter ac:name=\"name\">' \
            '<ri:attachment ri:filename=\"%s\" /></ac:parameter><ac:parameter ' \
            'ac:name=\"height\">250</ac:parameter></ac:structured-macro></p>'
image_html = '<p><ac:image ac:height=\"250\"><ri:attachment ri:filename=\"%s\" /></ac:image></p>'
link_html = '<ac:link><ri:attachment ri:filename=\"%s\" /></ac:link>'


class CustomFormatter(logging.Formatter):
    def __init__(self):
        super(CustomFormatter, self).__init__()

    def format(self, record: logging.LogRecord) -> str:
        match record.levelno:
            case logging.INFO:
                self._style._fmt = "%(msg)s"
            case logging.ERROR:
                self._style._fmt = "ERROR - %(asctime)s - %(msg)s"

        return super().format(record)


def request_request(method, url, **additional_params):
    try:
        response = requests.request(method, url, **additional_params)
        response.raise_for_status()

        return response.json()
    except requests.exceptions.HTTPError as err_h:
        smart_logger.error(err_h)
    except requests.exceptions.ConnectionError as err_c:
        smart_logger.error(err_c)
    except requests.exceptions.Timeout as err_t:
        smart_logger.error(err_t)
    except requests.exceptions.RequestException as err:
        smart_logger.error(err)


def init_db(start=0):
    global constants, auth_details, db

    if constants['host'][-1] != '/':
        constants['host'] += '/'

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
    global db, attachment_html

    try:
        arguments, _ = getopt.getopt(sys.argv[1:], 'h', ['help', 'init-db', 'use-link'])

        for current_argument, _ in arguments:
            match current_argument:
                case ('-h' | '--help'):
                    print('optional arguments:')
                    print('  --init-db\tto initialize the database.')
                    print('  --use-link\tto post attachments as hyperlinks.')

                    sys.exit()

                case '--init-db':
                    db.truncate()
                    init_db()

                case '--use-link':
                    attachment_html = link_html

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

    query_response = db.search(page_query.title == str(title))

    if not query_response:
        db.insert({'title': title, 'occurrences': 1})
    else:
        valid_title = False
        original_title = title
        occurrences = query_response[0]['occurrences'] + 1

        while not valid_title:
            db.update({'occurrences': occurrences}, page_query.title == str(original_title))

            title = f"{original_title} - #{occurrences}"
            query_response = db.search(page_query.title == str(title))

            if not query_response:
                valid_title = True
            else:
                occurrences += 1

    return title


def get_latest_ancestor(ancestors_name):
    global db, page_query

    query_response = db.search(page_query.title == str(ancestors_name))

    occurrences = query_response[0]['occurrences']

    if occurrences != 1:
        ancestors_name = f"{ancestors_name} - #{occurrences}"

    return ancestors_name


def publish_page(title, ancestors_name=None, root_conf=False):
    global constants, auth_details

    title = get_latest_title(title)

    if ancestors_name and not root_conf:
        ancestors_name = get_latest_ancestor(ancestors_name)

    url = constants['host'] + 'rest/api/content'

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    payload = {
        "type": "page",
        "title": title,
        "space": {
            "key": constants['space_key']
        }
    }

    logger_prefix = f'Publishing page: "{title}"'

    if ancestors_name:
        payload['ancestors'] = [{'id': get_page_id(ancestors_name)}]

        smart_logger.info(f'{logger_prefix} under ancestor: "{ancestors_name}"')

    else:
        smart_logger.info(f"{logger_prefix} as top-level page")

    response = request_request(
        "POST",
        url,
        json=payload,
        headers=headers,
        auth=auth_details
    )

    return response['id']


def publish_attachment(page_id, file_path):
    global constants, auth_details

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
                "value": (image_html if filetype.is_image(file_path) else attachment_html) % file_name,
                "representation": "storage"
            }
        }
    }

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


if __name__ == '__main__':
    with open('constants.json') as const_file:
        constants = json.load(const_file)

    smart_logger = logging.getLogger()
    attachment_html = file_html
    auth_details = (constants['username'], constants['password'])
    db = TinyDB(constants["db"])
    page_query = Query()

    parse_args()
    init_logger()

    for root, sub_dirs, files in os.walk(constants['path']):
        root_name = os.path.basename(root)

        if root == constants['path']:
            if not constants['root_page_on_confluence']:
                publish_page(root_name)
            else:
                publish_page(root_name, constants['root_page_on_confluence'], True)

            for sub_dir in sub_dirs:
                publish_page(sub_dir, root_name)

        else:
            for sub_dir in sub_dirs:
                publish_page(sub_dir, root_name)

        for file in files:
            file_id = publish_page(file, root_name)
            publish_attachment(file_id, os.path.join(root, file))
