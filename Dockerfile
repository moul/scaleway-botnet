FROM dockerfile/python

RUN pip install celery
RUN pip install redis

ENTRYPOINT ["/data/shell.py"]
ADD ./shell.py /data/shell.py
