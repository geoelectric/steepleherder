#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Submits steeplechase WebRTC test results to treeherder"""

from ConfigParser import ConfigParser
import glob
import hashlib
import json
import os
from sys import argv
import socket
import uuid

from thclient import TreeherderJobCollection
from thclient import TreeherderRequest
from thclient import TreeherderResultSetCollection

import steepleparse


def create_revision_hash():
    sha = hashlib.sha1()
    sha.update(str(uuid.uuid4()))

    return sha.hexdigest()


def get_config():
    my_dir = os.path.dirname(os.path.realpath(argv[0]))
    my_ini = os.path.join(my_dir, 'steepleherder.ini')

    cp = ConfigParser()
    cp.read(my_ini)

    config = {}
    config['credentials'] = dict(cp.items('Credentials'))
    config['repo'] = dict(cp.items('Repo'))
    config['system'] = dict(cp.items('System'))
    return config


def get_app_information(config):
    app_ini = os.path.join(config['system']['autdir'],
                           'firefox', 'application.ini')

    cp = ConfigParser()
    cp.read(app_ini)
    return cp.get('App', 'SourceStamp'), cp.get('App', 'SourceRepository')


def get_files(config):
    aut_glob = os.path.join(config['system']['autdir'], 'firefox*bz2')
    test_glob = os.path.join(config['system']['testsdir'], 'firefox*zip')
    return glob.glob(aut_glob) + glob.glob(test_glob)


def get_build_version(filename):
    file_parts = filename.split('.')
    return '.'.join(file_parts[0:-2])


def get_result_summary(results):
    def add_line(title, value):
        summary['job_details'].append({
            'title': title,
            'value': str(value),
            'content_type': 'text'})

    summary = {'job_details': []}
    add_line('Total Failed', results['total failed'])
    add_line('Total Passed', results['total passed'])
    add_line('Session Runtime', results['session runtime'])

    for client in results['clients']:
        name = client['name']
        add_line(name + ' Total Blocks', client['blocks'])
        add_line(name + ' Failed Blocks', len(client['failed blocks']))
        add_line(name + ' Pass Streak', client['longest pass'])
        add_line(name + ' Session Time', client['session runtime'])
        add_line(name + ' Session Failures', len(client['session failures']))
        add_line(name + ' Setup Failures', len(client['setup failures']))
        add_line(name + ' Cleanup Failures', len(client['cleanup failures']))

    return summary


def get_result_string(results):
    if (results['total failed'] is None or
        results['total passed'] is None or
        results['session runtime'] is None or
        len(results['clients']) <= 1):
            return 'busted'
       
    passed = True
    for client in results['clients']:
        passed = (passed and client['session runtime'] > 10000
                         and len(client['setup failures']) == 0
                         and len(client['cleanup failures']) == 0
                         and len(client['session failures']) == 0
                         and len(client['failed blocks']) < 20)
        if not passed:
            break

    if passed:
        return 'success'
    else:
        return 'testfailed'


def main():
    submit_time, start_time, end_time = argv[1:4]

    config = get_config()

    app_revision, app_repository = get_app_information(config)
    files = get_files(config)
    build_version = get_build_version(os.path.basename(files[0]))
    push_time = int(os.stat(files[0]).st_ctime)
    results = steepleparse.parse(config['system']['logfile'])
    result_set_hash = create_revision_hash()

    trsc = TreeherderResultSetCollection()
    trs = trsc.get_resultset()

    trs.add_revision_hash(result_set_hash)
    trs.add_author('Firefox Nightly')
    trs.add_push_timestamp(push_time)

    tr = trs.get_revision()

    tr.add_revision(app_revision)
    tr.add_author('Firefox Nightly')
    tr.add_comment(build_version)
    tr.add_files([os.path.basename(f) for f in files])
    tr.add_repository(app_repository)

    trs.add_revision(tr)
    trsc.add(trs)

    tjc = TreeherderJobCollection()
    tj = tjc.get_job()

    tj.add_revision_hash(result_set_hash)
    tj.add_project(config['repo']['project'])
    tj.add_job_guid(str(uuid.uuid4()))

    tj.add_group_name('WebRTC QA Tests')
    tj.add_group_symbol('WebRTC')
    tj.add_job_name('Endurance')
    tj.add_job_symbol('end')

    tj.add_build_info('linux', 'linux64', 'x86_64')
    tj.add_machine_info('linux', 'linux64', 'x86_64')
    tj.add_description('WebRTC Sunny Day')
    tj.add_option_collection({'opt': True})  # must not be {}!
    tj.add_reason('testing')
    tj.add_who('Mozilla Platform QA')


    tj.add_submit_timestamp(submit_time)
    tj.add_start_timestamp(start_time)
    tj.add_end_timestamp(end_time)

    tj.add_state('completed')
    tj.add_machine(socket.gethostname())

    result_string = get_result_string(results)
    tj.add_result(result_string)
    if result_string != 'busted': 
        summary = get_result_summary(results)
        tj.add_artifact('Job Info', 'json', summary)
    
    tj.add_artifact('Results', 'json', results)

    tjc.add(tj)

    print 'trsc = ' + json.dumps(json.loads(trsc.to_json()), sort_keys=True,
                                 indent=4, separators=(',', ': '))

    print 'tjc = ' + json.dumps(json.loads(tjc.to_json()), sort_keys=True,
                                indent=4, separators=(',', ': '))

    req = TreeherderRequest(
        protocol='http',
        host=config['repo']['host'],
        project=config['repo']['project'],
        oauth_key=config['credentials']['key'],
        oauth_secret=config['credentials']['secret']
    )

    req.post(trsc)
    req.post(tjc)


if __name__ == '__main__':
    main()
