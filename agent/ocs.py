import shlex
import redis
import os
import sys
from subprocess import Popen, PIPE, STDOUT

from celery import Celery


amqp_user = os.environ.get('AMQP_USER', 'guest:guest')
backend_host = os.environ.get('MASTER', '127.0.0.1')
amqp = 'amqp://{}@{}:5672'.format(amqp_user, backend_host)

celery = Celery('tasks', broker=amqp, backend=amqp)
redis_instance = redis.Redis(host=backend_host)


@celery.task(shared=True, time_limit=60)
def run_command(command):
    task_id = run_command.request.id
    proc = Popen(
        ['/bin/bash', '-c', command],
        stdout=PIPE, stderr=STDOUT,
        env={'PATH': os.environ['PATH']},
    )

    redis_instance.publish('task:{}:pid'.format(task_id), 42)

    while True:
        line = proc.stdout.readline()
        if line:
            print(line)
            redis_instance.publish('task:{}:stdout'.format(task_id),
                                   line.rstrip())
        else:
            proc.wait()
            redis_instance.publish('task:{}:finish'.format(task_id),
                                   str(proc.returncode))
            break
    ret = {
        'retcode': proc.returncode,
    }
    print(ret)
    return ret
