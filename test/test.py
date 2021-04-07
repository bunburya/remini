#!/usr/bin/env python3

import logging
import ignition

logging.getLogger().setLevel(logging.DEBUG)

def test_response():
    """Request the given URL and test that the server returns the given \
            status code.

    """

    with open('test_urls.txt') as f:
        test_data = f.readlines()

    for line in test_data:
        line = line.strip()
        if (not line) or line.startswith('#'):
            continue
        url, code = line.split()
        logging.info(f'Testing that URL {url} gives response code {code}.')
        response = ignition.request(url)
        
        if len(code) == 1:
            assert response.basic_status == code
        else:
            assert response.status == code

