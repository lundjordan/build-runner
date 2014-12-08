# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import time
import shlex
import json
import subprocess

from lib.config import Config, TaskConfig
from lib.graph import TaskGraph
from lib.utils import list_directory

import logging
log = logging.getLogger(__name__)


def run_task(t, env, max_time):
    start = time.time()
    proc = subprocess.Popen(t, stdin=open(os.devnull, 'r'), env=env)
    while True:
        if proc.poll() is not None:
            break

        if max_time == 0:
            # if we've set to run forever, we can sleep for a lot longer
            # than 1 second.
            time.sleep(20)
        elif time.time() - start > max_time:
            # Try killing it
            log.warn("exceeded max_time; killing")
            proc.terminate()
            return "RETRY"
        else:
            time.sleep(1)

    rv = proc.wait()
    if rv == 0:
        return "OK"
    elif rv == 2:
        return "HALT"
    else:
        return "RETRY"


def process_taskdir(config, dirname):
    tasks = list_directory(dirname)
    # Filter out the halting task
    if config.halt_task in tasks:
        tasks.remove(config.halt_task)

    # Get a list of a TaskConfig objects mapping task to their dependencies
    taskconfigs = []
    for t in tasks:
        deps = config.get(t, 'depends_on')
        if deps is not None:
            taskconfigs.append(TaskConfig(t, map(str.strip, deps.split(','))))
        else:
            taskconfigs.append(TaskConfig(t, []))

    tg = TaskGraph(taskconfigs)  # construct the dependency graph
    task_list = tg.sequential_ordering()  # get a topologically sorted order

    log.debug("tasks: %s", task_list)

    env = os.environ.copy()
    new_env = config.get_env()
    log.debug("Updating env with %s", new_env)
    env.update(new_env)

    default_config = {
        "max_time": int(config.max_time),
        "max_tries": int(config.max_tries),
        "sleep_time": int(config.sleep_time),
        "interpreter": config.interpreter,
    }

    for try_num in range(1, config.max_tries + 1):
        for t in task_list:
            # Get the portion of a task's config that can override default_config
            task_config = config.get_task_config(t)
            task_config = {k: v for k, v in task_config.items() if k in default_config}

            # do the override
            for k, v in default_config.items():
                if k not in task_config:
                    task_config[k] = v

            # For consistent log info
            task_stats = dict(task=t, try_num=try_num, max_retries=config.max_tries)
            if config.pre_task_hook:
                pre_task_hook_cmd = shlex.split("{} '{}'".format(config.pre_task_hook, json.dumps(task_stats)))
                log.debug("running pre-task hook: %s", " ".join(pre_task_hook_cmd))
                run_task(pre_task_hook_cmd, env, max_time=task_config['max_time'])

            log.debug("%s: starting (max time %is)", t, config.max_time)
            task_cmd = os.path.join(dirname, t)
            if task_config['interpreter']:
                log.debug("%s: running with interpreter (%s)", t, task_config['interpreter'])
                # using shlex affords the ability to pass arguments to the
                # interpreter as well (i.e. bash -c)
                task_cmd = shlex.split("{} '{}'".format(task_config['interpreter'], task_cmd))
            r = run_task(task_cmd, env, max_time=task_config['max_time'])
            log.debug("%s: %s", t, r)

            if config.post_task_hook:
                task_stats['result'] = r
                post_task_hook_cmd = shlex.split("{} '{}'".format(config.post_task_hook, json.dumps(task_stats)))
                log.debug("running post-task hook: %s", " ".join(post_task_hook_cmd))
                run_task(post_task_hook_cmd, env, max_time=config.max_time)

            halt_cmd = os.path.join(dirname, config.halt_task)
            if config.interpreter:
                # if a global task interpreter was set, it should apply
                # here as well
                halt_cmd = shlex.split("{} '{}'".format(config.interpreter, halt_cmd))

            if r == "OK":
                continue
            elif r == "RETRY":
                # No point in sleeping if we're on our last try
                if try_num == task_config['max_tries']:
                    log.warn("maximum attempts reached")
                    log.info("halting")
                    run_task(halt_cmd, env, max_time=task_config['max_time'])
                    return False
                # Sleep and try again
                log.debug("sleeping for %i", task_config['sleep_time'])
                time.sleep(task_config['sleep_time'])
                break
            elif r == "HALT":
                # stop/halt/reboot?
                log.info("halting")
                run_task(halt_cmd, env, max_time=task_config['max_time'])
                return False
        else:
            log.debug("all tasks completed!")
            return True


def make_argument_parser():
    import argparse
    parser = argparse.ArgumentParser(__doc__)
    parser.set_defaults(
        loglevel=logging.INFO,
    )
    parser.add_argument("-q", "--quiet", dest="loglevel", action="store_const", const=logging.WARN, help="quiet")
    parser.add_argument("-v", "--verbose", dest="loglevel", action="store_const", const=logging.DEBUG, help="verbose")
    parser.add_argument("-c", "--config", dest="config_file")
    parser.add_argument("-g", "--get", dest="get", help="get configuration value")
    parser.add_argument("-n", "--times", dest="times", type=int, help="run this many times (default is forever)")
    parser.add_argument("taskdir", help="task directory", nargs="?")

    return parser


def runner(config, taskdir, times):
    """Runs tasks in the taskdir up to `times` number of times

    times can be None to run forever
    """
    t = 0
    while True:
        t += 1
        if times and t > times:
            break
        log.info("iteration %i", t)
        if not process_taskdir(config, taskdir):
            exit(1)


def main():
    parser = make_argument_parser()
    args = parser.parse_args()
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=args.loglevel)

    config = Config()
    if args.config_file:
        config.load_config(args.config_file)

    if args.get:
        log.debug("getting %s", args.get)
        section, option = args.get.split(".", 1)
        v = config.get(section, option)
        if v is not None:
            print v
        exit(0)
    elif not args.taskdir:
        parser.error("taskdir required")

    if not os.path.exists(args.taskdir):
        log.error("%s doesn't exist", args.taskdir)
        exit(1)

    runner(config, args.taskdir, args.times)
