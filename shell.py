#!/usr/bin/env python

import argparse
import atexit
import cmd
import logging
import os
import readline
import redis
import select
import shlex
import sys
import threading

from celery import Celery
from celery.task.control import revoke


__version__ = '0.1.0'


def pubsub_monitoring(channels, redis_config):
    logger = logging.getLogger('botnet.pubsub')
    redis_instance = redis.Redis(**redis_config)
    pubsub = redis_instance.pubsub()
    for channel in channels.values():
        pubsub.subscribe(channel)

    while True:
        for message in pubsub.listen():
            if message['type'] == 'subscribe':
                logger.debug('Susbcribed to {}'.format(message['channel']))
            elif message['type'] == 'message':
                if message['channel'] == channels['stdout']:
                    logger.info(message['data'])
                elif message['channel'] == channels['pid']:
                    logger.debug('Process spawned on remote host with pid={}'
                                 .format(message['data']))
                elif message['channel'] == channels['finish']:
                    logger.info('Task finished')
                    return True
                else:
                    raise NotImplementedError('Unknown message channel: {}'
                                              .format(message))
            else:
                raise NotImplementedError('Unknown message type: {}'
                                          .format(message))


def start_pubsub_monitoring(args, task):
    channels = get_channels(task)
    redis_config = {
        'host': args.broker,
    }
    thread = threading.Thread(target=pubsub_monitoring,
                              args=[channels, redis_config])
    thread.setDaemon(True)
    thread.start()
    return thread


def get_channels(task):
    return {
        'stdout': 'task:{}:stdout'.format(task.task_id),
        'stderr': 'task:{}:stderr'.format(task.task_id),
        'finish': 'task:{}:finish'.format(task.task_id),
        'pid': 'task:{}:pid'.format(task.task_id),
    }


def setup_logging(args):
    logger = logging.getLogger('botnet')
    logger.propagate = False
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '[%(levelname)s] %(asctime)s %(name)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    logging_levels = {
        None: logging.INFO,
        0: logging.WARN,
        1: logging.INFO,
        2: logging.DEBUG,
    }
    logging_level = logging_levels.get(args.verbose, logging.DEBUG)
    logger.setLevel(logging_level)
    return logger


def parser_add_args(parser, include_call_command=True):
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verbose', '-v', action='count')
    parser.add_argument('--version', action='version',
                        version='%(prog)s {}'.format(__version__))

    default_broker = os.environ.get('OCS_BOTNET_BROKER', '127.0.0.1')
    parser.add_argument('-b', '--broker', help="Broker hostname/ip",
                        default=default_broker)
    parser.add_argument('--amqp-url', help="AMQP connection url")
    parser.add_argument('-t', '--time-limit', help="Task time limit",
                        default=60)
    parser.add_argument('--async', help="Ignore return value",
                        action='store_true')

    if include_call_command:
        parser.add_argument('command', nargs='?', metavar='COMMAND',
                            help='Command to execute')
    parser.add_argument('command_args', nargs=argparse.REMAINDER,
                        metavar='COMMAND_ARGS')
    return parser


def parse_command_line():
    description = "FIXME: add description"
    parser = argparse \
        .ArgumentParser(description=description,
                        formatter_class=argparse.RawTextHelpFormatter)
    parser = parser_add_args(parser, include_call_command=True)
    args = parser.parse_args()
    args.amqp_url = 'amqp://guest:guest@{}:5672/'.format(args.broker)
    return args


def is_one_command(shell, args):
    command = args.command
    if command:
        if hasattr(shell, 'do_{}'.format(command)):
            return True
        else:
            raise UnknownCommandException(
                'Unknown command "{}"'.format(command)
            )
    return False


def parse_loop_line(line):
    parser = argparse \
        .ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser = parser_add_args(parser, include_call_command=False)
    args = parser.parse_args(shlex.split(line))
    return args


class Shell(cmd.Cmd):

    prompt = '(NolpBotnet)> '

    def __init__(self, args):
        cmd.Cmd.__init__(self)
        self.args = args
        self.logger = logging.getLogger('botnet.shell')

    def merge_line_args(self, _line):
        line_args = parse_loop_line(_line)
        for key, value in self.args._get_kwargs():
            if key in line_args.__dict__ and not line_args.__dict__[key]:
                line_args.__dict__[key] = value
        return line_args

    def do_call(self, line_):
        args = self.merge_line_args(line_)

        command = ' '.join(args.command_args)
        app = Celery(broker=args.amqp_url, backend=args.amqp_url)

        self.logger.info('Executing: {}'.format(command))
        task_args = [
            'ocs.run_command',
        ]
        task_kwargs = {
            'args': [command],
            'time_limit': args.time_limit,
        }
        if args.async:
            task_kwargs.update({
                'countdown': 0,
            })
        else:
            task_kwargs.update({
                # 'immediate': True,
                'connect_timeout': 3,
                'countdown': 1,
            })
        task = app.send_task(*task_args, **task_kwargs)
        self.logger.debug('Task id: {}'.format(task.task_id))

        if args.async:
            return

        start_pubsub_monitoring(args, task)
        try:
            ret = task.get()
        except KeyboardInterrupt:
            self.logger.warn('^C: revoking task...')
            revoke(task.task_id, terminate=True)
            sys.exit(1)
        if ret['retcode'] is 0:
            self.logger.debug('Task succeeded (retcode=0)')
        else:
            self.logger.error('Task terminated with non-null value ({})'
                              .format(ret['retcode']))


def setup_history():
    readline.set_history_length(300)
    histfile = os.path.join(os.path.expanduser('~'), '.ocs-botnet')
    try:
        readline.read_history_file(histfile)
    except IOError:
        pass

    atexit.register(readline.write_history_file, histfile)


def main(argv=None):
    """ Command line entry-point. """

    if argv:
        sys.argv = argv
    args = parse_command_line()
    setup_logging(args)
    setup_history()

    shell = Shell(args)

    if is_one_command(shell, args):
        command = args.command.replace('-', '_')
        try:
            shell.onecmd('{} {}'.format(command, ' '.join(args.command_args)))
        except KeyboardInterrupt:
            print('')
    else:
        shell.cmdloop()


if __name__ == '__main__':
    main()
